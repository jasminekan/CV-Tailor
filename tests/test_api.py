import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    ExperienceBank,
    JobDescriptionAnalysis,
    JobDescriptionRequest,
    MatchRequest,
    Project,
)
from app.repositories.json_experience_bank import JsonExperienceBankRepository
from app.services.llm import LLMServiceError

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_is_served_from_root() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Analyse and match" in response.text


def test_frontend_assets_are_served() -> None:
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'request("/analyse"' in response.text
    assert 'request("/experience-bank"' in response.text
    assert 'request("/match"' in response.text


def test_analyse_returns_structured_llm_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_analysis = JobDescriptionAnalysis(
        job_title="Backend Engineer",
        technical_skills=["Python", "FastAPI"],
        other_keywords=["teamwork"],
        responsibilities=["Build reliable APIs"],
        qualifications=["Software development experience"],
    )

    def fake_llm_service(job_description: str) -> JobDescriptionAnalysis:
        assert "Python developer" in job_description
        return expected_analysis

    monkeypatch.setattr(
        "app.main.analyse_job_description_with_llm",
        fake_llm_service,
    )
    response = client.post(
        "/analyse",
        json={
            "job_description": (
                "We are looking for a Python developer to build reliable APIs."
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == expected_analysis.model_dump()


def test_analyse_returns_502_when_llm_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_llm_service(job_description: str) -> JobDescriptionAnalysis:
        raise LLMServiceError("Provider unavailable")

    monkeypatch.setattr(
        "app.main.analyse_job_description_with_llm",
        failing_llm_service,
    )
    response = client.post(
        "/analyse",
        json={
            "job_description": (
                "We are looking for a Python developer to build reliable APIs."
            )
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "The job description could not be analysed."
    }


def test_analyse_exposes_real_structured_service_with_compatible_legacy_fields(monkeypatch):
    from types import SimpleNamespace

    from app.models import JobDescriptionExtraction
    from app.services import llm

    source = "Backend Engineer. Python or Java is required. AWS is preferred."
    parsed = {
        "job_title": "Backend Engineer",
        "requirements": [
            {"text": "Python or Java", "source_text": "Python or Java is required.",
             "category": "skill", "importance": "required", "alternatives": ["Python", "Java"],
             "activity": None},
            {"text": "AWS", "source_text": "AWS is preferred.", "category": "skill",
             "importance": "preferred", "alternatives": ["AWS"], "activity": None},
        ],
    }
    captured = []

    def parse(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=None))])

    monkeypatch.setattr(llm, "Settings", lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model"))
    monkeypatch.setattr(llm, "OpenAI", lambda api_key: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)),
    ))
    response = client.post("/analyse", json={"job_description": source})
    assert response.status_code == 200
    result = response.json()
    assert result["job_title"] == "Backend Engineer"
    assert result["technical_skills"] == ["Python or Java", "AWS"]
    assert result["other_keywords"] == result["responsibilities"] == result["qualifications"] == []
    assert [item["id"] for item in result["requirements"]] == ["r1", "r2"]
    assert [item["importance"] for item in result["requirements"]] == ["required", "preferred"]
    assert result["requirements"][0]["alternatives"] == ["Python", "Java"]
    assert result["requirements"][0]["source_text"] == "Python or Java is required."
    assert captured[0]["response_format"] is JobDescriptionExtraction


def test_analyse_rejects_short_job_description() -> None:
    response = client.post(
        "/analyse",
        json={"job_description": "Too short"},
    )

    assert response.status_code == 422


def test_job_description_request_requires_meaningful_text() -> None:
    with pytest.raises(ValidationError):
        JobDescriptionRequest(job_description="Too short")


def test_analysis_lists_default_to_empty() -> None:
    analysis = JobDescriptionAnalysis(job_title="Software Engineer")

    assert analysis.technical_skills == []
    assert analysis.other_keywords == []
    assert analysis.responsibilities == []
    assert analysis.qualifications == []


def test_experience_bank_can_be_saved_and_loaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "app.main.experience_bank_repository",
        JsonExperienceBankRepository(tmp_path / "experience_bank.json"),
    )
    bank = ExperienceBank(projects=[Project(name="API", technologies=["Python"])])

    save_response = client.put("/experience-bank", json=bank.model_dump())
    load_response = client.get("/experience-bank")

    assert save_response.status_code == 200
    assert load_response.json() == bank.model_dump()


def test_match_uses_saved_experience_bank(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    repository = JsonExperienceBankRepository(tmp_path / "experience_bank.json")
    repository.save(ExperienceBank(projects=[Project(name="API", technologies=["Python"])]))
    monkeypatch.setattr("app.main.experience_bank_repository", repository)

    response = client.post(
        "/match",
        json=MatchRequest(
            job_analysis=JobDescriptionAnalysis(
                job_title="Engineer",
                technical_skills=["Python", "Docker"],
            )
        ).model_dump(),
    )

    assert response.status_code == 200
    assert response.json()["related_matches"][0]["requirement"] == "Python"
    assert response.json()["missing_requirements"][0]["requirement"] == "Docker"

@pytest.mark.parametrize("description", [" " * 20, "\t\n" * 20, "\u00a0" * 20])
def test_analyse_rejects_whitespace_before_calling_service(monkeypatch, description):
    def unexpected_call(job_description):
        pytest.fail("Whitespace-only requests must not reach the LLM service")

    monkeypatch.setattr("app.main.analyse_job_description_with_llm", unexpected_call)
    response = client.post("/analyse", json={"job_description": description})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "job_description"]


@pytest.mark.parametrize("blank", ["", "   ", "\t\n", "\u00a0"])
@pytest.mark.parametrize("field", [
    "job_title", "technical_skills", "other_keywords", "responsibilities", "qualifications",
])
def test_analysis_rejects_blank_title_and_individual_entries(field, blank):
    payload = {"job_title": "Engineer"}
    payload[field] = blank if field == "job_title" else ["Valid entry", blank]
    with pytest.raises(ValidationError):
        JobDescriptionAnalysis.model_validate(payload)


def test_analysis_allows_explicit_empty_lists_and_preserves_nonblank_text():
    payload = {
        "job_title": " Engineer ",
        "technical_skills": [],
        "other_keywords": [],
        "responsibilities": [],
        "qualifications": [],
    }
    assert JobDescriptionAnalysis.model_validate(payload).model_dump() == payload
    description = "  A valid multiline job description.\nPython developer.  "
    assert JobDescriptionRequest(job_description=description).job_description == description
