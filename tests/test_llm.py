from types import SimpleNamespace

import pytest

from app.models import JobDescriptionAnalysis
from app.services import llm


class FakeCompletions:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed
        self.response_format: object | None = None

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.response_format = kwargs["response_format"]
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