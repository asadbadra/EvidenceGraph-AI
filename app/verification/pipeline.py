"""Verified RAG pipeline: generate exactly like baseline, then verify (Stage 2.4).

FAIRNESS IS THE WHOLE POINT OF THIS MODULE
------------------------------------------
The verified pipeline must differ from `BaselineRAG` in exactly one respect:
it adds a claim-level verification pass *after* generation. Therefore it
reuses, unchanged:

- the same `Retriever` (same BM25 index, same `top_k`),
- the same `build_baseline_prompt` (same system instructions, same prompt),
- the same `LLMClient` for generation.

Generation is byte-for-byte the baseline path. Verification reads the answer
that was produced; it never regenerates, never revises, and never injects
evidence into the answer text. If the judge finds the answer unsupported, the
answer is still reported verbatim -- the verdict travels alongside it, so a
reader sees what was claimed *and* what the corpus can actually back.

That ordering is a deliberate constraint, not an implementation accident: the
research question asks whether post-hoc claim verification improves citation
quality, and it cannot be answered by a system that generates differently.

What is NOT claimed here: that verification improves accuracy. Whether it
does is the empirical question, measurable only on the labelled set (Stage
2.6) and reported there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Chunk
from app.llm.client import LLMClient
from app.llm.prompts import build_baseline_prompt
from app.retrieval.retriever import Retriever
from app.schemas import Citation, RetrievedChunk
from app.security import validate_citations
from app.verification.claims import ClaimExtraction, extract_claims
from app.verification.evidence import (
    CLAIM_RETRIEVAL_TOP_K,
    DEFAULT_CANDIDATE_LIMIT,
    EvidenceSet,
    link_evidence,
)
from app.verification.judge import Judge, LLMJudge
from app.verification.verdicts import ClaimVerdict, Verdict, VerdictSummary, summarize


@dataclass(frozen=True)
class VerifiedAnswerResult:
    """Baseline fields plus the claim-level verification record.

    A plain dataclass rather than a pydantic model: it carries `Claim`/
    `Verdict`/`EvidenceSet` objects that are domain types, not wire formats,
    and `app/schemas.py` stays a baseline-owned module untouched by Phase 2.
    """

    question: str
    answer_text: str
    citations: list[Citation]
    invalid_citation_markers: list[str]
    retrieved: list[RetrievedChunk]
    model: str
    extraction: ClaimExtraction
    verdicts: tuple[Verdict, ...]
    evidence_sets: tuple[EvidenceSet, ...] = ()
    # Set explicitly to True: this pipeline DOES perform the check. The
    # baseline's `False` is what makes the two systems distinguishable in
    # the evaluation data.
    unsupported_citation_check_performed: bool = True

    @property
    def summary(self) -> VerdictSummary:
        return summarize(self.verdicts)

    @property
    def unsupported_claims(self) -> tuple[Verdict, ...]:
        """Claims the corpus could not back -- the answer's weak points.

        Abstentions are included on purpose. `unverifiable` and
        `insufficient_evidence` both mean "we did not establish this", and a
        report reader needs to see those exactly as much as an outright
        contradiction.
        """
        return tuple(v for v in self.verdicts if v.label is not ClaimVerdict.SUPPORTED)


# Small helper: a real-database predicate for candidate validation. Caching
# keeps it to one query per distinct id instead of one per candidate.
def make_chunk_exists(session: Session) -> Callable[[int], bool]:
    """Return a predicate that is true only for chunk ids in `session`'s DB.

    This is the concrete wiring behind `link_evidence(chunk_is_known=...)`,
    and therefore the reason a verdict can only cite chunks that are real
    records rather than merely integers the judge produced.
    """
    cache: dict[int, bool] = {}

    def chunk_exists(chunk_id: int) -> bool:
        if chunk_id not in cache:
            cache[chunk_id] = (
                session.execute(select(Chunk.id).where(Chunk.id == chunk_id)).first()
                is not None
            )
        return cache[chunk_id]

    return chunk_exists


class VerifiedRAG:
    """Baseline generation plus claim-level evidence verification."""

    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        *,
        top_k: int = 4,
        judge: Judge | None = None,
        claim_retrieval_top_k: int = CLAIM_RETRIEVAL_TOP_K,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        chunk_is_known: Callable[[int], bool] | None = None,
    ) -> None:
        # Identical to BaselineRAG's construction: same retriever, same LLM,
        # same top_k default.
        self._retriever = retriever
        self._llm = llm
        self._top_k = top_k
        self._judge: Judge = judge if judge is not None else LLMJudge(llm)
        self._claim_retrieval_top_k = claim_retrieval_top_k
        self._candidate_limit = candidate_limit
        self._chunk_is_known = chunk_is_known

    def run(self, question: str) -> VerifiedAnswerResult:
        """Generate with the baseline path, then verify every extracted claim.

        Post-generation only. The answer text returned is exactly what the
        baseline pipeline would have produced for the same question.
        """
        # ---- Generation: unchanged from BaselineRAG ----
        retrieved = self._retriever.retrieve(question, top_k=self._top_k)
        prompt = build_baseline_prompt(question, retrieved)
        answer_text = self._llm.complete(prompt).strip()
        citations, invalid = validate_citations(answer_text, retrieved)

        # ---- Verification: the only addition ----
        extraction = extract_claims(answer_text)
        verdicts: list[Verdict] = []
        evidence_sets: list[EvidenceSet] = []
        for claim in extraction.claims:
            evidence = link_evidence(
                claim,
                retrieved,
                retriever=self._retriever,
                top_k=self._claim_retrieval_top_k,
                limit=self._candidate_limit,
                chunk_is_known=self._chunk_is_known,
            )
            evidence_sets.append(evidence)
            verdicts.append(self._judge.judge(evidence))

        return VerifiedAnswerResult(
            question=question,
            answer_text=answer_text,
            citations=citations,
            invalid_citation_markers=invalid,
            retrieved=retrieved,
            model=getattr(self._llm, "model", "unknown"),
            extraction=extraction,
            verdicts=tuple(verdicts),
            evidence_sets=tuple(evidence_sets),
            unsupported_citation_check_performed=True,
        )
