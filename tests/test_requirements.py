import json
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import (
    ExperienceBank, ExperienceBankMatch, JobDescriptionAnalysis,
    LegacyJobDescriptionAnalysis, RequirementActivity, StructuredRequirement,
)
from app.services.matching import _requirements, match_experience_bank
from app.services.requirements import prepare_requirements
from app.services.technical_relationships import ActivityCondition


def requirement(**changes):
    return {
        "id": "r1", "text": "Python", "source_text": "Python experience is required.",
        "category": "skill", "importance": "required", "alternatives": ["Python"],
        "activity": None, **changes,
    }


def analysis(*items, **legacy_fields):
    return JobDescriptionAnalysis(
        job_title="Engineer", requirements=list(items), **legacy_fields,
    )


def test_legacy_analysis_retains_exact_five_field_serialization():
    payload = {
        "job_title": " Engineer ", "technical_skills": [" Python "],
        "other_keywords": ["Agile"], "responsibilities": ["Build APIs"],
        "qualifications": ["BSc Computer Science"],
    }
    job = JobDescriptionAnalysis.model_validate(payload)
    assert job.requirements is None
    assert job.model_dump() == payload
    assert json.loads(job.model_dump_json()) == payload
    assert JobDescriptionAnalysis.model_validate(job.model_dump()) == job


def test_explicit_null_requirements_use_legacy_adaptation():
    job = JobDescriptionAnalysis(job_title="Engineer", requirements=None, technical_skills=["Python"])
    assert "requirements" not in job.model_dump()
    assert [item.text for item in prepare_requirements(job)] == ["Python"]


def test_extraction_schema_remains_five_fields():
    assert set(LegacyJobDescriptionAnalysis.model_json_schema()["properties"]) == {
        "job_title", "technical_skills", "other_keywords", "responsibilities", "qualifications",
    }
    assert "requirements" in JobDescriptionAnalysis.model_json_schema()["properties"]


def test_public_output_schema_retains_typed_analysis_fields():
    expected = {
        "job_title", "technical_skills", "other_keywords", "responsibilities",
        "qualifications", "requirements",
    }
    output_schema = JobDescriptionAnalysis.model_json_schema(mode="serialization")
    assert set(output_schema["properties"]) == expected
    api_schema = app.openapi()
    response = api_schema["paths"]["/analyse"]["post"]["responses"]["200"]
    reference = response["content"]["application/json"]["schema"]["$ref"]
    assert set(api_schema["components"]["schemas"][reference.rsplit("/", 1)[1]]["properties"]) == expected


def test_requirement_preserves_ids_alternative_order_and_original_wording():
    payload = requirement(
        text="Python or Java", source_text="  Essential:\nPython OR Java experience.  ",
        alternatives=["Python", "Java"],
    )
    assert StructuredRequirement.model_validate(payload).model_dump() == payload


@pytest.mark.parametrize("field", ["id", "text", "source_text"])
@pytest.mark.parametrize("blank", ["", " ", "\t\n", "\u00a0"])
def test_requirement_rejects_blank_identifiers_and_wording(field, blank):
    with pytest.raises(ValidationError, match="non-whitespace"):
        StructuredRequirement.model_validate(requirement(**{field: blank}))


@pytest.mark.parametrize("field,value", [
    ("category", "technical_skill"), ("importance", "mandatory"),
    ("activity", "deploy anything"), ("activity", "cloud_architecture"),
    ("activity", "production_operations"), ("activity", ""),
])
def test_requirement_rejects_unsupported_controlled_values(field, value):
    with pytest.raises(ValidationError, match=field):
        StructuredRequirement.model_validate(requirement(**{field: value}))


@pytest.mark.parametrize("alternatives", [[], "Python", [None], [1], [""], ["\t\n"], ("Python",)])
def test_requirement_rejects_empty_or_malformed_alternative_groups(alternatives):
    with pytest.raises(ValidationError, match="alternatives"):
        StructuredRequirement.model_validate(requirement(alternatives=alternatives))


@pytest.mark.parametrize("field", ["id", "text", "source_text", "category", "alternatives"])
def test_requirement_requires_core_fields(field):
    payload = requirement()
    del payload[field]
    with pytest.raises(ValidationError, match=field):
        StructuredRequirement.model_validate(payload)


def test_optional_requirement_metadata_has_conservative_defaults():
    payload = requirement()
    del payload["importance"]
    del payload["activity"]
    item = StructuredRequirement.model_validate(payload)
    assert item.importance == "unspecified"
    assert item.activity is None


def test_unknown_requirement_fields_are_rejected():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        StructuredRequirement.model_validate(requirement(score=100))


@pytest.mark.parametrize("items", [{}, "Python", [None], [{}], (requirement(),)])
def test_analysis_rejects_malformed_structured_lists(items):
    with pytest.raises(ValidationError):
        JobDescriptionAnalysis(job_title="Engineer", requirements=items)


@pytest.mark.parametrize("second_id", ["r1", " r1 "])
def test_analysis_rejects_duplicate_requirement_ids_across_categories(second_id):
    with pytest.raises(ValidationError, match="Duplicate requirement ID"):
        analysis(requirement(), requirement(id=second_id, category="responsibility"))


def test_structured_requirements_derive_legacy_fields_in_category_order():
    items = [
        requirement(id="soft", text="Teamwork", category="other_keyword", alternatives=["Teamwork"]),
        requirement(id="or", text="Python or Java", alternatives=["Python", "Java"]),
        requirement(id="degree", text="BSc Computer Science", category="qualification",
                    alternatives=["BSc Computer Science"]),
        requirement(id="deploy", text="Deploy cloud applications", category="responsibility",
                    alternatives=["cloud technology"], activity="cloud_deployment"),
        requirement(id="aws", text="AWS", importance="preferred", alternatives=["AWS"]),
    ]
    job = analysis(*items)
    assert job.technical_skills == ["Python or Java", "AWS"]
    assert job.other_keywords == ["Teamwork"]
    assert job.responsibilities == ["Deploy cloud applications"]
    assert job.qualifications == ["BSc Computer Science"]
    assert [item.id for item in job.requirements] == [item["id"] for item in items]
    assert JobDescriptionAnalysis.model_validate(job.model_dump()) == job


def test_explicit_consistent_legacy_projection_is_accepted_without_double_preparation():
    job = analysis(requirement(), technical_skills=["Python"], qualifications=[])
    assert len(prepare_requirements(job)) == 1
    assert job.technical_skills == ["Python"]


@pytest.mark.parametrize("category,field", [
    ("skill", "technical_skills"), ("other_keyword", "other_keywords"),
    ("responsibility", "responsibilities"), ("qualification", "qualifications"),
])
def test_explicit_legacy_fields_cannot_contradict_structured_text(category, field):
    with pytest.raises(ValidationError, match=f"{field} contradicts"):
        analysis(requirement(category=category), **{field: ["Different text"]})


@pytest.mark.parametrize("legacy", [[], ["Python", "Java"], ["Java or Python"]])
def test_or_projection_requires_one_exact_grouped_display_string(legacy):
    with pytest.raises(ValidationError, match="technical_skills contradicts"):
        analysis(requirement(text="Python or Java", alternatives=["Python", "Java"]),
                 technical_skills=legacy)


def test_structured_projection_rejects_reordered_legacy_lists():
    with pytest.raises(ValidationError, match="technical_skills contradicts"):
        analysis(requirement(), requirement(id="r2", text="Java", alternatives=["Java"]),
                 technical_skills=["Java", "Python"])


def test_empty_structured_list_is_authoritative_and_cannot_hide_legacy_obligations():
    job = analysis()
    assert prepare_requirements(job) == []
    assert job.technical_skills == []
    assert job.model_dump()["requirements"] == []
    with pytest.raises(ValidationError, match="technical_skills contradicts"):
        analysis(technical_skills=["Python"])


def test_required_preferred_and_unspecified_requirements_remain_distinct():
    job = analysis(*(requirement(
        id=importance, text="AWS", source_text=f"AWS: {importance}",
        importance=importance, alternatives=["AWS"],
    ) for importance in ("required", "preferred", "unspecified")))
    prepared = prepare_requirements(job)
    assert [item.importance for item in prepared] == ["required", "preferred", "unspecified"]
    assert [item.id for item in prepared] == ["required", "preferred", "unspecified"]


def test_activity_constraints_on_same_technology_remain_distinct():
    job = analysis(*(requirement(
        id=activity or "none", text="AWS", alternatives=["AWS"], activity=activity,
    ) for activity in (None, "technology_usage", "api_development", "cloud_deployment")))
    assert [item.activity for item in prepare_requirements(job)] == [
        None, "technology_usage", "api_development", "cloud_deployment",
    ]
    assert set(get_args(ActivityCondition)) <= set(get_args(RequirementActivity))


def test_python_or_java_is_one_group_and_python_and_java_are_separate_records():
    grouped = prepare_requirements(analysis(requirement(
        text="Python or Java", alternatives=["Python", "Java"],
    )))
    independent = prepare_requirements(analysis(
        requirement(), requirement(id="java", text="Java", alternatives=["Java"]),
    ))
    assert len(grouped) == 1
    assert grouped[0].alternatives == ["Python", "Java"]
    assert [item.alternatives for item in independent] == [["Python"], ["Java"]]


@pytest.mark.parametrize("first,second", [
    ("JavaScript", "JS"), ("TypeScript", "TS"), ("PostgreSQL", "Postgres"),
    ("REST APIs", "API development"),
])
def test_structured_alias_duplicates_keep_first_id_and_original_wording(first, second):
    job = analysis(
        requirement(text=first, alternatives=[first]),
        requirement(id="r2", text=second, alternatives=[second], source_text="Another source."),
    )
    prepared = prepare_requirements(job)
    assert [(item.id, item.text, item.alternatives) for item in prepared] == [("r1", first, [first])]
    assert job.requirements[1].source_text == "Another source."
    assert job.technical_skills == [first, second]  # Projection preserves the authoritative list.


def test_reordered_or_alias_groups_deduplicate_without_reordering_first_alternatives():
    job = analysis(
        requirement(text="JavaScript or Python", alternatives=["JavaScript", "Python"]),
        requirement(id="r2", text="Python OR JS", alternatives=["Python", "JS"]),
    )
    prepared = prepare_requirements(job)
    assert len(prepared) == 1
    assert prepared[0].alternatives == ["JavaScript", "Python"]


def test_or_group_is_distinct_from_independent_atomic_requirements():
    job = analysis(
        requirement(text="Python or Java", alternatives=["Python", "Java"]),
        requirement(id="python"), requirement(id="java", text="Java", alternatives=["Java"]),
    )
    assert len(prepare_requirements(job)) == 3


def test_structured_categories_and_substantive_display_qualifiers_are_preserved():
    job = analysis(
        requirement(), requirement(id="other", category="other_keyword"),
        requirement(id="secure", text="Develop secure Python APIs", activity="api_development"),
        requirement(id="api", text="Develop Python APIs", activity="api_development"),
    )
    assert [item.id for item in prepare_requirements(job)] == ["r1", "other", "secure", "api"]


def test_legacy_adapter_preserves_v2_order_alias_deduplication_and_qualification_precedence():
    job = JobDescriptionAnalysis(
        job_title="Engineer", qualifications=["BSc Computer Science"],
        technical_skills=["BSc Computer Science", "JavaScript", "JS", "Python"],
        other_keywords=["JS", "Teamwork"], responsibilities=["JavaScript", "Build APIs"],
    )
    prepared = prepare_requirements(job)
    assert [(item.text, item.category) for item in prepared] == [
        ("BSc Computer Science", "qualification"), ("JavaScript", "skill"),
        ("Python", "skill"), ("Teamwork", "other_keyword"), ("Build APIs", "responsibility"),
    ]
    assert [item.text for item in prepared] == [text for text, _ in _requirements(job)]
    assert all(item.importance == "unspecified" and item.activity is None for item in prepared)
    assert all(item.source_text == item.text for item in prepared)
    assert prepared[2].id == "legacy:technical_skills:4"


def test_legacy_simple_or_groups_are_preserved_and_deduplicated():
    job = JobDescriptionAnalysis(
        job_title="Engineer", technical_skills=[" Python OR Java ", "Java or Python", "JS or TS"],
    )
    prepared = prepare_requirements(job)
    assert len(prepared) == 2
    assert prepared[0].text == prepared[0].source_text == " Python OR Java "
    assert prepared[0].alternatives == ["Python", "Java"]
    assert prepared[1].alternatives == ["JS", "TS"]


@pytest.mark.parametrize("text", [
    "Python and Java", "Python/Java", "Python or an equivalent language",
    "Python or Java and SQL", "Python or QuantumScript", "Experience with Python or Java",
    "Python or", "Required AWS", "C# .NET", "Python/ or Java", "Python (preferred) or Java",
])
def test_ambiguous_or_unsupported_legacy_wording_is_opaque(text):
    prepared = prepare_requirements(JobDescriptionAnalysis(job_title="Engineer", technical_skills=[text]))
    assert len(prepared) == 1
    assert prepared[0].alternatives == [text]
    assert prepared[0].source_text == text
    assert prepared[0].importance == "unspecified"
    assert prepared[0].activity is None


def test_legacy_separate_languages_remain_independent():
    prepared = prepare_requirements(JobDescriptionAnalysis(
        job_title="Engineer", technical_skills=["Python", "Java"],
    ))
    assert [item.alternatives for item in prepared] == [["Python"], ["Java"]]


def test_legacy_qualifications_keep_degree_pairing_alternatives_and_independent_certificate():
    degree = "BSc in Engineering or MSc in Computer Science"
    shared = "Bachelor's or Master's degree in Computer Science, Engineering, or a related field"
    job = JobDescriptionAnalysis(
        job_title="Engineer", qualifications=[degree, shared, "AWS Certified Developer"],
    )
    assert [item.alternatives for item in prepare_requirements(job)] == [
        [degree], [shared], ["AWS Certified Developer"],
    ]


def test_legacy_preparation_keeps_punctuation_distinctions():
    names = ["C", "C++", "C#", ".NET", "Java", "JavaScript", "SQL", "PostgreSQL"]
    prepared = prepare_requirements(JobDescriptionAnalysis(job_title="Engineer", technical_skills=names))
    assert [item.text for item in prepared] == names


@pytest.mark.parametrize("structured", [False, True])
def test_preparation_is_deterministic_and_does_not_mutate_analysis(structured):
    job = analysis(requirement()) if structured else JobDescriptionAnalysis(
        job_title="Engineer", technical_skills=["Python", "Java"],
    )
    before = job.model_dump_json()
    first, second = prepare_requirements(job), prepare_requirements(job)
    assert first == second
    first[0].alternatives.append("Unrelated")
    first[0].source_text = "Changed"
    assert second[0].alternatives == ["Python"]
    assert job.model_dump_json() == before


def test_preparation_does_not_load_technical_relationships(monkeypatch):
    def unexpected_load(*args, **kwargs):
        pytest.fail("Requirement preparation must not infer technical relationships")

    monkeypatch.setattr("app.services.technical_relationships.load_technical_relationships", unexpected_load)
    assert len(prepare_requirements(analysis(requirement()))) == 1


@pytest.mark.parametrize("payload", [
    {"requirements": [{}]},
    {"requirements": [requirement(), requirement()]},
    {"requirements": [requirement(activity="anything")]},
    {"requirements": [requirement()], "technical_skills": ["Java"]},
])
def test_match_api_rejects_invalid_structured_payload_before_bank_access(monkeypatch, payload):
    def unexpected_load():
        pytest.fail("Invalid analysis must fail before bank access")

    monkeypatch.setattr("app.main.experience_bank_repository", SimpleNamespace(load=unexpected_load))
    response = TestClient(app).post("/match", json={"job_analysis": {"job_title": "Engineer", **payload}})
    assert response.status_code == 422


def test_match_api_accepts_and_projects_structured_data_without_new_matching_rules(monkeypatch):
    captured = []

    def capture_match(bank, job):
        captured.append(job)
        return ExperienceBankMatch(job_title=job.job_title)

    monkeypatch.setattr("app.main.experience_bank_repository", SimpleNamespace(load=ExperienceBank))
    monkeypatch.setattr("app.main.match_experience_bank", capture_match)
    response = TestClient(app).post("/match", json={"job_analysis": {
        "job_title": "Engineer", "requirements": [requirement()],
    }})
    assert response.status_code == 200
    assert captured[0].requirements[0].importance == "required"
    assert captured[0].technical_skills == ["Python"]
    assert _requirements(captured[0]) == [("Python", "skill")]


def test_legacy_and_structured_matching_share_support_and_scores_but_preserve_metadata():
    legacy = JobDescriptionAnalysis(job_title="Engineer", technical_skills=["Python"])
    structured = analysis(requirement())
    bank = ExperienceBank(skills=["Python"])
    structured_result = match_experience_bank(bank, structured)
    legacy_result = match_experience_bank(bank, legacy)
    assert structured_result.related_matches[0].requirement == legacy_result.related_matches[0].requirement == "Python"
    assert structured_result.related_matches[0].evidence == legacy_result.related_matches[0].evidence
    assert structured_result.ranked_evidence[0].score == legacy_result.ranked_evidence[0].score == 3
    assert structured_result.related_matches[0].requirement_details.importance == "required"
    assert legacy_result.related_matches[0].requirement_details.importance == "unspecified"
