from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
import httpx
from openai import BadRequestError, OpenAIError
from pydantic import ValidationError

from app.main import app
from app.models import JobDescriptionAnalysis, JobDescriptionExtraction
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


def extracted_requirement(text="Python", **changes):
    return {
        "text": text, "source_text": text, "category": "skill",
        "importance": "unspecified", "alternatives": [text], "activity": None,
        **changes,
    }


def test_llm_service_validates_and_returns_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_response = {
        "job_title": "Backend Engineer",
        "requirements": [extracted_requirement()],
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

    result = llm.analyse_job_description_with_llm("Backend Engineer. Python experience.")

    assert isinstance(result, JobDescriptionAnalysis)
    assert result.job_title == "Backend Engineer"
    assert result.technical_skills == ["Python"]
    assert result.requirements[0].id == "r1"
    assert completions.response_format is JobDescriptionExtraction


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


def test_typed_structured_extraction_is_adapted_to_compatible_analysis(monkeypatch):
    completions = FakeCompletions(JobDescriptionExtraction(
        job_title="Engineer", requirements=[extracted_requirement()],
    ))
    configure_fake_client(monkeypatch, completions)
    result = llm.analyse_job_description_with_llm("Engineer using Python for services.")
    assert isinstance(result, JobDescriptionAnalysis)
    assert result.requirements[0].id == "r1"
    assert set(result.model_dump()) == {
        "job_title", "technical_skills", "other_keywords", "responsibilities", "qualifications",
        "requirements",
    }
    assert completions.response_format is JobDescriptionExtraction
    assert set(completions.response_format.model_json_schema()["properties"]) == {
        "job_title", "requirements",
    }


def test_qualification_prompt_preserves_alternatives_and_independent_requirements(monkeypatch):
    degree = "Bachelor's or Master's degree in Computer Science, Engineering, or a related field"
    certificate = "AWS Certified Developer"
    completions = FakeCompletions({
        "job_title": "Engineer",
        "requirements": [
            extracted_requirement(degree, category="qualification"),
            extracted_requirement(certificate, category="qualification"),
        ],
    })
    monkeypatch.setattr(
        llm,
        "Settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model")
    )
    monkeypatch.setattr(llm, "OpenAI", lambda api_key: FakeOpenAI(completions))
    result = llm.analyse_job_description_with_llm(degree + ". Also requires " + certificate)
    prompt = " ".join(completions.messages[0]["content"].split())
    assert "Preserve alternative qualifications as a single requirement string" in prompt
    assert "Do not expand alternatives into separate mandatory requirements" in prompt
    assert "Keep genuinely independent requirements as separate items" in prompt
    assert degree in prompt
    assert result.qualifications == [degree, certificate]
    assert completions.response_format is JobDescriptionExtraction


def configure_fake_client(monkeypatch, completions):
    monkeypatch.setattr(llm, "Settings", lambda: SimpleNamespace(
        openai_api_key="test-key", openai_model="test-model",
    ))
    monkeypatch.setattr(llm, "OpenAI", lambda api_key: FakeOpenAI(completions))


@pytest.mark.parametrize("refusal", [None, "Cannot analyse this description"])
def test_missing_parsed_output_or_refusal_becomes_service_error_and_502(monkeypatch, refusal):
    # A refusal must fail even if a parsed object is present.
    parsed = {"job_title": "Engineer", "requirements": []} if refusal else None
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
    "job_title", "text", "source_text", "alternatives", "category", "importance", "activity",
])
def test_invalid_extracted_content_is_wrapped_and_returns_502(monkeypatch, field):
    parsed = {"job_title": "Engineer", "requirements": [extracted_requirement()]}
    if field == "job_title":
        parsed[field] = " \t\n"
    else:
        parsed["requirements"][0][field] = ["Valid entry", " \t\n"] if field == "alternatives" else " \t\n"
    configure_fake_client(monkeypatch, FakeCompletions(parsed))
    with pytest.raises(llm.LLMServiceError) as caught:
        llm.analyse_job_description_with_llm("A valid job description.")
    assert isinstance(caught.value.__cause__, ValidationError)
    response = TestClient(app).post("/analyse", json={
        "job_description": "A valid job description.",
    })
    assert response.status_code == 502
    assert response.json() == {"detail": "The job description could not be analysed."}


def test_provider_schema_is_structured_only_with_required_nullable_activity():
    schema = JobDescriptionExtraction.model_json_schema()
    assert set(schema["properties"]) == set(schema["required"]) == {"job_title", "requirements"}
    assert schema["additionalProperties"] is False
    item_schema = schema["$defs"]["ExtractedRequirement"]
    assert set(item_schema["properties"]) == set(item_schema["required"]) == {
        "text", "source_text", "category", "importance", "alternatives", "activity",
    }
    assert item_schema["additionalProperties"] is False
    assert {variant.get("type") for variant in item_schema["properties"]["activity"]["anyOf"]} == {
        "string", "null",
    }


def test_normal_structured_extraction_preserves_metadata_and_derives_all_lists(monkeypatch):
    source = (
        "Backend Engineer\nEssential: Python or Java experience.\n"
        "Preferred: AWS experience.\nWork collaboratively with colleagues.\n"
        "Design and build APIs.\nDeploy applications to Azure.\n"
        "A BSc in Computer Science is required."
    )
    requirements = [
        extracted_requirement("Python or Java", source_text="Essential: Python or Java experience.",
                              importance="required", alternatives=["Python", "Java"]),
        extracted_requirement("AWS", source_text="Preferred: AWS experience.", importance="preferred"),
        extracted_requirement("Teamwork", source_text="Work collaboratively with colleagues.",
                              category="other_keyword"),
        extracted_requirement("API development", source_text="Design and build APIs.",
                              category="responsibility", activity="api_development"),
        extracted_requirement("Cloud deployment", source_text="Deploy applications to Azure.",
                              category="responsibility", activity="cloud_deployment"),
        extracted_requirement("BSc in Computer Science", source_text="A BSc in Computer Science is required.",
                              category="qualification", importance="required"),
    ]
    completions = FakeCompletions({"job_title": "Backend Engineer", "requirements": requirements})
    configure_fake_client(monkeypatch, completions)
    result = llm.analyse_job_description_with_llm(source)
    assert result.technical_skills == ["Python or Java", "AWS"]
    assert result.other_keywords == ["Teamwork"]
    assert result.responsibilities == ["API development", "Cloud deployment"]
    assert result.qualifications == ["BSc in Computer Science"]
    assert [item.importance for item in result.requirements] == [
        "required", "preferred", "unspecified", "unspecified", "unspecified", "required",
    ]
    assert result.requirements[0].alternatives == ["Python", "Java"]
    assert [item.id for item in result.requirements] == [f"r{i}" for i in range(1, 7)]
    assert completions.messages[1] == {"role": "user", "content": source}
    assert all(item.source_text in source for item in result.requirements)


def test_independently_required_languages_are_separate(monkeypatch):
    source = "Engineer. Python and Java are both required."
    items = [extracted_requirement(language, importance="required",
                                   source_text="Python and Java are both required.")
             for language in ("Python", "Java")]
    configure_fake_client(monkeypatch, FakeCompletions({"job_title": "Engineer", "requirements": items}))
    result = llm.analyse_job_description_with_llm(source)
    assert result.technical_skills == ["Python", "Java"]
    assert [item.alternatives for item in result.requirements] == [["Python"], ["Java"]]


def test_duties_prior_experience_cloud_mentions_and_deployment_stay_distinct(monkeypatch):
    source = (
        "Engineer. Responsibilities: build APIs. Prior API development experience is required. "
        "Cloud technologies include Azure AI Search. "
        "Prior experience deploying applications to AWS is required. "
        "Use Azure AI Search for retrieval."
    )
    items = [
        extracted_requirement("Build APIs", source_text="Responsibilities: build APIs.",
                              category="responsibility", activity="api_development"),
        extracted_requirement("API development experience", source_text="Prior API development experience is required.",
                              importance="required", activity="api_development"),
        extracted_requirement("Azure AI Search", source_text="Cloud technologies include Azure AI Search."),
        extracted_requirement("AWS deployment experience",
                              source_text="Prior experience deploying applications to AWS is required.",
                              importance="required", activity="cloud_deployment"),
        extracted_requirement("Use Azure AI Search", source_text="Use Azure AI Search for retrieval.",
                              category="responsibility", activity="technology_usage"),
    ]
    configure_fake_client(monkeypatch, FakeCompletions({"job_title": "Engineer", "requirements": items}))
    result = llm.analyse_job_description_with_llm(source)
    assert result.requirements[0].category == "responsibility"
    assert result.requirements[0].importance == "unspecified"
    assert result.requirements[1].category == "skill"
    assert result.requirements[1].importance == "required"
    assert result.requirements[2].activity is None
    assert result.requirements[3].activity == "cloud_deployment"
    assert result.requirements[4].activity == "technology_usage"


def test_degree_alternatives_preserve_complete_level_subject_branches(monkeypatch):
    degree = "BSc in Engineering or MSc in Computer Science"
    source = "Engineer. Requires " + degree + "."
    items = [extracted_requirement(degree, category="qualification", importance="required",
                                   alternatives=["BSc in Engineering", "MSc in Computer Science"])]
    configure_fake_client(monkeypatch, FakeCompletions({"job_title": "Engineer", "requirements": items}))
    result = llm.analyse_job_description_with_llm(source)
    assert result.qualifications == [degree]
    assert result.requirements[0].alternatives == ["BSc in Engineering", "MSc in Computer Science"]


def test_nested_alternatives_can_remain_one_opaque_requirement(monkeypatch):
    wording = "(Python and FastAPI) or (Java and Spring)"
    source = "Engineer. Experience with " + wording + "."
    configure_fake_client(monkeypatch, FakeCompletions({
        "job_title": "Engineer", "requirements": [extracted_requirement(wording)],
    }))
    result = llm.analyse_job_description_with_llm(source)
    assert result.requirements[0].alternatives == [wording]
    assert result.technical_skills == [wording]


def test_explicit_empty_requirements_derive_empty_categories(monkeypatch):
    configure_fake_client(monkeypatch, FakeCompletions({"job_title": "Engineer", "requirements": []}))
    result = llm.analyse_job_description_with_llm("Engineer. Contact our recruitment team.")
    assert result.requirements == []
    assert all(result.model_dump()[field] == [] for field in (
        "technical_skills", "other_keywords", "responsibilities", "qualifications",
    ))


@pytest.mark.parametrize("parsed", [
    {"job_title": "Engineer"},
    {"job_title": "Engineer", "requirements": None},
    {"job_title": "Engineer", "requirements": [{}]},
    {"job_title": "Engineer", "requirements": [], "technical_skills": ["Python"]},
    {"job_title": "Engineer", "requirements": [extracted_requirement(id="model-id")]},
])
def test_missing_malformed_or_independent_legacy_output_fails(monkeypatch, parsed):
    configure_fake_client(monkeypatch, FakeCompletions(parsed))
    with pytest.raises(llm.LLMServiceError):
        llm.analyse_job_description_with_llm("Engineer. Python is required.")


def test_unsupported_source_quote_is_a_service_error_and_generic_502(monkeypatch):
    configure_fake_client(monkeypatch, FakeCompletions({
        "job_title": "Engineer", "requirements": [extracted_requirement("Rust")],
    }))
    with pytest.raises(llm.LLMServiceError) as caught:
        llm.analyse_job_description_with_llm("Engineer. Python is required.")
    assert isinstance(caught.value.__cause__, ValueError)
    response = TestClient(app).post("/analyse", json={"job_description": "Engineer. Python is required."})
    assert response.status_code == 502
    assert response.json() == {"detail": "The job description could not be analysed."}


def test_empty_provider_choices_are_wrapped_as_service_error_and_502(monkeypatch):
    configure_fake_client(monkeypatch, SimpleNamespace(parse=lambda **kwargs: SimpleNamespace(choices=[])))
    with pytest.raises(llm.LLMServiceError) as caught:
        llm.analyse_job_description_with_llm("Engineer. Python is required.")
    assert isinstance(caught.value.__cause__, IndexError)
    response = TestClient(app).post("/analyse", json={"job_description": "Engineer. Python is required."})
    assert response.status_code == 502
    assert response.json() == {"detail": "The job description could not be analysed."}


def test_prompt_contains_conservative_importance_activity_and_source_rules():
    prompt = " ".join(llm.EXTRACTION_PROMPT.split())
    for rule in (
        "Do not produce requirement IDs or the legacy", "Never invent a quote",
        "otherwise use unspecified", "Do not turn responsibilities into required prior experience",
        "Do not infer cloud deployment", "never cross-pair levels and subjects",
        "Do not invent logical groupings", "Do not invent requirements",
    ):
        assert rule.lower() in prompt.lower()


def test_provider_failure_logs_safe_status_and_schema_metadata(monkeypatch, caplog):
    error = BadRequestError(
        "PRIVATE_PROVIDER_MESSAGE",
        response=httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")),
        body={"code": "invalid_json_schema", "param": "response_format", "message": "PRIVATE_PROVIDER_BODY"},
    )

    def parse(**kwargs):
        raise error

    configure_fake_client(monkeypatch, SimpleNamespace(parse=parse))
    with pytest.raises(llm.LLMServiceError) as caught:
        llm.analyse_job_description_with_llm("Engineer. Python is required.")
    assert caught.value.__cause__ is error
    assert "stage=provider" in caplog.text
    assert "upstream_status=400" in caplog.text
    assert "upstream_code=invalid_json_schema" in caplog.text
    assert "upstream_parameter=response_format" in caplog.text
    assert "PRIVATE_PROVIDER" not in caplog.text
    assert "test-key" not in caplog.text


def test_schema_failure_logs_paths_and_types_without_private_inputs(monkeypatch, caplog):
    configure_fake_client(monkeypatch, FakeCompletions({
        "job_title": "PRIVATE_TITLE", "requirements": [extracted_requirement(activity="PRIVATE_ACTIVITY")],
        "PRIVATE_FIELD_NAME": "PRIVATE_FIELD_VALUE",
    }))
    with pytest.raises(llm.LLMServiceError):
        llm.analyse_job_description_with_llm("Engineer. Python is required.")
    assert "stage=structured_validation" in caplog.text
    assert "requirements.0.activity:literal_error" in caplog.text
    assert "unknown_field:extra_forbidden" in caplog.text
    assert "PRIVATE_" not in caplog.text


@pytest.mark.parametrize("refusal", [None, "PRIVATE_REFUSAL"])
def test_missing_output_and_refusals_log_safe_reasons(monkeypatch, caplog, refusal):
    configure_fake_client(monkeypatch, FakeCompletions(None, refusal=refusal))
    with pytest.raises(llm.LLMServiceError):
        llm.analyse_job_description_with_llm("Engineer. Python is required.")
    assert "stage=provider_response" in caplog.text
    assert ("reason=refusal" if refusal else "reason=missing_parsed_output") in caplog.text
    assert "PRIVATE_REFUSAL" not in caplog.text


def test_configuration_failure_is_identified_before_provider_access(monkeypatch, caplog):
    from pydantic import BaseModel

    class MissingKey(BaseModel):
        openai_api_key: str

    def settings():
        return MissingKey.model_validate({})

    def unexpected_client(**kwargs):
        pytest.fail("Invalid configuration must fail before provider access")

    monkeypatch.setattr(llm, "Settings", settings)
    monkeypatch.setattr(llm, "OpenAI", unexpected_client)
    with pytest.raises(llm.LLMServiceError):
        llm.analyse_job_description_with_llm("Engineer. Python is required.")
    assert "stage=configuration" in caplog.text
    assert "openai_api_key:missing" in caplog.text


def test_successful_analysis_does_not_log_failure(monkeypatch, caplog):
    configure_fake_client(monkeypatch, FakeCompletions({
        "job_title": "Engineer", "requirements": [extracted_requirement()],
    }))
    assert llm.analyse_job_description_with_llm("Engineer. Python is required.").technical_skills == ["Python"]
    assert not any("Job analysis failed" in message for message in caplog.messages)
