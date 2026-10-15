"""Prepare authoritative requirements without evaluating evidence."""

import re
from collections.abc import Callable

from app.models import JobDescriptionAnalysis, StructuredRequirement
from app.services.matching_terms import _canonical


# Only complete, familiar technology names are split in legacy OR wording.
# This vocabulary does not read or traverse the technical relationship catalogue.
_LEGACY_OR_NAMES = {
    "python", "java", "javascript", "typescript", "postgresql", "azure", "aws",
    "fastapi", "oracle database", "sql", "c", "c++", "c#", ".net",
    "js", "ts", "postgres",
}


def _or_parts(text: str) -> list[str]:
    return re.split(r"\s+or\s+", text.strip(), flags=re.IGNORECASE)


def _legacy_alternatives(text: str, category: str) -> list[str]:
    if category == "skill":
        parts = _or_parts(text)
        if len(parts) > 1 and all(" ".join(part.split()).lower() in _LEGACY_OR_NAMES for part in parts):
            return parts
    # Preserve degrees, conjunctions, slashes, qualifiers and unknown branches.
    return [text]


def _equivalence_key(
    requirement: StructuredRequirement, canonicalise: Callable[[str], str] = _canonical,
) -> tuple[str, tuple[str, ...]]:
    options = tuple(sorted({canonicalise(option) for option in requirement.alternatives}))
    wording = canonicalise(requirement.text)
    parts = _or_parts(requirement.text)
    if (
        (len(options) == 1 and wording == options[0])
        or (
            requirement.category != "qualification" and len(parts) > 1
            and tuple(sorted({canonicalise(part) for part in parts})) == options
        )
    ):
        # Concise options can be equivalent despite alias or OR ordering.
        wording = ""
    # Keep substantive display qualifiers: "secure Python APIs" is not "Python".
    return wording, options


def prepare_requirements(
    job: JobDescriptionAnalysis, *, canonicalise: Callable[[str], str] = _canonical,
) -> list[StructuredRequirement]:
    """Return independent records in deterministic order; never mutate the input.

    Structured records are authoritative, including an explicitly empty list.
    Deduplication keeps the first ID/wording and preserves category, importance
    and activity distinctions. The original analysis retains every source quote.

    Legacy records keep V2 qualification-first, cross-category alias precedence.
    Their source_text is the available extracted string, not a recovered JD quote;
    importance/activity are not guessed. The matcher may supply a catalogue-aware
    equivalence function; preparation itself never loads or traverses a catalogue.
    """
    if job.requirements is not None:
        prepared: list[StructuredRequirement] = []
        seen: set[tuple] = set()
        for requirement in job.requirements:
            key = (
                requirement.category, requirement.importance, requirement.activity,
                *_equivalence_key(requirement, canonicalise),
            )
            if key not in seen:
                seen.add(key)
                prepared.append(requirement.model_copy(deep=True))
        return prepared

    prepared = []
    seen_legacy: set[tuple[str, tuple[str, ...]]] = set()
    for category, field in (
        ("qualification", "qualifications"),
        ("skill", "technical_skills"),
        ("other_keyword", "other_keywords"),
        ("responsibility", "responsibilities"),
    ):
        for index, text in enumerate(getattr(job, field), 1):
            requirement = StructuredRequirement(
                id=f"legacy:{field}:{index}", text=text, source_text=text,
                category=category, alternatives=_legacy_alternatives(text, category),
            )
            key = _equivalence_key(requirement, canonicalise)
            if key not in seen_legacy:
                seen_legacy.add(key)
                prepared.append(requirement)
    return prepared
