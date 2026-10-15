"""Shared V2 terminology rules; unrelated to Current CV skill selection."""

import re


def _normalise(value: str) -> str:
    value = value.lower().replace("’", "'")
    value = re.sub(r"\b(bachelor|master)'s\b", r"\1s", value)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#.]", " ", value)).strip().rstrip(".")


# Equivalent terminology only; retained verbatim from the V2 matcher.
_CONCEPTS = {
    "javascript": ("javascript", "js"),
    "typescript": ("typescript", "ts"),
    "postgresql": ("postgresql", "postgres"),
    "api development": (
        "api development", "api design", "api endpoint", "api endpoints", "rest api", "rest apis",
    ),
    "backend development": ("backend development", "back end development", "backend"),
    "full stack development": (
        "full stack development", "fullstack development", "full stack application",
        "full stack applications", "fullstack application", "fullstack applications",
    ),
    "agile": ("agile", "agile methodologies", "agile environment", "agile environments"),
    "testing": ("testing", "software testing"),
    "unit testing": ("unit testing", "unit test", "unit tests"),
    "automated testing": ("automated testing", "automated test", "automated tests"),
    "mentoring": ("mentoring", "mentored", "mentor", "mentorship", "team mentorship", "team mentoring"),
    "debugging": ("debugging", "debugged"),
    "code reviews": ("code reviews", "code review"),
    "stakeholder communication": ("stakeholder communication", "stakeholder interaction"),
}
_BROADER = {"testing": {"unit testing", "automated testing"}}


def _contains(text: str, phrase: str) -> bool:
    return bool(phrase) and re.search(
        r"(?<![a-z0-9+#.])" + re.escape(phrase) + r"(?![a-z0-9+#.])", text,
    ) is not None


def _canonical(value: str) -> str:
    value = _normalise(value)
    for concept, aliases in _CONCEPTS.items():
        if value in aliases:
            return concept
    return value


def _concepts(value: str) -> set[str]:
    value = _normalise(value)
    return {concept for concept, aliases in _CONCEPTS.items()
            if any(_contains(value, alias) for alias in aliases)}
