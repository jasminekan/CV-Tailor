"""Deterministic matching of local evidence, without inheriting parent claims."""

import re
from dataclasses import dataclass, field as dataclass_field

from app.models import (
    EvidenceReference,
    EvidenceSupport,
    ExperienceBank,
    ExperienceBankMatch,
    JobDescriptionAnalysis,
    MatchResult,
    MatchingSignal,
    RankedEvidence,
    RelationshipReference,
    StructuredRequirement,
)
from app.services.matching_terms import _BROADER, _CONCEPTS, _canonical, _concepts, _contains, _normalise
from app.services.matching_activity import (
    api_development_without_maintenance, complete_api_request, complete_cloud_request,
    demonstrates, oracle_database_development, positive_clauses,
)
from app.services.requirements import prepare_requirements
from app.services.technical_relationships import (
    TechnicalRelationshipCatalogue, load_technical_relationships,
)


def _positive_text(text: str) -> str:
    # Do not turn obvious denials or aspirations into demonstrated experience.
    return " ".join(positive_clauses(text))


@dataclass
class _Evidence:
    reference: EvidenceReference
    tags: list[str]
    text: str
    field: str = ""
    raw_text: str = ""
    statements: list[tuple[str, str]] = dataclass_field(default_factory=list)
    tag_origins: dict[str, str] = dataclass_field(default_factory=dict)


def _collect_evidence(bank: ExperienceBank) -> list[_Evidence]:
    collected: list[_Evidence] = []

    def add(
        item_id: str,
        source_type: str,
        label: str,
        text: str,
        tags: list[str],
        field: str = "",
        outcomes: list[str] | tuple[str, ...] = (),
        technologies: list[str] | tuple[str, ...] = (),
    ) -> None:
        origin = "credential" if source_type in {"education", "certification"} else "wording"
        statements = [(clause, origin) for clause in positive_clauses(text)]
        statements += [(clause, "outcome") for outcome in outcomes for clause in positive_clauses(outcome)]
        origins = {tag: "standalone_skill" if source_type == "skill" else
                   "credential" if source_type == "certification" else "skill_tag" for tag in tags}
        origins.update({tag: "technology_tag" for tag in technologies})
        collected.append(_Evidence(
            EvidenceReference(
                evidence_id=item_id,
                source_type=source_type,
                source_label=label,
                text=text
            ),
            [*tags, *technologies], " ".join(clause for clause, _ in statements), field,
            ". ".join([text, *outcomes]),
            statements, origins,
        ))

    for skill in bank.skills:
        add(f"skill:{_normalise(skill)}", "skill", "Skills", "", [skill])
        collected[-1].reference.text = skill
    for role in bank.work_experience:
        label = f"{role.role} at {role.employer}"
        add(role.id, "work_experience", label, role.summary, role.skills, technologies=role.technologies)
        for item in role.achievements:
            add(
                item.id,
                "achievement",
                label,
                item.text,
                item.skills,
                outcomes=item.outcomes, technologies=item.technologies,
            )
    for project in bank.projects:
        add(
            project.id,
            "project",
            project.name,
            project.description,
            project.skills, technologies=project.technologies,
        )
        for item in project.evidence:
            add(
                item.id,
                "project_evidence",
                project.name,
                item.text,
                item.skills,
                outcomes=item.outcomes, technologies=item.technologies,
            )
    for item in bank.education:
        add(item.id, "education", item.qualification, item.qualification, [], item.field)
    for item in bank.certifications:
        add(item.id, "certification", item.name, item.name, item.skills)
    for item in bank.additional_evidence:
        add(
            item.id,
            "additional_evidence",
            "Additional evidence",
            item.text,
            item.skills,
            outcomes=item.outcomes, technologies=item.technologies,
        )
    return collected


_LEVELS = {
    "bachelor": ("bsc", "b.sc", "b.sc.", "ba", "bachelor", "bachelors"),
    "master": ("msc", "m.sc", "m.sc.", "ma", "master", "masters"),
    "doctorate": ("phd", "ph.d", "doctorate"),
}
_SUBJECTS = (
    "software engineering",
    "computer engineering",
    "electrical engineering",
    "computer science",
    "engineering"
)


def _levels(text: str) -> set[str]:
    return {
        level for level,
        aliases in _LEVELS.items() if any(_contains(text, alias) for alias in aliases)
    }


def _subjects(text: str) -> set[str]:
    found = set()
    for subject in _SUBJECTS:
        if _contains(text, subject):
            found.add(subject)
            text = text.replace(subject, " ")
    return found


def _degree_pairs(text: str) -> set[tuple[str, str]]:
    """Parse explicit OR branches and shared levels/subjects, without cross-pairing."""
    text = _normalise(text)
    if _contains(text, "and") and (len(_levels(text)) > 1 or len(_subjects(text)) > 1):
        return set()  # Compound qualifications are not interpreted as alternatives.
    pairs = set()
    pending_levels = set()
    active_levels = set()
    for branch in re.split(r"\bor\b", text):
        levels, subjects = _levels(branch), _subjects(branch)
        if levels and not subjects:
            pending_levels |= levels
            active_levels = set()
        elif subjects:
            if levels:
                active_levels = pending_levels | levels
                pending_levels = set()
            elif pending_levels:
                active_levels = pending_levels
                pending_levels = set()
            pairs.update((level, subject) for level in active_levels for subject in subjects)
    return pairs


def _denied(requirement: str, item: _Evidence) -> bool:
    """Explicit local denial overrides tags; it never invalidates other records."""
    concept = _canonical(requirement)
    phrases = _CONCEPTS.get(concept, (concept,))
    if concept == "c# .net":
        phrases = ("c#", ".net")
    text = _normalise(item.raw_text)
    for phrase in phrases:
        token = r"(?<![a-z0-9+#.])" + re.escape(phrase) + r"(?![a-z0-9+#.])"
        patterns = (
            r"\b(?:no|without|lack|lacks|lacking)\s+" + token + r"\s+(?:experience|knowledge|skills?)\b",
            r"\b(?:no|without|lack|lacks|lacking)\s+(?:experience|knowledge|skills?)\s+(?:with|in|of)\s+" + token,
            r"\b(?:not|never)\s+(?:used|using|worked with)\s+" + token,
        )
        if any(re.search(pattern, text) for pattern in patterns):
            return True
    return False


# Activity patterns require an action and its object, not a generic verb alone.
_ACTIVITIES = {
    "API development": r"\b(?:designed|developed|implemented|built)\b.{0,80}\b(?:api|apis)\b",
    "testing": r"\b(?:wrote|added|created|implemented)\b.{0,80}\b(?:unit|automated) tests?\b",
    "LLM integration": r"\b(?:integrated|implemented|built)\b.{0,60}\b(?:llm|large language model|openai)\b",
    "production operations": r"\b(?:built|supported|investigated|resolved|operated|maintained)\b.{0,80}\b(?:monitoring|production|deployments?)\b",
    "project leadership": r"\b(?:led|managed|directed)\b.{0,40}\bprojects?\b",
    "system ownership": r"\b(?:owned|took ownership of)\b.{0,40}\b(?:systems?|services?)\b",
    "delivery": r"\b(?:delivered|managed)\b.{0,40}\b(?:deadlines?|deliverables?|releases?|project priorities)\b",
}
_REQUEST_ACTIVITIES = {
    "API development": r"\b(?:design|develop|build)\b.{0,50}\b(?:api|apis)\b",
    "production operations": r"\b(?:operate|maintain|deploy)\b.{0,50}\b(?:systems?|services?|software)\b|\b(?:systems?|services?)\b.{0,50}\b(?:operate|maintain|deploy)\b",
    "project leadership": r"\b(?:lead|drive|manage)\b.{0,50}\bprojects?\b",
    "system ownership": r"\bown\b.{0,50}\b(?:systems?|services?)\b",
    "delivery": r"\b(?:lead|manage|deliver)\b.{0,60}\b(?:priorities|deadlines|deliverables|releases)\b",
}


def _activities(item: _Evidence) -> set[str]:
    return {name for name, pattern in _ACTIVITIES.items() if re.search(pattern, item.text)}


def _related_support(
    requirement: str,
    category: str,
    item: _Evidence
) -> tuple[int, list[str], str]:
    text = _normalise(requirement)
    activities = _activities(item)
    supported = []
    testing_evidence = (
        "testing" in activities
        or _concepts(item.text) & {"unit testing", "automated testing"}
    )
    if _contains(text, "testable code") and testing_evidence:
        supported.append("testing practices supporting testability")
    if _contains(text, "ai proficiency") and "LLM integration" in activities:
        supported.append("demonstrated LLM integration")
    if category == "responsibility":
        supported += sorted(
            name
            for name, pattern in _REQUEST_ACTIVITIES.items()
            if name in activities and re.search(pattern, text)
        )
        local_concepts = _concepts(item.text) | {
            _canonical(tag) for tag in item.tags if not _denied(tag, item)
        }
        supported += sorted(_concepts(requirement) & local_concepts)
    if supported:
        supported = list(dict.fromkeys(supported))
        label = (
            "Partial responsibility support"
            if category == "responsibility"
            else "Related support"
        )
        explanation = (
            f"{label}: {', '.join(supported)}; "
            "other requested claims are not established"
        )
        return 1, supported, explanation
    return 0, [], ""


def _support(requirement: str, category: str, item: _Evidence) -> tuple[int, list[str], str]:
    """0 = absent, 1 = related/partial, 2 = direct. Used by both outputs."""
    normalised = _normalise(requirement)
    concept = _canonical(requirement)
    kind = item.reference.source_type
    if _denied(requirement, item):
        return 0, [], ""
    if category == "qualification":
        if kind not in {"education", "certification"}:
            return 0, [], ""
        if _levels(normalised) and kind != "education":
            return 0, [], ""
        if _contains(normalised, "certified") and kind != "certification":
            return 0, [], ""
        if normalised == _normalise(item.reference.text):
            return 2, [item.reference.text], "Exact qualification"
        if _levels(normalised):
            evidence_degree = item.reference.text
            if not _subjects(_normalise(evidence_degree)):
                evidence_degree += " " + item.field
            if kind == "education" and _degree_pairs(normalised) & _degree_pairs(evidence_degree):
                return 2, [item.reference.text, item.field], "Degree level and subject match"
            return 0, [], ""
        # No fuzzy certification matching or subject-only qualification claims.
        return 0, [], ""

    # Treat this one explicit compound as a conjunction on a single record.
    if normalised == "c# .net":
        local = " ".join([item.text, *(_normalise(tag) for tag in item.tags)])
        if all(_contains(local, part) for part in ("c#", ".net")):
            direct = all(_contains(item.text, part) for part in ("c#", ".net"))
            basis = "description" if direct else "declarations"
            return (2 if direct else 1), ["C#", ".NET"], f"Same-record C# and .NET {basis}"
        return 0, [], ""

    tags = [tag for tag in item.tags if _canonical(tag) == concept]
    # A bounded exact phrase is enough for direct support of a concise skill.
    phrases = _CONCEPTS.get(concept, (normalised,))
    text_signals = [phrase for phrase in phrases if _contains(item.text, phrase)]
    broader = _BROADER.get(concept, set())
    text_signals += sorted(_concepts(item.text) & broader)
    if text_signals:
        return 2, list(dict.fromkeys(text_signals)), "Direct wording in evidence"
    if tags:
        strength = 1 if kind in {"skill", "work_experience", "project", "certification"} else 2
        return strength, tags, "Explicit local tags" if strength == 2 else "Declared skill or parent context"

    return _related_support(requirement, category, item)


def _practical_support(requirement: str, item: _Evidence) -> bool:
    """Require a matching activity or a signal inside the action/object span."""
    text = _normalise(requirement)
    concept = _canonical(requirement)
    for sentence in re.split(r"[.!?;\n](?=\s|$)", item.raw_text):
        positive = _positive_text(sentence)
        for name, pattern in _ACTIVITIES.items():
            for activity in re.finditer(pattern, positive):
                if concept == _canonical(name):
                    return True
                if any(_contains(activity.group(), phrase) for phrase in _CONCEPTS.get(concept, (text,))):
                    return True
                if _contains(text, "testable code") and name == "testing":
                    return True
                if _contains(text, "ai proficiency") and name == "LLM integration":
                    return True
                requested = _REQUEST_ACTIVITIES.get(name)
                if requested and re.search(requested, text):
                    return True
    return False


def _requirements(job: JobDescriptionAnalysis) -> list[tuple[str, str]]:
    """Retained private compatibility view; matching uses prepared records."""
    return [(item.text, "skill" if item.category == "other_keyword" else item.category)
            for item in prepare_requirements(job)]


@dataclass
class _Decision:
    strength: int = 0
    alternative: str = ""
    signals: list[MatchingSignal] = dataclass_field(default_factory=list)
    reason: str = ""
    practical: bool = False


def _names(concept: str, catalogue: TechnicalRelationshipCatalogue) -> tuple[str, ...]:
    names = [concept, *_CONCEPTS.get(concept, ())]
    if concept in catalogue.concepts:
        names += catalogue.concepts[concept].aliases
    return tuple(dict.fromkeys(names))


def _requirement_key(value: str, catalogue: TechnicalRelationshipCatalogue) -> str:
    """Equivalent wording only: retain substantive qualifiers and conjunctions."""
    value = _normalise(value)
    value = re.sub(r"^(?:experience (?:with|in|using)|knowledge of|proficiency in)\s+", "", value)
    value = re.sub(r"\s+experience$", "", value)
    aliases = {alias: concept for concept, names in _CONCEPTS.items() for alias in names}
    aliases.update({_normalise(alias): concept for concept, entry in catalogue.concepts.items()
                    for alias in (concept, *entry.aliases)})
    pattern = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
    return re.sub(r"(?<![a-z0-9+#.])(?:" + pattern + r")(?![a-z0-9+#.])",
                  lambda match: aliases[match.group()], value)


def _neutral_display(requirement: StructuredRequirement, catalogue: TechnicalRelationshipCatalogue) -> bool:
    options = {_requirement_key(option, catalogue) for option in requirement.alternatives}
    display = _requirement_key(requirement.text, catalogue)
    return display in options or {
        _requirement_key(part, catalogue) for part in re.split(r"\s+or\s+", requirement.text, flags=re.I)
    } == options


def _rejected(name: str, item: _Evidence, catalogue: TechnicalRelationshipCatalogue) -> bool:
    names = _names(name, catalogue)
    if name == "oracle database" and _denied("Oracle", item):
        return True
    if any(_denied(alias, item) for alias in names):
        return True
    # A local declaration cannot override an exclusively negative/future mention.
    mentioned = any(_contains(_normalise(item.raw_text), _normalise(alias)) for alias in names)
    positive = any(_contains(clause, _normalise(alias))
                   for clause, _ in item.statements for alias in names)
    return mentioned and not positive


def _activity(
    item: _Evidence, activity: str, names: tuple[str, ...] = (),
) -> tuple[str, str] | None:
    if item.reference.source_type in {"education", "certification", "skill"}:
        return None
    return next(((clause, origin) for clause, origin in item.statements
                 if demonstrates(activity, clause, names)), None)


def _signal_origin(signal: str, item: _Evidence) -> str:
    if item.reference.source_type in {"education", "certification"}:
        return "credential"
    concept = _canonical(signal)
    names = _CONCEPTS.get(concept, (signal,))
    for clause, origin in item.statements:
        if any(_contains(clause, _normalise(name)) for name in names):
            return origin
    for tag in item.tags:
        if _canonical(tag) == concept:
            return item.tag_origins[tag]
    return "wording"


def _observed_concepts(
    item: _Evidence, catalogue: TechnicalRelationshipCatalogue,
) -> list[tuple[str, MatchingSignal]]:
    observed = []
    # Longest known name wins within a phrase: Azure AI Search is not an Azure alias.
    labels = sorted(((name, concept) for concept, entry in catalogue.concepts.items()
                     for name in (concept, *entry.aliases)), key=lambda entry: len(entry[0]), reverse=True)
    for clause, origin in item.statements:
        remaining = clause
        for label, concept in labels:
            label = _normalise(label)
            if _contains(remaining, label) and not _rejected(concept, item, catalogue):
                observed.append((concept, MatchingSignal(signal=label, origin=origin)))
                remaining = re.sub(r"(?<![a-z0-9+#.])" + re.escape(label) + r"(?![a-z0-9+#.])", " ", remaining)
        if (
            "oracle database" in catalogue.concepts
            and oracle_database_development(clause)
            and not _rejected("oracle database", item, catalogue)
        ):
            observed.append(("oracle database", MatchingSignal(
                signal=clause, origin=origin, demonstrated_activity="technology_usage",
            )))
    for tag in item.tags:
        concept = catalogue.resolve_concept(tag)
        if concept and not _rejected(concept, item, catalogue):
            observed.append((concept, MatchingSignal(signal=tag, origin=item.tag_origins[tag])))
    return observed


def _direct_decision(
    requirement: StructuredRequirement, alternative: str, item: _Evidence,
    catalogue: TechnicalRelationshipCatalogue,
) -> _Decision:
    concept = _requirement_key(alternative, catalogue)
    if _rejected(concept, item, catalogue):
        return _Decision()
    category = "skill" if requirement.category == "other_keyword" else requirement.category
    strength, signals, reason = _support(alternative, category, item)
    if requirement.category == "qualification":
        if requirement.activity:
            return _Decision()
        return _Decision(strength, alternative,
                         [MatchingSignal(signal=signal, origin="credential") for signal in signals], reason)

    # Equivalent catalogue names supplement the retained V2 aliases.
    if concept in catalogue.concepts or concept != _normalise(alternative):
        for alias in _names(concept, catalogue):
            support, local, why = _support(alias, category, item)
            if support > strength:
                strength, signals, reason = support, local, why
    if concept == "oracle database":
        context = next(((clause, origin) for clause, origin in item.statements
                        if oracle_database_development(clause)), None)
        if context and _activity(item, "technology_usage", _names(concept, catalogue)):
            strength, signals, reason = 2, [context[0]], "Demonstrated Oracle SQL database development"

    names = ("c#", ".net") if concept == "c# .net" else _names(concept, catalogue)
    controlled = _activity(item, requirement.activity, names if concept in catalogue.concepts
                           and catalogue.concepts[concept].kind == "technology" else ()) if requirement.activity else None
    # Non-catalogue technology alternatives (e.g. Java) still bind to their own name.
    if requirement.activity and concept not in catalogue.concepts and category == "skill":
        controlled = _activity(item, requirement.activity, names)
    if concept == "c# .net" and requirement.activity:
        controlled = next(((clause, origin) for clause, origin in item.statements
                           if all(demonstrates(requirement.activity, clause, (name,)) for name in names)), None)

    if requirement.activity and not controlled:
        return _Decision()
    practical = False
    usage = None
    capability_activity = None
    main_api_support = None
    if strength:
        if item.reference.source_type in {"education", "certification", "skill"}:
            strength, reason = 1, "Relevant declaration or credential; practical activity is not established"
        elif reason == "Explicit local tags":
            # Local capability tags can be backed by the very same record's API work.
            demonstrated_capability = (
                concept in {"api development", "backend development"} and _activity(item, "api_development")
            )
            capability_activity = demonstrated_capability if demonstrated_capability else None
            strength = 2 if demonstrated_capability else 1
            reason = "Same-record API activity and capability tag" if demonstrated_capability else "Explicit local declaration; practical use is not established"
            practical = bool(demonstrated_capability)
        is_technology = (
            concept in catalogue.concepts and catalogue.concepts[concept].kind == "technology"
            or category == "skill" and concept not in _CONCEPTS and concept not in catalogue.concepts
            or concept in {"javascript", "typescript", "postgresql"}
        )
        if is_technology and strength == 2:
            usage = (
                next(((clause, origin) for clause, origin in item.statements
                      if all(demonstrates("technology_usage", clause, (name,)) for name in names)), None)
                if concept == "c# .net" else _activity(item, "technology_usage", names)
            )
            if usage:
                practical = True
            else:
                strength, reason = 1, "Technology wording; practical use is not established"

    # Simple controlled duties can match completed wording without literal tense equality.
    if controlled:
        clause, origin = controlled
        relevant_action_wording = (
            requirement.activity == "api_development" and re.search(r"\bapis?\b", _normalise(alternative))
            or requirement.activity == "cloud_deployment" and re.search(r"\bdeploy(?:ment)?\b", _normalise(alternative))
        )
        named_technology = concept in catalogue.concepts and catalogue.concepts[concept].kind == "technology"
        if not strength and not relevant_action_wording and not named_technology:
            return _Decision()
        simple = (
            requirement.activity == "api_development" and complete_api_request(alternative, clause)
            or requirement.activity == "cloud_deployment" and complete_cloud_request(alternative)
            or concept in catalogue.concepts and catalogue.concepts[concept].kind == "technology"
            or strength > 0 and concept in {"api development", "backend development", "cloud technology"}
            or category == "skill" and _neutral_display(requirement, catalogue)
        )
        if simple:
            strength, signals, reason, practical = 2, [alternative], f"Demonstrated {requirement.activity}", True
        elif not strength:
            strength, signals, reason, practical = 1, [requirement.activity], "Partial activity support; other requested claims are not established", True

    if category == "responsibility" and requirement.activity in {None, "api_development"}:
        main_api = next(((clause, origin) for clause, origin in item.statements
                         if api_development_without_maintenance(alternative, clause)), None)
        if main_api and _activity(item, "api_development") and strength < 2:
            strength, signals, practical = 2, ["API development"], True
            reason = "Demonstrated API development; API maintenance is not established by this evidence"
            # Legacy input has no activity metadata; preserve the actual wording origin.
            capability_activity = main_api
            main_api_support = main_api

    if category == "responsibility" and not requirement.activity and item.reference.source_type not in {"education", "certification", "skill"}:
        # Only a tense change of otherwise identical completed wording is direct.
        tense = {"collaborated": "collaborate", "designed": "design", "developed": "develop",
                 "maintained": "maintain", "built": "build", "implemented": "implement"}
        for clause, origin in item.statements:
            wording = " ".join(tense.get(word, word) for word in clause.split())
            if _contains(wording, _normalise(alternative)):
                strength, signals, reason, practical = 2, [alternative], "Completed responsibility wording", True
                break
    if strength == 2 and not _neutral_display(requirement, catalogue):
        strength, reason = 1, "Partial alternative support; additional display qualifiers are not established"
    # A service name containing a platform name is scoped wording, not equivalence.
    if concept in catalogue.concepts and catalogue.concepts[concept].kind == "technology":
        observed = {source for source, _ in _observed_concepts(item, catalogue)}
        if concept not in observed and any(_contains(_normalise(source), concept) for source in observed):
            strength, practical = min(strength, 1), False
            reason = "Platform named within a specific service; platform-wide activity is not established"
    structured_signals = [MatchingSignal(
        signal=signal, origin=controlled[1] if controlled else main_api_support[1] if main_api_support else _signal_origin(signal, item),
        demonstrated_activity="api_development" if main_api_support else requirement.activity if controlled else "technology_usage" if usage else None,
    ) for signal in signals]
    if capability_activity:
        structured_signals.append(MatchingSignal(
            signal=capability_activity[0], origin=capability_activity[1], demonstrated_activity="api_development",
        ))
    return _Decision(strength, alternative, structured_signals, reason, practical)


def _relationship_decision(
    requirement: StructuredRequirement, alternative: str, item: _Evidence,
    catalogue: TechnicalRelationshipCatalogue,
) -> _Decision:
    target = _requirement_key(alternative, catalogue)
    if requirement.category == "qualification" or target not in catalogue.concepts or _rejected(target, item, catalogue):
        return _Decision()
    best = _Decision()
    for source, signal in _observed_concepts(item, catalogue):
        for edge in catalogue.relationships_from(source):
            if edge.target != target:
                continue
            names = _names(source, catalogue)
            constrained = _activity(item, requirement.activity, names) if requirement.activity else None
            if requirement.activity and not constrained:
                continue
            condition = _activity(item, edge.strong_when, names) if edge.strong_when else None
            source_usage = _activity(item, "technology_usage", names)
            strength = 2 if edge.type == "broader" and condition else 1
            if strength == 2 and not _neutral_display(requirement, catalogue):
                strength = 1
            relationship = RelationshipReference(
                source=source, target=target, type=edge.type, confidence=edge.confidence,
            )
            provenance = signal.model_copy(update={
                "relationship": relationship,
                "demonstrated_activity": requirement.activity if constrained else edge.strong_when if condition else "technology_usage" if source_usage else None,
                "origin": constrained[1] if constrained else condition[1] if condition else signal.origin,
            })
            reason = f"Explicit {edge.type} relationship: {source} → {target}"
            if strength == 2:
                reason += f"; demonstrated {edge.strong_when}"
            elif edge.type == "transferable":
                reason += "; transferable relevance, not direct platform experience"
            elif edge.type == "uses_language":
                reason += "; does not independently demonstrate language proficiency"
            else:
                reason += "; the strong-support activity condition is not established"
            if requirement.activity:
                reason += f"; same-clause {requirement.activity}"
            decision = _Decision(strength, alternative, [provenance], reason, bool(constrained or condition or source_usage))
            if decision.strength > best.strength or decision.strength == best.strength and decision.practical and not best.practical:
                best = decision
    return best


def _evaluate_requirement(
    requirement: StructuredRequirement, item: _Evidence, catalogue: TechnicalRelationshipCatalogue,
) -> _Decision:
    best = _Decision()
    for alternative in requirement.alternatives:
        direct = _direct_decision(requirement, alternative, item, catalogue)
        related = _relationship_decision(requirement, alternative, item, catalogue)
        decision = related if (
            related.strength > direct.strength
            or related.strength == direct.strength and related.practical and not direct.practical
        ) else direct
        if decision.strength > best.strength or (
            decision.strength == best.strength and decision.practical and not best.practical
        ):
            best = decision
    return best


def match_experience_bank(
    bank: ExperienceBank,
    job: JobDescriptionAnalysis,
    *,
    catalogue: TechnicalRelationshipCatalogue | None = None,
) -> ExperienceBankMatch:
    catalogue = catalogue if catalogue is not None else load_technical_relationships()
    collected = _collect_evidence(bank)
    requirements = prepare_requirements(job, canonicalise=lambda value: _requirement_key(value, catalogue))
    buckets = {"strong": [], "related": [], "missing": []}
    evidence_matches: list[list[tuple[StructuredRequirement, _Decision, EvidenceSupport]]] = [[] for _ in collected]
    for requirement in requirements:
        matches = []
        signals = []
        for index, item in enumerate(collected):
            decision = _evaluate_requirement(requirement, item, catalogue)
            if decision.strength:
                support = EvidenceSupport(
                    requirement_id=requirement.id, evidence_id=item.reference.evidence_id,
                    status="strong" if decision.strength == 2 else "related",
                    selected_alternative=decision.alternative,
                    signals=decision.signals, explanation=decision.reason,
                )
                matches.append((item.reference, decision, support))
                signals.extend(signal.signal for signal in decision.signals)
                evidence_matches[index].append((requirement, decision, support))
        strength = max((match[1].strength for match in matches), default=0)
        status = {0: "missing", 1: "related", 2: "strong"}[strength]
        best = next((match for match in matches if match[1].strength == strength), None)
        buckets[status].append(MatchResult(
            requirement=requirement.text,
            status=status,
            matched_signals=list(dict.fromkeys(signals)),
            evidence=[match[0] for match in matches],
            requirement_details=requirement,
            selected_alternative=best[1].alternative if best else None,
            evidence_support=[match[2] for match in matches],
            explanation=(
                f"{best[1].reason}: {best[0].source_label}."
                if best else "No supporting evidence was found in the experience bank."
            ),
        ))
    ranked_with_priority: list[tuple[RankedEvidence, int]] = []
    for item, matches in zip(collected, evidence_matches):
        if not matches:
            continue
        # Only demonstrated, relevant activity earns the practical tie-break.
        has_wording_support = any(signal.origin in {"wording", "outcome", "credential"}
                                  for _, decision, _ in matches for signal in decision.signals)
        practical = any(decision.practical or (
            has_wording_support and item.reference.source_type not in {"education", "certification"}
            and _practical_support(decision.alternative, item)
        ) for _, decision, _ in matches)
        tie_break = 2 if practical else int(bool(item.text) and has_wording_support)
        # Each requirement contributes 10 for direct or 3 for related support.
        ranked_item = RankedEvidence(
            rank=0,
            evidence=item.reference,
            status="strong" if any(decision.strength == 2 for _, decision, _ in matches) else "related",
            matched_signals=[requirement.text for requirement, _, _ in matches],
            evidence_support=[support for _, _, support in matches],
            score=sum(10 if decision.strength == 2 else 3 for _, decision, _ in matches),
            explanation="; ".join(
                f"{requirement.text}: {'strong' if decision.strength == 2 else 'related'} ({decision.reason})"
                for requirement, decision, _ in matches
            ),
        )
        ranked_with_priority.append((ranked_item, tie_break))
    ranked_with_priority.sort(
        key=lambda entry: (entry[0].score, entry[1]), reverse=True
    )
    ranked = [item for item, _ in ranked_with_priority]
    for index, item in enumerate(ranked, 1):
        item.rank = index
    return ExperienceBankMatch(
        job_title=job.job_title,
        strong_matches=buckets["strong"],
        related_matches=buckets["related"],
        missing_requirements=buckets["missing"],
        ranked_evidence=ranked
    )
