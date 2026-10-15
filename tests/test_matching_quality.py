"""Real-review wording in controlled fixtures; no reads/writes of saved bank data."""

import pytest

from app.models import (
    Certification, EvidenceItem, ExperienceBank, JobDescriptionAnalysis,
    Project, StructuredRequirement, WorkExperience,
)
from app.services.matching import match_experience_bank
from app.services.technical_relationships import load_technical_relationships


ORACLE_DEVELOPMENT = (
    "Developed SQL stored procedures in Oracle to automate production data calculations, "
    "replacing manual processing with repeatable database logic"
)
API_DEVELOPMENT = (
    "Designed and implemented REST API endpoints for job description analysis, "
    "experience-bank management and evidence matching"
)
API_DUTY = "Develop and maintain backend APIs"
COLLABORATIVE_DESIGN = "Collaborate with engineers to design software solutions"


def match(bank, text, *, category="skill", activity=None, structured=True):
    if structured:
        job = JobDescriptionAnalysis(job_title="Engineer", requirements=[StructuredRequirement(
            id="r1", text=text, source_text=text, category=category, activity=activity,
            alternatives=[text], importance="unspecified",
        )])
    else:
        field = "responsibilities" if category == "responsibility" else "technical_skills"
        job = JobDescriptionAnalysis(job_title="Engineer", **{field: [text]})
    result = match_experience_bank(bank, job)
    rows = [*result.strong_matches, *result.related_matches, *result.missing_requirements]
    assert len(rows) == 1
    return rows[0], result


def evidence(text, *, technologies=(), outcomes=()):
    return ExperienceBank(additional_evidence=[EvidenceItem(
        id="record", text=text, technologies=list(technologies), outcomes=list(outcomes),
    )])


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("tags", [[], ["SQL", "Oracle Database"]])
def test_actual_oracle_database_development_is_wording_support_not_tag_promotion(structured, tags):
    bank = evidence(ORACLE_DEVELOPMENT, technologies=tags)
    before = bank.model_dump_json()
    row, result = match(bank, "relational databases", structured=structured)
    assert row.status == "strong"
    support = row.evidence_support[0]
    assert support.status == "strong"
    assert support.signals[0].origin == "wording"
    assert support.signals[0].relationship.source == "oracle database"
    assert support.signals[0].relationship.target == "relational databases"
    assert support.signals[0].relationship.type == "broader"
    assert support.signals[0].demonstrated_activity == "technology_usage"
    assert "stored procedures in oracle" in support.signals[0].signal
    assert result.ranked_evidence[0].score == 10
    assert result.ranked_evidence[0].evidence_support == row.evidence_support
    assert bank.model_dump_json() == before


@pytest.mark.parametrize("text", [
    "Created SQL queries using Oracle",
    "Wrote PL/SQL stored procedures in Oracle",
    "Maintained stored procedures in Oracle",
    "Developed SQL stored procedures in Oracle Database",
])
def test_contextual_database_rule_covers_completed_database_work(text):
    row, _ = match(evidence(text), "relational databases")
    assert row.status == "strong"


def test_contextual_oracle_development_also_supports_direct_usage_without_global_aliases():
    row, _ = match(evidence(ORACLE_DEVELOPMENT), "Oracle Database", activity="technology_usage")
    assert row.status == "strong"
    assert row.evidence_support[0].signals[0].origin == "wording"
    assert load_technical_relationships().resolve_concept("Oracle") is None


def test_direct_oracle_development_without_activity_metadata_is_also_wording_based():
    row, _ = match(evidence(ORACLE_DEVELOPMENT), "Oracle Database")
    assert row.status == "strong"
    assert row.evidence_support[0].signals[0].origin == "wording"


def test_explicit_sql_development_is_direct_language_evidence_not_inferred_proficiency():
    row, _ = match(evidence(ORACLE_DEVELOPMENT), "SQL")
    assert row.status == "strong"
    signal = row.evidence_support[0].signals[0]
    assert signal.origin == "wording"
    assert signal.relationship is None
    assert signal.demonstrated_activity == "technology_usage"


@pytest.mark.parametrize("bank", [
    ExperienceBank(skills=["Oracle Database"]),
    evidence("Improved a reporting service", technologies=["Oracle Database"]),
    ExperienceBank(work_experience=[WorkExperience(
        id="role", employer="Example", role="Engineer", technologies=["Oracle Database"],
    )]),
])
def test_oracle_database_declarations_alone_remain_related(bank):
    row, result = match(bank, "relational databases")
    assert row.status == "related"
    assert result.ranked_evidence[0].score == 3
    assert all(signal.demonstrated_activity is None for support in row.evidence_support for signal in support.signals)


@pytest.mark.parametrize("text", [
    "Oracle", "Worked for Oracle", "Developed an Oracle integration",
    "Developed SQL stored procedures in PostgreSQL",
    "Developed SQL stored procedures. Used Oracle for another task.",
    "Developed SQL stored procedures in Oracle Cloud",
    "Planning to develop SQL stored procedures in Oracle",
    "Never developed SQL stored procedures in Oracle",
])
def test_vendor_mentions_unrelated_records_and_future_or_denied_work_are_not_database_proof(text):
    row, _ = match(evidence(text, technologies=["Oracle Database"]), "relational databases")
    assert row.status != "strong"


def test_database_context_does_not_override_explicit_local_vendor_denial():
    row, _ = match(evidence(
        ORACLE_DEVELOPMENT, technologies=["Oracle Database"], outcomes=["No Oracle experience"],
    ), "relational databases")
    assert row.status == "missing"


def test_contextual_database_activity_keeps_outcome_provenance():
    row, _ = match(evidence("Automated a calculation workflow", outcomes=[ORACLE_DEVELOPMENT]), "relational databases")
    assert row.status == "strong"
    assert row.evidence_support[0].signals[0].origin == "outcome"


def test_contextual_work_in_a_credential_title_does_not_prove_hands_on_activity():
    bank = ExperienceBank(certifications=[Certification(id="cert", name=ORACLE_DEVELOPMENT)])
    row, _ = match(bank, "relational databases")
    assert row.status == "related"
    assert row.evidence_support[0].signals[0].origin == "credential"


def test_database_context_cannot_be_combined_across_clauses_or_records():
    same_record = evidence("Developed SQL stored procedures. Oracle", technologies=["Oracle Database"])
    assert match(same_record, "relational databases")[0].status == "related"
    bank = ExperienceBank(additional_evidence=[
        EvidenceItem(id="sql", text="Developed SQL stored procedures"),
        EvidenceItem(id="vendor", text="Oracle", technologies=["Oracle Database"]),
    ])
    assert match(bank, "relational databases")[0].status == "related"


def test_stored_procedures_without_explicit_sql_do_not_infer_strong_language_proficiency():
    row, result = match(evidence("Developed stored procedures in Oracle"), "SQL")
    assert row.status == "related"
    assert row.evidence_support[0].signals[0].relationship.type == "uses_language"
    assert result.ranked_evidence[0].score == 3


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("tags", [[], ["Python", "FastAPI"]])
def test_actual_api_development_is_strong_relevance_with_an_explicit_maintenance_caveat(structured, tags):
    bank = evidence(API_DEVELOPMENT, technologies=tags)
    row, result = match(bank, API_DUTY, category="responsibility", activity="api_development", structured=structured)
    assert row.status == "strong"
    assert "Demonstrated API development" in row.explanation
    assert "maintenance is not established by this evidence" in row.explanation
    assert API_DUTY not in row.matched_signals
    assert all(signal.demonstrated_activity == "api_development"
               for support in row.evidence_support for signal in support.signals)
    assert all(signal.origin == "wording" for signal in row.evidence_support[0].signals)
    assert result.ranked_evidence[0].score == 10
    assert result.ranked_evidence[0].evidence_support == row.evidence_support
    assert "maintenance is not established" in result.ranked_evidence[0].explanation


def test_production_api_endpoint_is_recognised_without_implying_cloud_deployment():
    bank = evidence("Developed a production API endpoint using Python and FastAPI.")
    row, _ = match(bank, API_DUTY, category="responsibility", activity="api_development")
    assert row.status == "strong"
    deployment, _ = match(bank, "Deploy applications to cloud infrastructure",
                          category="responsibility", activity="cloud_deployment")
    assert deployment.status == "missing"


def test_maintenance_only_and_additional_quality_claims_are_not_upgraded_from_api_development():
    bank = evidence(API_DEVELOPMENT)
    for duty in ["Maintain backend APIs", "Develop and maintain secure backend APIs",
                 "Develop and maintain scalable APIs", "Develop and maintain APIs and database deployments"]:
        row, _ = match(bank, duty, category="responsibility", activity="api_development")
        assert row.status != "strong"


@pytest.mark.parametrize("text", [
    "Built backend calculation services", "Integrated a third-party REST API",
    "Built an API client using Python", "Maintained API documentation",
    "Planning to design and implement REST API endpoints",
    "Never designed or implemented REST API endpoints",
    "Maintained REST API endpoints",
])
def test_other_backend_work_consumption_documentation_and_aspirations_do_not_prove_api_building(text):
    row, _ = match(evidence(text, technologies=["Python", "FastAPI"]), API_DUTY,
                    category="responsibility", activity="api_development")
    assert row.status != "strong"


def test_credential_and_parent_tags_cannot_supply_the_api_development_capability():
    bank = ExperienceBank(
        certifications=[Certification(id="cert", name=API_DEVELOPMENT)],
        projects=[Project(
            id="project", name="Example", technologies=["FastAPI"],
            evidence=[EvidenceItem(id="child", text="Improved a frontend")],
        )],
    )
    row, _ = match(bank, API_DUTY, category="responsibility", activity="api_development")
    assert row.status == "missing"


def test_positive_api_maintenance_is_acknowledged_only_when_the_record_demonstrates_it():
    row, _ = match(evidence("Developed and maintained REST APIs"), API_DUTY,
                    category="responsibility", activity="api_development")
    assert row.status == "strong"
    assert "maintenance is not established" not in row.explanation


def test_collaboration_and_separate_api_design_do_not_manufacture_collaborative_design():
    bank = ExperienceBank(
        work_experience=[WorkExperience(
            employer="Example", role="Software Engineer", summary="Worked in an Agile environment",
        )],
        additional_evidence=[
            EvidenceItem(id="collaboration", text=(
                "Collaborated with product owners, scrum masters, developers, and QA engineers across multiple projects."
            )),
            EvidenceItem(id="design", text=API_DEVELOPMENT),
            EvidenceItem(id="presentation", text="Presented technical solutions and project updates to stakeholders."),
        ],
    )
    row, result = match(bank, COLLABORATIVE_DESIGN, category="responsibility")
    assert row.status == "missing"
    assert result.ranked_evidence == []


def test_explicit_combined_collaborative_design_still_matches():
    row, _ = match(evidence("Collaborated with engineers to design software solutions"),
                    COLLABORATIVE_DESIGN, category="responsibility")
    assert row.status == "strong"


def test_multiple_local_python_tags_remain_related_and_are_not_reinterpreted_as_activity():
    bank = ExperienceBank(projects=[Project(
        name="Example", technologies=["Python"],
        evidence=[
            EvidenceItem(id="models", text="Created structured data models", technologies=["Python"]),
            EvidenceItem(id="persistence", text="Implemented local JSON persistence", technologies=["Python"]),
        ],
    )])
    before = bank.model_dump_json()
    row, result = match(bank, "Python")
    assert row.status == "related"
    assert all(entry.score == 3 for entry in result.ranked_evidence)
    assert all(signal.origin == "technology_tag" and signal.demonstrated_activity is None
               for support in row.evidence_support for signal in support.signals)
    assert bank.model_dump_json() == before
