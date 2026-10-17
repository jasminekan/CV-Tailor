"""Coverage-aware reference selection over existing matching decisions; no I/O."""

from dataclasses import dataclass
import re

from app.models import (
    CVCandidateIndex, CVBulletCandidate, CVProjectCandidate, CVRequirementCoverage,
    CVSelectionDecision, CVSelectionReason, CVWorkProjectSelection, CurrentCV,
    CurrentCVProjectSelection, CurrentCVWorkSelection, EvidenceSupport,
    ExperienceBankMatch, StructuredRequirement,
)


_GAIN_REASONS = (
    "new_strong_coverage", "stronger_coverage", "new_related_coverage", "better_evidence_quality",
)
_IMPORTANCE = ("required", "unspecified", "preferred")
_TOKEN = re.compile(r"(?:\.[^\W_]+|[^\W_]+)(?:[.'+#][^\W_]+)*[+#]*|[^\w\s]")


def _quality(support: EvidenceSupport) -> int:
    """Order provenance, not proficiency: strong activity/wording, related activity/wording."""
    wording = [signal for signal in support.signals if signal.origin in {"wording", "outcome"}]
    if not wording:
        return 0
    activity = any(signal.demonstrated_activity is not None for signal in wording)
    return (4 if activity else 3) if support.status == "strong" else (2 if activity else 1)


@dataclass
class _Context:
    requirements: dict[str, StructuredRequirement]
    bank_status: dict[str, str]
    supports: dict[str, dict[str, EvidenceSupport]]
    missing_metadata: bool


def _support_key(support: EvidenceSupport, requirements: dict[str, StructuredRequirement]) -> tuple:
    requirement = requirements.get(support.requirement_id)
    options = requirement.alternatives if requirement else []
    option_position = options.index(support.selected_alternative) if support.selected_alternative in options else len(options)
    return (-_quality(support), support.status != "strong", option_position,
            support.selected_alternative, support.model_dump_json())


def _match_context(matches: ExperienceBankMatch) -> _Context:
    requirements, bank_status = {}, {}
    records = []
    missing_metadata = False
    for status, rows in (("strong", matches.strong_matches), ("related", matches.related_matches),
                         ("missing", matches.missing_requirements)):
        for row in rows:
            if row.requirement_details:
                requirement = row.requirement_details
                requirements[requirement.id] = requirement
                bank_status[requirement.id] = status
            else:
                missing_metadata = True
            records.extend(row.evidence_support)
    for ranked in matches.ranked_evidence:
        records.extend(ranked.evidence_support)

    supports: dict[str, dict[str, EvidenceSupport]] = {}
    for support in sorted(records, key=lambda item: _support_key(item, requirements)):
        requirement_id = support.requirement_id
        if requirement_id not in bank_status:
            bank_status[requirement_id] = "related"
        if requirement_id not in requirements:
            missing_metadata = True
        # Do not turn formal qualification support into competitive bullet relevance.
        if requirement_id in requirements and requirements[requirement_id].category == "qualification":
            continue
        supports.setdefault(support.evidence_id, {}).setdefault(requirement_id, support)
    # Older/custom results can lack requirement metadata, but support IDs still
    # provide distinct obligations. Importance then remains unspecified.
    for requirement_id in bank_status.keys() - requirements.keys():
        if any(item.requirement_id == requirement_id and item.status == "strong" for item in records):
            bank_status[requirement_id] = "strong"
    return _Context(requirements, bank_status, supports, missing_metadata)


def _combine(context: _Context, evidence_ids: list[str]) -> dict[str, EvidenceSupport]:
    combined = {}
    for evidence_id in evidence_ids:
        for requirement_id, support in context.supports.get(evidence_id, {}).items():
            if requirement_id not in combined or _support_key(support, context.requirements) < _support_key(combined[requirement_id], context.requirements):
                combined[requirement_id] = support
    return combined


def _update_coverage(coverage: dict[str, int], supports: dict[str, EvidenceSupport]) -> None:
    for requirement_id, support in supports.items():
        coverage[requirement_id] = max(coverage.get(requirement_id, 0), _quality(support))


def _gains(supports: dict[str, EvidenceSupport], coverage: dict[str, int]) -> dict[str, CVSelectionReason]:
    gains = {}
    for requirement_id, support in supports.items():
        quality, previous = _quality(support), coverage.get(requirement_id, 0)
        if quality <= previous:
            continue
        if quality >= 3:
            reason = "new_strong_coverage" if previous == 0 else "stronger_coverage" if previous < 3 else "better_evidence_quality"
        else:
            reason = "new_related_coverage" if previous == 0 else "better_evidence_quality"
        gains[requirement_id] = reason
    return gains


def _score(supports: dict[str, EvidenceSupport]) -> int:
    # Existing 10/3 coverage weights, at most once per requirement; no new points.
    return sum(10 if support.status == "strong" else 3 for support in supports.values())


def _priority(context: _Context, supports: dict[str, EvidenceSupport], coverage: dict[str, int],
              score: int) -> tuple[int, ...]:
    gains = _gains(supports, coverage)
    # Lexicographic counts, not a new weighted score. Within each gain category,
    # compare evidence quality before importance, then breadth and original score.
    counts = tuple(sum(
        reason == kind and _quality(supports[requirement_id]) == quality
        and (context.requirements[requirement_id].importance if requirement_id in context.requirements else "unspecified") == importance
        for requirement_id, reason in gains.items()
    ) for kind in _GAIN_REASONS for quality in (4, 3, 2, 1) for importance in _IMPORTANCE)
    return (*counts, len(gains), score)


def _order(priority: tuple[int, ...], cv_position: int | None, bank_position: int, source_id: str) -> tuple:
    return (*(-value for value in priority), cv_position is None,
            cv_position if cv_position is not None else 0, bank_position, source_id)


def _normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def _repetition_tokens(text: str) -> tuple[str, ...]:
    # Retain signs, currencies, percentages and technical punctuation. Dropping
    # general punctuation would collapse -20%/20%, $100/£100 or C/C++/C#.
    return tuple(token for token in _TOKEN.findall(_normalise(text))
                 if token not in {"a", "an", "the", ".", ",", "!", "?"})


def _support_signature(context: _Context, evidence_id: str) -> tuple:
    supports = context.supports.get(evidence_id, {})
    return (set(supports), {signal.demonstrated_activity for support in supports.values()
                           for signal in support.signals if signal.demonstrated_activity})


def _duplicate(candidate: CVBulletCandidate, selected: list[CVBulletCandidate], context: _Context) -> tuple[CVSelectionReason, str] | None:
    item = candidate.evidence
    for other in selected:
        old = other.evidence
        # Preserve potentially distinct technologies and outcomes even when text
        # is close. No cross-parent merging, synonym expansion or fuzzy matching.
        if (candidate.parent_id != other.parent_id
            or {_normalise(tag) for tag in item.technologies} != {_normalise(tag) for tag in old.technologies}
            or {_normalise(outcome) for outcome in item.outcomes} != {_normalise(outcome) for outcome in old.outcomes}):
            continue
        if _normalise(item.text) == _normalise(old.text):
            return "exact_duplicate", old.id
        core = _repetition_tokens(item.text)
        if len(core) >= 4 and core == _repetition_tokens(old.text) and _support_signature(context, item.id) == _support_signature(context, old.id):
            return "repetitive_evidence", old.id
    return None


@dataclass
class _SelectedBullet:
    candidate: CVBulletCandidate
    reasons: list[CVSelectionReason]
    marginal: list[str]


def _select_bullets(candidates: list[CVBulletCandidate], limit: int | None, context: _Context,
                    initial_coverage: dict[str, int], blocked: set[str]) -> list[_SelectedBullet]:
    selected = []
    coverage = dict(initial_coverage)
    remaining = {item.evidence.id: item for item in candidates if item.evidence.id not in blocked}
    while remaining and (limit is None or len(selected) < limit):
        eligible = [item for item in remaining.values()
                    if _gains(context.supports.get(item.evidence.id, {}), coverage)
                    and not _duplicate(item, [choice.candidate for choice in selected], context)]
        if not eligible:
            break
        def key(item):
            supports = context.supports.get(item.evidence.id, {})
            return _order(_priority(context, supports, coverage, _score(supports)),
                          item.current_cv_position, item.bank_position, item.evidence.id)
        best = min(eligible, key=key)
        supports = context.supports.get(best.evidence.id, {})
        gains = _gains(supports, coverage)
        selected.append(_SelectedBullet(best, [reason for reason in _GAIN_REASONS if reason in gains.values()], sorted(gains)))
        _update_coverage(coverage, supports)
        del remaining[best.evidence.id]
    for item in sorted(remaining.values(), key=lambda item: (item.current_cv_position is None,
                        item.current_cv_position if item.current_cv_position is not None else 0, item.bank_position, item.evidence.id)):
        if limit is not None and len(selected) >= limit:
            break
        if item.is_currently_selected and not _duplicate(item, [choice.candidate for choice in selected], context):
            selected.append(_SelectedBullet(item, ["baseline_retained"], []))
    return selected


def _display_order(selected: list[_SelectedBullet]) -> list[_SelectedBullet]:
    return sorted(selected, key=lambda choice: (choice.candidate.current_cv_position is None,
                  choice.candidate.current_cv_position if choice.candidate.current_cv_position is not None else 0,
                  choice.candidate.bank_position, choice.candidate.evidence.id))


def _no_gain_reason(supports: dict[str, EvidenceSupport]) -> CVSelectionReason:
    return "already_covered" if any(_quality(support) for support in supports.values()) else "declaration_only" if supports else "no_relevant_support"


def _bullet_decisions(candidates: list[CVBulletCandidate], selected: list[_SelectedBullet],
                      limit: int | None, context: _Context, blocked: set[str], parent_selected=True) -> list[CVSelectionDecision]:
    choices = {choice.candidate.evidence.id: choice for choice in selected}
    decisions = []
    for candidate in sorted(candidates, key=lambda item: (item.bank_position, item.evidence.id)):
        source_id = candidate.evidence.id
        choice = choices.get(source_id) if parent_selected else None
        supports = context.supports.get(source_id, {})
        duplicate = _duplicate(candidate, [item.candidate for item in selected if item.candidate.evidence.id != source_id], context)
        if choice:
            reasons = choice.reasons
        elif source_id in blocked:
            reasons = ["invalid_reference"]
        elif not parent_selected:
            reasons = ["project_not_selected"]
        elif duplicate:
            reasons = [duplicate[0]]
        elif limit is not None and len(selected) >= limit:
            reasons = ["limit_reached"]
        else:
            reasons = [_no_gain_reason(supports)]
        decisions.append(CVSelectionDecision(
            source_type=candidate.source_type, source_id=source_id, parent_id=candidate.parent_id,
            selected=choice is not None, was_in_current_cv=candidate.is_currently_selected,
            reason_codes=reasons, marginal_requirement_ids=choice.marginal if choice else [],
            evidence_support=[supports[key] for key in sorted(supports)],
            duplicate_of=duplicate[1] if duplicate and reasons[0] in {"exact_duplicate", "repetitive_evidence"} else None,
        ))
    return decisions


@dataclass
class _ProjectBundle:
    candidate: CVProjectCandidate
    bullets: list[_SelectedBullet]
    supports: dict[str, EvidenceSupport]


def _bundle(project: CVProjectCandidate, context: _Context, coverage: dict[str, int],
            limit: int | None, blocked: set[str]) -> _ProjectBundle:
    inside = dict(coverage)
    _update_coverage(inside, context.supports.get(project.project.id, {}))
    bullets = _select_bullets(project.contributions, limit, context, inside, blocked)
    return _ProjectBundle(project, bullets, _combine(context, [project.project.id, *(item.candidate.evidence.id for item in bullets)]))


def _invalid_baseline(index: CVCandidateIndex) -> tuple[list[CVSelectionDecision], set[str]]:
    decisions, blocked = [], set()
    work = {item.role.id: {child.evidence.id for child in item.achievements} for item in index.work_experience}
    projects = {item.project.id: {child.evidence.id for child in item.contributions} for item in index.projects}
    for selections, parents, parent_type, child_type, parent_field, child_field in (
        (index.baseline.work_experience, work, "work_experience", "achievement", "work_experience_id", "achievement_ids"),
        (index.baseline.projects, projects, "project", "project_evidence", "project_id", "contribution_ids"),
    ):
        for selection in selections:
            parent_id = getattr(selection, parent_field)
            if parent_id not in parents:
                decisions.append(CVSelectionDecision(source_type=parent_type, source_id=parent_id,
                    selected=False, was_in_current_cv=True, reason_codes=["invalid_reference"]))
            for source_id in getattr(selection, child_field):
                if source_id not in parents.get(parent_id, set()):
                    blocked.add(source_id)
                    decisions.append(CVSelectionDecision(source_type=child_type, source_id=source_id,
                        parent_id=parent_id, selected=False, was_in_current_cv=True, reason_codes=["invalid_reference"]))
    return decisions, blocked


def select_work_and_projects(index: CVCandidateIndex, matches: ExperienceBankMatch) -> CVWorkProjectSelection:
    """Return independent proposed references, keeping the saved baseline untouched.

    Each retained role gets a coverage-first pass and then baseline retention.
    Projects compete as capped bundles against already selected work coverage.
    No matcher calls, skill changes, text rewriting, repository or network access.
    """
    context = _match_context(matches)
    decisions, blocked = _invalid_baseline(index)
    settings = index.tailoring_settings
    work_selections = []
    coverage: dict[str, int] = {}
    selected_evidence_ids = []
    for role in sorted(index.work_experience, key=lambda item: (item.current_cv_position, item.bank_position, item.role.id)):
        # The existing preview retains the role's original summary. Account for
        # that context under its own ID, never as a selectable achievement or as
        # proof belonging to one of its children.
        role_supports = context.supports.get(role.role.id, {})
        selected_evidence_ids.append(role.role.id)
        _update_coverage(coverage, role_supports)
        decisions.append(CVSelectionDecision(
            source_type="work_experience", source_id=role.role.id,
            selected=True, was_in_current_cv=True, reason_codes=["baseline_retained"],
            evidence_support=[role_supports[key] for key in sorted(role_supports)],
        ))
        selected = _select_bullets(role.achievements, settings.max_achievements_per_role, context, {}, blocked)
        ids = [item.candidate.evidence.id for item in _display_order(selected)]
        work_selections.append(CurrentCVWorkSelection(work_experience_id=role.role.id, achievement_ids=ids))
        selected_evidence_ids.extend(ids)
        _update_coverage(coverage, _combine(context, ids))
        decisions.extend(_bullet_decisions(role.achievements, selected, settings.max_achievements_per_role, context, blocked))

    remaining = {project.project.id: project for project in index.projects}
    chosen: dict[str, tuple[_ProjectBundle, list[CVSelectionReason], list[str]]] = {}
    while remaining and (settings.max_projects is None or len(chosen) < settings.max_projects):
        bundles = [_bundle(project, context, coverage, settings.max_contributions_per_project, blocked)
                   for project in remaining.values()]
        eligible = [bundle for bundle in bundles if _gains(bundle.supports, coverage)]
        if not eligible:
            break
        best = min(eligible, key=lambda bundle: _order(
            _priority(context, bundle.supports, coverage, _score(bundle.supports)),
            bundle.candidate.current_cv_position, bundle.candidate.bank_position, bundle.candidate.project.id))
        gains = _gains(best.supports, coverage)
        project_id = best.candidate.project.id
        chosen[project_id] = (best, [reason for reason in _GAIN_REASONS if reason in gains.values()], sorted(gains))
        _update_coverage(coverage, best.supports)
        del remaining[project_id]
    for project in sorted(remaining.values(), key=lambda item: (item.current_cv_position is None,
                          item.current_cv_position if item.current_cv_position is not None else 0, item.bank_position, item.project.id)):
        if settings.max_projects is not None and len(chosen) >= settings.max_projects:
            break
        if project.is_currently_selected:
            bundle = _bundle(project, context, coverage, settings.max_contributions_per_project, blocked)
            chosen[project.project.id] = (bundle, ["baseline_retained"], [])
            _update_coverage(coverage, bundle.supports)

    project_selections = []
    for project_id, (bundle, _, _) in chosen.items():
        ids = [item.candidate.evidence.id for item in _display_order(bundle.bullets)]
        project_selections.append(CurrentCVProjectSelection(project_id=project_id, contribution_ids=ids))
        selected_evidence_ids.extend([project_id, *ids])
    for project in sorted(index.projects, key=lambda item: (item.bank_position, item.project.id)):
        project_id = project.project.id
        choice = chosen.get(project_id)
        supports = context.supports.get(project_id, {})
        if choice:
            bundle, reasons, marginal = choice
        else:
            bundle = _bundle(project, context, coverage, settings.max_contributions_per_project, blocked)
            reasons = ["limit_reached"] if settings.max_projects is not None and len(chosen) >= settings.max_projects else [_no_gain_reason(bundle.supports)]
            marginal = []
        decisions.append(CVSelectionDecision(
            source_type="project", source_id=project_id, selected=choice is not None,
            was_in_current_cv=project.is_currently_selected, reason_codes=reasons,
            marginal_requirement_ids=marginal, evidence_support=[supports[key] for key in sorted(supports)],
            bundle_evidence_ids=[project_id, *(item.candidate.evidence.id for item in _display_order(bundle.bullets))] if choice else [],
        ))
        decisions.extend(_bullet_decisions(project.contributions, bundle.bullets if choice else [],
                         settings.max_contributions_per_project, context, blocked, parent_selected=choice is not None))

    covered_requirements = []
    for requirement_id in sorted(context.bank_status):
        ids = [evidence_id for evidence_id in selected_evidence_ids if requirement_id in context.supports.get(evidence_id, {})]
        selected_supports = [context.supports[evidence_id][requirement_id] for evidence_id in ids]
        status = "strong" if any(item.status == "strong" for item in selected_supports) else "related" if ids else "not_selected"
        covered_requirements.append(CVRequirementCoverage(
            requirement_id=requirement_id, requirement_details=context.requirements.get(requirement_id),
            bank_status=context.bank_status[requirement_id], selected_status=status,
            selected_evidence_ids=ids,
            meaningful_evidence_ids=[item.evidence_id for item in selected_supports if _quality(item)],
        ))
    return CVWorkProjectSelection(
        proposed_cv=CurrentCV(work_experience=work_selections, projects=project_selections,
                              skill_groups=index.baseline.skill_groups, tailoring_settings=settings),
        decisions=decisions, coverage=covered_requirements,
        education_ids=[item.id for item in index.education],
        certification_ids=[item.id for item in index.certifications],
        reference_issues=index.reference_issues,
        warnings=(["baseline_reference_issues"] if index.reference_issues else [])
                 + (["matching_metadata_unavailable"] if context.missing_metadata else []),
    ).model_copy(deep=True)
