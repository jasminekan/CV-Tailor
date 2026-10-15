"""Conservative, local activity checks; tags and credentials are never actions."""

import re

from app.services.matching_terms import _contains, _normalise


_ACTIONS = (
    r"used|using|integrated|implemented|built|developed|designed|maintained|created|"
    r"configured|queried|deployed|released|published|hosted|worked|wrote|added|"
    r"collaborated|led|managed|owned|tested"
)
_NON_EXPERIENCE = re.compile(
    r"\b(?:no|not|never|without|lack|lacks|lacking|learning|learn|plan|planning|"
    r"hope|aspire|aspiring|intend|intending|would|could|will|want|wish|aim|"
    r"proposed|proposal|hypothetical|considering)\b", re.I,
)
_API_ACTION = re.compile(
    r"\b(?:designed|developed|implemented|built|maintained|created|extended)"
    r"(?:\s+(?:and|designed|developed|implemented|built|maintained|created|extended))*"
    r"\s+(?:(?:a|an|the|new|secure|rest|restful|backend|back end|web|service|"
    r"scalable|reliable|production|\d+)\s+)*apis?\b"
    r"(?!\s+(?:clients?|integrations?|consumers?|wrappers?|requests?|tests?|documentation|docs|specifications?)\b)"
)
_API_USING = re.compile(
    r"\bused\b.{0,80}\bto\s+(?:build|develop|implement|maintain|design)"
    r"\s+(?:(?:a|an|the|rest|restful|backend)\s+)*apis?\b"
    r"(?!\s+(?:clients?|integrations?|consumers?|wrappers?|requests?|tests?|documentation|docs)\b)"
)
_CLOUD = r"(?:azure|aws|amazon web services|cloud (?:infrastructure|platforms?|environments?))"
_APPLICATION = r"(?:applications?|apps?|services?|apis?|websites?)"
_DEPLOY = re.compile(
    r"\b(?:deployed|released|published|hosted)\b.{0,100}\b" + _APPLICATION
    + r"\b.{0,80}\b(?:to|on|onto|into|in)\s+(?:the\s+)?" + _CLOUD + r"\b"
    + r"|\b" + _APPLICATION + r"\b.{0,40}\b(?:was|were)\s+deployed"
    + r"\b.{0,80}\b(?:to|on|onto|into|in)\s+(?:the\s+)?" + _CLOUD + r"\b"
)
_ORACLE_DATABASE_DEVELOPMENT = re.compile(
    r"\b(?:developed|implemented|created|wrote|maintained|refactored)"
    r"\s+(?:(?:a|an|the|new|existing|complex)\s+)*"
    r"(?:(?:sql|pl sql)\s+(?:stored procedures?|queries|functions?|triggers?)|stored procedures?)"
    r"\s+(?:in|using|with|on)\s+(?:the\s+)?oracle(?: database)?\b"
    r"(?!\s+cloud\b)"
)


def oracle_database_development(clause: str) -> bool:
    """Disambiguate Oracle only through completed, explicitly database work.

    This is a contextual wording rule, not a global Oracle/Oracle Database alias.
    Tags, credentials and evidence-record boundaries are handled by the matcher.
    """
    return not _NON_EXPERIENCE.search(clause) and bool(_ORACLE_DATABASE_DEVELOPMENT.search(clause))


def positive_clauses(text: str) -> list[str]:
    """Keep linked objects/actions; split independent actions before checking."""
    clauses = re.split(r"[.!?;\n](?=\s|$)", text)
    result = []
    for sentence in clauses:
        # "Designed and implemented APIs" shares an object; "Used Azure and
        # built APIs with FastAPI" has independent action/object spans.
        boundaries = []
        for match in re.finditer(
            r"\s+(?:but|whereas|while|however)\s+|"
            r",\s+(?=(?:with|familiar|certified|skills|technologies)\b)|"
            r",?\s+and\s+(?=(?:(?:i|we|they)\s+)?(?:" + _ACTIONS + r")\b)",
            sentence, flags=re.I,
        ):
            previous = sentence[:match.start()].strip().split()
            if "and" in match.group().lower() and previous and re.fullmatch(_ACTIONS, previous[-1], re.I):
                continue
            boundaries.append((match.start(), match.end()))
        start = 0
        pieces = []
        for left, right in boundaries:
            pieces.append(sentence[start:left])
            start = right
        pieces.append(sentence[start:])
        for clause in pieces:
            if clause.strip() and not _NON_EXPERIENCE.search(clause):
                result.append(_normalise(clause))
    return result


def _named(text: str, names: tuple[str, ...]) -> bool:
    return any(_contains(text, _normalise(name)) for name in names)


def demonstrates(activity: str, clause: str, names: tuple[str, ...] = ()) -> bool:
    """The activity and named technology must be connected in this clause."""
    if _NON_EXPERIENCE.search(clause):
        return False
    if activity == "cloud_deployment":
        deployment = _DEPLOY.search(clause)
        if not deployment:
            return False
        if not names:
            return True
        # Bind a requested platform to the destination, not a different tool.
        destination = re.search(
            r"\b(?:to|on|onto|into|in)\s+(?:the\s+)?" + _CLOUD + r"\b.*",
            deployment.group(),
        )
        return bool(destination and _named(destination.group(), names))
    if activity == "technology_usage":
        if not names:
            return False
        if oracle_database_development(clause) and (
            any(_normalise(name) == "oracle database" for name in names)
            or any(_normalise(name) == "sql" for name in names) and _contains(clause, "sql")
        ):
            return True
        for action in re.finditer(
            r"\b(?:used|using|integrated|configured|queried|implemented|working with|worked with)\b",
            clause,
        ):
            if _named(clause[action.end():action.end() + 120], names):
                return True
        for name in names:
            name = _normalise(name)
            if re.search(re.escape(name) + r"\s+(?:was|were)\s+(?:used|integrated|configured)\b", clause):
                return True
        for action in re.finditer(r"\b(?:built|developed|maintained|designed|created)\b", clause):
            span = clause[action.end():action.end() + 140]
            connector = re.search(r"\b(?:using|with|in|on|via)\b", span)
            if connector and _named(span[connector.end():], names):
                return True
        return demonstrates("cloud_deployment", clause, names)
    if activity == "api_development":
        action = _API_ACTION.search(clause) or _API_USING.search(clause)
        if not action:
            return False
        return not names or demonstrates("technology_usage", clause, names)
    return False


def complete_api_request(request: str, clause: str) -> bool:
    """Only recognise simple action/API wording, retaining compound obligations."""
    text = _normalise(request)
    allowed = {
        "develop", "maintain", "build", "design", "implement", "create", "and", "or",
        "a", "an", "the", "backend", "back", "end", "rest", "restful", "api", "apis",
        "development", "design", "endpoints", "endpoint",
    }
    if set(text.split()) - allowed:
        return False
    for requested, past in (
        (("develop", "build", "implement", "create"), ("developed", "built", "implemented", "created")),
        (("maintain",), ("maintained",)),
        (("design",), ("designed",)),
    ):
        if any(_contains(text, word) for word in requested) and not any(_contains(clause, word) for word in past):
            return False
    return demonstrates("api_development", clause)


def api_development_without_maintenance(request: str, clause: str) -> bool:
    """Strong relevance to a simple development-and-maintenance duty's main capability.

    Keep complete_api_request strict. This exception requires demonstrated API
    development and removes only an unproven maintenance action, not other claims.
    """
    text = _normalise(request)
    if (
        not _contains(text, "maintain") or _contains(text, "or")
        or not any(_contains(text, word) for word in ("develop", "build", "implement", "create"))
        or _contains(clause, "maintained")
    ):
        return False
    main_request = re.sub(r"\bmaintain\b", "", text)
    return complete_api_request(main_request, clause)


def complete_cloud_request(request: str) -> bool:
    text = _normalise(request)
    allowed = {
        "deploy", "deployment", "applications", "application", "app", "apps",
        "services", "service", "to", "on", "in", "onto", "cloud", "infrastructure",
        "platform", "platforms", "a", "an", "the",
    }
    return not (set(text.split()) - allowed)
