"""Offline evaluator checks; controlled outputs never establish live model quality."""

import json
from types import SimpleNamespace

from openai import OpenAIError
from openai.types import CompletionUsage
from pydantic import ValidationError
import pytest

from app.models import JobDescriptionExtraction
from app.services.llm import EXTRACTION_PROMPT
from evaluations.extraction import __main__ as cli
from evaluations.extraction.harness import (
    FixtureSuite, PROMPTS, contains, evaluate, load_fixtures, run_case, summarise, tokens,
)


@pytest.fixture
def suite():
    return load_fixtures()


@pytest.fixture
def case(suite):
    return suite.cases[0]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_reviewed_fixtures_pass_their_canonical_contract(suite, index):
    case = suite.cases[index]
    evaluation = evaluate(case, case.expected_extraction())
    assert evaluation["passed"]
    assert evaluation["metrics"]["completeness"] == 1
    assert all(evaluation["metrics"][field]["accuracy_on_matched"] == 1
               for field in ("category", "importance", "alternatives", "activity"))


def test_controlled_description_is_exact_and_expectations_are_seven(case):
    expected_input = (
        "We are hiring a Software Engineer to develop and maintain backend APIs.\n\n"
        "Candidates must have experience with Python or Java and relational databases.\n\n"
        "Experience with AWS or Azure is desirable but not essential.\n\n"
        "You will collaborate with engineers to design software solutions and deploy "
        "applications to cloud infrastructure.\n\n"
        "A Bachelor's degree in Computer Science or a related field is preferred."
    )
    assert case.job_description == expected_input
    assert len(case.expected) == 7


def test_replayed_six_requirement_output_reports_actual_introductory_omission(case):
    extraction = case.expected_extraction()
    extraction.requirements.pop(0)
    result = evaluate(case, extraction)
    assert not result["passed"]
    assert result["missing"] == [{"id": "backend_api_duty", "text": "Develop and maintain backend APIs"}]
    assert result["metrics"]["completeness"] == 6 / 7
    assert not result["incorrect"]
    assert not result["unexpected"]


def test_metadata_errors_match_content_independently_of_wrong_category(case):
    extraction = case.expected_extraction()
    item = extraction.requirements[3]
    item.category = "qualification"
    item.importance = "required"
    item.activity = "cloud_deployment"
    item.alternatives = ["Azure"]
    result = evaluate(case, extraction)
    assert result["missing"] == []
    assert {error["field"] for error in result["incorrect"]} == {
        "category", "importance", "activity", "alternatives",
    }
    assert all(error["expected_id"] == "cloud_or" and error["actual_index"] == 3
               for error in result["incorrect"])
    assert result["metrics"]["importance"]["correct"] == 6


def test_duplicate_requirement_is_reported_without_inflating_completeness(case):
    extraction = case.expected_extraction()
    extraction.requirements.append(extraction.requirements[1].model_copy(deep=True))
    result = evaluate(case, extraction)
    assert result["duplicates"] == [{"expected_id": "language_or", "actual_indices": [1, 7],
                                     "texts": ["Python or Java", "Python or Java"]}]
    assert result["metrics"]["covered_count"] == 7
    assert result["metrics"]["actual_count"] == 8
    assert not result["passed"]


def test_combined_collaboration_is_not_interchangeable_actions(case):
    extraction = case.expected_extraction()
    extraction.requirements[4].alternatives = ["Collaborate with engineers", "Design software solutions"]
    result = evaluate(case, extraction)
    assert result["incorrect"] == [{
        "expected_id": "collaborative_design", "text": "Collaborate with engineers to design software solutions",
        "actual_index": 4, "field": "alternatives",
        "expected": [["Collaborate with engineers to design software solutions"]],
        "actual": ["Collaborate with engineers", "Design software solutions"],
    }]


def test_or_group_split_into_two_obligations_is_not_counted_as_complete(case):
    extraction = case.expected_extraction()
    original = extraction.requirements.pop(1)
    extraction.requirements.extend([
        original.model_copy(update={"text": "Python", "alternatives": ["Python"]}),
        original.model_copy(update={"text": "Java", "alternatives": ["Java"]}),
    ])
    result = evaluate(case, extraction)
    assert result["missing"][0]["id"] == "language_or"
    assert [item["requirement"]["text"] for item in result["unexpected"]] == ["Python", "Java"]


def test_independent_and_requirements_merged_into_or_are_reported(suite):
    case = suite.cases[1]
    extraction = case.expected_extraction()
    python = extraction.requirements.pop(0)
    extraction.requirements.pop(0)
    extraction.requirements.insert(0, python.model_copy(update={
        "text": "Python or Java", "alternatives": ["Python", "Java"],
    }))
    result = evaluate(case, extraction)
    assert [item["id"] for item in result["missing"]] == ["python_required", "java_required"]
    assert result["merged_requirements"] == [{
        "actual_index": 0, "text": "Python or Java", "expected_ids": ["python_required", "java_required"],
    }]
    assert result["metrics"]["covered_count"] == 5


def test_distinct_duties_merged_in_one_record_are_reported(case):
    extraction = case.expected_extraction()
    collaboration = extraction.requirements.pop(4)
    extraction.requirements.pop(4)
    combined = "Collaborate with engineers to design software solutions and deploy applications to cloud infrastructure"
    extraction.requirements.append(collaboration.model_copy(update={"text": combined, "alternatives": [combined]}))
    result = evaluate(case, extraction)
    assert result["merged_requirements"][0]["expected_ids"] == ["collaborative_design", "cloud_deployment_duty"]
    assert {item["id"] for item in result["missing"]} == {"collaborative_design", "cloud_deployment_duty"}


def test_invented_and_duplicated_unexpected_content_is_reported(case):
    extraction = case.expected_extraction()
    invented = extraction.requirements[1].model_copy(update={"text": "Rust", "alternatives": ["Rust"]})
    extraction.requirements.extend([invented, invented.model_copy(deep=True)])
    result = evaluate(case, extraction)
    assert [row["actual_index"] for row in result["unexpected"]] == [7, 8]
    assert result["duplicates"][0]["expected_id"] is None


def test_shared_source_does_not_supply_missing_content(case):
    extraction = case.expected_extraction()
    extraction.requirements.pop(5)
    # The collaboration source still includes deployment, but its own text does not.
    assert "deploy applications" in extraction.requirements[4].source_text
    result = evaluate(case, extraction)
    assert result["missing"] == [{"id": "cloud_deployment_duty", "text": "Deploy applications to cloud infrastructure"}]


def test_reviewed_degree_representations_pass_but_cross_pairing_fails(case, suite):
    extraction = case.expected_extraction()
    extraction.requirements[-1].alternatives = [
        "Bachelor's degree in Computer Science", "Bachelor's degree in a related field",
    ]
    assert evaluate(case, extraction)["passed"]
    backend = suite.cases[1].expected_extraction()
    backend.requirements[-1].alternatives = ["BSc in Computer Science", "MSc in Engineering"]
    result = evaluate(suite.cases[1], backend)
    assert result["incorrect"][0]["field"] == "alternatives"


def test_reviewed_aliases_choice_order_and_formatting_are_tolerated_without_mutation(suite):
    case = suite.cases[2]
    extraction = case.expected_extraction()
    extraction.requirements[2].text = "Experience with JS or TS"
    extraction.requirements[2].alternatives = ["TS", "JS"]
    extraction.requirements[4].alternatives = ["Microsoft Azure", "Amazon Web Services"]
    before = (case.model_dump(), extraction.model_dump())
    first = evaluate(case, extraction)
    assert first["passed"]
    assert evaluate(case, extraction) == first
    assert (case.model_dump(), extraction.model_dump()) == before


@pytest.mark.parametrize("name, other", [("C", "C++"), ("C++", "C#"), ("Java", "JavaScript")])
def test_reviewed_phrase_matching_preserves_technical_boundaries(name, other):
    assert not contains(tokens(other), name)
    assert contains(tokens(f"Experience with {name}."), name)


def test_empty_output_and_wrong_title_are_quality_failures(case):
    result = evaluate(case, JobDescriptionExtraction(job_title="Different role", requirements=[]))
    assert result["metrics"]["completeness"] == 0
    assert len(result["missing"]) == 7
    assert result["metrics"]["category"]["accuracy_on_matched"] is None
    assert not result["job_title_correct"]


@pytest.mark.parametrize("invalid", ["version", "case_id", "expected_id", "anchors", "source", "alias"])
def test_malformed_reviewed_fixtures_fail_clearly(suite, invalid):
    payload = suite.model_dump()
    case = payload["cases"][0]
    if invalid == "version":
        payload["schema_version"] = 2
    elif invalid == "case_id":
        payload["cases"][1]["id"] = case["id"]
    elif invalid == "expected_id":
        case["expected"][1]["id"] = case["expected"][0]["id"]
    elif invalid == "anchors":
        case["expected"][0]["match_terms"] = [[]]
    elif invalid == "source":
        case["expected"][0]["source_text"] = "Invented original quotation"
    else:
        case["expected"][0]["option_aliases"] = {"Python": ["JS"], "Java": ["JS"]}
    with pytest.raises(ValidationError):
        FixtureSuite.model_validate(payload)


def fake_client(parsed, *, usage=True, refusal=None, error=None):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        return SimpleNamespace(
            model="resolved-model-snapshot",
            usage=CompletionUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150) if usage else None,
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(parsed=parsed, refusal=refusal))],
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))), calls


def test_runner_records_schema_prompts_model_usage_and_projection(case):
    client, calls = fake_client(case.expected_extraction())
    record = run_case(client, case, "requested-model", "current", 2, (2, 8))
    assert record["status"] == "ok"
    assert record["evaluation"]["passed"]
    assert record["resolved_model"] == "resolved-model-snapshot"
    assert record["repeat"] == 2
    assert record["usage"]["total_tokens"] == 150
    assert record["estimated_cost_usd"] == pytest.approx(0.0006)
    assert record["analysis"]["responsibilities"][0] == "Develop and maintain backend APIs"
    assert len(calls) == 1
    assert calls[0]["response_format"] is JobDescriptionExtraction
    assert calls[0]["messages"][0]["content"] == EXTRACTION_PROMPT
    assert calls[0]["messages"][1]["content"] == case.job_description
    summary = summarise([record])[0]
    assert summary["fully_correct"] == 1
    assert summary["tokens"]["total_tokens"] == 150


def test_source_failure_keeps_provider_content_and_semantic_evaluation(case):
    extraction = case.expected_extraction()
    extraction.requirements[0].source_text = "You will develop and maintain backend APIs."
    client, _ = fake_client(extraction)
    record = run_case(client, case, "model", "simple", 1)
    assert record["status"] == "source_error"
    assert record["error"]["requirement_id"] == "r1"
    assert record["extraction"]["requirements"][0]["source_text"].startswith("You will")
    assert record["evaluation"]["passed"]
    assert record["analysis"] is None
    summary = summarise([record])[0]
    assert summary["fully_correct"] == 0
    assert summary["valid_analyses"] == 0


@pytest.mark.parametrize("failure", ["refusal", "missing", "schema", "provider"])
def test_runner_records_failures_without_raw_error_or_refusal_text(case, failure):
    client, _ = fake_client(
        {} if failure == "schema" else None,
        refusal="private refusal text" if failure == "refusal" else None,
        error=OpenAIError("private provider credentials") if failure == "provider" else None,
    )
    record = run_case(client, case, "model", "current", 1)
    assert record["status"] == {
        "refusal": "refusal", "missing": "missing_output", "schema": "schema_error", "provider": "provider_error",
    }[failure]
    assert record["evaluation"] is None
    assert "private" not in json.dumps(record)


def test_missing_usage_is_unknown_and_errors_do_not_raise_quality_averages(case):
    client, _ = fake_client(case.expected_extraction(), usage=False)
    success = run_case(client, case, "model", "current", 1, (2, 8))
    failed, _ = fake_client(None, usage=False)
    failure = run_case(failed, case, "model", "current", 2)
    summary = summarise([success, failure])[0]
    assert summary["attempts"] == 2
    assert summary["fully_correct"] == 1
    assert summary["evaluated_attempts"] == 1
    assert summary["usage_available_attempts"] == 0
    assert summary["tokens"]["total_tokens"] is None
    assert summary["estimated_cost_usd"] is None


def test_dry_run_matrix_never_reads_credentials_or_constructs_client(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline run touched API configuration or client")

    monkeypatch.setattr(cli, "Settings", forbidden)
    monkeypatch.setattr(cli.openai, "OpenAI", forbidden)
    original = EXTRACTION_PROMPT
    output = tmp_path / "plan.json"
    assert cli.main(["--model", "baseline", "--model", "stronger", "--repeats", "3", "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["mode"] == "dry_run"
    assert report["request_count"] == 36
    assert report["records"] == []
    assert report["prompts"]["current"] == original == PROMPTS["current"]
    assert len(PROMPTS["simple"]) < len(PROMPTS["current"])
    assert len(report["schema_sha256"]) == 64


def test_cli_live_matrix_uses_single_attempt_client_and_continues_after_failure(monkeypatch, tmp_path, suite):
    calls = []
    configuration = []
    by_input = {case.job_description: case for case in suite.cases}

    class Client:
        def __init__(self, **kwargs):
            configuration.append(kwargs)
            self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self.parse))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def parse(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise OpenAIError("secret-value")
            case = by_input[kwargs["messages"][1]["content"]]
            client, _ = fake_client(case.expected_extraction())
            return client.chat.completions.parse(**kwargs)

    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(openai_api_key="secret-value"))
    monkeypatch.setattr(cli.openai, "OpenAI", Client)
    output = tmp_path / "comparison.json"
    assert cli.main(["--live", "--model", "baseline", "--model", "stronger",
                     "--repeats", "2", "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert len(calls) == 24
    assert configuration == [{"api_key": "secret-value", "max_retries": 0, "timeout": 60.0}]
    assert report["records"][0]["status"] == "provider_error"
    assert report["records"][-1]["status"] == "ok"
    assert len(report["summary"]) == 4
    assert "secret-value" not in output.read_text()


@pytest.mark.parametrize("extra", [
    ["--repeats", "0"], ["--case", "unknown"], ["--timeout", "nan"],
    ["--input-usd-per-million", "2"],
    ["--input-usd-per-million", "nan", "--output-usd-per-million", "8"],
])
def test_cli_rejects_bad_configuration_before_network(extra):
    with pytest.raises(SystemExit) as error:
        cli.main(["--model", "model", *extra])
    assert error.value.code == 2


def test_existing_output_cannot_be_overwritten_or_trigger_live_call(monkeypatch, tmp_path):
    saved = tmp_path / "saved.json"
    saved.write_text("preserve this")
    monkeypatch.setattr(cli, "Settings", lambda: pytest.fail("Network configuration reached"))
    with pytest.raises(SystemExit):
        cli.main(["--live", "--model", "model", "--output", str(saved)])
    assert saved.read_text() == "preserve this"
