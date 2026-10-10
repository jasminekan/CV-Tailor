from types import SimpleNamespace

import pytest

from app.models import JobDescriptionAnalysis
from app.services import llm


class FakeCompletions:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed
        self.response_format: object | None = None
        self.messages = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.response_format = kwargs["response_format"]
        self.messages = kwargs["messages"]
        message = SimpleNamespace(parsed=self.parsed, refusal=None)
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
