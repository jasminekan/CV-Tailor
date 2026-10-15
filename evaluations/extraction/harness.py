"""Deterministic fixture checks and an opt-in, single-attempt provider runner.

No LLM grader, production prompt mutation, inferred requirements or saved-bank
access. Reviewed phrase anchors identify items independently of their metadata.
"""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from time import perf_counter
import unicodedata

from openai import APIStatusError, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.models import JobDescriptionExtraction, StructuredRequirement
from app.services.job_extraction import SourceQuotationError, analysis_from_extraction
from app.services.llm import EXTRACTION_PROMPT


DIRECTORY = Path(__file__).resolve().parent
FIXTURES = DIRECTORY / "fixtures.json"
PROMPTS = {"current": EXTRACTION_PROMPT, "simple": (DIRECTORY / "simple_prompt.txt").read_text()}
TOKEN = re.compile(r"(?:\.[^\W_]+|[^\W_]+)(?:[.'+#][^\W_]+)*[+#]*")


def tokens(value: str) -> tuple[str, ...]:
    value = unicodedata.normalize("NFKC", value).casefold().replace("’", "'")
    return tuple(TOKEN.findall(value))


def contains(words: tuple[str, ...], phrase: str) -> bool:
    needle = tokens(phrase)
    return any(words[i:i + len(needle)] == needle for i in range(len(words) - len(needle) + 1))


class ExpectedRequirement(StructuredRequirement):
    # Every group must match; variants within a group are explicitly equivalent.
    match_terms: list[list[str]] = Field(min_length=1)
    option_aliases: dict[str, list[str]] = Field(default_factory=dict)
    accepted_alternative_sets: list[list[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_reviewed_rules(self):
        groups = [*self.match_terms, *self.accepted_alternative_sets, *self.option_aliases.values()]
        if any(not group or any(not tokens(term) for term in group) for group in groups):
            raise ValueError("Reviewed rule groups must contain nonblank phrases.")
        aliases = {}
        for name, values in self.option_aliases.items():
            if not tokens(name):
                raise ValueError("Option names must be nonblank.")
            for value in [name, *values]:
                key = tokens(value)
                if key in aliases and aliases[key] != tokens(name):
                    raise ValueError("Conflicting reviewed option aliases.")
                aliases[key] = tokens(name)
        return self

    def content(self) -> dict:
        return self.model_dump(exclude={
            "id", "match_terms", "option_aliases", "accepted_alternative_sets",
        })


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    review_notes: str
    job_description: str
    job_title: str
    expected: list[ExpectedRequirement] = Field(min_length=1)

    @field_validator("id", "review_notes", "job_description", "job_title")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Fixture fields cannot be blank.")
        return value

    @model_validator(mode="after")
    def check_expectations(self):
        ids = [item.id.strip() for item in self.expected]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate expected requirement IDs.")
        # Check authored canonical requirements against the same source boundary.
        analysis_from_extraction(self.expected_extraction(), self.job_description)
        for item in self.expected:
            words = [tokens(item.text), *(tokens(option) for option in item.alternatives)]
            if not all(any(contains(part, term) for part in words for term in group)
                       for group in item.match_terms):
                raise ValueError(f"Reviewed anchors do not identify {item.id}.")
        return self

    def expected_extraction(self) -> JobDescriptionExtraction:
        return JobDescriptionExtraction(job_title=self.job_title, requirements=[
            item.content() for item in self.expected
        ])


class FixtureSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int
    cases: list[EvaluationCase] = Field(min_length=3)

    @model_validator(mode="after")
    def check_suite(self):
        if self.schema_version != 1:
            raise ValueError("Unsupported evaluation fixture version.")
        ids = [case.id.strip() for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate evaluation case IDs.")
        return self


def load_fixtures(path: Path = FIXTURES) -> FixtureSuite:
    return FixtureSuite.model_validate_json(path.read_text(encoding="utf-8"))


def _options(options: list[str], expected: ExpectedRequirement) -> tuple:
    aliases = {tokens(value): tokens(name) for name, values in expected.option_aliases.items()
               for value in [name, *values]}
    # Choice order is immaterial to quality; duplicates are not discarded.
    return tuple(sorted(aliases.get(tokens(option), tokens(option)) for option in options))


def evaluate(case: EvaluationCase, extraction: JobDescriptionExtraction) -> dict:
    matches = defaultdict(list)
    unexpected, merged, duplicates, incorrect = [], [], [], []
    signatures = defaultdict(list)
    for index, actual in enumerate(extraction.requirements):
        words = [tokens(actual.text), *(tokens(option) for option in actual.alternatives)]
        # Never identify a requirement using a shared source quotation.
        ids = [expected.id for expected in case.expected if all(
            any(contains(part, term) for part in words for term in group)
            for group in expected.match_terms
        )]
        if len(ids) == 1:
            matches[ids[0]].append(index)
        elif ids:
            merged.append({"actual_index": index, "text": actual.text, "expected_ids": ids})
        else:
            unexpected.append({"actual_index": index, "requirement": actual.model_dump()})
        if len(ids) != 1:
            signatures[(tokens(actual.text), tuple(sorted(map(tokens, actual.alternatives))))].append(index)

    missing = []
    checks = []
    correct = {field: 0 for field in ("category", "importance", "alternatives", "activity")}
    for expected in case.expected:
        indices = matches[expected.id]
        if not indices:
            missing.append({"id": expected.id, "text": expected.text})
            continue
        if len(indices) > 1:
            duplicates.append({"expected_id": expected.id, "actual_indices": indices,
                               "texts": [extraction.requirements[i].text for i in indices]})
        for position, index in enumerate(indices):
            actual = extraction.requirements[index]
            fields = {field: getattr(actual, field) == getattr(expected, field)
                      for field in ("category", "importance", "activity")}
            allowed = [expected.alternatives, *expected.accepted_alternative_sets]
            fields["alternatives"] = _options(actual.alternatives, expected) in [
                _options(options, expected) for options in allowed
            ]
            if position == 0:
                for field, ok in fields.items():
                    correct[field] += int(ok)
            for field, ok in fields.items():
                if not ok:
                    incorrect.append({"expected_id": expected.id, "text": expected.text,
                                      "actual_index": index, "field": field,
                                      "expected": allowed if field == "alternatives" else getattr(expected, field),
                                      "actual": getattr(actual, field)})
            checks.append({"expected_id": expected.id, "actual_index": index, "checks": fields})
    duplicates.extend({"expected_id": None, "actual_indices": indices,
                       "texts": [extraction.requirements[i].text for i in indices]}
                      for indices in signatures.values() if len(indices) > 1)
    covered = len(case.expected) - len(missing)
    metrics = {"expected_count": len(case.expected), "actual_count": len(extraction.requirements),
               "covered_count": covered, "completeness": covered / len(case.expected)}
    for field, count in correct.items():
        metrics[field] = {"correct": count, "matched": covered,
                          "accuracy_on_matched": count / covered if covered else None}
    title_ok = tokens(extraction.job_title) == tokens(case.job_title)
    return {"metrics": metrics, "job_title_correct": title_ok, "missing": missing,
            "incorrect": incorrect, "duplicates": duplicates, "unexpected": unexpected,
            "merged_requirements": merged, "checks": checks,
            "passed": title_ok and not any([missing, incorrect, duplicates, unexpected, merged])}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def run_case(client, case: EvaluationCase, model: str, variant: str, repeat: int,
             prices: tuple[float, float] | None = None) -> dict:
    record = {"case_id": case.id, "requested_model": model, "prompt_variant": variant,
              "prompt_sha256": digest(PROMPTS[variant]), "repeat": repeat,
              "started_at": datetime.now(timezone.utc).isoformat(), "status": "provider_error",
              "resolved_model": None, "usage": None, "estimated_cost_usd": None,
              "extraction": None, "analysis": None, "evaluation": None}
    start = perf_counter()
    try:
        completion = client.chat.completions.parse(
            model=model, messages=[{"role": "system", "content": PROMPTS[variant]},
                                   {"role": "user", "content": case.job_description}],
            response_format=JobDescriptionExtraction,
        )
        record["resolved_model"] = completion.model
        record["usage"] = completion.usage.model_dump() if completion.usage else None
        if prices and record["usage"]:
            usage = record["usage"]
            record["estimated_cost_usd"] = (
                usage["prompt_tokens"] * prices[0] + usage["completion_tokens"] * prices[1]
            ) / 1_000_000
        message = completion.choices[0].message
        record["finish_reason"] = completion.choices[0].finish_reason
        if message.refusal or message.parsed is None:
            record["status"] = "refusal" if message.refusal else "missing_output"
            return record
        record["status"] = "schema_error"
        extraction = JobDescriptionExtraction.model_validate(message.parsed)
        record["extraction"] = extraction.model_dump()
        record["evaluation"] = evaluate(case, extraction)
        record["status"] = "source_error"
        record["analysis"] = analysis_from_extraction(extraction, case.job_description).model_dump()
        record["status"] = "ok"
    except SourceQuotationError as error:
        record["error"] = {"type": "SourceQuotationError", "requirement_id": error.requirement_id}
    except ValidationError:
        record["status"] = "schema_error"
        record["error"] = {"type": "ValidationError"}
    except (OpenAIError, ValueError, IndexError, KeyError) as error:
        # No raw provider error bodies, refusal text or configuration secrets.
        record["error"] = {"type": type(error).__name__}
        if isinstance(error, APIStatusError):
            record["error"]["upstream_status"] = error.status_code
    finally:
        record["elapsed_seconds"] = round(perf_counter() - start, 3)
    return record


def summarise(records: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for record in records:
        groups[(record["requested_model"], record["prompt_variant"])].append(record)
    summaries = []
    for (model, variant), rows in groups.items():
        evaluated = [row["evaluation"] for row in rows if row["evaluation"] is not None]
        totals = {name: sum(item["metrics"][name] for item in evaluated)
                  for name in ("expected_count", "actual_count", "covered_count")}
        expected, covered = totals["expected_count"], totals["covered_count"]
        usages = [row["usage"] for row in rows if row["usage"] is not None]
        summaries.append({
            "model": model, "prompt_variant": variant, "attempts": len(rows),
            "valid_analyses": sum(row["status"] == "ok" for row in rows),
            "fully_correct": sum(row["status"] == "ok" and row["evaluation"]["passed"] for row in rows),
            "evaluated_attempts": len(evaluated), **totals,
            "completeness_on_evaluated": covered / expected if expected else None,
            "metadata": {field: {
                "correct": sum(item["metrics"][field]["correct"] for item in evaluated),
                "matched": covered,
            } for field in ("category", "importance", "alternatives", "activity")},
            "usage_available_attempts": len(usages),
            "tokens": {field: sum(usage[field] for usage in usages) if usages else None
                       for field in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "cost_available_attempts": sum(row["estimated_cost_usd"] is not None for row in rows),
            "estimated_cost_usd": (sum(row["estimated_cost_usd"] for row in rows
                                       if row["estimated_cost_usd"] is not None)
                                   if any(row["estimated_cost_usd"] is not None for row in rows) else None),
        })
    return summaries
