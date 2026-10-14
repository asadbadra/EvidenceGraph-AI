"""Claim extraction from a generated answer.

A *claim* here is one sentence-level fragment of an answer that asserts
something checkable against the corpus. Extraction is deliberately
PERMISSIVE: it removes only fragments it can *justify* removing, and leaves
everything else for the verifier to judge. Over-filtering at this stage
would hide real claims from verification, which is the opposite of the point.

Removed (with the reason recorded, never silently):

- Fragments that are only citation markers or whitespace.
- Interrogative fragments -- a question asserts nothing to verify.
- The canned abstention sentence the baseline prompt instructs the model to
  emit verbatim (see `ABSTENTION_SENTENCES`).

Everything else becomes a claim, including hedges and recommendations. Those
are exactly what `unverifiable` exists to label, and deciding that is the
classifier's job (Stage 2.3), not the segmenter's.

CHARACTER SPANS
---------------
Each claim records `start`/`end` offsets into the *original* answer text, so
`answer_text[claim.start:claim.end]` returns the raw sentence exactly as the
model wrote it, citation markers included. `claim.text` is a normalised form
(markers stripped, whitespace collapsed) used for retrieval and judging.
Keeping both means a verdict is traceable to the precise source wording --
the property the whole project is built around.

SENTENCE SEGMENTATION
---------------------
Boundary detection reuses the same lookbehind the chunker uses
(`(?<=[.!?])\\s+`), but is implemented locally so this module can track
character offsets without depending on the chunker's internal representation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.security import CITATION_PATTERN

# Sentence boundary: a sentence terminal followed by whitespace. Kept
# identical in behaviour to app.ingestion.chunking's split so that claims and
# chunks agree on where a sentence starts and ends.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")

# The abstention sentence the baseline prompt (app.llm.prompts) instructs the
# model to emit verbatim when the passages do not contain the answer.
#
# MIRRORED, not imported: the string is inlined in prompts.SYSTEM_INSTRUCTIONS
# rather than exposed as a constant, and editing that baseline module to
# extract it would violate the "baseline untouched" constraint. The trade-off
# is a silent drift risk -- if the prompt's wording changes, this set would
# stop matching and the abstention would be treated as an ordinary claim.
# That failure mode is soft (a spurious claim the classifier can reject), not
# a correctness break, and it is recorded here so the coupling is visible.
ABSTENTION_SENTENCES = frozenset(
    {
        "insufficient evidence in the retrieved passages.",
    }
)


@dataclass(frozen=True)
class Claim:
    """One checkable assertion extracted from a generated answer.

    `text` is normalised for matching and judging; `start`/`end` locate the
    original sentence in the answer, so the raw wording is always recoverable.
    `markers` are the citation markers that appeared in that sentence, in
    order, which is how Stage 2.2 links a claim to the passages the model
    itself cited.
    """

    text: str
    start: int
    end: int
    markers: tuple[str, ...] = ()

    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)

    def raw(self, answer_text: str) -> str:
        """Return the original sentence exactly as written."""
        return answer_text[self.start : self.end]


@dataclass(frozen=True)
class SkippedFragment:
    """A fragment deliberately NOT promoted to a claim, with the reason.

    Recorded rather than dropped silently so an operator can see what was
    excluded and why -- the same honesty rule the ingestion audit trail
    follows for records it rejects.
    """

    text: str
    start: int
    end: int
    reason: str


@dataclass(frozen=True)
class ClaimExtraction:
    """Result of extracting claims from one answer."""

    claims: tuple[Claim, ...]
    skipped: tuple[SkippedFragment, ...] = ()


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Return `[start, end)` spans covering each sentence in `text`.

    A span ends immediately after the sentence's terminal punctuation, so
    trailing whitespace belongs to the gap between spans and is never
    included. Trailing text with no terminal punctuation is returned as a
    final span, because dropping it would silently lose content.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


# A space immediately before punctuation, left behind when a citation marker
# is removed ("execution [1]." -> "execution ."). Removed during
# normalisation so stored claim text reads naturally.
_STRANDED_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?)\]])")


def _normalise(fragment: str) -> str:
    """Collapse whitespace and repair punctuation spacing.

    Whitespace is collapsed rather than merely stripped because removing a
    citation marker can leave a double space, and because answers are
    frequently multi-line (bullet lists, wrapped paragraphs). Space before
    punctuation is then removed, since deleting a trailing marker
    ("execution [1].") would otherwise leave "execution ." -- text that is
    stored and shown to the judge, so it should read as the author wrote it.
    """
    collapsed = " ".join(fragment.split())
    return _STRANDED_SPACE_BEFORE_PUNCT.sub(r"\1", collapsed)


def _is_abstention(text: str) -> bool:
    """True when `text` is the pipeline's canned abstention sentence.

    Compared case-insensitively and ignoring a trailing full stop, so an
    otherwise-verbatim echo with different casing or punctuation is still
    recognised as an abstention rather than a verifiable claim.
    """
    normalised = text.lower().strip().rstrip(".!")
    return f"{normalised}." in ABSTENTION_SENTENCES


def extract_claims(answer_text: str) -> ClaimExtraction:
    """Extract checkable claims from `answer_text`.

    Deterministic and dependency-free: no LLM, no network, no clock. The same
    answer always yields the same claims and spans, which is what makes the
    evaluation reproducible.

    Later stages may add optional LLM-based decomposition of multi-part
    sentences into atomic claims; that refinement is off by default and does
    not change this function's behaviour.
    """
    claims: list[Claim] = []
    skipped: list[SkippedFragment] = []

    for raw_start, raw_end in _sentence_spans(answer_text):
        raw = answer_text[raw_start:raw_end]
        stripped = raw.strip()
        if not stripped:
            continue  # pure whitespace between sentences; not a fragment at all

        # Re-anchor to the stripped text so offsets point at real content,
        # not at leading whitespace the segmenter happened to include.
        lead = len(raw) - len(raw.lstrip())
        start = raw_start + lead
        end = start + len(stripped)

        markers = tuple(m.group(0) for m in CITATION_PATTERN.finditer(stripped))
        without_markers = _normalise(CITATION_PATTERN.sub("", stripped))

        if not without_markers:
            skipped.append(
                SkippedFragment(stripped, start, end, "no text after removing citation markers")
            )
            continue
        if without_markers.endswith("?"):
            skipped.append(SkippedFragment(stripped, start, end, "question, not an assertion"))
            continue
        if _is_abstention(without_markers):
            skipped.append(SkippedFragment(stripped, start, end, "abstention statement"))
            continue

        claims.append(Claim(text=without_markers, start=start, end=end, markers=markers))

    return ClaimExtraction(claims=tuple(claims), skipped=tuple(skipped))
