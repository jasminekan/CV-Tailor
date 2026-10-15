"""Verify extracted quotations and build the compatible analysis in Python."""

import re
import unicodedata

from app.models import JobDescriptionAnalysis, JobDescriptionExtraction, StructuredRequirement


# Match words and technical punctuation, retaining C/C++/C#, .NET, Node.js and
# version numbers as distinct tokens. Other punctuation separates words.
_SOURCE_TOKEN = re.compile(r"(?:\.[^\W_]+|[^\W_]+)(?:[.'+#][^\W_]+)*[+#]*")
_SOURCE_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})


class SourceQuotationError(ValueError):
    """A rejected quotation, identified without including private source wording."""

    def __init__(self, requirement_id: str) -> None:
        self.requirement_id = requirement_id
        super().__init__(
            f"Requirement {requirement_id} source_text is not a supported contiguous quotation."
        )


def _source_tokens(value: str) -> list[tuple[str, int, int]]:
    # Translation preserves character offsets; case/Unicode folding is confined
    # to token values so recovered spans always refer to the untouched input.
    return [
        (unicodedata.normalize("NFKC", match.group()).casefold(), match.start(), match.end())
        for match in _SOURCE_TOKEN.finditer(value.translate(_SOURCE_APOSTROPHES))
    ]


def _verified_source(
    source_text: str,
    job_description: str,
    document_tokens: list[tuple[str, int, int]],
    requirement_id: str,
) -> str:
    quote_tokens = [token for token, _, _ in _source_tokens(source_text)]
    if quote_tokens:
        count = len(quote_tokens)
        for index in range(len(document_tokens) - count + 1):
            span = document_tokens[index:index + count]
            if [token for token, _, _ in span] == quote_tokens:
                # Exact quotations retain their punctuation. For harmless
                # formatting differences return an actual original-input span.
                if source_text in job_description:
                    return source_text
                return job_description[span[0][1]:span[-1][2]]
    raise SourceQuotationError(requirement_id)


def analysis_from_extraction(
    extraction: JobDescriptionExtraction,
    job_description: str,
) -> JobDescriptionAnalysis:
    """Assign stable IDs and derive legacy lists through the analysis model.

    Verification is lexical, not proof of the interpretation's correctness.
    Quotes must retain token order, negation, alternatives and technical names.
    No fuzzy paraphrase fallback, guessed source text or requirement deduplication
    occurs here. Provider order and every verified source occurrence are retained.
    """
    document_tokens = _source_tokens(job_description)
    requirements = []
    for index, item in enumerate(extraction.requirements, 1):
        requirement_id = f"r{index}"
        content = item.model_dump()
        content["source_text"] = _verified_source(
            item.source_text, job_description, document_tokens, requirement_id,
        )
        requirements.append(StructuredRequirement(id=requirement_id, **content))
    return JobDescriptionAnalysis(job_title=extraction.job_title, requirements=requirements)
