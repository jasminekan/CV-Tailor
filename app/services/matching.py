import re

from app.models import EvidenceReference, ExperienceBank, ExperienceBankMatch
from app.models import JobDescriptionAnalysis, MatchResult, RankedEvidence


def _normalise(value: str) -> str:
    normalised = re.sub(r"[^a-z0-9+#.]", " ", value.lower())
    return re.sub(r"\s+", " ", normalised).strip()


def _signals(value: str) -> set[str]:
    normalised = _normalise(value)
    tokens = {normalised}
    if normalised.endswith("s"):
        tokens.add(normalised[:-1])
    aliases = {
        "rest api": "rest apis",
        "rest apis": "rest api",
        "javascript": "js",
        "typescript": "ts",
        "postgresql": "postgres",
    }
    if normalised in aliases:
        tokens.add(aliases[normalised])
    return tokens


def _match_signals(requirement: str, values: list[str]) -> list[str]:
    requirement_signals = _signals(requirement)
    return [value for value in values if requirement_signals & _signals(value)]


def _reference(
    evidence_id: str,
    source_type: str,
    source_label: str,
    text: str,
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=evidence_id,
        source_type=source_type,
        source_label=source_label,
        text=text,
    )


def _collect_evidence(bank: ExperienceBank) -> list[tuple[EvidenceReference, list[str]]]:
    collected: list[tuple[EvidenceReference, list[str]]] = []
    for skill in bank.skills:
        collected.append((
            _reference(f"skill:{_normalise(skill)}", "skill", "Skills", skill),
            [skill],
        ))
    for role in bank.work_experience:
        role_values = role.skills + role.technologies
        collected.append((
            _reference(role.id, "work_experience", f"{role.role} at {role.employer}", role.summary),
            role_values,
        ))
        for item in role.achievements:
            collected.append((
                _reference(item.id, "achievement", f"{role.role} at {role.employer}", item.text),
                role_values + item.skills + item.technologies,
            ))
    for project in bank.projects:
        project_values = project.skills + project.technologies
        collected.append((
            _reference(project.id, "project", project.name, project.description),
            project_values,
        ))
        for item in project.evidence:
            collected.append((
                _reference(item.id, "project_evidence", project.name, item.text),
                project_values + item.skills + item.technologies,
            ))
    for certification in bank.certifications:
        collected.append((
            _reference(certification.id, "certification", certification.name, certification.name),
            certification.skills + [certification.name],
        ))
    for education in bank.education:
        collected.append((
            _reference(education.id, "education", education.qualification, education.qualification),
            [education.qualification, education.field],
        ))
    for item in bank.additional_evidence:
        collected.append((_reference(item.id, "additional_evidence", "Additional evidence", item.text), item.skills + item.technologies))
    return collected


def _result(requirement: str, evidence: list[tuple[EvidenceReference, list[str]]]) -> MatchResult:
    matched_signals = [
        value
        for _, values in evidence
        for value in values
        if _signals(requirement) & _signals(value)
    ]
    status = "strong" if any(reference.source_type in {"achievement", "project_evidence", "work_experience"} for reference, _ in evidence) else "related"
    explanation = (
        f"Supported by {evidence[0][0].source_label}."
        if evidence else "No supporting evidence was found in the experience bank."
    )
    return MatchResult(
        requirement=requirement,
        status=status,
        matched_signals=list(dict.fromkeys(matched_signals)),
        evidence=[reference for reference, _ in evidence],
        explanation=explanation,
    )


def match_experience_bank(
    bank: ExperienceBank,
    job: JobDescriptionAnalysis,
) -> ExperienceBankMatch:
    collected = _collect_evidence(bank)
    requirements = job.technical_skills + job.other_keywords + job.qualifications
    strong_matches: list[MatchResult] = []
    related_matches: list[MatchResult] = []
    missing: list[MatchResult] = []

    for requirement in requirements:
        matches = [
            (reference, values)
            for reference, values in collected
            if _match_signals(requirement, values)
        ]
        result = _result(requirement, matches)
        if not matches:
            result.status = "missing"
            missing.append(result)
        elif result.status == "strong":
            strong_matches.append(result)
        else:
            related_matches.append(result)

    ranked: list[RankedEvidence] = []
    for reference, values in collected:
        matched = [requirement for requirement in requirements if _match_signals(requirement, values)]
        if not matched:
            continue
        score = len(matched) * 10
        if reference.source_type in {"achievement", "project_evidence"}:
            score += 5
        status = "strong" if reference.source_type in {"achievement", "project_evidence", "work_experience"} else "related"
        ranked.append(RankedEvidence(
            rank=0,
            evidence=reference,
            status=status,
            matched_signals=matched,
            score=score,
            explanation=f"{reference.source_label} provides evidence for {', '.join(matched)}.",
        ))
    ranked.sort(key=lambda item: item.score, reverse=True)
    for index, item in enumerate(ranked, start=1):
        item.rank = index

    return ExperienceBankMatch(
        job_title=job.job_title,
        strong_matches=strong_matches,
        related_matches=related_matches,
        missing_requirements=missing,
        ranked_evidence=ranked,
    )