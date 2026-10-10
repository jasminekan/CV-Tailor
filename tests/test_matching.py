import pytest

from app.models import (
    Certification, Education, EvidenceItem, ExperienceBank,
    JobDescriptionAnalysis, Project, WorkExperience,
)
from app.services.matching import match_experience_bank


def match(bank, **requirements):
    return match_experience_bank(
        bank,
        JobDescriptionAnalysis(job_title="Engineer", **requirements)
    )


def test_parent_tags_do_not_make_children_matches():
    bank = ExperienceBank(
        work_experience=[WorkExperience(
            id="role",
            employer="Example",
            role="Engineer",
            skills=["Python"],
            achievements=[EvidenceItem(id="bullet", text="Built REST APIs", skills=["REST APIs"])]
        )],
        projects=[Project(
            id="project",
            name="API",
            technologies=["Python"],
            evidence=[EvidenceItem(id="frontend", text="Created a responsive frontend")]
        )],
    )
    result = match(bank, technical_skills=["Python", "Docker"])
    assert not result.strong_matches
    assert [r.requirement for r in result.related_matches] == ["Python"]
    assert [r.requirement for r in result.missing_requirements] == ["Docker"]
    assert {e.evidence_id for e in result.related_matches[0].evidence} == {"role", "project"}
    assert {r.evidence.evidence_id for r in result.ranked_evidence} == {"role", "project"}


@pytest.mark.parametrize(
    "stored,requested",
    [
        ("PostgreSQL", "Postgres"),
        ("JS", "JavaScript"),
        ("TS", "TypeScript"),
        ("REST APIs", "REST API")
    ]
)
def test_aliases_are_symmetric(stored, requested):
    result = match(ExperienceBank(skills=[stored]), technical_skills=[requested])
    assert len(result.related_matches) == 1
    assert not result.strong_matches


def test_direct_evidence_ranks_above_declared_context():
    bank = ExperienceBank(
        skills=["Python"],
        projects=[Project(
            name="API",
            technologies=["Python"],
            evidence=[EvidenceItem(id="direct", text="Built services using Python")]
        )]
    )
    result = match(bank, technical_skills=["Python"])
    assert result.strong_matches[0].requirement == "Python"
    assert result.ranked_evidence[0].evidence.evidence_id == "direct"
    assert result.ranked_evidence[0].score == 10
    assert all(r.status == "related" and r.score == 3 for r in result.ranked_evidence[1:])


def test_untagged_descriptions_and_directional_testing():
    bank = ExperienceBank(
        work_experience=[WorkExperience(
            employer="Example",
            role="Engineer",
            summary="Worked in an Agile development environment."
        )],
        additional_evidence=[
            EvidenceItem(id="tests", text="Wrote 20+ unit tests."),
            EvidenceItem(id="mentor", text="Mentored two junior developers.")
        ],
        projects=[Project(name="Tests", description="Added automated tests for API endpoints.")],
    )
    result = match(
        bank,
        other_keywords=["Agile methodologies", "mentoring"],
        technical_skills=["testing", "unit testing", "automated testing"]
    )
    assert len(result.strong_matches) == 5
    generic = match(
        ExperienceBank(additional_evidence=[EvidenceItem(text="Performed software testing")]),
        technical_skills=["unit testing"]
    )
    assert generic.missing_requirements


@pytest.mark.parametrize("requirement,text", [
    ("Java", "Used JavaScript"), ("Go", "Worked on ongoing improvements"),
    ("C", "Built services in C#"), ("SQL", "Used PostgreSQL"),
    ("Python", "No Python experience."), ("unit testing", "Planning to write unit tests."),
])
def test_boundaries_and_obvious_negative_or_aspirational_text(requirement, text):
    result = match(
        ExperienceBank(additional_evidence=[EvidenceItem(text=text)]),
        technical_skills=[requirement]
    )
    assert result.missing_requirements


@pytest.mark.parametrize(
    "qualification",
    [
        "BSc Hons Computer Science",
        "Bachelor's degree in Computer Science",
        "B.Sc. Computer Science"
    ]
)
def test_degree_level_and_subject_match_together(qualification):
    bank = ExperienceBank(education=[Education(
        qualification=qualification,
        institution="Example",
        field="Computer Science"
    )])
    result = match(
        bank,
        qualifications=["Bachelor’s or Master’s degree in Computer Science, Engineering, or a related field"]
    )
    assert len(result.strong_matches) == 1
    assert result.ranked_evidence[0].status == "strong"


def test_wrong_degree_level_subject_and_subject_only_claims_do_not_match():
    bank = ExperienceBank(
        education=[Education(
            qualification="BSc",
            field="Computer Science",
            institution="Example"
        )],
        skills=["Computer Science"]
    )
    result = match(
        bank,
        qualifications=["Master's degree in Computer Science", "Bachelor's degree in Engineering"]
    )
    assert len(result.missing_requirements) == 2


def test_certification_name_can_be_strong_but_skill_is_not_a_certificate():
    bank = ExperienceBank(certifications=[Certification(
        name="AWS Certified Cloud Practitioner",
        skills=["AWS"]
    )])
    result = match(
        bank,
        qualifications=["AWS Certified Cloud Practitioner", "AWS Certified Developer"]
    )
    assert len(result.strong_matches) == 1
    assert len(result.missing_requirements) == 1


def test_local_tags_and_outcomes_are_preserved_and_matched():
    item = EvidenceItem(
        text="Improved an internal service",
        skills=["Python"],
        outcomes=["Added automated tests"]
    )
    bank = ExperienceBank(additional_evidence=[item])
    before = bank.model_dump()
    result = match(bank, technical_skills=["Python", "automated testing"])
    assert len(result.strong_matches) == 2
    assert bank.model_dump() == before


def test_responsibilities_are_partial_when_only_some_obligations_are_supported():
    bank = ExperienceBank(additional_evidence=[EvidenceItem(text="Mentored junior developers")])
    result = match(
        bank,
        responsibilities=[
            "Mentor junior team members and lead project deadlines",
            "Design scalable microservices"
        ]
    )
    assert len(result.related_matches) == 1
    assert len(result.missing_requirements) == 1
    assert result.ranked_evidence[0].status == "related"
    assert "Partial responsibility support" in result.related_matches[0].explanation


def test_equivalent_requirements_do_not_inflate_scores_and_ties_are_stable():
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(id="first", text="Used JavaScript"),
        EvidenceItem(id="second", text="Used JavaScript")
    ])
    result = match(
        bank,
        technical_skills=["JavaScript", "JS", "javascript"],
        other_keywords=["JavaScript"],
        responsibilities=["JavaScript"]
    )
    assert len(result.strong_matches) == 1
    assert [r.score for r in result.ranked_evidence] == [10, 10]
    assert [r.evidence.evidence_id for r in result.ranked_evidence] == ["first", "second"]
    assert result == match(
        bank,
        technical_skills=["JavaScript", "JS", "javascript"],
        other_keywords=["JavaScript"],
        responsibilities=["JavaScript"]
    )


def test_rank_and_requirement_strength_share_the_same_per_requirement_decisions():
    bank = ExperienceBank(additional_evidence=[EvidenceItem(text="Mentored junior developers using Python")])
    result = match(
        bank,
        technical_skills=["Python"],
        responsibilities=["Mentor junior developers and manage deadlines"]
    )
    assert len(result.strong_matches) == len(result.related_matches) == 1
    ranked = result.ranked_evidence[0]
    assert ranked.status == "strong"  # Best support, as at requirement level.
    assert ranked.score == 13
    assert "Python: strong" in ranked.explanation
    assert "manage deadlines: related" in ranked.explanation


def test_backend_child_tags_are_local_and_frontend_bullet_is_excluded():
    bank = ExperienceBank(projects=[Project(
        name="CV Tailor", skills=["backend development"],
        evidence=[
            EvidenceItem(
                id="api",
                text="Implemented REST API endpoints",
                skills=["backend development"]
            ),
            EvidenceItem(id="ui", text="Created a responsive frontend"),
        ],
    )])
    result = match(bank, technical_skills=["backend development"])
    assert {e.evidence_id for e in result.strong_matches[0].evidence} == {
        bank.projects[0].id,
        "api"
    }
    assert result.ranked_evidence[0].evidence.evidence_id == "api"
    assert "ui" not in {r.evidence.evidence_id for r in result.ranked_evidence}


def test_existing_copied_tags_are_not_silently_removed():
    bank = ExperienceBank(projects=[Project(
        name="API", skills=["backend development"],
        evidence=[EvidenceItem(
            text="Created a responsive frontend",
            skills=["backend development"]
        )],
    )])
    before = bank.model_dump_json()
    result = match(bank, technical_skills=["backend development"])
    # Provenance is absent: an explicit child claim is retained until reviewed.
    assert result.strong_matches
    assert bank.model_dump_json() == before


def test_compound_requires_same_record_and_does_not_inherit():
    bank = ExperienceBank(work_experience=[WorkExperience(
        employer="Example", role="Engineer", technologies=["C#", ".NET"],
        achievements=[EvidenceItem(text="Built a frontend")],
    )])
    result = match(bank, technical_skills=["C# .NET"])
    assert len(result.related_matches) == 1
    assert len(result.related_matches[0].evidence) == 1
    assert result.related_matches[0].evidence[0].source_type == "work_experience"
    split = match(ExperienceBank(skills=["C#", ".NET"]), technical_skills=["C# .NET"])
    assert split.missing_requirements


def test_compound_direct_description_is_strong():
    result = match(
        ExperienceBank(additional_evidence=[EvidenceItem(text="Built services using C# and .NET")]),
        technical_skills=["C# .NET"]
    )
    assert result.strong_matches


@pytest.mark.parametrize(
    "requirement",
    [
        "testable code",
        "Write testable code",
        "Write clean, maintainable, extendable, and testable code"
    ]
)
def test_tests_support_testability_only_as_related(requirement):
    bank = ExperienceBank(additional_evidence=[EvidenceItem(text="Wrote 20 unit tests to improve coverage")])
    result = match(bank, responsibilities=[requirement])
    assert result.related_matches
    assert "other requested claims are not established" in result.related_matches[0].explanation
    assert result.ranked_evidence[0].status == "related"
    assert result.ranked_evidence[0].score == 3


@pytest.mark.parametrize(
    "text",
    [
        "Built an API integration",
        "Worked on AI-focused projects",
        "Planning to integrate an LLM API"
    ]
)
def test_ai_proficiency_requires_demonstrated_llm_integration(text):
    assert match(
        ExperienceBank(additional_evidence=[EvidenceItem(text=text)]),
        other_keywords=["AI proficiency"]
    ).missing_requirements


def test_llm_integration_and_mentorship():
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(text="Integrated an LLM API to extract structured information"),
        EvidenceItem(text="Mentored junior developers")
    ])
    result = match(bank, other_keywords=["AI proficiency", "mentorship"])
    assert [r.requirement for r in result.related_matches] == ["AI proficiency"]
    assert [r.requirement for r in result.strong_matches] == ["mentorship"]


@pytest.mark.parametrize("text,requirement", [
    ("Designed and implemented REST API endpoints", "Design and develop APIs"),
    (
        "Built an automated monitoring workflow for production alerts",
        "Build, own, and operate your systems to high levels of resilience and service"
    ),
    ("Led two engineering projects", "Lead and drive specific projects critical to company needs"),
    ("Owned production services", "Build, own, and operate systems"),
    (
        "Managed project deadlines and deliverables",
        "Lead project priorities, deadlines, and deliverables"
    ),
])
def test_explicit_engineering_activities_support_responsibilities(text, requirement):
    result = match(
        ExperienceBank(additional_evidence=[EvidenceItem(text=text)]),
        responsibilities=[requirement]
    )
    assert result.related_matches
    assert "other requested claims" in result.related_matches[0].explanation


@pytest.mark.parametrize(
    "requirement",
    [
        "Lead engineering projects",
        "Own production systems",
        "Manage project deadlines",
        "Define and design loosely coupled, scalable systems",
        "clean code",
        "microservices architecture",
        "Go",
        "payments knowledge"
    ]
)
def test_unrelated_implementation_does_not_support_unsupported_claims(requirement):
    result = match(
        ExperienceBank(additional_evidence=[EvidenceItem(text="Implemented REST API endpoints")]),
        responsibilities=[requirement]
    )
    assert result.missing_requirements


def test_unrelated_api_activity_does_not_win_agile_tie():
    bank = ExperienceBank(
        work_experience=[WorkExperience(
            employer="Example",
            role="Engineer",
            summary="Worked in an Agile environment"
        )],
        additional_evidence=[EvidenceItem(
            id="practical",
            text="Implemented API endpoints in an Agile environment"
        )],
    )
    result = match(bank, other_keywords=["Agile"])
    assert [r.score for r in result.ranked_evidence] == [10, 10]
    assert result.ranked_evidence[0].evidence.source_type == "work_experience"
    assert all(r.status == "strong" for r in result.ranked_evidence)


def test_grouped_degree_alternatives_are_one_requirement_and_certificate_stays_independent():
    degree = "Bachelor's or Master's degree in Computer Science, Engineering, or a related field"
    bank = ExperienceBank(education=[Education(
        qualification="BSc Hons Computer Science",
        institution="Example",
        field="Computer Science"
    )])
    result = match(bank, qualifications=[degree, "AWS Certified Developer"])
    assert [r.requirement for r in result.strong_matches] == [degree]
    assert [r.requirement for r in result.missing_requirements] == ["AWS Certified Developer"]
    assert result.ranked_evidence[0].score == 10


@pytest.mark.parametrize("wording", ["team mentorship", "team mentoring", "team-mentorship"])
def test_team_mentorship_matches_direct_mentoring(wording):
    bank = ExperienceBank(additional_evidence=[EvidenceItem(text="Mentored two junior developers")])
    result = match(bank, other_keywords=[wording])
    assert result.strong_matches
    assert result.ranked_evidence[0].score == 10


@pytest.mark.parametrize(
    "wording",
    ["full-stack development", "full stack development", "fullstack development"]
)
def test_full_stack_project_description_does_not_propagate_to_children(wording):
    bank = ExperienceBank(projects=[Project(
        id="project", name="CV Tailor", description="Developed a full-stack application using Python and JavaScript",
        evidence=[
            EvidenceItem(id="api", text="Built REST API endpoints"),
            EvidenceItem(id="ui", text="Built a responsive frontend")
        ],
    )])
    result = match(bank, technical_skills=[wording])
    assert [e.evidence_id for e in result.strong_matches[0].evidence] == ["project"]
    assert [r.evidence.evidence_id for r in result.ranked_evidence] == ["project"]
    assert result.ranked_evidence[0].score == 10


def test_separate_backend_and_frontend_records_do_not_establish_full_stack():
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(text="Built backend services"),
        EvidenceItem(text="Built frontend interfaces")
    ])
    assert match(bank, technical_skills=["full-stack development"]).missing_requirements


@pytest.mark.parametrize("denial,tag", [
    ("No Python experience", "Python"),
    ("No experience with Python", "Python"),
    ("Never used JavaScript", "JS"),
    ("Lacking PostgreSQL knowledge", "Postgres"),
])
def test_explicit_denial_overrides_local_tags_only(denial, tag):
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(id="denied", text=denial, skills=[tag]),
        EvidenceItem(id="positive", text=f"Built services using {tag}"),
    ])
    result = match(bank, technical_skills=[tag])
    assert result.strong_matches
    assert [e.evidence_id for e in result.strong_matches[0].evidence] == ["positive"]
    assert [r.evidence.evidence_id for r in result.ranked_evidence] == ["positive"]


def test_denial_in_outcome_overrides_tags_without_removing_unrelated_capability():
    bank = ExperienceBank(additional_evidence=[EvidenceItem(
        text="Implemented services using FastAPI", skills=["Python", "FastAPI"],
        outcomes=["No Python experience"],
    )])
    result = match(bank, technical_skills=["Python", "FastAPI"])
    assert [r.requirement for r in result.missing_requirements] == ["Python"]
    assert [r.requirement for r in result.strong_matches] == ["FastAPI"]


def test_denied_tags_cannot_supply_partial_responsibility_support():
    bank = ExperienceBank(additional_evidence=[EvidenceItem(
        text="No mentoring experience", skills=["mentorship"],
    )])
    result = match(bank, responsibilities=["Mentor junior developers and manage deadlines"])
    assert result.missing_requirements


@pytest.mark.parametrize("qualification,field,supported", [
    ("BSc", "Computer Science", False),
    ("BSc", "Engineering", True),
    ("MSc", "Computer Science", True),
    ("MSc", "Engineering", False),
])
def test_degree_alternatives_preserve_level_subject_pairs(qualification, field, supported):
    bank = ExperienceBank(education=[Education(
        qualification=qualification, field=field, institution="Example",
    )])
    result = match(bank, qualifications=["BSc in Engineering or MSc in Computer Science"])
    assert bool(result.strong_matches) == supported
    assert bool(result.missing_requirements) != supported


@pytest.mark.parametrize("qualification,field", [
    ("BSc", "Computer Science"), ("MSc", "Engineering"),
])
def test_shared_degree_levels_and_subjects_remain_supported(qualification, field):
    bank = ExperienceBank(education=[Education(
        qualification=qualification, field=field, institution="Example",
    )])
    result = match(bank, qualifications=[
        "Bachelor's or Master's degree in Computer Science, Engineering, or a related field",
    ])
    assert result.strong_matches


def test_joint_degree_requirements_are_not_treated_as_alternatives():
    bank = ExperienceBank(education=[Education(
        qualification="BSc Computer Science", institution="Example",
    )])
    assert match(bank, qualifications=["BSc in Computer Science and MSc in Engineering"]).missing_requirements


@pytest.mark.parametrize("requirements", [
    ["REST API", "REST APIs", "API development"],
    ["API development", "REST APIs", "REST API"],
])
def test_overlapping_api_aliases_have_one_key_and_one_reward(requirements):
    bank = ExperienceBank(additional_evidence=[EvidenceItem(text="Implemented REST API endpoints")])
    result = match(bank, technical_skills=requirements)
    assert len(result.strong_matches) == 1
    assert result.strong_matches[0].requirement == requirements[0]
    assert result.ranked_evidence[0].score == 10


def test_alias_groups_do_not_overlap():
    from app.services.matching import _CONCEPTS
    aliases = [alias for group in _CONCEPTS.values() for alias in group]
    assert len(aliases) == len(set(aliases))


def test_unrelated_activity_does_not_win_tie_for_requirement():
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(id="plain", text="Worked in an Agile environment"),
        EvidenceItem(id="unrelated", text="Worked in an Agile environment. Built API endpoints."),
    ])
    result = match(bank, other_keywords=["Agile"])
    assert [r.score for r in result.ranked_evidence] == [10, 10]
    assert [r.evidence.evidence_id for r in result.ranked_evidence] == ["plain", "unrelated"]


def test_relevant_activity_still_wins_tie_and_scores_are_unchanged():
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(id="description", text="Experience with API development"),
        EvidenceItem(id="practical", text="Implemented API endpoints"),
    ])
    result = match(bank, technical_skills=["API development"])
    assert [r.evidence.evidence_id for r in result.ranked_evidence] == ["practical", "description"]
    assert [r.score for r in result.ranked_evidence] == [10, 10]


def test_unrelated_action_in_same_sentence_does_not_earn_practical_priority():
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(id="plain", text="Worked in an Agile environment"),
        EvidenceItem(id="unrelated", text="Implemented API endpoints in an Agile environment"),
    ])
    result = match(bank, other_keywords=["Agile"])
    assert [r.evidence.evidence_id for r in result.ranked_evidence] == ["plain", "unrelated"]
    assert [r.score for r in result.ranked_evidence] == [10, 10]
