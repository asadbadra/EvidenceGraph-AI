"""Deterministic, dependency-free document chunking.

Strategy: split on paragraph boundaries first, then greedily pack sentences
into chunks up to `max_chars`, with a configurable character overlap so that
statements spanning a boundary remain retrievable.
"""

from __future__ import annotations

import re

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def chunk_text(text: str, *, max_chars: int = 900, overlap_chars: int = 150) -> list[str]:
    """Split `text` into overlapping chunks of at most `max_chars` characters.

    - Empty/whitespace input returns [].
    - A single unit longer than `max_chars` is hard-split so no unit is lost.
    - `overlap_chars` characters of the previous chunk's tail are prepended
      to the next chunk when available.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must satisfy 0 <= overlap < max_chars")

    text = text.strip()
    if not text:
        return []

    units: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(text):
        paragraph = paragraph.strip()
        if paragraph:
            units.extend(_split_sentences(paragraph))

    # Hard-split any oversized unit.
    expanded: list[str] = []
    for unit in units:
        if len(unit) <= max_chars:
            expanded.append(unit)
        else:
            for start in range(0, len(unit), max_chars):
                expanded.append(unit[start : start + max_chars])

    chunks: list[str] = []
    current = ""
    for unit in expanded:
        candidate = f"{current} {unit}".strip() if current else unit
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap_chars:] if overlap_chars else ""
            current = f"{tail} {unit}".strip() if tail else unit
            # The overlap plus the new unit may still exceed max_chars.
            # Emit slices until the remainder fits; each pass removes
            # (max_chars - overlap_chars) > 0 characters, so this terminates.
            while len(current) > max_chars:
                chunks.append(current[:max_chars])
                current = (
                    current[max_chars - overlap_chars :]
                    if overlap_chars
                    else current[max_chars:]
                )
    if current:
        chunks.append(current)

    return [c for c in chunks if c]
