import pytest
from pydantic import ValidationError

from app.models import JobDescriptionExtraction
from app.services.job_extraction import analysis_from_extraction


def extraction(source_text, **changes):
    return JobDescriptionExtraction.model_validate({
        "job_title": "Engineer",
        "requirements": [{
            "text": "Technical experience", "source_text": source_text, "category": "skill",
            "importance": "unspecified", "alternatives": ["Technical experience"], "activity": None,
            **changes,
        }],
    })


@pytest.mark.parametrize("quote,source", [
    ("Python experience.", "Engineer. Python experience."),
    ("Python or Java", "Engineer. Python\t or\nJava."),
    ("Python, Java", "Engineer. Python; Java."),
    ("Bachelor's degree", "Engineer. Bachelor’s degree is preferred."),
    ("C# / .NET", "Engineer. C#/.NET experience."),
    ("API development", "Engineer. API-development experience."),
    ("python experience", "Engineer. PYTHON experience."),
])
def test_source_validation_tolerates_harmless_formatting_and_returns_original_span(quote, source):
    result = analysis_from_extraction(extraction(quote), source)
    assert result.requirements[0].source_text in source
    if quote in source:
        assert result.requirements[0].source_text == quote


@pytest.mark.parametrize("quote,source", [
    ("Rust experience", "Engineer. Python experience."),
    ("Java", "Engineer. JavaScript experience."),
    ("C", "Engineer. C++ experience."),
    ("C#", "Engineer. C++ experience."),
    (".NET", "Engineer. NET experience."),
    ("SQL", "Engineer. PostgreSQL experience."),
    ("Python 3.10", "Engineer. Python 3.11 experience."),
    ("Node.js", "Engineer. Nodejs experience."),
    ("Python or Java", "Engineer. Python and Java experience."),
    ("Python experience", "Engineer. Python not experience."),
    ("Java Python", "Engineer. Python Java."),
    ("Python Java", "Engineer. Python and Java."),
    ("Proficient in Python", "Engineer. Experience working with Python."),
    ("...", "Engineer. ..."),
])
def test_source_validation_rejects_unsupported_or_changed_wording(quote, source):
    with pytest.raises(ValueError, match="source_text"):
        analysis_from_extraction(extraction(quote), source)


def test_source_normalisation_does_not_replace_original_whitespace_or_punctuation():
    source = "Engineer. Bachelor’s\n degree; in Computer Science."
    result = analysis_from_extraction(extraction("Bachelor's degree in Computer Science"), source)
    assert result.requirements[0].source_text == "Bachelor’s\n degree; in Computer Science"


def test_ids_order_quotes_and_input_are_stable_without_deduplication():
    parsed = extraction("Python")
    parsed.requirements.append(parsed.requirements[0].model_copy(deep=True))
    before = parsed.model_dump_json()
    first = analysis_from_extraction(parsed, "Engineer. Python experience.")
    second = analysis_from_extraction(parsed, "Engineer. Python experience.")
    assert first == second
    assert [item.id for item in first.requirements] == ["r1", "r2"]
    assert first.technical_skills == ["Technical experience", "Technical experience"]
    assert parsed.model_dump_json() == before


def test_title_and_source_are_preserved_without_rewriting():
    parsed = extraction("Python")
    parsed.job_title = "  Backend Engineer  "
    result = analysis_from_extraction(parsed, "Backend Engineer. Python is required.")
    assert result.job_title == parsed.job_title
    assert result.requirements[0].source_text == "Python"


@pytest.mark.parametrize("missing_field", ["importance", "activity"])
def test_provider_metadata_must_be_explicit(missing_field):
    payload = extraction("Python").model_dump()
    del payload["requirements"][0][missing_field]
    with pytest.raises(ValidationError, match=missing_field):
        JobDescriptionExtraction.model_validate(payload)
