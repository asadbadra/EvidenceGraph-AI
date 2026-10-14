"""Evidence linking: attach candidate passages to a claim (Stage 2.2).

For each claim, build one candidate set from two independent sources:

- **cited**   -- the passages the model cited on that sentence, resolved from
                 the generation-time retrieval via the claim's marker list.
- **retrieved** -- a fresh retrieval run on the claim's own text, which finds
                 support the model failed to cite and detects misattribution
                 (a claim cited to [3] that is really backed by [1]).

Checking cited passages alone cannot distinguish "cited the wrong passage"
from "the corpus is silent" -- that is why the second source exists.

Candidates are deduplicated by `chunk_id` (cited first: they are the ones
under scrutiny), validated against known database records when a validator
is supplied, and truncated to a configured limit.

The no-fabrication invariant is NOT reimplemented here. `make_evidence_verdict`
simply hands `EvidenceSet.chunk_ids` to `make_verdict` as the candidate set,
so rule 2 (no evidence id outside the candidates) is active for every verdict
built from an evidence set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from app.schemas import RetrievedChunk
from app.verification.claims import Claim
from app.verification.verdicts import ClaimVerdict, Verdict, make_verdict

# Candidate cap. Bounded so judge cost stays predictable as the corpus grows;
# 8 is the plan's stated default and is deliberately small.
DEFAULT_CANDIDATE_LIMIT = 8

# How many passages to pull for the claim-level re-retrieval. Wider than the
# final candidate limit, because the cited set claims some of those slots and
# because a little recall headroom helps find misattributed support.
CLAIM_RETRIEVAL_TOP_K = 12

# Where a candidate came from. Recorded, never guessed.
ORIGIN_CITED = "cited"
ORIGIN_RETRIEVED = "retrieved"


@dataclass(frozen=True)
class EvidenceCandidate:
    """One candidate passage, with provenance and its origin in this set."""

    chunk_id: int
    document_id: int
    external_id: str
    title: str
    source_url: str
    published_at: str
    text: str
    score: float
    origin: str

    @property
    def was_cited(self) -> bool:
        return self.origin == ORIGIN_CITED


@dataclass(frozen=True)
class EvidenceSet:
    """The candidate set for one claim, plus what could not be resolved."""

    claim: Claim
    candidates: tuple[EvidenceCandidate, ...]
    unresolved_markers: tuple[str, ...] = ()
    rejected_chunk_ids: tuple[int, ...] = ()

    @property
    def chunk_ids(self) -> tuple[int, ...]:
        """Candidate ids, in order -- passed to `make_verdict` as the set."""
        return tuple(c.chunk_id for c in self.candidates)

    @property
    def cited(self) -> tuple[EvidenceCandidate, ...]:
        return tuple(c for c in self.candidates if c.was_cited)

    @property
    def is_empty(self) -> bool:
        return not self.candidates


def _to_candidate(chunk: RetrievedChunk, origin: str) -> EvidenceCandidate:
    return EvidenceCandidate(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        external_id=chunk.external_id,
        title=chunk.title,
        source_url=chunk.source_url,
        published_at=chunk.published_at,
        text=chunk.text,
        score=chunk.score,
        origin=origin,
    )


def resolve_cited_chunks(
    claim: Claim, retrieved: Sequence[RetrievedChunk]
) -> tuple[list[RetrievedChunk], tuple[str, ...]]:
    """Resolve a claim's citation markers against the generation retrieval.

    Returns `(chunks, unresolved_markers)`. A marker is unresolved when it is
    out of range for `retrieved` -- the model cited something that was never
    retrieved. Those are recorded rather than dropped silently, because an
    unresolvable citation is itself a reportable quality defect.
    """
    chunks: list[RetrievedChunk] = []
    unresolved: list[str] = []
    seen: set[int] = set()
    for marker in claim.markers:
        index = int(marker[1:-1])
        if 1 <= index <= len(retrieved):
            chunk = retrieved[index - 1]
            # The same chunk cited twice on one claim is still one candidate.
            if chunk.chunk_id not in seen:
                seen.add(chunk.chunk_id)
                chunks.append(chunk)
        else:
            unresolved.append(marker)
    return chunks, tuple(unresolved)


def link_evidence(
    claim: Claim,
    retrieved: Sequence[RetrievedChunk],
    *,
    retriever=None,
    top_k: int = CLAIM_RETRIEVAL_TOP_K,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
    chunk_is_known: Callable[[int], bool] | None = None,
) -> EvidenceSet:
    """Build the candidate evidence set for `claim`.

    `retrieved` is the generation-time passage list, used only to resolve the
    claim's own citation markers. `retriever` (optional) supplies claim-level
    re-retrieval; when omitted the set is cited-only, which keeps the two
    contributions independently testable.

    `chunk_is_known` validates a candidate id against the database. Supplying
    it enables the "candidates must be real records" check; `None` skips it,
    which is only correct before the pipeline wires a real session in Stage
    2.4.

    Raises `ValueError` on a non-positive `limit` rather than silently
    returning an empty set -- an empty candidate set is a meaningful signal
    (no evidence exists), so it must never be produced by a misconfiguration.
    """
    if limit <= 0:
        raise ValueError("limit must be a positive integer")
    if top_k < 0:
        raise ValueError("top_k must not be negative")

    cited, unresolved = resolve_cited_chunks(claim, retrieved)

    ordered: list[EvidenceCandidate] = []
    seen_ids: set[int] = set()
    rejected: list[int] = []
    rejected_ids: set[int] = set()

    def add(chunk: RetrievedChunk, origin: str) -> None:
        if chunk.chunk_id in seen_ids:
            return  # already a candidate; cited-then-retrieved order decides origin
        if chunk_is_known is not None and not chunk_is_known(chunk.chunk_id):
            # Record each rejected id once, even if it surfaces from both
            # sources -- the anomaly is about the id, not each occurrence.
            if chunk.chunk_id not in rejected_ids:
                rejected_ids.add(chunk.chunk_id)
                rejected.append(chunk.chunk_id)
            return
        seen_ids.add(chunk.chunk_id)
        ordered.append(_to_candidate(chunk, origin))

    # Cited first: these are the passages the answer's citations point at, so
    # they must survive deduplication ahead of merely-retrieved ones.
    for chunk in cited:
        add(chunk, ORIGIN_CITED)
        if len(ordered) >= limit:
            break

    if retriever is not None and len(ordered) < limit:
        for chunk in retriever.retrieve(claim.text, top_k=top_k):
            if len(ordered) >= limit:
                break
            add(chunk, ORIGIN_RETRIEVED)

    return EvidenceSet(
        claim=claim,
        candidates=tuple(ordered),
        unresolved_markers=unresolved,
        rejected_chunk_ids=tuple(rejected),
    )


def make_evidence_verdict(
    evidence: EvidenceSet,
    label: ClaimVerdict,
    *,
    evidence_chunk_ids: Sequence[int] = (),
    rationale: str = "",
) -> Verdict:
    """Build a verdict, constraining the judge's evidence to this set.

    `evidence_chunk_ids` are the candidates the judge selected as supporting
    or contradicting the claim (Stage 2.3 supplies them). Passing them
    through `candidate_chunk_ids` is this function's entire reason to exist:
    it makes rule 2 of the no-fabrication invariant impossible to forget at
    the call site, so a judge cannot cite a chunk it was never shown.

    With no ids given, a `supported` label self-downgrades -- correct, since
    claiming support while naming nothing is incoherent. Label correction and
    downgrade ordering remain `make_verdict`'s, unchanged.
    """
    return make_verdict(
        evidence.claim,
        label,
        evidence_chunk_ids=evidence_chunk_ids,
        rationale=rationale,
        candidate_chunk_ids=evidence.chunk_ids,
    )
