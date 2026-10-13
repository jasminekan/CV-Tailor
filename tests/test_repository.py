import json

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app
from app.models import ExperienceBank, Project
from app.repositories.json_experience_bank import (
    ExperienceBankRepositoryError,
    JsonExperienceBankRepository,
)


def test_repository_round_trips_an_experience_bank(tmp_path) -> None:
    repository = JsonExperienceBankRepository(tmp_path / "experience_bank.json")
    bank = ExperienceBank(projects=[Project(name="API", technologies=["Python"])])

    repository.save(bank)

    assert repository.load() == bank


def test_repository_returns_empty_bank_when_file_is_missing(tmp_path) -> None:
    repository = JsonExperienceBankRepository(tmp_path / "missing.json")

    assert repository.load() == ExperienceBank()


def test_repository_rejects_corrupt_json(tmp_path) -> None:
    path = tmp_path / "experience_bank.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(ExperienceBankRepositoryError):
        JsonExperienceBankRepository(path).load()


def test_repository_writes_valid_json(tmp_path) -> None:
    path = tmp_path / "experience_bank.json"
    JsonExperienceBankRepository(path).save(ExperienceBank())

    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


@pytest.mark.parametrize("payload", [
    {"work_experience": [{"employer": "Example", "role": "Engineer"}]},
    {"work_experience": [{"id": "role", "employer": "Example", "role": "Engineer", "achievements": [{"text": "Bullet"}]}]},
    {"projects": [{"name": "Project"}]},
    {"projects": [{"id": "project", "name": "Project", "evidence": [{"text": "Contribution"}]}]},
    {"education": [{"institution": "University", "qualification": "BSc"}]},
    {"certifications": [{"name": "Certificate"}]},
    {"additional_evidence": [{"text": "Evidence"}]},
])
def test_stored_records_without_ids_fail_without_generating_unstable_references(tmp_path, monkeypatch, payload):
    path = tmp_path / "bank.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    repository = JsonExperienceBankRepository(path)
    with pytest.raises(ExperienceBankRepositoryError):
        repository.load()
    monkeypatch.setattr("app.main.experience_bank_repository", repository)
    response = TestClient(app).get("/experience-bank")
    assert response.status_code == 503
    assert response.json() == {"detail": "The experience bank could not be loaded."}
    assert path.read_bytes() == before


def test_put_still_generates_and_persists_ids_for_new_bank_records(tmp_path, monkeypatch):
    repository = JsonExperienceBankRepository(tmp_path / "bank.json")
    monkeypatch.setattr("app.main.experience_bank_repository", repository)
    response = TestClient(app).put("/experience-bank", json={
        "work_experience": [{"employer": "Example", "role": "Engineer", "achievements": [{"text": "Achievement"}]}],
        "projects": [{"name": "Project", "evidence": [{"text": "Contribution"}]}],
    })
    assert response.status_code == 200
    first = repository.load()
    assert first == repository.load()
    assert first.model_dump() == response.json()
    assert first.work_experience[0].id
    assert first.work_experience[0].achievements[0].id
    assert first.projects[0].id
    assert first.projects[0].evidence[0].id


def test_bank_save_cleanup_failure_preserves_original_error_and_saved_file(tmp_path, monkeypatch):
    path = tmp_path / "bank.json"
    repository = JsonExperienceBankRepository(path)
    repository.save(ExperienceBank(skills=["Python"]))
    before = path.read_bytes()
    original_unlink = Path.unlink
    failure = OSError("Replace failed")

    def fail_replace(*args):
        raise failure

    def fail_cleanup(self, *args, **kwargs):
        if self == path.with_suffix(".json.tmp"):
            raise PermissionError("Cleanup denied")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr("app.repositories.json_experience_bank.os.replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(ExperienceBankRepositoryError) as caught:
        repository.save(ExperienceBank())
    assert caught.value.__cause__ is failure
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure", [PermissionError("Read denied"), OSError("I/O failure")])
def test_bank_read_failure_is_not_treated_as_a_missing_empty_store(tmp_path, monkeypatch, failure):
    path = tmp_path / "bank.json"
    repository = JsonExperienceBankRepository(path)
    repository.save(ExperienceBank(skills=["Python"]))
    before = path.read_bytes()
    original_read = Path.read_text
    original_exists = Path.exists

    def fail_read(self, *args, **kwargs):
        if self == path:
            raise failure
        return original_read(self, *args, **kwargs)

    def failed_stat(self):
        return False if self == path else original_exists(self)

    monkeypatch.setattr(Path, "read_text", fail_read)
    monkeypatch.setattr(Path, "exists", failed_stat)
    with pytest.raises(ExperienceBankRepositoryError) as caught:
        repository.load()
    assert caught.value.__cause__ is failure
    assert path.read_bytes() == before
