import json

import pytest

from app.models import CurrentCV, CurrentCVSkillGroup, ExperienceBank
from app.services.current_cv import build_skill_catalogue, validate_current_cv_references
from app.services.technical_relationships import (
    DEFAULT_CATALOGUE_PATH,
    TechnicalRelationshipCatalogueError,
    load_technical_relationships,
)


@pytest.fixture
def payload():
    return {
        "schema_version": 1,
        "concepts": {
            "azure": {"kind": "technology", "aliases": ["Microsoft Azure"]},
            "aws": {"kind": "technology", "aliases": ["Amazon Web Services"]},
            "cloud technology": {"kind": "capability", "aliases": ["Cloud platforms"]},
        },
        "relationships": [
            {
                "from": "azure", "to": "cloud technology", "type": "broader",
                "confidence": "high", "strong_when": "technology_usage",
            },
            {
                "from": "azure", "to": "aws", "type": "transferable",
                "confidence": "medium", "strong_when": None,
            },
        ],
    }


def load_payload(tmp_path, payload):
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_technical_relationships(path)


def test_default_catalogue_loads_from_any_working_directory(tmp_path, monkeypatch):
    before = DEFAULT_CATALOGUE_PATH.read_bytes()
    monkeypatch.chdir(tmp_path)
    catalogue = load_technical_relationships()
    assert catalogue.schema_version == 1
    assert len(catalogue.concepts) == 11
    assert len(catalogue.relationships) == 10
    assert catalogue.resolve_concept("Microsoft Azure") == "azure"
    assert catalogue.resolve_concept("Amazon Web Services") == "aws"
    assert catalogue.resolve_concept("Cloud technologies") == "cloud technology"
    assert catalogue.resolve_concept("Structured Query Language") == "sql"
    assert catalogue.resolve_concept("Oracle") is None  # Ambiguous vendor name.
    assert DEFAULT_CATALOGUE_PATH.read_bytes() == before


def test_default_relationships_preserve_reviewed_types_and_activity_conditions():
    catalogue = load_technical_relationships()
    edges = {
        (edge.source, edge.target): (edge.type, edge.confidence, edge.strong_when)
        for edge in catalogue.relationships
    }
    assert edges == {
        ("azure", "cloud technology"): ("broader", "high", "technology_usage"),
        ("aws", "cloud technology"): ("broader", "high", "technology_usage"),
        ("azure ai search", "cloud technology"): ("broader", "high", "technology_usage"),
        ("azure", "aws"): ("transferable", "medium", None),
        ("aws", "azure"): ("transferable", "medium", None),
        ("fastapi", "python"): ("uses_language", "high", None),
        ("fastapi", "api development"): ("broader", "high", "api_development"),
        ("fastapi", "backend development"): ("broader", "high", "api_development"),
        ("oracle database", "relational databases"): ("broader", "high", "technology_usage"),
        ("oracle database", "sql"): ("uses_language", "high", None),
    }


@pytest.mark.parametrize("version", [0, 2, True, "1", 1.0, None])
def test_rejects_unsupported_or_coerced_schema_versions(tmp_path, payload, version):
    payload["schema_version"] = version
    with pytest.raises(TechnicalRelationshipCatalogueError, match="schema_version"):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("field", ["schema_version", "concepts", "relationships"])
def test_rejects_missing_catalogue_sections(tmp_path, payload, field):
    del payload[field]
    with pytest.raises(TechnicalRelationshipCatalogueError, match=field):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("concept_id", [
    "", "Azure", " azure", "azure ", "cloud  technology", "cloud\ttechnology",
    "cloud/technology", "#",
])
def test_rejects_noncanonical_concept_identifiers(tmp_path, payload, concept_id):
    payload["concepts"][concept_id] = {"kind": "technology", "aliases": []}
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Invalid concept identifier"):
        load_payload(tmp_path, payload)


def test_rejects_empty_concept_catalogue(tmp_path, payload):
    payload["concepts"] = {}
    with pytest.raises(TechnicalRelationshipCatalogueError, match="concepts"):
        load_payload(tmp_path, payload)


def test_rejects_unsupported_concept_kind(tmp_path, payload):
    payload["concepts"]["azure"]["kind"] = "framework"
    with pytest.raises(TechnicalRelationshipCatalogueError, match="kind"):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("alias", ["", " ", "\t\n", "\u00a0"])
def test_rejects_blank_aliases(tmp_path, payload, alias):
    payload["concepts"]["azure"]["aliases"].append(alias)
    with pytest.raises(TechnicalRelationshipCatalogueError, match="non-whitespace"):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("concept_id,alias", [
    ("azure", "Microsoft Azure"),
    ("azure", "  MICROSOFT\tAZURE "),
    ("aws", "Microsoft Azure"),
    ("azure", " AWS "),
    ("azure", "Azure"),
])
def test_rejects_duplicate_aliases_and_conflicts_with_ids(tmp_path, payload, concept_id, alias):
    payload["concepts"][concept_id]["aliases"].append(alias)
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Duplicate or conflicting alias"):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("text", [
    '{"schema_version":1,"schema_version":1,"concepts":{},"relationships":[]}',
    '{"schema_version":1,"concepts":{"azure":{"kind":"technology"},'
    '"azure":{"kind":"capability"}},"relationships":[]}',
    '{"schema_version":1,"concepts":{"azure":{"kind":"technology",'
    '"kind":"capability"}},"relationships":[]}',
])
def test_rejects_duplicate_json_keys_before_parsing_discards_them(tmp_path, text):
    path = tmp_path / "duplicate.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Duplicate JSON key"):
        load_technical_relationships(path)


@pytest.mark.parametrize("endpoint", ["from", "to"])
def test_rejects_unknown_relationship_endpoints(tmp_path, payload, endpoint):
    payload["relationships"][0][endpoint] = "unknown"
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Unknown relationship endpoint"):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("endpoint", ["from", "to"])
def test_requires_both_relationship_endpoints(tmp_path, payload, endpoint):
    del payload["relationships"][0][endpoint]
    with pytest.raises(TechnicalRelationshipCatalogueError, match=endpoint):
        load_payload(tmp_path, payload)


def test_aliases_cannot_be_used_as_relationship_identifiers(tmp_path, payload):
    payload["relationships"][0]["from"] = "Microsoft Azure"
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Unknown relationship endpoint"):
        load_payload(tmp_path, payload)


def test_deleted_concept_invalidates_its_relationships(tmp_path, payload):
    del payload["concepts"]["azure"]
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Unknown relationship endpoint"):
        load_payload(tmp_path, payload)


def test_rejects_self_relationships(tmp_path, payload):
    payload["relationships"][0]["to"] = "azure"
    with pytest.raises(TechnicalRelationshipCatalogueError, match="different concepts"):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("changes", [{}, {"confidence": "medium"}, {"strong_when": None}])
def test_rejects_duplicate_logical_edges_even_with_different_metadata(tmp_path, payload, changes):
    payload["relationships"].append({**payload["relationships"][0], **changes})
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Duplicate relationship"):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("field,value", [
    ("type", "equivalent"), ("confidence", "low"), ("confidence", 0.9),
    ("strong_when", "cloud_deployment"), ("strong_when", "production_operations"),
    ("strong_when", ""),
])
def test_rejects_unsupported_relationship_metadata(tmp_path, payload, field, value):
    payload["relationships"][0][field] = value
    with pytest.raises(TechnicalRelationshipCatalogueError, match=field):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("condition", ["technology_usage", "api_development", None])
def test_accepts_controlled_activity_conditions_without_evaluating_them(tmp_path, payload, condition):
    payload["relationships"][0]["strong_when"] = condition
    edge = load_payload(tmp_path, payload).relationships[0]
    assert edge.strong_when == condition


def test_omitted_activity_condition_defaults_to_none(tmp_path, payload):
    del payload["relationships"][0]["strong_when"]
    assert load_payload(tmp_path, payload).relationships[0].strong_when is None


@pytest.mark.parametrize("relationship_type", ["transferable", "uses_language"])
def test_non_broader_relationships_cannot_declare_strong_support(tmp_path, payload, relationship_type):
    payload["relationships"][0]["type"] = relationship_type
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Only broader relationships"):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("location", ["catalogue", "concept", "relationship"])
def test_rejects_unknown_fields_at_every_level(tmp_path, payload, location):
    item = {
        "catalogue": payload,
        "concept": payload["concepts"]["azure"],
        "relationship": payload["relationships"][0],
    }[location]
    item["unexpected"] = True
    with pytest.raises(TechnicalRelationshipCatalogueError, match="unexpected"):
        load_payload(tmp_path, payload)


def test_outgoing_relationships_are_directional(tmp_path, payload):
    catalogue = load_payload(tmp_path, payload)
    assert [edge.target for edge in catalogue.relationships_from("azure")] == [
        "cloud technology", "aws",
    ]
    assert catalogue.relationships_from("aws") == []
    assert catalogue.relationships_from("cloud technology") == []
    with pytest.raises(KeyError, match="Unknown concept identifier"):
        catalogue.relationships_from("unknown")


def test_chain_does_not_create_multi_hop_relationship(tmp_path, payload):
    payload["relationships"][0]["from"] = "aws"
    catalogue = load_payload(tmp_path, payload)
    # azure -> aws -> cloud technology; there is no azure -> cloud edge.
    assert [edge.target for edge in catalogue.relationships_from("azure")] == ["aws"]
    assert [edge.target for edge in catalogue.relationships_from("aws")] == ["cloud technology"]
    assert catalogue.resolve_concept("Azure") == "azure"
    assert len(catalogue.relationships) == 2


def test_name_resolution_is_exact_and_preserves_labels(tmp_path, payload):
    payload["concepts"]["azure"]["aliases"] = ["  Microsoft\tAzure  "]
    catalogue = load_payload(tmp_path, payload)
    assert catalogue.resolve_concept("MICROSOFT\u00a0Azure") == "azure"
    assert catalogue.resolve_concept("Microsoft") is None
    assert catalogue.resolve_concept("Azure deployment") is None
    assert catalogue.resolve_concept("  ") is None
    assert catalogue.concepts["azure"].aliases == ["  Microsoft\tAzure  "]


def test_c_cplusplus_csharp_and_other_punctuation_remain_distinct(tmp_path):
    labels = ["C", "C++", "C#", ".NET", "Node.js"]
    payload = {
        "schema_version": 1,
        "concepts": {label.lower(): {"kind": "technology", "aliases": []} for label in labels},
        "relationships": [],
    }
    catalogue = load_payload(tmp_path, payload)
    assert [catalogue.resolve_concept(label) for label in labels] == [label.lower() for label in labels]
    assert catalogue.resolve_concept("C+") is None
    assert catalogue.resolve_concept("NET") is None
    assert catalogue.resolve_concept("Nodejs") is None


def test_loads_and_queries_are_deterministic_and_independent():
    first = load_technical_relationships()
    before = first.model_dump(by_alias=True)
    second = load_technical_relationships()
    assert second.model_dump(by_alias=True) == before
    assert list(first.concepts) == list(second.concepts)
    first.relationships_from("azure").clear()
    first.resolve_concept("Microsoft Azure")
    assert first.model_dump(by_alias=True) == before
    second.concepts["azure"].aliases.append("Test alias")
    assert first.resolve_concept("Test alias") is None


def test_catalogue_loading_never_accesses_bank_or_cv_repositories(monkeypatch):
    def unexpected_load(*args, **kwargs):
        pytest.fail("Technical relationships must be independent of user JSON stores")

    monkeypatch.setattr("app.repositories.json_experience_bank.JsonExperienceBankRepository.load", unexpected_load)
    monkeypatch.setattr("app.repositories.json_current_cv.JsonCurrentCVRepository.load", unexpected_load)
    assert len(load_technical_relationships().concepts) == 11


def test_relationships_do_not_make_inferred_skills_selectable_in_current_cv():
    bank = ExperienceBank(skills=["Microsoft Azure", "FastAPI", "Oracle Database"])
    cv = CurrentCV(skill_groups=[CurrentCVSkillGroup(
        name="Explicit skills", skill_keys=["microsoft azure", "fastapi", "oracle database"],
    )])
    before_bank, before_cv = bank.model_dump_json(), cv.model_dump_json()
    catalogue = load_technical_relationships()
    assert catalogue.resolve_concept("Microsoft Azure") == "azure"
    assert {edge.target for edge in catalogue.relationships_from("fastapi")} == {
        "python", "api development", "backend development",
    }
    assert build_skill_catalogue(bank) == {
        "microsoft azure": "Microsoft Azure", "fastapi": "FastAPI", "oracle database": "Oracle Database",
    }
    assert validate_current_cv_references(cv, bank) == []
    inferred_cv = CurrentCV(skill_groups=[CurrentCVSkillGroup(name="Inferred", skill_keys=["aws", "python", "sql"])])
    assert [issue.reference for issue in validate_current_cv_references(inferred_cv, bank)] == ["aws", "python", "sql"]
    assert bank.model_dump_json() == before_bank
    assert cv.model_dump_json() == before_cv


@pytest.mark.parametrize("content", [b"not JSON", b"\xff", b"[]"])
def test_unreadable_or_malformed_catalogue_fails_clearly(tmp_path, content):
    path = tmp_path / "invalid.json"
    path.write_bytes(content)
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Could not load") as caught:
        load_technical_relationships(path)
    assert str(path) in str(caught.value)
    assert caught.value.__cause__ is not None
    assert path.read_bytes() == content


def test_missing_catalogue_fails_without_creating_a_file(tmp_path):
    path = tmp_path / "missing.json"
    with pytest.raises(TechnicalRelationshipCatalogueError, match="Could not load") as caught:
        load_technical_relationships(path)
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert not path.exists()
