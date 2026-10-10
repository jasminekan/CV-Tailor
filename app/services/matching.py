"""Deterministic matching of local evidence, without inheriting parent claims."""

import re
from dataclasses import dataclass

from app.models import (
    EvidenceReference,
    ExperienceBank,
    ExperienceBankMatch,
    JobDescriptionAnalysis,
    MatchResult,
    RankedEvidence,
)


def _normalise(value: str) -> str:
    value = value.lower().replace("’", "'")
    value = re.sub(r"\b(bachelor|master)'s\b", r"\1s", value)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#.]", " ", value)).strip().rstrip(".")


# Equivalences only. Broader support is kept separate below.
_CONCEPTS = {
    "javascript": ("javascript", "js"),
    "typescript": ("typescript", "ts"),
    "postgresql": ("postgresql", "postgres"),
    "rest api": ("rest api", "rest apis"),
    "api development": (
        "api development",
        "api design",
        "api endpoint",
        "api endpoints",
        "rest api",
        "rest apis"
    ),
    "backend development": ("backend development", "back end development", "backend"),
    "full stack development": (
        "full stack development",
        "fullstack development",
        "full stack application",
        "full stack applications",
        "fullstack application",
        "fullstack applications"
    ),
    "agile": ("agile", "agile methodologies", "agile environment", "agile environments"),
    "testing": ("testing", "software testing"),
    "unit testing": ("unit testing", "unit test", "unit tests"),
    "automated testing": ("automated testing", "automated test", "automated tests"),
    "mentoring": (
        "mentoring",
        "mentored",
        "mentor",
        "mentorship",
        "team mentorship",
        "team mentoring"
    ),
    "debugging": ("debugging", "debugged"),
    "code reviews": ("code reviews", "code review"),
    "stakeholder communication": ("stakeholder communication", "stakeholder interaction"),
}
# Specific practices support generic testing, never the reverse.
_BROADER = {"testing": {"unit testing", "automated testing"}}


def _contains(text: str, phrase: str) -> bool:
    return bool(phrase) and re.search(
        r"(?<![a-z0-9+#.])" + re.escape(phrase) + r"(?![a-z0-9+#.])",
        text
    ) is not None


def _canonical(value: str) -> str:
    value = _normalise(value)
    for concept, aliases in _CONCEPTS.items():
        if value in aliases:
            return concept
    return value


def _concepts(value: str) -> set[str]:
    value = _normalise(value)
    return {
        concept
        for concept, aliases in _CONCEPTS.items()
        if any(_contains(value, alias) for alias in aliases)
    }


def _positive_text(text: str) -> str:
    # Do not turn obvious denials or aspirations into demonstrated experience.
    parts = re.split(r"[.!?;\n](?=\s|$)", text)
    return " ".join(_normalise(part) for part in parts if not re.search(
        r"\b(no|not|never|without|lack|lacks|lacking|learning|learn|plan|planning|hope|aspire|aspiring)\b", part, re.I
    ))


@dataclass
class _Evidence:
    reference: EvidenceReference
    tags: list[str]
    text: str
    field: str = ""


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
    ) -> None:
        collected.append(_Evidence(
            EvidenceReference(
                evidence_id=item_id,
                source_type=source_type,
                source_label=label,
                text=text
            ),
            tags, _positive_text(". ".join([text, *outcomes])), field,
        ))

    for skill in bank.skills:
        add(f"skill:{_normalise(skill)}", "skill", "Skills", "", [skill])
        collected[-1].reference.text = skill
    for role in bank.work_experience:
        label = f"{role.role} at {role.employer}"
        add(role.id, "work_experience", label, role.summary, role.skills + role.technologies)
        for item in role.achievements:
            add(
                item.id,
                "achievement",
                label,
                item.text,
                item.skills + item.technologies,
                outcomes=item.outcomes
            )
    for project in bank.projects:
        add(
            project.id,
            "project",
            project.name,
            project.description,
            project.skills + project.technologies
        )
        for item in project.evidence:
            add(
                item.id,
                "project_evidence",
                project.name,
                item.text,
                item.skills + item.technologies,
                outcomes=item.outcomes
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
            item.skills + item.technologies,
            outcomes=item.outcomes
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
        local_concepts = _concepts(item.text) | {_canonical(tag) for tag in item.tags}
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
    if category == "qualification":
        if kind not in {"education", "certification"}:
            return 0, [], ""
        if normalised == _normalise(item.reference.text):
            return 2, [item.reference.text], "Exact qualification"
        levels = _levels(normalised)
        if levels:
            subjects = _subjects(normalised)
            evidence_subjects = _subjects(_normalise(item.reference.text + " " + item.field))
            if kind == "education" and levels & _levels(item.text) and subjects & evidence_subjects:
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


def _requirements(job: JobDescriptionAnalysis) -> list[tuple[str, str]]:
    requirements: list[tuple[str, str]] = []
    seen: set[str] = set()
    # Qualifications retain their category even if duplicated elsewhere.
    for category, values in (
        ("qualification", job.qualifications),
        ("skill", job.technical_skills + job.other_keywords),
        ("responsibility", job.responsibilities)
    ):
        for value in values:
            key = _canonical(value)
            if key and key not in seen:
                seen.add(key)
                requirements.append((value, category))
    return requirements


def match_experience_bank(
    bank: ExperienceBank,
    job: JobDescriptionAnalysis
) -> ExperienceBankMatch:
    collected = _collect_evidence(bank)
    requirements = _requirements(job)
    buckets = {"strong": [], "related": [], "missing": []}
    evidence_matches: list[list[tuple[str, int, str]]] = [[] for _ in collected]
    for requirement, category in requirements:
        matches = []
        signals = []
        for index, item in enumerate(collected):
            strength, local_signals, reason = _support(requirement, category, item)
            if strength:
                matches.append((item.reference, strength, reason))
                signals.extend(local_signals)
                evidence_matches[index].append((requirement, strength, reason))
        strength = max((match[1] for match in matches), default=0)
        status = {0: "missing", 1: "related", 2: "strong"}[strength]
        best = next((match for match in matches if match[1] == strength), None)
        buckets[status].append(MatchResult(
            requirement=requirement,
            status=status,
            matched_signals=list(dict.fromkeys(signals)),
            evidence=[match[0] for match in matches],
            explanation=(
                f"{best[2]}: {best[0].source_label}."
                if best else "No supporting evidence was found in the experience bank."
            ),
        ))
    ranked_with_priority: list[tuple[RankedEvidence, int]] = []
    for item, matches in zip(collected, evidence_matches):
        if not matches:
            continue
        # Only demonstrated, relevant activity earns the practical tie-break.
        has_support_beyond_tags = any(
            reason != "Declared skill or parent context" for _, _, reason in matches
        )
        practical = bool(_activities(item)) and has_support_beyond_tags
        tie_break = 2 if practical else int(bool(item.text) and has_support_beyond_tags)
        # Each requirement contributes 10 for direct or 3 for related support.
        ranked_item = RankedEvidence(
            rank=0,
            evidence=item.reference,
            status="strong" if any(strength == 2 for _, strength, _ in matches) else "related",
            matched_signals=[requirement for requirement, _, _ in matches],
            score=sum(10 if strength == 2 else 3 for _, strength, _ in matches),
            explanation="; ".join(
                f"{requirement}: {'strong' if strength == 2 else 'related'} ({reason})"
                for requirement, strength, reason in matches
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
