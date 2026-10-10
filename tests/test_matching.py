from app.models import EvidenceItem, ExperienceBank, JobDescriptionAnalysis, WorkExperience
from app.services.matching import match_experience_bank


def test_matching_uses_explicit_evidence_and_reports_missing_requirements() -> None:
    bank = ExperienceBank(
        work_experience=[
            WorkExperience(
                employer="Example",
                role="Backend Engineer",
                skills=["Python"],
                technologies=["FastAPI"],
                achievements=[
                    EvidenceItem(
                        text="Built REST APIs for internal services",
                        skills=["REST APIs"],
                    )
                ],
            )
        ]
    )
    job = JobDescriptionAnalysis(
        job_title="Software Engineer",
        technical_skills=["Python", "Docker"],
    )

    result = match_experience_bank(bank, job)

    assert [item.requirement for item in result.strong_matches] == ["Python"]
    assert [item.requirement for item in result.missing_requirements] == ["Docker"]
    assert result.strong_matches[0].evidence[0].source_type == "work_experience"
    assert result.ranked_evidence[0].evidence.source_type == "achievement"


def test_matching_handles_common_aliases() -> None:
    bank = ExperienceBank(
        projects=[],
        work_experience=[
            WorkExperience(
                employer="Example",
                role="Engineer",
                technologies=["PostgreSQL"],
            )
        ],
    )

    result = match_experience_bank(
        bank,
        JobDescriptionAnalysis(job_title="Engineer", technical_skills=["Postgres"]),
    )

    assert len(result.strong_matches) == 1