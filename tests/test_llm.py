from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openai import OpenAIError
from pydantic import ValidationError

from app.main import app
from app.models import JobDescriptionAnalysis
from app.services import llm


class FakeCompletions:
    def __init__(self, parsed: object, refusal: str | None = None) -> None:
        self.parsed = parsed
        self.refusal = refusal
        self.response_format: object | None = None
        self.messages = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.response_format = kwargs["response_format"]
        self.messages = kwargs["messages"]
        message = SimpleNamespace(parsed=self.parsed, refusal=self.refusal)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
        )


class FakeOpenAI:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def test_llm_service_validates_and_returns_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_response = {
        "job_title": "Backend Engineer",
        "technical_skills": ["Python"],
    }
    completions = FakeCompletions(parsed_response)

    monkeypatch.setattr(llm, "Settings", lambda: SimpleNamespace(
        openai_api_key="test-key",
        openai_model="test-model",
    ))
    monkeypatch.setattr(
        llm,
        "OpenAI",
        lambda api_key: FakeOpenAI(completions),
    )

    result = llm.analyse_job_description_with_llm("A valid job description.")

    assert result == JobDescriptionAnalysis(
        job_title="Backend Engineer",
        technical_skills=["Python"],
    )
    assert completions.response_format is JobDescriptionAnalysis


def test_llm_service_rejects_malformed_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions = FakeCompletions({"technical_skills": ["Python"]})

    monkeypatch.setattr(llm, "Settings", lambda: SimpleNamespace(
        openai_api_key="test-key",
        openai_model="test-model",
    ))
    monkeypatch.setattr(
        llm,
        "OpenAI",
        lambda api_key: FakeOpenAI(completions),
    )

    with pytest.raises(llm.LLMServiceError):
        llm.analyse_job_description_with_llm("A valid job description.")


def test_qualification_prompt_preserves_alternatives_and_independent_requirements(monkeypatch):
    degree = "Bachelor's or Master's degree in Computer Science, Engineering, or a related field"
    certificate = "AWS Certified Developer"
    completions = FakeCompletions({
        "job_title": "Engineer",
        "qualifications": [degree, certificate]
    })
    monkeypatch.setattr(
        llm,
        "Settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model")
    )
    monkeypatch.setattr(llm, "OpenAI", lambda api_key: FakeOpenAI(completions))
    result = llm.analyse_job_description_with_llm(degree + ". Also requires " + certificate)
    prompt = completions.messages[0]["content"]
    assert "Preserve alternative qualifications as a single requirement string" in prompt
    assert "Do not expand alternatives into separate mandatory requirements" in prompt
    assert "Keep genuinely independent requirements as separate items" in prompt
    assert degree in prompt
    assert result.qualifications == [degree, certificate]
    assert completions.response_format is JobDescriptionAnalysis


def configure_fake_client(monkeypatch, completions):
    monkeypatch.setattr(llm, "Settings", lambda: SimpleNamespace(
        openai_api_key="test-key", openai_model="test-model",
    ))
    monkeypatch.setattr(llm, "OpenAI", lambda api_key: FakeOpenAI(completions))


@pytest.mark.parametrize("refusal", [None, "Cannot analyse this description"])
def test_missing_parsed_output_or_refusal_becomes_service_error_and_502(monkeypatch, refusal):
    # A refusal must fail even if a parsed object is present.
    parsed = {"job_title": "Engineer"} if refusal else None
    configure_fake_client(monkeypatch, FakeCompletions(parsed, refusal=refusal))
    with pytest.raises(llm.LLMServiceError, match="did not return an analysis"):
        llm.analyse_job_description_with_llm("A valid job description.")
    response = TestClient(app).post("/analyse", json={
        "job_description": "A valid job description.",
    })
    assert response.status_code == 502
    assert response.json() == {"detail": "The job description could not be analysed."}


def test_provider_error_is_wrapped_and_returns_502(monkeypatch):
    provider_error = OpenAIError("Provider failure containing private diagnostics")

    class FailingCompletions:
        def parse(self, **kwargs):
            raise provider_error

    configure_fake_client(monkeypatch, FailingCompletions())
    with pytest.raises(llm.LLMServiceError) as caught:
        llm.analyse_job_description_with_llm("A valid job description.")
    assert caught.value.__cause__ is provider_error
    response = TestClient(app).post("/analyse", json={
        "job_description": "A valid job description.",
    })
    assert response.status_code == 502
    assert response.json() == {"detail": "The job description could not be analysed."}


@pytest.mark.parametrize("field", [
    "job_title", "technical_skills", "other_keywords", "responsibilities", "qualifications",
])
def test_invalid_extracted_content_is_wrapped_and_returns_502(monkeypatch, field):
    parsed = {"job_title": "Engineer"}
    parsed[field] = " \t\n" if field == "job_title" else ["Valid entry", " \t\n"]
    configure_fake_client(monkeypatch, FakeCompletions(parsed))
    with pytest.raises(llm.LLMServiceError) as caught:
        llm.analyse_job_description_with_llm("A valid job description.")
    assert isinstance(caught.value.__cause__, ValidationError)
    response = TestClient(app).post("/analyse", json={
        "job_description": "A valid job description.",
    })
    assert response.status_code == 502
    assert response.json() == {"detail": "The job description could not be analysed."}
