"""Read-only orchestration with isolated JSON stores and the existing matcher."""

from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import (
    CurrentCV, ExperienceBank, JobDescriptionAnalysis, TailoringPreviewResponse,
)
from app.repositories.json_current_cv import CurrentCVRepositoryError, JsonCurrentCVRepository
from app.repositories.json_experience_bank import ExperienceBankRepositoryError, JsonExperienceBankRepository
from app.services.cv_candidates import build_cv_candidates
from app.services.cv_skills import select_cv_content
from app.services.job_extraction import analysis_from_extraction
from app.services.matching import match_experience_bank
from app.services.technical_relationships import (
    TechnicalRelationshipCatalogueError, load_technical_relationships,
)
from evaluations.extraction.harness import load_fixtures


@pytest.fixture
def bank():
    return ExperienceBank.model_validate({
        "skills": [" Python\t", "SQL", "Oracle Database", "FastAPI", "Testing", "Azure AI Search", "Unrelated"],
        "work_experience": [
            {"id": "role-a", "employer": "Example", "role": "Engineer", "start_date": "2023",
             "end_date": None, "summary": "  Original role context.\nKeep spacing.  ", "achievements": [
                {"id": "weak", "text": "Helped with an internal database task.", "technologies": ["Oracle Database"]},
                {"id": "testing", "text": "Wrote regression tests for reporting tools."},
                {"id": "oracle", "text": "Developed SQL stored procedures in Oracle to automate production data calculations, replacing manual processing with repeatable database logic",
                 "technologies": ["Oracle Database", "SQL"], "outcomes": ["Saved original manual effort."]},
            ]},
            {"id": "role-b", "employer": "Earlier employer", "role": "Developer", "achievements": [
                {"id": "general", "text": "Delivered planned internal tasks."},
            ]},
        ],
        "projects": [
            {"id": "old-project", "name": "Original utility", "description": "A local utility.", "evidence": [
                {"id": "old-note", "text": "Documented a command-line tool."},
            ]},
            {"id": "jobmatch", "name": "  JobMatch project  ", "description": "Original project description.\n",
             "link": "https://example.com/jobmatch", "evidence": [
                {"id": "api", "text": "  Designed and implemented REST API endpoints using Python and FastAPI for job description analysis, experience-bank management and evidence matching, exposing Azure AI Search index status.\n",
                 "technologies": ["Python", "FastAPI", "Azure AI Search"]},
                {"id": "new-note", "text": "Documented original project decisions."},
            ]},
        ],
        "education": [{"id": "degree", "institution": "Example University", "qualification": "BSc Hons Computer Science", "field": "Computer Science", "year": None}],
        "certifications": [{"id": "cert", "name": "Original certificate", "issuer": "Example", "year": "2024"}],
    })


@pytest.fixture
def current_cv():
    return CurrentCV.model_validate({
        "work_experience": [
            {"work_experience_id": "role-b", "achievement_ids": ["general"]},
            {"work_experience_id": "role-a", "achievement_ids": ["testing", "weak"]},
        ],
        "projects": [{"project_id": "old-project", "contribution_ids": ["old-note"]}],
        "skill_groups": [{"name": "Languages", "skill_keys": ["python"]},
                         {"name": "  Engineering  ", "skill_keys": ["testing"]}],
        "tailoring_settings": {"max_achievements_per_role": 2, "max_projects": 1,
                               "max_contributions_per_project": 1, "max_skills": 6},
    })


@pytest.fixture
def analysis():
    case = load_fixtures().cases[0]
    return analysis_from_extraction(case.expected_extraction(), case.job_description)


@pytest.fixture(autouse=True)
def repositories(tmp_path, monkeypatch, bank, current_cv):
    bank_repo = JsonExperienceBankRepository(tmp_path / "experience_bank.json")
    cv_repo = JsonCurrentCVRepository(tmp_path / "current_cv.json")
    bank_repo.save(bank)
    cv_repo.save(current_cv)
    monkeypatch.setattr("app.main.experience_bank_repository", bank_repo)
    monkeypatch.setattr("app.main.current_cv_repository", cv_repo)
    forbidden = Mock(side_effect=AssertionError("Preview must not save or call OpenAI."))
    monkeypatch.setattr(bank_repo, "save", forbidden)
    monkeypatch.setattr(cv_repo, "save", forbidden)
    monkeypatch.setattr("app.main.analyse_job_description_with_llm", forbidden)
    monkeypatch.setattr("app.services.llm.OpenAI", forbidden)
    return bank_repo, cv_repo


@pytest.fixture
def client():
    return TestClient(app)


def preview(client, analysis):
    return client.post("/tailoring/preview", json={"job_analysis": analysis.model_dump()})


def decision(data, source_id, source_type="achievement"):
    return next(item for item in data["decisions"] if item["source_id"] == source_id and item["source_type"] == source_type)


def test_structured_preview_is_exact_composition_of_existing_services(client, bank, current_cv, analysis):
    catalogue = load_technical_relationships()
    matching = match_experience_bank(bank, analysis, catalogue=catalogue)
    expected = select_cv_content(build_cv_candidates(bank, current_cv), matching, catalogue=catalogue)
    response = preview(client, analysis)
    assert response.status_code == 200
    result = TailoringPreviewResponse.model_validate(response.json())
    assert result.model_dump(exclude={"matching_result", "source_bank"}) == expected.model_dump()
    assert result.matching_result == matching
    assert result.source_bank == bank
    assert response.json() == result.model_dump(mode="json")


def test_work_selection_retains_order_and_baseline_breadth_but_replaces_weak_content(client, analysis):
    data = preview(client, analysis).json()
    assert data["proposed_cv"]["work_experience"] == [
        {"work_experience_id": "role-b", "achievement_ids": ["general"]},
        {"work_experience_id": "role-a", "achievement_ids": ["testing", "oracle"]},
    ]
    assert decision(data, "testing")["reason_codes"] == ["baseline_retained"]
    assert decision(data, "testing")["was_in_current_cv"]
    assert decision(data, "oracle")["selected"] and not decision(data, "oracle")["was_in_current_cv"]
    assert decision(data, "weak")["reason_codes"] == ["limit_reached"]
    assert decision(data, "weak")["was_in_current_cv"] and not decision(data, "weak")["selected"]


def test_project_and_contribution_recommendations_come_from_existing_selection(client, analysis):
    data = preview(client, analysis).json()
    assert data["proposed_cv"]["projects"] == [{"project_id": "jobmatch", "contribution_ids": ["api"]}]
    assert decision(data, "jobmatch", "project")["selected"]
    assert decision(data, "api", "project_evidence")["parent_id"] == "jobmatch"
    assert decision(data, "new-note", "project_evidence")["reason_codes"] == ["limit_reached"]
    assert not decision(data, "old-project", "project")["selected"]


def test_skill_groups_and_canonical_keys_are_selected_without_inferred_technologies(client, analysis):
    data = preview(client, analysis).json()
    groups = data["proposed_cv"]["skill_groups"]
    assert groups[:2] == [{"name": "Languages", "skill_keys": ["python"]},
                          {"name": "  Engineering  ", "skill_keys": ["testing"]}]
    assert groups[2]["name"] == "Additional skills"
    assert set(groups[2]["skill_keys"]) == {"oracle database", "fastapi", "sql", "azure ai search"}
    assert decision(data, "python", "skill")["original_text"] == " Python\t"
    assert not decision(data, "unrelated", "skill")["selected"]
    keys = [key for group in groups for key in group["skill_keys"]]
    assert "aws" not in keys and "azure" not in keys and "java" not in keys


def test_source_snapshot_preserves_exact_wording_headers_outcomes_and_optional_fields(client, bank, analysis):
    data = preview(client, analysis).json()
    assert data["source_bank"] == bank.model_dump(mode="json")
    api = bank.projects[1].evidence[0]
    assert decision(data, api.id, "project_evidence")["original_text"] == api.text
    assert decision(data, "role-a", "work_experience")["original_text"] == bank.work_experience[0].summary
    assert data["source_bank"]["projects"][1]["name"] == "  JobMatch project  "
    assert data["source_bank"]["projects"][1]["link"] == "https://example.com/jobmatch"
    assert data["source_bank"]["work_experience"][0]["end_date"] is None
    assert data["education_ids"] == ["degree"] and data["certification_ids"] == ["cert"]
    assert decision(data, "cert", "certification")["reason_codes"] == ["unchanged_credential"]


def test_or_importance_activity_and_provenance_survive_the_api(client, analysis):
    data = preview(client, analysis).json()
    matching = data["matching_result"]
    rows = [*matching["strong_matches"], *matching["related_matches"], *matching["missing_requirements"]]
    assert len(rows) == len(data["coverage"]) == len(data["skill_coverage"]) == 7
    by_id = {item["requirement_details"]["id"]: item for item in rows}
    assert by_id["r2"]["requirement_details"]["alternatives"] == ["Python", "Java"]
    assert by_id["r2"]["requirement_details"]["importance"] == "required"
    assert by_id["r4"]["requirement_details"]["importance"] == "preferred"
    assert by_id["r6"]["requirement_details"]["activity"] == "cloud_deployment"
    assert by_id["r6"]["status"] == "missing"
    oracle = decision(data, "oracle")
    assert oracle["requirement_importance"] == {"r3": "required"}
    assert oracle["evidence_support"][0]["signals"][0]["relationship"]["type"] == "broader"
    assert oracle["evidence_support"][0]["signals"][0]["demonstrated_activity"] == "technology_usage"
    assert all(item["evidence_id"] == "oracle" for item in oracle["evidence_support"])
    api_support = decision(data, "api", "project_evidence")["evidence_support"]
    assert any("maintenance" in item["explanation"].lower() for item in api_support)


def test_legacy_five_field_analysis_remains_supported(client):
    response = client.post("/tailoring/preview", json={"job_analysis": {
        "job_title": "Backend Engineer", "technical_skills": ["Python or Java", "Relational databases"],
        "other_keywords": [], "responsibilities": [], "qualifications": [],
    }})
    assert response.status_code == 200
    data = response.json()
    assert data["matching_result"]["job_title"] == "Backend Engineer"
    assert len(data["coverage"]) == 2
    assert all(item["requirement_details"]["importance"] == "unspecified" for item in data["coverage"])
    assert data["coverage"][0]["requirement_details"]["alternatives"] == ["Python", "Java"]
    assert not data["warnings"]


@pytest.mark.parametrize("field", ["max_achievements_per_role", "max_projects", "max_contributions_per_project", "max_skills"])
@pytest.mark.parametrize("limit", [0, 1, None])
def test_configured_limits_pass_through_unchanged(client, repositories, current_cv, analysis, field, limit):
    current_cv.tailoring_settings.__setattr__(field, limit)
    repositories[1].path.write_text(current_cv.model_dump_json(), encoding="utf-8")
    data = preview(client, analysis).json()
    assert data["proposed_cv"]["tailoring_settings"] == current_cv.tailoring_settings.model_dump()
    selected = data["proposed_cv"]
    if limit is not None:
        if field == "max_achievements_per_role":
            assert all(len(role["achievement_ids"]) <= limit for role in selected["work_experience"])
        elif field == "max_projects":
            assert len(selected["projects"]) <= limit
        elif field == "max_contributions_per_project":
            assert all(len(project["contribution_ids"]) <= limit for project in selected["projects"])
        else:
            assert sum(len(group["skill_keys"]) for group in selected["skill_groups"]) <= limit


@pytest.mark.parametrize("missing", [False, True])
def test_empty_or_missing_stores_return_preview_without_creating_files(client, repositories, analysis, missing):
    for repository, empty in zip(repositories, (ExperienceBank(), CurrentCV())):
        if missing:
            repository.path.unlink()
        else:
            repository.path.write_text(empty.model_dump_json(), encoding="utf-8")
    before = {str(repo.path): repo.path.read_bytes() if repo.path.exists() else None for repo in repositories}
    response = preview(client, analysis)
    assert response.status_code == 200
    data = response.json()
    assert data["proposed_cv"] == CurrentCV().model_dump()
    assert data["source_bank"] == ExperienceBank().model_dump()
    assert len(data["matching_result"]["missing_requirements"]) == 7
    assert data["decisions"] == [] and data["reference_issues"] == []
    assert before == {str(repo.path): repo.path.read_bytes() if repo.path.exists() else None for repo in repositories}


def test_missing_current_cv_does_not_invent_work_roles_but_allows_existing_project_and_skill_recommendations(client, repositories, analysis):
    repositories[1].path.unlink()
    data = preview(client, analysis).json()
    assert data["proposed_cv"]["work_experience"] == []
    assert data["proposed_cv"]["projects"] == [{"project_id": "jobmatch", "contribution_ids": ["api"]}]
    assert data["proposed_cv"]["skill_groups"]
    assert not repositories[1].path.exists()


def test_stale_and_wrong_parent_references_are_reported_without_saved_repairs(client, repositories, current_cv, analysis):
    payload = current_cv.model_dump()
    payload["work_experience"][0]["achievement_ids"] = []
    payload["work_experience"][1]["achievement_ids"] = ["removed-achievement", "general"]
    payload["projects"] = [{"project_id": "removed-project", "contribution_ids": ["removed-contribution"]}]
    payload["skill_groups"].append({"name": "Unavailable", "skill_keys": ["removed-skill"]})
    repositories[1].path.write_text(CurrentCV.model_validate(payload).model_dump_json(), encoding="utf-8")
    before = repositories[1].path.read_bytes()
    data = preview(client, analysis).json()
    references = {item["reference"] for item in data["reference_issues"]}
    assert references == {"removed-achievement", "general", "removed-project", "removed-contribution", "removed-skill"}
    assert "baseline_reference_issues" in data["warnings"]
    assert decision(data, "removed-skill", "skill")["reason_codes"] == ["invalid_reference"]
    assert not decision(data, "general")["selected"]  # Existing wrong-parent safeguard.
    assert repositories[1].path.read_bytes() == before


@pytest.mark.parametrize("job_analysis", [
    {"job_title": "Engineer"},
    {"job_title": "Engineer", "requirements": []},
])
def test_empty_requirements_retain_valid_baseline_under_existing_limits(client, current_cv, job_analysis):
    response = client.post("/tailoring/preview", json={"job_analysis": job_analysis})
    assert response.status_code == 200
    data = response.json()
    assert data["proposed_cv"] == current_cv.model_dump()
    assert data["coverage"] == [] and data["skill_coverage"] == []
    assert data["matching_result"]["ranked_evidence"] == []


def test_no_relevant_matches_preserve_baseline_and_bank_missing_status(client, current_cv):
    data = preview(client, JobDescriptionAnalysis(job_title="Engineer", technical_skills=["Rust"])).json()
    assert data["proposed_cv"] == current_cv.model_dump()
    assert data["coverage"][0]["bank_status"] == "missing"
    assert data["coverage"][0]["selected_status"] == "not_selected"
    assert data["matching_result"]["missing_requirements"][0]["requirement"] == "Rust"


def test_bank_coverage_stays_distinct_when_limits_exclude_all_support(client, repositories, current_cv, analysis):
    for field in type(current_cv.tailoring_settings).model_fields:
        setattr(current_cv.tailoring_settings, field, 0)
    repositories[1].path.write_text(current_cv.model_dump_json(), encoding="utf-8")
    data = preview(client, analysis).json()
    coverage = {item["requirement_id"]: item for item in data["coverage"]}
    assert data["coverage_scope"] == "work_and_projects"
    assert coverage["r2"]["bank_status"] == coverage["r3"]["bank_status"] == "strong"
    assert coverage["r2"]["selected_status"] == coverage["r3"]["selected_status"] == "not_selected"
    assert coverage["r7"]["bank_status"] == "strong"
    assert coverage["r7"]["selected_status"] == "not_selected"  # Education stays separate.
    assert data["education_ids"] == ["degree"]
    assert all(not item["selected_skill_keys"] for item in data["skill_coverage"])
    assert len(data["matching_result"]["strong_matches"]) == 4
    assert len(data["matching_result"]["related_matches"]) == 1
    assert len(data["matching_result"]["missing_requirements"]) == 2


@pytest.mark.parametrize("payload", [
    {}, {"job_analysis": None}, {"job_analysis": {}}, {"job_analysis": []},
    {"job_analysis": {"job_title": "  "}},
    {"job_analysis": {"job_title": "Engineer", "technical_skills": [""]}},
    {"job_analysis": {"job_title": "Engineer", "requirements": [{}]}},
    {"job_analysis": {"job_title": "Engineer", "requirements": [], "technical_skills": ["Python"]}},
])
def test_invalid_requests_fail_before_loading_any_saved_documents(client, repositories, monkeypatch, payload):
    for repo in repositories:
        monkeypatch.setattr(repo, "load", Mock(side_effect=AssertionError("Validate before loading.")))
    assert client.post("/tailoring/preview", json=payload).status_code == 422


@pytest.mark.parametrize("payload", ["{", '"invalid"', "null"])
def test_invalid_json_bodies_use_existing_fastapi_validation(client, payload):
    assert client.post("/tailoring/preview", content=payload, headers={"Content-Type": "application/json"}).status_code == 422


def test_repeat_requests_are_deterministic_and_never_write_or_call_openai(client, repositories, analysis, tmp_path):
    before = {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    first = preview(client, analysis)
    second = preview(client, analysis)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert before == {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    repositories[0].save.assert_not_called()
    repositories[1].save.assert_not_called()


def test_one_bank_and_catalogue_snapshot_is_shared_by_discovery_matching_and_selection(client, repositories, analysis, monkeypatch):
    bank_repo, cv_repo = repositories
    loaded_bank, loaded_cv = bank_repo.load(), cv_repo.load()
    before_bank, before_cv = loaded_bank.model_dump(), loaded_cv.model_dump()
    bank_load = Mock(side_effect=[loaded_bank, AssertionError("No second bank load.")])
    cv_load = Mock(side_effect=[loaded_cv, AssertionError("No second CV load.")])
    catalogue = load_technical_relationships()
    catalogue_load = Mock(return_value=catalogue)
    monkeypatch.setattr(bank_repo, "load", bank_load)
    monkeypatch.setattr(cv_repo, "load", cv_load)
    monkeypatch.setattr("app.main.load_technical_relationships", catalogue_load)
    monkeypatch.setattr("app.services.matching.load_technical_relationships", Mock(side_effect=AssertionError("Reuse catalogue.")))
    received = {}

    def discover(bank, current_cv):
        assert bank is loaded_bank and current_cv is loaded_cv
        received["index"] = build_cv_candidates(bank, current_cv)
        return received["index"]

    def match(bank, job, *, catalogue):
        assert bank is loaded_bank and catalogue is catalogue_load.return_value
        assert job == analysis
        received["matches"] = match_experience_bank(bank, job, catalogue=catalogue)
        return received["matches"]

    def select(index, matches, *, catalogue):
        assert index is received["index"] and matches is received["matches"]
        assert catalogue is catalogue_load.return_value
        return select_cv_content(index, matches, catalogue=catalogue)

    monkeypatch.setattr("app.main.build_cv_candidates", discover)
    monkeypatch.setattr("app.main.match_experience_bank", match)
    monkeypatch.setattr("app.main.select_cv_content", select)
    data = preview(client, analysis).json()
    bank_load.assert_called_once_with()
    cv_load.assert_called_once_with()
    catalogue_load.assert_called_once_with()
    assert loaded_bank.model_dump() == before_bank and loaded_cv.model_dump() == before_cv
    assert data["source_bank"] == before_bank


@pytest.mark.parametrize("target,error,detail", [
    ("bank", ExperienceBankRepositoryError, "The experience bank could not be loaded."),
    ("cv", CurrentCVRepositoryError, "The Current CV could not be loaded."),
    ("catalogue", TechnicalRelationshipCatalogueError, "The technical relationship catalogue could not be loaded."),
])
def test_service_errors_return_sanitised_503(client, repositories, analysis, monkeypatch, target, error, detail):
    failure = Mock(side_effect=error("Sensitive configuration and /private/internal/path must not be returned."))
    if target == "catalogue":
        monkeypatch.setattr("app.main.load_technical_relationships", failure)
    else:
        monkeypatch.setattr(repositories[0 if target == "bank" else 1], "load", failure)
    response = preview(client, analysis)
    assert response.status_code == 503
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize("store", [0, 1])
@pytest.mark.parametrize("content", ["", "{", '{"schema_version":999}'])
def test_corrupt_saved_json_is_not_silently_treated_as_an_empty_document(client, repositories, analysis, store, content):
    path = repositories[store].path
    path.write_text(content, encoding="utf-8")
    before = path.read_bytes()
    response = preview(client, analysis)
    assert response.status_code == 503
    assert path.read_bytes() == before
    assert str(path) not in response.text


def test_preloaded_catalogue_aliases_are_available_to_skill_selection(client, repositories):
    repositories[0].path.write_text(ExperienceBank(skills=["Microsoft Azure"]).model_dump_json(), encoding="utf-8")
    repositories[1].path.write_text(CurrentCV().model_dump_json(), encoding="utf-8")
    data = preview(client, JobDescriptionAnalysis(job_title="Engineer", technical_skills=["Azure"])).json()
    assert data["proposed_cv"]["skill_groups"] == [{"name": "Additional skills", "skill_keys": ["microsoft azure"]}]
    assert decision(data, "microsoft azure", "skill")["original_text"] == "Microsoft Azure"


def test_openapi_documents_reused_request_and_typed_full_response(client, analysis):
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/tailoring/preview"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/MatchRequest"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/TailoringPreviewResponse"}
    properties = schema["components"]["schemas"]["TailoringPreviewResponse"]["properties"]
    assert {"proposed_cv", "decisions", "coverage", "skill_coverage", "matching_result", "source_bank", "reference_issues", "warnings"} <= properties.keys()
    assert properties["decisions"]["items"] == {"$ref": "#/components/schemas/CVRecommendation"}
    assert TailoringPreviewResponse.model_validate(preview(client, analysis).json()).model_dump(mode="json")
