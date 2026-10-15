"""Validated, curated relationships; independent of matching and CV selection."""

import json
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_CATALOGUE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "technical_relationships.json"
)

ConceptKind = Literal["technology", "capability"]
RelationshipType = Literal["broader", "transferable", "uses_language"]
Confidence = Literal["high", "medium"]
ActivityCondition = Literal["technology_usage", "api_development"]


def _normalise_name(value: str) -> str:
    """Compare complete names, preserving punctuation and original labels."""
    return " ".join(value.split()).casefold()


class _CatalogueModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TechnicalConcept(_CatalogueModel):
    kind: ConceptKind
    aliases: list[str] = Field(default_factory=list)

    @field_validator("aliases")
    @classmethod
    def reject_blank_aliases(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Concept aliases must contain non-whitespace text.")
        return values


class TechnicalRelationship(_CatalogueModel):
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    type: RelationshipType
    confidence: Confidence
    # A condition checked against matching evidence, never inferred on load.
    # None means this relationship cannot establish strong support by itself.
    strong_when: ActivityCondition | None = None


class TechnicalRelationshipCatalogue(_CatalogueModel):
    schema_version: int = Field(strict=True, ge=1, le=1)
    concepts: dict[str, TechnicalConcept] = Field(min_length=1)
    relationships: list[TechnicalRelationship]

    @field_validator("concepts")
    @classmethod
    def validate_concept_ids(
        cls, concepts: dict[str, TechnicalConcept],
    ) -> dict[str, TechnicalConcept]:
        for concept_id in concepts:
            # Canonical lowercase names are stable IDs. Preserve C/C++/C#,
            # .NET and Node.js distinctions; reject blank or unstable spacing.
            if (
                re.fullmatch(r"[a-z0-9+#.]+(?: [a-z0-9+#.]+)*", concept_id) is None
                or re.search(r"[a-z0-9]", concept_id) is None
            ):
                raise ValueError(f"Invalid concept identifier: {concept_id!r}")
        return concepts

    @model_validator(mode="after")
    def validate_names_and_relationships(self) -> "TechnicalRelationshipCatalogue":
        # Register all IDs first, so an alias cannot shadow a later concept.
        names = {_normalise_name(concept_id): concept_id for concept_id in self.concepts}
        for concept_id, concept in self.concepts.items():
            for alias in concept.aliases:
                key = _normalise_name(alias)
                if key in names:
                    raise ValueError(
                        f"Duplicate or conflicting alias {alias!r} for {concept_id!r}; "
                        f"name already belongs to {names[key]!r}."
                    )
                names[key] = concept_id

        seen: set[tuple[str, str, str]] = set()
        for relationship in self.relationships:
            for endpoint in (relationship.source, relationship.target):
                if endpoint not in self.concepts:
                    raise ValueError(f"Unknown relationship endpoint: {endpoint!r}")
            if relationship.source == relationship.target:
                raise ValueError("Relationships must connect different concepts.")
            key = (relationship.source, relationship.target, relationship.type)
            if key in seen:
                raise ValueError(f"Duplicate relationship: {key!r}")
            seen.add(key)
            if relationship.type != "broader" and relationship.strong_when is not None:
                raise ValueError("Only broader relationships may specify strong_when.")
        return self

    def resolve_concept(self, name: str) -> str | None:
        """Resolve an exact ID or alias; never use substrings or relationships."""
        key = _normalise_name(name)
        for concept_id, concept in self.concepts.items():
            if key == concept_id or any(key == _normalise_name(alias) for alias in concept.aliases):
                return concept_id
        return None

    def relationships_from(self, concept_id: str) -> list[TechnicalRelationship]:
        """Return explicit outgoing edges in file order, with no traversal."""
        if concept_id not in self.concepts:
            raise KeyError(f"Unknown concept identifier: {concept_id!r}")
        return [edge for edge in self.relationships if edge.source == concept_id]


class TechnicalRelationshipCatalogueError(ValueError):
    """The catalogue could not be read or failed schema/integrity validation."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys before a dict could discard their values."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_technical_relationships(
    path: Path | str = DEFAULT_CATALOGUE_PATH,
) -> TechnicalRelationshipCatalogue:
    """Read and validate explicitly; missing/invalid data never becomes defaults.

    No experience-bank access, persistence, activity evaluation or application
    startup integration occurs here. Use model_dump(by_alias=True) for JSON keys.
    """
    catalogue_path = Path(path)
    try:
        payload = json.loads(
            catalogue_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
        return TechnicalRelationshipCatalogue.model_validate(payload)
    except (OSError, UnicodeError, ValueError) as error:
        raise TechnicalRelationshipCatalogueError(
            f"Could not load technical relationship catalogue {catalogue_path}: {error}"
        ) from error
