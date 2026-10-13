from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import CurrentCV, ExperienceBank
from app.repositories.json_current_cv import CurrentCVRepositoryError, JsonCurrentCVRepository
from app.repositories.json_experience_bank import ExperienceBankRepositoryError, JsonExperienceBankRepository
from app.services.current_cv import validate_current_cv_references


@pytest.fixture
def bank():
    return ExperienceBank.model_validate({
        "skills": ["Python", "C++", "C#", "FastAPI"],
        "work_experience": [
            {
                "id": "role-a", "employer": "Example", "role": "Engineer",
                "achievements": [
                    {"id": "achievement-a1", "text": "Built an API."},
                    {"id": "achievement-a2", "text": "Wrote tests."},
                ],
            },
            {
                "id": "role-b", "employer": "Other", "role": "Developer",
                "achievements": [
                    {"id": "achievement-b1", "text": "Built a service."},
                    {"id": "achievement-b2", "text": "Added monitoring."},
                ],
            },
        ],
        "projects": [
            {"id": "project-a", "name": "API project", "evidence": [
                {"id": "contribution-a1", "text": "Built a tool."},
                {"id": "contribution-a2", "text": "Documented the tool."},
            ]},
            {"id": "project-b", "name": "Other project", "evidence": [
                {"id": "contribution-b1", "text": "Added tests."},
                {"id": "contribution-b2", "text": "Added deployment."},
            ]},
        ],
    })


@pytest.fixture
def current_cv():
    return CurrentCV.model_validate({
        "work_experience": [
            {"work_experience_id": "role-b", "achievement_ids": ["achievement-b2", "achievement-b1"]},
            {"work_experience_id": "role-a", "achievement_ids": ["achievement-a2", "achievement-a1"]},
        ],
        "projects": [
            {"project_id": "project-b", "contribution_ids": ["contribution-b2", "contribution-b1"]},
            {"project_id": "project-a", "contribution_ids": ["contribution-a2", "contribution-a1"]},
        ],
        "skill_groups": [
            {"name": "  Languages  ", "skill_keys": ["c#", "python", "c++"]},
            {"name": "Backend", "skill_keys": ["fastapi"]},
            {"name": "Empty", "skill_keys": []},
        ],
        "tailoring_settings": {"max_projects": 0, "max_skills": 0},
    })


@pytest.fixture
def repositories(tmp_path, monkeypatch, bank):
    bank_repository = JsonExperienceBankRepository(tmp_path / "experience_bank.json")
    cv_repository = JsonCurrentCVRepository(tmp_path / "current_cv.json")
    bank_repository.save(bank)
    monkeypatch.setattr("app.main.experience_bank_repository", bank_repository)
    monkeypatch.setattr("app.main.current_cv_repository", cv_repository)
    return bank_repository, cv_repository


@pytest.fixture
def client(repositories):
    return TestClient(app)


def test_get_missing_cv_returns_defaults_without_creating_cv(client, repositories):
    bank_repository, cv_repository = repositories
    before_bank = bank_repository.path.read_bytes()
    response = client.get("/current-cv")
    assert response.status_code == 200
    assert response.json() == {"current_cv": CurrentCV().model_dump(), "reference_issues": []}
    assert not cv_repository.path.exists()
    assert bank_repository.path.read_bytes() == before_bank


def test_get_valid_cv_preserves_document_and_does_not_write(client, repositories, current_cv, monkeypatch):
    bank_repository, cv_repository = repositories
    cv_repository.save(current_cv)
    before_cv = cv_repository.path.read_bytes()
    before_bank = bank_repository.path.read_bytes()
    save = Mock(side_effect=AssertionError("GET must not save"))
    monkeypatch.setattr(cv_repository, "save", save)
    response = client.get("/current-cv")
    assert response.status_code == 200
    assert response.json() == {"current_cv": current_cv.model_dump(), "reference_issues": []}
    assert cv_repository.path.read_bytes() == before_cv
    assert bank_repository.path.read_bytes() == before_bank
    save.assert_not_called()


@pytest.mark.parametrize("change", ["delete_parents", "delete_bullets", "move_bullets", "delete_skill"])
def test_get_reports_bank_changes_without_discarding_saved_cv(client, repositories, bank, current_cv, change):
    bank_repository, cv_repository = repositories
    cv_repository.save(current_cv)
    before_cv = cv_repository.path.read_bytes()
    payload = bank.model_dump()
    if change == "delete_parents":
        payload["work_experience"].pop(0)
        payload["projects"].pop(0)
        expected = [
            ("work_experience[1].work_experience_id", "role-a"),
            ("work_experience[1].achievement_ids[0]", "achievement-a2"),
            ("work_experience[1].achievement_ids[1]", "achievement-a1"),
            ("projects[1].project_id", "project-a"),
            ("projects[1].contribution_ids[0]", "contribution-a2"),
            ("projects[1].contribution_ids[1]", "contribution-a1"),
        ]
    elif change == "delete_bullets":
        payload["work_experience"][0]["achievements"].pop(1)
        payload["projects"][0]["evidence"].pop(1)
        expected = [
            ("work_experience[1].achievement_ids[0]", "achievement-a2"),
            ("projects[1].contribution_ids[0]", "contribution-a2"),
        ]
    elif change == "move_bullets":
        moved_achievement = payload["work_experience"][0]["achievements"].pop(0)
        payload["work_experience"][1]["achievements"].append(moved_achievement)
        moved_contribution = payload["projects"][0]["evidence"].pop(0)
        payload["projects"][1]["evidence"].append(moved_contribution)
        expected = [
            ("work_experience[1].achievement_ids[1]", "achievement-a1"),
            ("projects[1].contribution_ids[1]", "contribution-a1"),
        ]
    else:
        payload["skills"].remove("Python")
        expected = [("skill_groups[0].skill_keys[1]", "python")]
    bank_repository.save(ExperienceBank.model_validate(payload))
    before_bank = bank_repository.path.read_bytes()
    response = client.get("/current-cv")
    assert response.status_code == 200
    assert response.json()["current_cv"] == current_cv.model_dump()
    issues = response.json()["reference_issues"]
    assert [(issue["path"], issue["reference"]) for issue in issues] == expected
    assert all(set(issue) == {"path", "reference", "reason"} for issue in issues)
    if change == "move_bullets":
        assert all("does not belong" in issue["reason"] for issue in issues)
    assert cv_repository.path.read_bytes() == before_cv
    assert bank_repository.path.read_bytes() == before_bank


def test_put_round_trip_preserves_all_nested_order_and_bank(client, repositories, current_cv):
    bank_repository, cv_repository = repositories
    before_bank = bank_repository.path.read_bytes()
    submitted = current_cv.model_dump()
    response = client.put("/current-cv", json=submitted)
    assert response.status_code == 200
    assert response.json() == submitted
    assert client.get("/current-cv").json() == {"current_cv": submitted, "reference_issues": []}
    assert cv_repository.load() == current_cv
    assert current_cv.model_dump() == submitted
    assert bank_repository.path.read_bytes() == before_bank


def test_put_validates_before_saving_without_modifying_models(client, repositories, current_cv, monkeypatch):
    bank_repository, cv_repository = repositories
    events = []
    original_load = bank_repository.load
    original_save = cv_repository.save

    def load_bank():
        events.append("load bank")
        return original_load()

    def validate(cv, bank):
        events.append("validate")
        before_cv = cv.model_dump_json()
        before_bank = bank.model_dump_json()
        issues = validate_current_cv_references(cv, bank)
        assert cv.model_dump_json() == before_cv
        assert bank.model_dump_json() == before_bank
        return issues

    def save_cv(cv):
        events.append("save CV")
        assert cv == current_cv
        return original_save(cv)

    monkeypatch.setattr(bank_repository, "load", load_bank)
    monkeypatch.setattr("app.main.validate_current_cv_references", validate)
    monkeypatch.setattr(cv_repository, "save", save_cv)
    assert client.put("/current-cv", json=current_cv.model_dump()).status_code == 200
    assert events == ["load bank", "validate", "save CV"]


def test_put_empty_cv_replaces_existing_cv(client, repositories, current_cv):
    _, cv_repository = repositories
    cv_repository.save(current_cv)
    response = client.put("/current-cv", json={})
    assert response.status_code == 200
    assert response.json() == CurrentCV().model_dump()
    assert cv_repository.load() == CurrentCV()


@pytest.mark.parametrize("payload,path,reference,reason", [
    (
        {"work_experience": [{"work_experience_id": "missing-role"}]},
        "work_experience[0].work_experience_id", "missing-role",
        "Work experience does not exist in the experience bank.",
    ),
    (
        {"projects": [{"project_id": "missing-project"}]},
        "projects[0].project_id", "missing-project",
        "Project does not exist in the experience bank.",
    ),
    (
        {"work_experience": [{"work_experience_id": "role-a", "achievement_ids": ["missing-achievement"]}]},
        "work_experience[0].achievement_ids[0]", "missing-achievement",
        "Achievement does not exist in the experience bank.",
    ),
    (
        {"projects": [{"project_id": "project-a", "contribution_ids": ["missing-contribution"]}]},
        "projects[0].contribution_ids[0]", "missing-contribution",
        "Contribution does not exist in the experience bank.",
    ),
    (
        {"work_experience": [{"work_experience_id": "role-a", "achievement_ids": ["achievement-b1"]}]},
        "work_experience[0].achievement_ids[0]", "achievement-b1",
        "Achievement does not belong to the selected work experience.",
    ),
    (
        {"projects": [{"project_id": "project-a", "contribution_ids": ["contribution-b1"]}]},
        "projects[0].contribution_ids[0]", "contribution-b1",
        "Contribution does not belong to the selected project.",
    ),
    (
        {"skill_groups": [{"name": "Languages", "skill_keys": ["rust"]}]},
        "skill_groups[0].skill_keys[0]", "rust",
        "Skill key is not available in the experience bank.",
    ),
])
def test_put_rejects_invalid_references_without_saving(
    client, repositories, current_cv, monkeypatch, payload, path, reference, reason,
):
    bank_repository, cv_repository = repositories
    cv_repository.save(current_cv)
    before_cv = cv_repository.path.read_bytes()
    before_bank = bank_repository.path.read_bytes()
    save = Mock(side_effect=AssertionError("Invalid references must not save"))
    monkeypatch.setattr(cv_repository, "save", save)
    response = client.put("/current-cv", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": [{"path": path, "reference": reference, "reason": reason}]}
    save.assert_not_called()
    assert cv_repository.path.read_bytes() == before_cv
    assert bank_repository.path.read_bytes() == before_bank


def test_put_returns_all_reference_issues_together(client, repositories):
    _, cv_repository = repositories
    response = client.put("/current-cv", json={
        "work_experience": [{"work_experience_id": "missing-role", "achievement_ids": ["missing-achievement"]}],
        "projects": [{"project_id": "project-a", "contribution_ids": ["contribution-b1"]}],
        "skill_groups": [{"name": "Languages", "skill_keys": ["python", "rust"]}],
    })
    assert response.status_code == 422
    assert [(issue["path"], issue["reference"]) for issue in response.json()["detail"]] == [
        ("work_experience[0].work_experience_id", "missing-role"),
        ("work_experience[0].achievement_ids[0]", "missing-achievement"),
        ("projects[0].contribution_ids[0]", "contribution-b1"),
        ("skill_groups[0].skill_keys[1]", "rust"),
    ]
    assert not cv_repository.path.exists()


@pytest.mark.parametrize("payload", [
    {"schema_version": 2},
    {"future_field": "data"},
    {"work_experience": [{}]},
    {"work_experience": [{"work_experience_id": " "}]},
    {"work_experience": [{"work_experience_id": "role-a"}, {"work_experience_id": "role-a"}]},
    {"projects": [{"project_id": "project-a", "contribution_ids": ["contribution-a1", "contribution-a1"]}]},
    {"skill_groups": [{"name": "Skills", "skill_keys": ["Python"]}]},
    {"tailoring_settings": {"max_skills": True}},
    [],
    {"current_cv": {}, "reference_issues": []},
])
def test_put_invalid_structure_fails_before_repository_access(client, repositories, current_cv, monkeypatch, payload):
    bank_repository, cv_repository = repositories
    cv_repository.save(current_cv)
    before_cv = cv_repository.path.read_bytes()
    before_bank = bank_repository.path.read_bytes()
    load = Mock(side_effect=AssertionError("Invalid structure must not load the bank"))
    save = Mock(side_effect=AssertionError("Invalid structure must not save"))
    monkeypatch.setattr(bank_repository, "load", load)
    monkeypatch.setattr(cv_repository, "save", save)
    response = client.put("/current-cv", json=payload)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    load.assert_not_called()
    save.assert_not_called()
    assert cv_repository.path.read_bytes() == before_cv
    assert bank_repository.path.read_bytes() == before_bank


@pytest.mark.parametrize("method,repository_kind,operation,expected_detail", [
    ("GET", "cv", "load", "The Current CV could not be loaded."),
    ("GET", "bank", "load", "The experience bank could not be loaded."),
    ("PUT", "bank", "load", "The experience bank could not be loaded."),
    ("PUT", "cv", "save", "The Current CV could not be saved."),
])
def test_repository_errors_return_generic_503_without_diagnostics(
    client, repositories, current_cv, monkeypatch, method, repository_kind, operation, expected_detail,
):
    bank_repository, cv_repository = repositories
    cv_repository.save(current_cv)
    before_cv = cv_repository.path.read_bytes()
    before_bank = bank_repository.path.read_bytes()
    repository = cv_repository if repository_kind == "cv" else bank_repository
    error_type = CurrentCVRepositoryError if repository_kind == "cv" else ExperienceBankRepositoryError
    failure = Mock(side_effect=error_type(f"Private diagnostics at {repository.path}"))
    monkeypatch.setattr(repository, operation, failure)
    response = client.request(method, "/current-cv", json=current_cv.model_dump() if method == "PUT" else None)
    assert response.status_code == 503
    assert response.json() == {"detail": expected_detail}
    assert str(repository.path) not in response.text
    assert "Private diagnostics" not in response.text
    assert cv_repository.path.read_bytes() == before_cv
    assert bank_repository.path.read_bytes() == before_bank


@pytest.mark.parametrize("repository_kind", ["cv", "bank"])
@pytest.mark.parametrize("stored", [b"not json", b'{"schema_version": 999}'])
def test_get_corrupt_or_invalid_stored_files_returns_503_without_overwriting(
    client, repositories, current_cv, repository_kind, stored,
):
    bank_repository, cv_repository = repositories
    cv_repository.save(current_cv)
    repository = cv_repository if repository_kind == "cv" else bank_repository
    repository.path.write_bytes(stored)
    before_cv = cv_repository.path.read_bytes()
    before_bank = bank_repository.path.read_bytes()
    response = client.get("/current-cv")
    assert response.status_code == 503
    expected = "The Current CV could not be loaded." if repository_kind == "cv" else "The experience bank could not be loaded."
    assert response.json() == {"detail": expected}
    assert cv_repository.path.read_bytes() == before_cv
    assert bank_repository.path.read_bytes() == before_bank


def test_put_corrupt_bank_does_not_save(client, repositories, current_cv, monkeypatch):
    bank_repository, cv_repository = repositories
    cv_repository.save(current_cv)
    before_cv = cv_repository.path.read_bytes()
    bank_repository.path.write_bytes(b"not json")
    save = Mock(side_effect=AssertionError("An unreadable bank must not allow saving"))
    monkeypatch.setattr(cv_repository, "save", save)
    response = client.put("/current-cv", json={})
    assert response.status_code == 503
    assert response.json() == {"detail": "The experience bank could not be loaded."}
    save.assert_not_called()
    assert cv_repository.path.read_bytes() == before_cv
    assert bank_repository.path.read_bytes() == b"not json"


@pytest.mark.parametrize("failure_stage", ["write", "replace"])
def test_actual_save_failure_preserves_previous_cv_and_bank(
    client, repositories, current_cv, monkeypatch, failure_stage,
):
    bank_repository, cv_repository = repositories
    cv_repository.save(CurrentCV())
    before_cv = cv_repository.path.read_bytes()
    before_bank = bank_repository.path.read_bytes()
    temporary_path = cv_repository.path.with_suffix(".json.tmp")
    original_write = Path.write_text

    def fail_write(self, *args, **kwargs):
        if self == temporary_path:
            original_write(self, "partial JSON", encoding="utf-8")
            raise OSError(f"Write failed at {self}")
        return original_write(self, *args, **kwargs)

    def fail_replace(source, destination):
        assert source == temporary_path
        assert destination == cv_repository.path
        assert cv_repository.path.read_bytes() == before_cv
        raise OSError(f"Replace failed at {destination}")

    if failure_stage == "write":
        monkeypatch.setattr(Path, "write_text", fail_write)
    else:
        monkeypatch.setattr("app.repositories.json_current_cv.os.replace", fail_replace)
    response = client.put("/current-cv", json=current_cv.model_dump())
    assert response.status_code == 503
    assert response.json() == {"detail": "The Current CV could not be saved."}
    assert cv_repository.path.read_bytes() == before_cv
    assert bank_repository.path.read_bytes() == before_bank
    assert not temporary_path.exists()


def test_put_can_replace_corrupt_previous_cv_after_validating_new_document(client, repositories, current_cv):
    _, cv_repository = repositories
    cv_repository.path.write_bytes(b"not json")
    response = client.put("/current-cv", json=current_cv.model_dump())
    assert response.status_code == 200
    assert response.json() == current_cv.model_dump()
    assert cv_repository.load() == current_cv


def test_current_cv_exposes_only_get_and_put_with_response_models():
    schema = app.openapi()
    endpoints = schema["paths"]["/current-cv"]
    assert set(endpoints) == {"get", "put"}
    assert endpoints["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/CurrentCVLoadResponse")
    assert endpoints["put"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/CurrentCV")
