"""V3.2.4 uses controlled bank records and analysis; no live extraction or user data."""

from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import (
    Certification, Education, EvidenceItem, ExperienceBank, JobDescriptionAnalysis,
    Project, StructuredRequirement, WorkExperience,
)
from app.services.current_cv import build_skill_catalogue
from app.services.job_extraction import analysis_from_extraction
from app.services.matching import match_experience_bank
from app.services.technical_relationships import (
    TechnicalRelationshipCatalogue, TechnicalRelationshipCatalogueError, load_technical_relationships,
)
from evaluations.extraction.harness import load_fixtures


def requirement(text, *, alternatives=None, category="skill", activity=None,
                importance="unspecified", id="r1"):
    return StructuredRequirement(
        id=id, text=text, source_text=f"Original description: {text}",
        category=category, importance=importance, alternatives=alternatives or [text], activity=activity,
    )


def analysis(*requirements):
    return JobDescriptionAnalysis(job_title="Engineer", requirements=list(requirements))


def practical(text, **fields):
    return ExperienceBank(additional_evidence=[EvidenceItem(id="e1", text=text, **fields)])


def match(bank, *requirements, **kwargs):
    return match_experience_bank(bank, analysis(*requirements), **kwargs)


def rows(result):
    return [*result.strong_matches, *result.related_matches, *result.missing_requirements]


def outcome(bank, text, **fields):
    result = match(bank, requirement(text, **fields))
    assert len(rows(result)) == 1
    return rows(result)[0], result


def test_structured_or_uses_one_supported_choice_one_obligation_and_one_reward():
    bank = practical("Built services using Python")
    item = requirement("Experience with Python or Java", alternatives=["Python", "Java"], importance="required")
    result = match(bank, item)
    row = result.strong_matches[0]
    assert len(rows(result)) == 1
    assert row.selected_alternative == "Python"
    assert row.requirement_details == item
    assert row.evidence_support[0].selected_alternative == "Python"
    assert result.ranked_evidence[0].score == 10
    assert not result.missing_requirements


def test_both_or_choices_on_one_record_do_not_reward_twice_and_ties_keep_option_order():
    result = match(practical("Used Python and Java"), requirement(
        "Java or Python", alternatives=["Java", "Python"],
    ))
    assert result.strong_matches[0].selected_alternative == "Java"
    assert result.ranked_evidence[0].score == 10
    assert len(result.ranked_evidence[0].evidence_support) == 1


def test_stronger_later_alternative_beats_earlier_related_choice():
    bank = practical("Used Python to implement services", technologies=["Java"])
    result = match(bank, requirement("Java or Python", alternatives=["Java", "Python"]))
    assert result.strong_matches[0].selected_alternative == "Python"
    assert result.ranked_evidence[0].score == 10


def test_independent_and_records_keep_the_unsupported_language_separate():
    result = match(practical("Used Python"), requirement("Python"), requirement("Java", id="java"))
    assert [row.requirement for row in result.strong_matches] == ["Python"]
    assert [row.requirement for row in result.missing_requirements] == ["Java"]


def test_preferred_and_required_are_metadata_with_identical_existing_weights():
    result = match(practical("Used AWS"), requirement("AWS", id="required", importance="required"),
                   requirement("AWS", id="preferred", importance="preferred"))
    assert [row.requirement_details.importance for row in result.strong_matches] == ["required", "preferred"]
    assert result.ranked_evidence[0].score == 20
    assert [support.requirement_id for support in result.ranked_evidence[0].evidence_support] == ["required", "preferred"]


def test_equivalent_technology_aliases_and_neutral_display_wording_deduplicate():
    result = match(practical("Used Microsoft Azure"),
                   requirement("Experience with Azure", alternatives=["Azure"]),
                   requirement("Microsoft Azure", id="r2"))
    assert len(rows(result)) == 1
    assert result.strong_matches[0].requirement_details.id == "r1"
    assert result.ranked_evidence[0].score == 10


def test_same_technology_with_different_activities_remains_independent():
    result = match(practical("Integrated Azure into a reporting service"),
                   requirement("Azure", activity="technology_usage"),
                   requirement("Azure", id="deploy", activity="cloud_deployment"))
    assert [row.requirement_details.id for row in result.strong_matches] == ["r1"]
    assert [row.requirement_details.id for row in result.missing_requirements] == ["deploy"]
    assert result.ranked_evidence[0].score == 10


def test_substantive_display_qualifiers_cannot_be_lost_through_an_atomic_alternative():
    row, _ = outcome(practical("Used Python"), "Develop secure Python APIs", alternatives=["Python"])
    assert row.status == "related"
    assert "additional" in row.explanation


@pytest.mark.parametrize("stored, requested", [
    ("Microsoft Azure", "Azure"), ("Azure", "Microsoft Azure"),
    ("Amazon Web Services", "AWS"), ("AWS", "Amazon Web Services"),
    ("Structured Query Language", "SQL"),
])
def test_catalogue_aliases_are_direct_equivalent_terminology(stored, requested):
    row, result = outcome(practical(f"Used {stored}"), requested)
    assert row.status == "strong"
    assert result.ranked_evidence[0].score == 10
    assert all(signal.relationship is None for signal in row.evidence_support[0].signals)


@pytest.mark.parametrize("text", [
    "Used Azure for a reporting service",
    "Integrated Azure AI Search into a retrieval service",
    "Deployed an application to AWS",
])
def test_practical_specific_cloud_work_supports_the_broader_capability(text):
    row, result = outcome(practical(text), "cloud technologies")
    assert row.status == "strong"
    signal = row.evidence_support[0].signals[0]
    assert signal.relationship.target == "cloud technology"
    assert signal.relationship.type == "broader"
    assert signal.relationship.confidence == "high"
    assert signal.demonstrated_activity == "technology_usage"
    assert result.ranked_evidence[0].score == 10


@pytest.mark.parametrize("bank", [
    ExperienceBank(skills=["Azure"]),
    practical("Azure"),
    practical("Reporting service", technologies=["Azure"]),
    ExperienceBank(projects=[Project(id="p", name="Reporting", technologies=["Azure"])]),
    ExperienceBank(certifications=[Certification(id="cert", name="Azure Certification", skills=["Azure"])]),
])
def test_cloud_declarations_and_credentials_provide_related_broad_relevance(bank):
    row, result = outcome(bank, "cloud technologies")
    assert row.status == "related"
    assert result.ranked_evidence[0].score == 3
    assert row.evidence_support[0].signals[0].demonstrated_activity is None


def test_azure_is_transferable_to_aws_but_never_strong_from_that_edge():
    row, result = outcome(practical("Used Azure to implement a service"), "AWS")
    assert row.status == "related"
    assert row.evidence_support[0].signals[0].relationship.type == "transferable"
    assert row.evidence_support[0].signals[0].relationship.confidence == "medium"
    assert "not direct platform experience" in row.explanation
    assert result.ranked_evidence[0].score == 3


def test_no_reverse_edge_is_inferred_when_an_explicit_direction_is_removed():
    payload = load_technical_relationships().model_dump(by_alias=True)
    payload["relationships"] = [edge for edge in payload["relationships"]
                               if (edge["from"], edge["to"]) != ("aws", "azure")]
    catalogue = TechnicalRelationshipCatalogue.model_validate(payload)
    row = rows(match(practical("Used AWS"), requirement("Azure"), catalogue=catalogue))[0]
    assert row.status == "missing"
    reverse = rows(match(practical("Used Azure"), requirement("AWS"), catalogue=catalogue))[0]
    assert reverse.status == "related"


def test_relationships_never_traverse_multiple_edges():
    payload = load_technical_relationships().model_dump(by_alias=True)
    payload["concepts"]["language ecosystem"] = {"kind": "capability"}
    payload["relationships"].append({
        "from": "python", "to": "language ecosystem", "type": "broader", "confidence": "high",
    })
    catalogue = TechnicalRelationshipCatalogue.model_validate(payload)
    result = match(practical("Used FastAPI"), requirement("language ecosystem"), catalogue=catalogue)
    assert result.missing_requirements
    assert not result.ranked_evidence


@pytest.mark.parametrize("text, target", [
    ("Built REST API endpoints using FastAPI", "backend development"),
    ("Maintained APIs using FastAPI", "API development"),
    ("Integrated Oracle Database into a reporting service", "relational databases"),
])
def test_broader_engineering_capabilities_require_the_catalogue_activity(text, target):
    row, _ = outcome(practical(text), target)
    assert row.status == "strong"
    assert row.evidence_support[0].signals[0].relationship.type == "broader"


@pytest.mark.parametrize("text, target", [
    ("FastAPI", "backend development"), ("Used FastAPI for a command-line tool", "API development"),
    ("Oracle Database", "relational databases"),
])
def test_broader_conditions_are_not_proved_by_a_name_or_unrelated_use(text, target):
    row, _ = outcome(practical(text), target)
    assert row.status == "related"


@pytest.mark.parametrize("text, target", [
    ("Built REST APIs using FastAPI", "Python"),
    ("Used Oracle Database to query data", "SQL"),
])
def test_uses_language_is_related_not_practical_language_proficiency(text, target):
    row, result = outcome(practical(text), target)
    assert row.status == "related"
    assert row.evidence_support[0].signals[0].relationship.type == "uses_language"
    assert "language proficiency" in row.explanation
    assert result.ranked_evidence[0].score == 3


def test_no_implicit_azure_ai_search_platform_edge_or_transfer_chain():
    bank = practical("Integrated Azure AI Search into a retrieval service")
    row, _ = outcome(bank, "AWS")
    assert row.status == "missing"
    grouped, _ = outcome(bank, "AWS or Azure", alternatives=["AWS", "Azure"], importance="preferred")
    assert grouped.status == "related"
    assert grouped.selected_alternative == "Azure"
    assert "specific service" in grouped.explanation


@pytest.mark.parametrize("text, technology", [
    ("Used Python to build a service", "Python"),
    ("Integrated Azure AI Search into a retrieval service", "Azure AI Search"),
    ("Worked with Oracle Database on reporting", "Oracle Database"),
    ("Deployed an application to Azure App Service", "Azure"),
])
def test_named_technology_usage_needs_positive_connected_wording(text, technology):
    row, _ = outcome(practical(text), technology, activity="technology_usage")
    assert row.status == "strong"
    assert row.evidence_support[0].signals[0].demonstrated_activity == "technology_usage"


@pytest.mark.parametrize("text", [
    "Azure", "Built REST API endpoints", "Planning to integrate Azure",
    "No Azure experience", "Never used Azure", "Learning Azure",
    "Want to use Azure", "Would deploy an application to Azure",
])
def test_technology_tags_cannot_bypass_unsatisfied_usage_constraints(text):
    row, _ = outcome(practical(text, technologies=["Azure"]), "Azure", activity="technology_usage")
    assert row.status == "missing"


@pytest.mark.parametrize("text", [
    "Built REST API endpoints using FastAPI",
    "Developed and maintained backend APIs using FastAPI",
    "Designed and implemented REST APIs using FastAPI",
    "Used FastAPI to build REST APIs",
    "Using FastAPI developed REST APIs",
])
def test_api_activity_is_connected_to_the_named_framework(text):
    row, _ = outcome(practical(text), "FastAPI", activity="api_development")
    assert row.status == "strong"


@pytest.mark.parametrize("text", [
    "Used FastAPI for a script. Built APIs using Python.",
    "Used FastAPI for reporting and built APIs using Python.",
    "Built REST APIs using Python, with FastAPI for an unrelated script.",
    "Built REST APIs", "Planning to build APIs using FastAPI",
    "Integrated a third-party API using FastAPI",
    "Built an API client using FastAPI",
    "Maintained API documentation using FastAPI",
])
def test_unrelated_api_work_or_api_consumption_does_not_establish_api_development(text):
    row, _ = outcome(practical(text, technologies=["FastAPI"]), "FastAPI", activity="api_development")
    assert row.status == "missing"


@pytest.mark.parametrize("text", [
    "Deployed an application to Azure App Service",
    "Deployed a service to Azure", "An application was deployed to Azure",
])
def test_completed_application_deployment_to_the_requested_platform_is_strong(text):
    row, _ = outcome(practical(text), "Azure", activity="cloud_deployment")
    assert row.status == "strong"


@pytest.mark.parametrize("text", [
    "Integrated Azure AI Search into a retrieval service",
    "Used Azure for search. Deployed an application to AWS.",
    "Used Azure for search and deployed an application to AWS.",
    "Built an application using Azure", "Deployed configuration to Azure",
    "Planning to deploy an application to Azure", "Would deploy an application to Azure",
])
def test_deployment_is_not_inferred_or_borrowed_from_another_destination(text):
    row, _ = outcome(practical(text, technologies=["Azure"]), "Azure", activity="cloud_deployment")
    # Actual AWS deployment may provide related Azure relevance via its explicit edge.
    assert row.status == ("related" if "to AWS" in text else "missing")


def test_azure_deployment_supports_aws_deployment_only_as_transferable_activity():
    row, result = outcome(practical("Deployed an application to Azure"), "AWS", activity="cloud_deployment")
    assert row.status == "related"
    signal = row.evidence_support[0].signals[0]
    assert signal.relationship.source == "azure"
    assert signal.demonstrated_activity == "cloud_deployment"
    assert result.ranked_evidence[0].score == 3


def test_a_generic_cloud_deployment_duty_needs_deployment_not_a_cloud_tag():
    duty = requirement("Deploy applications to cloud infrastructure", category="responsibility", activity="cloud_deployment")
    assert match(ExperienceBank(skills=["Azure"]), duty).missing_requirements
    assert match(practical("Integrated Azure AI Search into a retrieval service"), duty).missing_requirements
    assert match(practical("Deployed an application to Azure"), duty).strong_matches


def test_compound_api_duty_and_quality_qualifiers_are_not_overstated():
    duty = requirement("Develop and maintain backend APIs", category="responsibility", activity="api_development")
    assert match(practical("Developed and maintained backend APIs using Python"), duty).strong_matches
    development = match(practical("Built REST APIs using Python"), duty)
    assert development.strong_matches
    assert "maintenance is not established" in development.strong_matches[0].explanation
    secure = requirement("Develop secure APIs", category="responsibility", activity="api_development")
    assert match(practical("Built REST APIs using Python"), secure).related_matches


def test_an_activity_metadata_value_cannot_make_an_unrelated_capability_match():
    row, _ = outcome(practical("Built REST APIs using FastAPI"), "relational databases", activity="api_development")
    assert row.status == "missing"


@pytest.mark.parametrize("kind", ["education", "certification"])
def test_credentials_never_establish_engineering_activities(kind):
    bank = ExperienceBank(**{
        ("education" if kind == "education" else "certifications"): [Education(id="edu", institution="Example", qualification="Azure") if kind == "education"
               else Certification(id="cert", name="AWS Certified Developer", skills=["Azure"])],
    })
    row, _ = outcome(bank, "Azure")
    assert row.status == "related"
    assert row.evidence_support[0].signals[0].origin == "credential"
    for activity in ["technology_usage", "api_development", "cloud_deployment"]:
        constrained, _ = outcome(bank, "Azure", activity=activity)
        assert constrained.status == "missing"


def test_qualification_support_uses_appropriate_credentials_and_preserves_degree_pairs():
    bank = ExperienceBank(
        skills=["BSc Computer Science", "AWS Certified Developer"],
        education=[Education(id="edu", institution="Example", qualification="BSc", field="Computer Science")],
        certifications=[Certification(id="cert", name="AWS Certified Developer")],
        additional_evidence=[EvidenceItem(id="claim", text="BSc in Engineering")],
    )
    result = match(
        bank,
        requirement("BSc in Engineering or MSc in Computer Science", category="qualification",
                    alternatives=["BSc in Engineering", "MSc in Computer Science"]),
        requirement("AWS Certified Developer", id="cert", category="qualification"),
    )
    assert [row.requirement_details.id for row in result.missing_requirements] == ["r1"]
    assert result.strong_matches[0].evidence[0].evidence_id == "cert"
    wrong_type = ExperienceBank(certifications=[Certification(name="BSc Computer Science")])
    assert outcome(wrong_type, "BSc Computer Science", category="qualification")[0].status == "missing"


def test_parent_fields_descriptions_and_local_tags_keep_their_own_provenance():
    bank = ExperienceBank(
        skills=["Azure"],
        work_experience=[WorkExperience(
            id="role", employer="Example", role="Engineer", technologies=["Azure"],
            achievements=[EvidenceItem(id="child", text="Maintained an internal tool", skills=["Azure"])],
        )],
        projects=[Project(
            id="project", name="Example", description="Used Azure to implement a service",
            evidence=[EvidenceItem(id="unrelated", text="Created a frontend")],
        )],
        additional_evidence=[EvidenceItem(id="outcome", text="Improved a service", outcomes=["Integrated Azure into reporting"])],
    )
    result = match(bank, requirement("Azure"))
    support = {entry.evidence_id: entry for entry in result.strong_matches[0].evidence_support}
    assert support["skill:azure"].signals[0].origin == "standalone_skill"
    assert support["role"].signals[0].origin == "technology_tag"
    assert support["child"].signals[0].origin == "skill_tag"
    assert support["project"].signals[0].origin == "wording"
    assert support["outcome"].signals[0].origin == "outcome"
    assert "unrelated" not in support
    assert support["child"].status == "related"


def test_parent_usage_or_tags_do_not_propagate_activity_to_a_child():
    bank = ExperienceBank(projects=[Project(
        id="parent", name="API", description="Built REST APIs using FastAPI", technologies=["Python"],
        evidence=[EvidenceItem(id="child", text="Created a responsive frontend")],
    )])
    result = match(bank, requirement("backend development"))
    assert {ref.evidence_id for ref in result.strong_matches[0].evidence} == {"parent"}
    constrained = match(bank, requirement("Python", activity="api_development"))
    assert not constrained.strong_matches
    assert "child" not in {row.evidence.evidence_id for row in constrained.ranked_evidence}


def test_no_activity_is_manufactured_by_combining_separate_records():
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(id="cloud", text="Used Azure for reporting"),
        EvidenceItem(id="deployment", text="Deployed an application to an internal server"),
    ])
    assert match(bank, requirement("Azure", activity="cloud_deployment")).missing_requirements


def test_denials_block_relationships_locally_and_leave_other_records_available():
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(id="denial", text="No Python experience. Used FastAPI to implement a service.", technologies=["Python"]),
        EvidenceItem(id="real", text="Used Python for reporting"),
    ])
    result = match(bank, requirement("Python"))
    assert {ref.evidence_id for ref in result.strong_matches[0].evidence} == {"real"}


def test_unconstrained_local_technology_tags_are_related_and_bank_is_not_mutated():
    bank = practical("Built a frontend", technologies=["Python"])
    before = bank.model_dump_json()
    row, _ = outcome(bank, "Python")
    assert row.status == "related"
    assert row.evidence_support[0].signals[0].origin == "technology_tag"
    assert bank.model_dump_json() == before


def test_ranked_evidence_reuses_the_exact_per_requirement_decisions_and_weights():
    bank = practical("Built REST APIs using FastAPI")
    result = match(bank, requirement("backend development"), requirement("Python", id="python"))
    ranked = result.ranked_evidence[0]
    assert ranked.score == 13
    assert ranked.status == "strong"
    supports = [row.evidence_support[0] for row in rows(result) if row.evidence_support]
    assert ranked.evidence_support == supports


def test_practical_related_wording_outranks_declarations_without_new_weights():
    bank = ExperienceBank(
        skills=["Python"],
        certifications=[Certification(id="cert", name="FastAPI Certificate")],
        additional_evidence=[EvidenceItem(id="real", text="Built REST APIs using FastAPI", technologies=["Python"])],
    )
    result = match(bank, requirement("Python"))
    assert all(row.score == 3 for row in result.ranked_evidence)
    assert result.ranked_evidence[0].evidence.evidence_id == "real"
    signal = result.ranked_evidence[0].evidence_support[0].signals[0]
    assert signal.origin == "wording"
    assert signal.relationship.type == "uses_language"
    assert signal.demonstrated_activity == "technology_usage"


def test_matching_cannot_add_inferred_current_cv_skill_choices():
    bank = practical("Built REST APIs", technologies=["FastAPI"])
    before = build_skill_catalogue(bank)
    match(bank, requirement("Python"), requirement("backend development", id="backend"))
    assert build_skill_catalogue(bank) == before
    assert set(before) == {"fastapi"}


def test_deterministic_matching_does_not_mutate_job_bank_or_catalogue():
    bank = practical("Integrated Oracle Database into a service")
    job = analysis(requirement("relational databases"))
    catalogue = load_technical_relationships()
    before = bank.model_dump_json(), job.model_dump_json(), catalogue.model_dump_json()
    first = match_experience_bank(bank, job, catalogue=catalogue)
    assert first == match_experience_bank(bank, job, catalogue=catalogue)
    assert (bank.model_dump_json(), job.model_dump_json(), catalogue.model_dump_json()) == before


def test_structured_empty_list_is_authoritative_and_legacy_bare_or_remains_supported():
    bank = practical("Used Python")
    assert not rows(match_experience_bank(bank, analysis()))
    legacy = match_experience_bank(bank, JobDescriptionAnalysis(job_title="Engineer", technical_skills=["Python or Java"]))
    assert len(rows(legacy)) == 1
    assert legacy.strong_matches[0].selected_alternative == "Python"
    assert legacy.strong_matches[0].requirement_details.importance == "unspecified"


def controlled_regression():
    fixture = load_fixtures().cases[0]
    job = analysis_from_extraction(fixture.expected_extraction(), fixture.job_description)
    # Exact wording/metadata from the successful GPT-5.4 controlled analysis.
    job = JobDescriptionAnalysis(job_title=job.job_title, requirements=[
        item.model_copy(update={"text": "Experience with Python or Java"}) if item.id == "r2" else
        item.model_copy(update={"text": "Experience with relational databases"}) if item.id == "r3" else
        item.model_copy(update={"text": "Experience with AWS or Azure"}) if item.id == "r4" else item
        for item in job.requirements
    ])
    bank = ExperienceBank(
        work_experience=[WorkExperience(id="role", employer="Example", role="Engineer", achievements=[
            EvidenceItem(id="apis", text="Developed and maintained backend APIs using Python"),
            EvidenceItem(id="database", text="Integrated Oracle Database into a reporting service"),
            EvidenceItem(id="team", text="Collaborated with engineers to design software solutions"),
            EvidenceItem(id="deployment", text="Deployed an application to Azure App Service"),
        ])],
        education=[Education(id="degree", qualification="BSc Hons Computer Science", institution="Example", field="Computer Science")],
    )
    return bank, job


def test_actual_seven_requirement_analysis_matches_relevant_bank_records_without_double_counting():
    bank, job = controlled_regression()
    result = match_experience_bank(bank, job)
    assert len(rows(result)) == 7
    assert not result.missing_requirements
    assert {row.requirement_details.id for row in result.strong_matches} == {f"r{i}" for i in range(1, 8)}
    by_id = {row.requirement_details.id: row for row in rows(result)}
    assert by_id["r2"].selected_alternative == "Python"
    assert by_id["r3"].evidence_support[0].signals[0].relationship.source == "oracle database"
    assert by_id["r4"].selected_alternative == "Azure"
    assert by_id["r4"].requirement_details.importance == "preferred"
    assert by_id["r6"].requirement_details.importance == "unspecified"
    assert {ref.evidence_id for ref in by_id["r7"].evidence} == {"degree"}


def test_match_endpoint_preserves_structured_metadata_provenance_and_legacy_fields(monkeypatch):
    bank, job = controlled_regression()
    monkeypatch.setattr("app.main.experience_bank_repository", SimpleNamespace(load=lambda: bank))
    response = TestClient(app).post("/match", json={"job_analysis": job.model_dump()})
    assert response.status_code == 200
    result = response.json()
    assert len(result["strong_matches"]) == 7
    assert result["missing_requirements"] == []
    assert all("requirement" in row and "evidence" in row and "explanation" in row for row in result["strong_matches"])
    preferred = next(row for row in result["strong_matches"] if row["requirement_details"]["id"] == "r4")
    assert preferred["requirement_details"]["importance"] == "preferred"
    assert preferred["selected_alternative"] == "Azure"


def test_invalid_catalogue_fails_clearly_at_the_match_endpoint(monkeypatch):
    monkeypatch.setattr("app.main.experience_bank_repository", SimpleNamespace(load=ExperienceBank))
    def unavailable():
        raise TechnicalRelationshipCatalogueError("Invalid catalogue")
    monkeypatch.setattr("app.services.matching.load_technical_relationships", unavailable)
    response = TestClient(app).post("/match", json={"job_analysis": {"job_title": "Engineer", "technical_skills": ["Python"]}})
    assert response.status_code == 503
    assert response.json()["detail"] == "The technical relationship catalogue could not be loaded."
