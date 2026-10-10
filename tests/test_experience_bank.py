import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import (
    Certification, Education, EvidenceItem, ExperienceBank, Project, WorkExperience,
)
from app.repositories.json_experience_bank import (
    ExperienceBankRepositoryError, JsonExperienceBankRepository,
)


@pytest.mark.parametrize("blank", ["", " ", "\t\n", "\u00a0"])
@pytest.mark.parametrize("field", ["text", "skills", "technologies", "outcomes"])
def test_evidence_rejects_blank_content(field, blank):
    payload = {"text": "An achievement"}
    payload[field] = blank if field == "text" else ["Valid entry", blank]
    with pytest.raises(ValidationError):
        EvidenceItem.model_validate(payload)


@pytest.mark.parametrize("model,payload", [
    (EvidenceItem, {"text": "Achievement"}),
    (WorkExperience, {"employer": "Example", "role": "Engineer"}),
    (Project, {"name": "Project"}),
    (Education, {"institution": "University", "qualification": "BSc"}),
    (Certification, {"name": "Certificate"}),
])
@pytest.mark.parametrize("blank", ["", "\t \n"])
def test_all_record_ids_must_be_nonblank(model, payload, blank):
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "id": blank})


@pytest.mark.parametrize("payload", [
    {"skills": [" "]},
    {"work_experience": [{"employer": "Example", "role": "Engineer", "skills": [" "]}]},
    {"work_experience": [{"employer": "Example", "role": "Engineer", "technologies": [" "]}]},
    {"projects": [{"name": "Project", "skills": [" "]}]},
    {"projects": [{"name": "Project", "technologies": [" "]}]},
    {"certifications": [{"name": "Certificate", "skills": [" "]}]},
])
def test_parent_and_standalone_tags_must_be_nonblank(payload):
    with pytest.raises(ValidationError):
        ExperienceBank.model_validate(payload)


def test_valid_text_and_optional_fields_are_preserved():
    payload = {
        "id": "custom-id", "text": "  Built services.\nAdded tests.  ",
        "skills": [" Python "], "technologies": [" FastAPI "],
        "outcomes": [" Improved coverage "],
    }
    assert EvidenceItem.model_validate(payload).model_dump() == payload
    bank = ExperienceBank(
        work_experience=[WorkExperience(employer="Example", role="Engineer")],
        projects=[Project(name="Project")],
        education=[Education(institution="University", qualification="BSc")],
        certifications=[Certification(name="Certificate")],
        additional_evidence=[EvidenceItem(text="Evidence")],
    )
    assert bank.work_experience[0].summary == ""
    assert bank.projects[0].description == ""
    assert bank.education[0].field == ""
    assert bank.certifications[0].issuer == ""
    assert bank.additional_evidence[0].outcomes == []
    assert bank.work_experience[0].start_date is None
    assert bank.projects[0].link is None
    assert ExperienceBank().skills == []


@pytest.mark.parametrize("payload", [
    {"additional_evidence": [{"id": "same", "text": "One"}, {"id": "same", "text": "Two"}]},
    {"work_experience": [{"id": "same", "employer": "Example", "role": "Engineer", "achievements": [{"id": "same", "text": "Child"}]}]},
    {"work_experience": [{"employer": "Example", "role": "Engineer", "achievements": [{"id": "same", "text": "Work"}]}], "projects": [{"name": "Project", "evidence": [{"id": "same", "text": "Project"}]}]},
    {"education": [{"id": "same", "institution": "University", "qualification": "BSc"}], "certifications": [{"id": "same", "name": "Certificate"}]},
])
def test_ids_are_unique_across_bank_records(payload):
    with pytest.raises(ValidationError, match="Duplicate experience-bank ID"):
        ExperienceBank.model_validate(payload)


@pytest.mark.parametrize("version", [0, 2, 999, "1", True, 1.0])
def test_only_integer_schema_version_one_is_supported(version):
    with pytest.raises(ValidationError):
        ExperienceBank(schema_version=version)


@pytest.mark.parametrize("payload", [
    {"future_field": "data"},
    {"additional_evidence": [{"text": "Evidence", "future_field": "data"}]},
    {"work_experience": [{"employer": "Example", "role": "Engineer", "future_field": "data"}]},
    {"projects": [{"name": "Project", "evidence": [{"text": "Evidence", "future_field": "data"}]}]},
    {"education": [{"institution": "University", "qualification": "BSc", "future_field": "data"}]},
    {"certifications": [{"name": "Certificate", "future_field": "data"}]},
])
def test_unknown_fields_are_rejected_at_every_bank_level(payload):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ExperienceBank.model_validate(payload)


@pytest.mark.parametrize("invalid", [
    {"schema_version": 2},
    {"unknown": "must not disappear"},
    {"additional_evidence": [{"text": " "}]},
    {"additional_evidence": [{"id": "same", "text": "One"}, {"id": "same", "text": "Two"}]},
])
def test_invalid_put_does_not_overwrite_bank(monkeypatch, tmp_path, invalid):
    path = tmp_path / "bank.json"
    repository = JsonExperienceBankRepository(path)
    repository.save(ExperienceBank(skills=["Python"]))
    before = path.read_bytes()
    monkeypatch.setattr("app.main.experience_bank_repository", repository)
    response = TestClient(app).put("/experience-bank", json=invalid)
    assert response.status_code == 422
    assert path.read_bytes() == before


@pytest.mark.parametrize("payload", [{"schema_version": 2}, {"unknown": "data"}])
def test_invalid_saved_bank_fails_to_load_without_modifying_file(monkeypatch, tmp_path, payload):
    path = tmp_path / "bank.json"
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    repository = JsonExperienceBankRepository(path)
    with pytest.raises(ExperienceBankRepositoryError):
        repository.load()
    monkeypatch.setattr("app.main.experience_bank_repository", repository)
    assert TestClient(app).get("/experience-bank").status_code == 503
    assert path.read_bytes() == before
