"""Explicit skill recommendations and explanations over existing selection/support."""

from dataclasses import dataclass, field
import re

from app.models import (
    CVCandidateIndex, CVRecommendation, CVSelectionDecision, CVSelectionResult,
    CVSkillCandidate, CVSkillRelevance, CVSkillRequirementCoverage, CurrentCVSkillGroup,
    EvidenceSupport, ExperienceBankMatch, StructuredRequirement, normalise_skill_key,
)
from app.services.cv_selection import _match_context, _quality, _support_key, select_work_and_projects
from app.services.matching_activity import positive_clauses
from app.services.matching_terms import _CONCEPTS, _normalise
from app.services.technical_relationships import TechnicalRelationshipCatalogue


def _names(catalogue: TechnicalRelationshipCatalogue | None) -> dict[str, str]:
    # Equivalent names only. Unknown punctuation is never collapsed, and no
    # relationship is traversed to create a skill or establish its proficiency.
    names = {normalise_skill_key(alias): concept for concept, aliases in _CONCEPTS.items()
             for alias in (concept, *aliases)}
    if catalogue is not None:
        names.update({normalise_skill_key(alias): concept for concept, entry in catalogue.concepts.items()
                      for alias in (concept, *entry.aliases)})
    return names


def _identity(value: str, names: dict[str, str]) -> str:
    key = normalise_skill_key(value)
    return names.get(key, key)


def _records(index: CVCandidateIndex) -> dict[str, tuple[str, list[str], list[str]]]:
    """Own wording/outcomes/technologies, never inherited parent metadata."""
    records = {}
    for role in [*(item.role for item in index.work_experience), *index.out_of_baseline_work_experience]:
        records[role.id] = (role.summary, [], role.technologies)
        for item in role.achievements:
            records[item.id] = (item.text, item.outcomes, item.technologies)
    for candidate in index.projects:
        project = candidate.project
        records[project.id] = (project.description, [], project.technologies)
        for item in project.evidence:
            records[item.id] = (item.text, item.outcomes, item.technologies)
    for item in index.additional_evidence:
        records[item.id] = (item.text, item.outcomes, item.technologies)
    return records


def _raw_supports(
    matches: ExperienceBankMatch,
    requirements: dict[str, StructuredRequirement],
) -> dict[str, dict[str, EvidenceSupport]]:
    records = [support for rows in (matches.strong_matches, matches.related_matches, matches.missing_requirements)
               for row in rows for support in row.evidence_support]
    records.extend(support for item in matches.ranked_evidence for support in item.evidence_support)
    result = {}
    for support in sorted(records, key=lambda item: _support_key(item, requirements)):
        result.setdefault(support.evidence_id, {}).setdefault(support.requirement_id, support)
    return result


def _synthetic_ids(
    index: CVCandidateIndex,
    matches: ExperienceBankMatch,
    physical_ids: set[str],
) -> tuple[dict[str, str], set[str]]:
    candidates: dict[str, list[str]] = {}
    for skill in index.skills:
        candidates.setdefault(f"skill:{_normalise(skill.label)}", []).append(skill.skill_key)
    references = [reference for rows in (matches.strong_matches, matches.related_matches, matches.missing_requirements)
                  for row in rows for reference in row.evidence]
    references.extend(item.evidence for item in matches.ranked_evidence)
    actual = {item.evidence_id for item in references if item.source_type == "skill"}
    ambiguous = {key for key in actual if len(candidates.get(key, [])) > 1 or key in physical_ids}
    return {key: candidates[key][0] for key in actual - ambiguous if key in candidates}, ambiguous


@dataclass
class _Profile:
    candidate: CVSkillCandidate
    links: dict[str, CVSkillRelevance] = field(default_factory=dict)
    supports: dict[tuple[str, str], EvidenceSupport] = field(default_factory=dict)

    def link(self, requirement_id, kind, support=None, demonstrated=False):
        order = ("explicit_requirement", "technical_relationship", "supporting_technology")
        if requirement_id not in self.links:
            self.links[requirement_id] = CVSkillRelevance(requirement_id=requirement_id, kind=kind)
        link = self.links[requirement_id]
        if order.index(kind) < order.index(link.kind):
            link.kind = kind
        if support is not None:
            self.supports[(support.evidence_id, requirement_id)] = support
            if support.evidence_id not in link.evidence_ids:
                link.evidence_ids.append(support.evidence_id)
            if demonstrated and support.evidence_id not in link.demonstrated_evidence_ids:
                link.demonstrated_evidence_ids.append(support.evidence_id)


def _demonstrated(skill_name: str, support: EvidenceSupport, named: bool, names: dict[str, str]) -> bool:
    for signal in support.signals:
        if signal.origin not in {"wording", "outcome"} or signal.demonstrated_activity is None:
            continue
        relationship = signal.relationship
        if relationship is not None:
            if _identity(relationship.source, names) == skill_name:
                return True
            if (_identity(relationship.target, names) == skill_name
                and relationship.type == "broader" and support.status == "strong"):
                return True
        elif named or _identity(signal.signal, names) == skill_name:
            return True
    return False


def _mentioned(label: str, text: str, names: dict[str, str]) -> bool:
    identity = _identity(label, names)
    equivalents = [label, *(alias for alias, concept in names.items() if concept == identity)]
    wording = normalise_skill_key(text)
    return any(re.search(r"(?<![\w+#.])" + re.escape(normalise_skill_key(alias)) + r"(?![\w+#.])", wording)
               for alias in equivalents)


def _associated(
    profile: _Profile,
    support: EvidenceSupport,
    record: tuple[str, list[str], list[str]],
    names: dict[str, str],
) -> bool:
    wording, outcomes, technologies = record
    if profile.candidate.skill_key not in {normalise_skill_key(label) for label in technologies}:
        return False
    if not _quality(support):
        return False
    # Positive original fields plus existing meaningful matching support establish
    # a local association only. They never establish active use of this technology.
    fields = []
    if any(signal.origin == "wording" for signal in support.signals):
        fields.append(wording)
    if any(signal.origin == "outcome" for signal in support.signals):
        fields.extend(outcomes)
    return any(_mentioned(profile.candidate.label, clause, names)
               for text in fields for clause in positive_clauses(text))


def _profiles(
    index: CVCandidateIndex,
    matches: ExperienceBankMatch,
    requirements: dict[str, StructuredRequirement],
    supports: dict[str, dict[str, EvidenceSupport]],
    selected_ids: set[str],
    names: dict[str, str],
) -> tuple[list[_Profile], set[str]]:
    records = _records(index)
    synthetic, ambiguous = _synthetic_ids(index, matches, set(records))
    profiles = []
    for candidate in sorted(index.skills, key=lambda item: (item.bank_position, item.skill_key)):
        profile = _Profile(candidate)
        identity = _identity(candidate.label, names)
        for requirement_id, requirement in requirements.items():
            if requirement.category != "qualification" and any(_identity(option, names) == identity for option in requirement.alternatives):
                profile.link(requirement_id, "explicit_requirement")
        for evidence_id in sorted(supports):
            if evidence_id in ambiguous:
                continue
            for requirement_id, support in supports[evidence_id].items():
                requirement = requirements.get(requirement_id)
                if requirement is not None and requirement.category == "qualification":
                    continue
                named = _identity(support.selected_alternative, names) == identity
                exact_signal = any(_identity(signal.signal, names) == identity for signal in support.signals)
                relationships = [signal.relationship for signal in support.signals if signal.relationship]
                relationship = any(identity in {_identity(edge.source, names), _identity(edge.target, names)} for edge in relationships)
                standalone = synthetic.get(evidence_id) == candidate.skill_key
                if named or exact_signal or relationship or standalone:
                    kind = "technical_relationship" if relationships else "explicit_requirement"
                    profile.link(requirement_id, kind, support, _demonstrated(identity, support, named, names))
                elif evidence_id in selected_ids and evidence_id in records and _associated(profile, support, records[evidence_id], names):
                    profile.link(requirement_id, "supporting_technology", support)
        for link in profile.links.values():
            link.evidence_ids.sort()
            link.demonstrated_evidence_ids.sort()
        profiles.append(profile)
    return profiles, ambiguous


def _skill_priority(
    profile: _Profile,
    represented: set[str],
    requirements: dict[str, StructuredRequirement],
) -> tuple:
    new = set(profile.links) - represented
    required = {key for key in new if key in requirements and requirements[key].importance == "required"
                and profile.links[key].kind == "explicit_requirement"}
    demonstrated = any(link.demonstrated_evidence_ids for link in profile.links.values())
    supporting = any(link.kind == "supporting_technology" for link in profile.links.values())
    tier = 0 if required else 1 if demonstrated else 2 if supporting else 3 if new else 4
    quality = max((_quality(item) for item in profile.supports.values()), default=0)
    # Associations and related target technologies cannot borrow an engineering
    # record's strong/activity classification as skill-specific practical proof.
    if not demonstrated:
        quality = min(quality, 3 if any(item.status == "strong" and all(signal.relationship is None for signal in item.signals)
                                      for item in profile.supports.values()) and not supporting else 1)
    counts = tuple(sum((requirements[key].importance if key in requirements else "unspecified") == importance for key in new)
                   for importance in ("required", "unspecified", "preferred"))
    candidate = profile.candidate
    return (tier, not demonstrated, -quality, *(-count for count in counts), -len(profile.links),
            not candidate.is_currently_selected,
            candidate.current_cv_group_index if candidate.current_cv_group_index is not None else 0,
            candidate.current_cv_position if candidate.current_cv_position is not None else 0,
            candidate.bank_position, candidate.skill_key)


def _choose_skills(
    profiles: list[_Profile],
    limit: int | None,
    requirements: dict[str, StructuredRequirement],
    names: dict[str, str],
) -> tuple[list[_Profile], dict[str, str], dict[str, list[str]]]:
    chosen, reasons, marginal = [], {}, {}
    represented, identities = set(), set()
    while limit is None or len(chosen) < limit:
        eligible = [item for item in profiles if item.links and item.candidate.skill_key not in reasons
                    and _identity(item.candidate.label, names) not in identities]
        if not eligible:
            break
        best = min(eligible, key=lambda item: _skill_priority(item, represented, requirements))
        key = best.candidate.skill_key
        tier = _skill_priority(best, represented, requirements)[0]
        reasons[key] = {0: "required_explicit_skill", 1: "demonstrated_skill", 2: "supporting_technology"}.get(tier, "relevant_explicit_skill")
        marginal[key] = sorted(set(best.links) - represented)
        chosen.append(best)
        identities.add(_identity(best.candidate.label, names))
        represented.update(best.links)
    for item in sorted(profiles, key=lambda item: (not item.candidate.is_currently_selected,
                       item.candidate.current_cv_group_index if item.candidate.current_cv_group_index is not None else 0,
                       item.candidate.current_cv_position if item.candidate.current_cv_position is not None else 0,
                       item.candidate.bank_position, item.candidate.skill_key)):
        if limit is not None and len(chosen) >= limit:
            break
        key = item.candidate.skill_key
        if item.candidate.is_currently_selected and key not in reasons and _identity(item.candidate.label, names) not in identities:
            chosen.append(item)
            reasons[key] = "baseline_retained"
            marginal[key] = []
            identities.add(_identity(item.candidate.label, names))
    return chosen, reasons, marginal


def _groups(
    index: CVCandidateIndex,
    chosen: list[_Profile],
    names: dict[str, str],
) -> tuple[list[CurrentCVSkillGroup], dict[str, str]]:
    anchors = {}
    for group_index, group in enumerate(index.baseline.skill_groups):
        for key in group.skill_keys:
            anchors.setdefault(_identity(key, names), set()).add(group_index)
    fallback = next((position for position, group in enumerate(index.baseline.skill_groups)
                     if normalise_skill_key(group.name) == "additional skills"), len(index.baseline.skill_groups))
    placement = {}
    for profile in chosen:
        candidate = profile.candidate
        matching_groups = anchors.get(_identity(candidate.label, names), set())
        if candidate.is_currently_selected:
            placement[candidate.skill_key] = candidate.current_cv_group_index
        elif len(matching_groups) == 1:
            placement[candidate.skill_key] = next(iter(matching_groups))
        else:
            placement[candidate.skill_key] = fallback
    result, group_names = [], {}
    for position in range(len(index.baseline.skill_groups) + 1):
        baseline = index.baseline.skill_groups[position] if position < len(index.baseline.skill_groups) else None
        keys = [key for key in (baseline.skill_keys if baseline else []) if placement.get(key) == position]
        keys.extend(item.candidate.skill_key for item in chosen
                    if placement[item.candidate.skill_key] == position and item.candidate.skill_key not in keys)
        if keys:
            name = baseline.name if baseline else "Additional skills"
            result.append(CurrentCVSkillGroup(name=name, skill_keys=keys))
            group_names.update({key: name for key in keys})
    return result, group_names


def _basis(supports, *, skill=False, demonstrated=False):
    basis = set()
    for support in supports:
        for signal in support.signals:
            if signal.origin == "wording":
                basis.add("demonstrated_wording" if signal.demonstrated_activity and (not skill or demonstrated) else "wording")
            else:
                basis.add(signal.origin)
            if signal.relationship:
                basis.add("technical_relationship")
    return basis


_MESSAGES = {
    "new_strong_coverage": "Selected to add strong requirement support.",
    "stronger_coverage": "Selected to strengthen existing requirement support.",
    "new_related_coverage": "Selected to add related requirement support.",
    "better_evidence_quality": "Selected for better recorded evidence quality.",
    "baseline_retained": "Retained from Current CV within available capacity.",
    "limit_reached": "Omitted because the section limit was reached.",
    "exact_duplicate": "Omitted as duplicate recorded content.",
    "repetitive_evidence": "Omitted as clearly repetitive content within the same parent.",
    "already_covered": "Omitted because it adds no stronger or distinct requirement support.",
    "declaration_only": "Not introduced as a bullet because support is declaration-only.",
    "no_relevant_support": "No relevant support justifies introducing this content.",
    "project_not_selected": "Omitted because its project was not selected.",
    "invalid_reference": "Unavailable baseline reference; no repair or relocation was applied.",
    "equivalent_skill": "Omitted because an equivalent recorded skill label was selected.",
    "required_explicit_skill": "Selected as an explicitly recorded skill named in a required requirement.",
    "demonstrated_skill": "Selected for relevant skill-specific demonstrated experience.",
    "supporting_technology": "Selected as an explicit supporting technology associated with selected content.",
    "relevant_explicit_skill": "Selected as an explicitly recorded skill relevant to the job.",
    "unchanged_credential": "Retained in its existing credential section, outside engineering-content competition.",
}


def _recommendation(decision, requirements, *, original_text=None, group_name=None, previous_group_name=None,
                    links=(), bundle_supports=()):
    supports = decision.evidence_support
    skill = decision.source_type == "skill"
    demonstrated = any(link.demonstrated_evidence_ids for link in links)
    ids = sorted({item.requirement_id for item in [*supports, *bundle_supports]} | {link.requirement_id for link in links})
    basis = _basis(supports, skill=skill, demonstrated=demonstrated)
    if skill:
        if original_text is not None:
            basis.add("catalogue_declaration")
        if any(link.kind == "supporting_technology" for link in links):
            basis.add("selected_content_association")
    if "baseline_retained" in decision.reason_codes:
        basis.add("baseline")
    message = " ".join(_MESSAGES[reason] for reason in decision.reason_codes)
    if skill and decision.selected and not demonstrated:
        message += " Practical use of this skill is not established by the available support."
    return CVRecommendation(**decision.model_dump(), original_text=original_text,
        group_name=group_name, previous_group_name=previous_group_name,
        supported_requirement_ids=ids,
        requirement_importance={key: requirements[key].importance if key in requirements else "unspecified" for key in ids},
        support_basis=sorted(basis), recommendation=message, skill_relevance=list(links))


def select_cv_content(index: CVCandidateIndex, matches: ExperienceBankMatch, *,
                      catalogue: TechnicalRelationshipCatalogue | None = None) -> CVSelectionResult:
    """Complete the pure preview; catalogue is optional preloaded alias data only.

    Work/project decisions are delegated to select_work_and_projects. No loading, matching,
    rewriting, saving, relationship traversal or new selectable skills occurs.
    """
    work = select_work_and_projects(index, matches)
    context = _match_context(matches)
    names = _names(catalogue)
    raw = _raw_supports(matches, context.requirements)
    selected_ids = {item.source_id for item in work.decisions if item.selected}
    profiles, ambiguous = _profiles(index, matches, context.requirements, raw, selected_ids, names)
    chosen, reasons, marginal = _choose_skills(profiles, index.tailoring_settings.max_skills, context.requirements, names)
    groups, group_names = _groups(index, chosen, names)
    records = _records(index)
    recommendations = []
    for item in work.decisions:
        bundle_supports = [support for evidence_id in item.bundle_evidence_ids for support in raw.get(evidence_id, {}).values()]
        recommendations.append(_recommendation(item, context.requirements,
            original_text=records[item.source_id][0] if item.source_id in records else None,
            bundle_supports=bundle_supports))
    selected_aliases = {_identity(item.candidate.label, names): item.candidate.skill_key for item in chosen}
    for profile in profiles:
        candidate = profile.candidate
        key = candidate.skill_key
        equivalent = selected_aliases.get(_identity(candidate.label, names))
        selected = key in reasons
        full = index.tailoring_settings.max_skills is not None and len(chosen) >= index.tailoring_settings.max_skills
        if selected:
            reason = reasons[key]
        elif equivalent:
            reason = "equivalent_skill"
        elif full and (profile.links or candidate.is_currently_selected):
            reason = "limit_reached"
        else:
            reason = "no_relevant_support"
        decision = CVSelectionDecision(source_type="skill", source_id=key, selected=selected,
            was_in_current_cv=candidate.is_currently_selected, reason_codes=[reason],
            marginal_requirement_ids=marginal.get(key, []),
            evidence_support=[profile.supports[pair] for pair in sorted(profile.supports)],
            duplicate_of=equivalent if not selected and equivalent else None)
        recommendations.append(_recommendation(decision, context.requirements,
            original_text=candidate.label, group_name=group_names.get(key),
            previous_group_name=candidate.current_cv_group_name,
            links=[profile.links[requirement_id] for requirement_id in sorted(profile.links)]))
    available = {item.skill_key for item in index.skills}
    for group in index.baseline.skill_groups:
        for key in group.skill_keys:
            if key not in available:
                decision = CVSelectionDecision(source_type="skill", source_id=key,
                    selected=False, was_in_current_cv=True, reason_codes=["invalid_reference"])
                recommendations.append(_recommendation(decision, context.requirements, previous_group_name=group.name))
    for source_type, records in (("education", index.education), ("certification", index.certifications)):
        for item in records:
            decision = CVSelectionDecision(source_type=source_type, source_id=item.id, selected=True,
                was_in_current_cv=True, reason_codes=["unchanged_credential"],
                evidence_support=[raw[item.id][key] for key in sorted(raw.get(item.id, {}))])
            recommendations.append(_recommendation(decision, context.requirements,
                original_text=item.qualification if source_type == "education" else item.name))
    data = work.model_dump()
    data["proposed_cv"]["skill_groups"] = [group.model_dump() for group in groups]
    data["decisions"] = recommendations
    data["skill_coverage"] = [CVSkillRequirementCoverage(requirement_id=key,
        selected_skill_keys=[item.candidate.skill_key for item in chosen if key in item.links])
        for key in sorted(context.bank_status)]
    if ambiguous:
        data["warnings"].append("ambiguous_skill_identity")
    return CVSelectionResult(**data).model_copy(deep=True)
