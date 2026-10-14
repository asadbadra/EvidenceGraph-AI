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
- Bibliography fragments: a bare heading ("References:") or a list of
  reference entries (`[n] Title | ... | https://...`). A reference list is
  not an assertion; promoting it to a claim would inflate the supported
  count with something no judge can contradict.

Everything else becomes a claim, including hedges and recommendations. Those
are exactly what `unverifiable` exists to label, and deciding that is the
classifier's job (Stage 2.3), not the segmenter's.

CITATION SCAFFOLD REPAIR (Stage 2.9)
------------------------------------
Observed in the live local smoke test (runs/smoke-20261014-143159): removing
citation markers can leave behind scaffolding words whose only job was to
hold the markers in place -- "According to [1] and [2], X" degraded to
"According to and, X", and "the CISA advisory [1] and [2], which" to "the
CISA advisory and, which". Two repairs fix exactly those shapes, both
KEYED TO MARKERS so ordinary prose is never rewritten:

- A leading "According to [n]( and [m])?," attribution is dropped from the
  claim TEXT: the assertion is what follows the attribution. The markers
  are still recorded (they are the model's own citations for that
  assertion) and the span is unchanged, so `raw()` still recovers the
  sentence exactly as written.
- A run of two or more markers joined by commas/"and" and terminated by a
  comma ("[1] and [2],") is removed together with its joiners, leaving the
  sentence's own comma in place. A single "[1]," needs no repair (the
  whitespace normaliser already handles it), and an "and" joining real
  words ("the advisory [1] and the notes [2] confirm X") is kept, because
  there the conjunction is prose, not scaffold. A blanket "and," -> ","
  rewrite was considered and rejected: it would corrupt legitimate prose
  such as "weaponized and, according to CISA, actively used".

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


# --- Citation scaffold repair (see module docstring) -----------------------
#
# Both patterns are anchored to citation markers on purpose. The failure
# mode this stage must not repeat is an over-broad text rewrite: a bare
# "and," -> "," substitution would mangle ordinary prose, so every repair
# below requires a [n] marker to fire.

# A leading attribution whose objects are only citation markers:
# "According to [1] and [2], X". The trailing comma and whitespace belong
# to the scaffold; the assertion starts right after.
_LEADING_ATTRIBUTION = re.compile(
    r"\AAccording to\s+\[\d+\](?:\s*(?:,|and|&)\s*\[\d+\])*(?:\s*,)?\s*",
    re.IGNORECASE,
)

# Two or more markers joined by commas/"and"/"&" and immediately followed
# by a comma: "[1] and [2], which ...". The lookahead keeps the sentence's
# own comma (and everything after it) untouched; a single "[1]," does not
# match, because the joiner repetition requires at least one extra marker.
_MARKER_RUN_BEFORE_COMMA = re.compile(
    r"\[\d+\](?:\s*(?:,|and|&)\s*\[\d+\])+(?=\s*,)"
)

# Bibliography recognition (see module docstring). Headings are matched
# exactly; entries are recognised as "[n] ... https://... " with no
# sentence-terminal punctuation, since prose assertions end with ". " /
# "! " / "? " and reference entries end with bare URLs.
_BIBLIOGRAPHY_HEADING = re.compile(
    r"(?:references|sources|bibliography|works cited|citations)\s*[:.]?\s*",
    re.IGNORECASE,
)
_BIBLIOGRAPHY_LEAD = re.compile(
    r"\A(?:references|sources|bibliography|works cited|citations)\s*[:.]?\s*",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://", re.IGNORECASE)
_PROSE_TERMINAL = re.compile(r"[.!?]\s")


def _bibliography_reason(fragment: str) -> str | None:
    """Return a skip reason when `fragment` is a reference list, else None.

    Narrow by design: a heading alone asserts nothing, and an entry list is
    recognised only as marker-led + URL-bearing + free of sentence-terminal
    punctuation. The URL requirement keeps a genuine claim that merely opens
    with a citation marker ("[1] confirms the date was 2021-12-10.") from
    being swallowed, and a heading followed by prose ("Sources: CISA added
    the CVE on 2021-12-10.") likewise stays a claim.
    """
    if _BIBLIOGRAPHY_HEADING.fullmatch(fragment):
        return "bibliography heading"
    body = _BIBLIOGRAPHY_LEAD.sub("", fragment, count=1)
    if not CITATION_PATTERN.match(body):
        return None
    if not _URL.search(body):
        return None
    if _PROSE_TERMINAL.search(body):
        return None
    return "bibliography reference list"


def _strip_citation_scaffold(fragment: str) -> str:
    """Remove marker-keyed scaffolding words; see module docstring."""
    without_attribution = _LEADING_ATTRIBUTION.sub("", fragment, count=1)
    return _MARKER_RUN_BEFORE_COMMA.sub("", without_attribution)


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

        bibliography = _bibliography_reason(stripped)
        if bibliography is not None:
            skipped.append(SkippedFragment(stripped, start, end, bibliography))
            continue

        without_markers = _normalise(
            CITATION_PATTERN.sub("", _strip_citation_scaffold(stripped))
        )

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
