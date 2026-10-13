"""Security helpers.

Phase 0 responsibilities:
- Treat retrieved document text as untrusted input (delimit + instruct).
- Validate citation markers: format-only check that a marker refers to a
  chunk that was actually retrieved.

Evidence-support verification (does the passage actually support the claim?)
is intentionally NOT performed here. See the Verified RAG phase.
"""

from __future__ import annotations

import re
from typing import Iterable

from app.schemas import Citation, RetrievedChunk

# Markers like [1], [2], ... referencing the numbered retrieval list.
CITATION_PATTERN = re.compile(r"\[(\d+)\]")

# Fence used to isolate untrusted retrieved text inside prompts.
UNTRUSTED_BEGIN = "<untrusted_retrieved_content>"
UNTRUSTED_END = "</untrusted_retrieved_content>"


def wrap_untrusted(text: str) -> str:
    """Wrap retrieved text in explicit delimiters for prompt inclusion."""
    # Strip any fence terminators so content cannot break out of the wrapper.
    cleaned = text.replace(UNTRUSTED_END, "")
    return f"{UNTRUSTED_BEGIN}\n{cleaned}\n{UNTRUSTED_END}"


def extract_citation_markers(answer_text: str) -> list[str]:
    """Return citation markers in the order they appear, de-duplicated."""
    seen: list[str] = []
    for match in CITATION_PATTERN.finditer(answer_text):
        marker = match.group(0)
        if marker not in seen:
            seen.append(marker)
    return seen


def validate_citations(
    answer_text: str, retrieved: Iterable[RetrievedChunk]
) -> tuple[list[Citation], list[str]]:
    """Validate citation markers against the retrieved set.

    Returns (valid_citations, invalid_markers).

    Scope: format/provenance validation only. A citation is "valid" iff its
    number maps to a retrieved chunk. Whether the cited text *supports* the
    surrounding claim is a separate concern handled by claim-level
    verification in a later phase.
    """
    retrieved_list = list(retrieved)
    valid: list[Citation] = []
    invalid: list[str] = []
    for marker in extract_citation_markers(answer_text):
        index = int(marker[1:-1])
        if 1 <= index <= len(retrieved_list):
            chunk = retrieved_list[index - 1]
            valid.append(
                Citation(
                    marker=marker,
                    chunk_id=chunk.chunk_id,
                    external_id=chunk.external_id,
                    source_url=chunk.source_url,
                    title=chunk.title,
                )
            )
        else:
            invalid.append(marker)
    return valid, invalid
