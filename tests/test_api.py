import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.main import app
from app.models import JobDescriptionAnalysis, JobDescriptionRequest
from app.services.llm import LLMServiceError

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_is_served_from_root() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Analyse job" in response.text


def test_frontend_assets_are_served() -> None:
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'fetch("/analyse"' in response.text


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