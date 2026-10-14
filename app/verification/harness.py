"""Shared A/B evaluation harness (Phase 2, Stage 2.6).

Both systems are run over the same question list, against the same corpus,
through the same `Retriever` type, with the same generation prompt and the
same generation model. The ONLY intended difference is that the verified
pipeline adds a post-generation claim-level check.

`BaselineRAG` is imported and used as-is. Nothing in this module modifies it,
and the harness never regenerates or rewrites an answer -- it records what
each pipeline produced.

Results are written to the additive `eval_runs`/`eval_results`/`verif_claims`
tables so every reported number is recomputable from stored rows.

WHAT THIS HARNESS DELIBERATELY DOES NOT DO
------------------------------------------
It does not assert that verification is better. It records both systems'
outputs and the conditions of the run; whether the verified system is better
is a question for the metrics and, ultimately, for a live run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.db import EvalResult, EvalRun, VerifClaim
from app.llm.client import LLMClient
from app.pipelines.baseline import BaselineRAG
from app.retrieval.retriever import Retriever
from app.verification.judge import Judge
from app.verification.metrics import (
    Agreement,
    CitationQuality,
    citation_quality,
    judge_agreement,
    match_claims_to_gold,
    mechanism_metrics,
)
from app.verification.pipeline import VerifiedRAG

SYSTEM_BASELINE = "baseline"
SYSTEM_VERIFIED = "verified"

# A retriever factory, so each system gets a fresh instance while still
# sharing the same construction. Passing one Retriever to both would let the
# second system see the first system's cached index state.
RetrieverFactory = Callable[[], Retriever]


@dataclass(frozen=True)
class QuestionResult:
    """One system's outcome for one question, plus its storage row id."""

    system: str
    question: str
    answer_text: str
    eval_result_id: int


@dataclass(frozen=True)
class EvalOutcome:
    """The stored rows for one completed A/B run."""

    eval_run_id: int
    results: tuple[QuestionResult, ...]

    def for_system(self, system: str) -> tuple[QuestionResult, ...]:
        return tuple(r for r in self.results if r.system == system)


def load_questions(path) -> list[dict]:
    """Load and validate the pilot question set."""
    import pathlib

    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"{path}: no questions found")
    for entry in questions:
        for key in ("id", "category", "question"):
            if not str(entry.get(key, "")).strip():
                raise ValueError(f"{path}: question entry missing {key!r}")
    return questions


def _store_result(
    session: Session,
    run_id: int,
    system: str,
    question: str,
    answer_text: str,
    model: str,
    retrieved_count: int,
    citation_count: int,
    invalid_marker_count: int,
    *,
    verdicts=(),
    check_performed: bool,
) -> int:
    """Persist one system/question outcome and return its row id."""
    summary = mechanism_metrics(verdicts)
    row = EvalResult(
        eval_run_id=run_id,
        system=system,
        question=question,
        answer_text=answer_text,
        model=model,
        retrieved_count=retrieved_count,
        citation_count=citation_count,
        invalid_marker_count=invalid_marker_count,
        claims_total=summary.total_claims,
        supported_count=summary.supported,
        contradicted_count=summary.contradicted,
        insufficient_count=summary.insufficient_evidence,
        unverifiable_count=summary.unverifiable,
        with_anomalies=summary.with_anomalies,
        unsupported_check_performed=1 if check_performed else 0,
    )
    session.add(row)
    session.flush()

    for index, verdict in enumerate(verdicts):
        session.add(
            VerifClaim(
                eval_result_id=row.id,
                claim_index=index,
                claim_text=verdict.claim.text,
                label=verdict.label.value,
                evidence_ids_json=json.dumps(list(verdict.evidence_chunk_ids)),
                rationale=verdict.rationale,
                anomalies_json=json.dumps(list(verdict.anomalies)),
            )
        )
    session.flush()
    return row.id


def run_ab_eval(
    session: Session,
    questions: Sequence[dict],
    *,
    baseline_llm: LLMClient,
    verified_llm: LLMClient,
    retriever_factory: RetrieverFactory,
    judge: Judge | None = None,
    top_k: int = 4,
    corpus_tag: str = "",
    notes: str = "",
    chunk_is_known: Callable[[int], bool] | None = None,
) -> EvalOutcome:
    """Run both pipelines over `questions` and persist the results.

    The baseline runs first and the verified second, both over identical
    inputs. An empty corpus is an error rather than a silent zero-row run:
    an evaluation over no documents would produce numbers that look like
    findings.
    """
    baseline_retriever = retriever_factory()
    baseline_retriever.refresh()
    if baseline_retriever.is_empty:
        raise ValueError(
            "evaluation corpus is empty; ingest documents before running the "
            "A/B comparison"
        )

    run = EvalRun(
        corpus_tag=corpus_tag,
        baseline_model=getattr(baseline_llm, "model", "unknown"),
        verified_model=getattr(verified_llm, "model", "unknown"),
        prompt_version="baseline-v1",
        judge_name=type(judge).__name__ if judge is not None else "LLMJudge",
        question_count=len(questions),
        notes=notes,
    )
    session.add(run)
    session.flush()

    baseline = BaselineRAG(baseline_retriever, baseline_llm, top_k=top_k)
    verified = VerifiedRAG(
        retriever_factory(),
        verified_llm,
        top_k=top_k,
        judge=judge,
        chunk_is_known=chunk_is_known,
    )

    stored: list[QuestionResult] = []
    for entry in questions:
        question = str(entry["question"])

        base_out = baseline.run(question)
        base_id = _store_result(
            session,
            run.id,
            SYSTEM_BASELINE,
            question,
            base_out.answer_text,
            base_out.model,
            len(base_out.retrieved),
            len(base_out.citations),
            len(base_out.invalid_citation_markers),
            check_performed=False,  # baseline performs no support check
        )
        stored.append(
            QuestionResult(
                SYSTEM_BASELINE,
                question,
                base_out.answer_text,
                base_id,
            )
        )

        ver_out = verified.run(question)
        ver_id = _store_result(
            session,
            run.id,
            SYSTEM_VERIFIED,
            question,
            ver_out.answer_text,
            ver_out.model,
            len(ver_out.retrieved),
            len(ver_out.citations),
            len(ver_out.invalid_citation_markers),
            verdicts=ver_out.verdicts,
            check_performed=True,
        )
        stored.append(
            QuestionResult(
                SYSTEM_VERIFIED,
                question,
                ver_out.answer_text,
                ver_id,
            )
        )

    run.finished_at = datetime.now(timezone.utc)
    session.flush()
    return EvalOutcome(eval_run_id=run.id, results=tuple(stored))


def citation_quality_for_run(session: Session, eval_run_id: int) -> dict[str, CitationQuality]:
    """Per-system citation quality, read back from the stored rows.

    `verified_citations` is ALWAYS None here, including for the verified
    system: the schema stores a citation's existence and validity, but not
    which verdict (if any) supported the specific sentence a marker sits on.
    Computing it would require inferring a link the data does not record, so
    it is reported as unknown rather than guessed. `invalid_marker_rate` is a
    direct count and is honest for both systems.
    """
    rows = (
        session.query(EvalResult)
        .filter(EvalResult.eval_run_id == eval_run_id)
        .all()
    )
    # A run holds one EvalResult per system per question, so the counts are
    # SUMMED across every question row of each system. An earlier version
    # assigned (out[row.system] = ...), which kept only the last row and
    # silently dropped the earlier questions' citations and invalid markers
    # on multi-question runs. The metric definitions are unchanged --
    # `invalid_marker_rate` is still invalid markers over all marker-bearing
    # citations, now correctly across the whole run.
    totals: dict[str, list[int]] = {}
    for row in rows:
        acc = totals.setdefault(row.system, [0, 0])
        acc[0] += row.citation_count
        acc[1] += row.invalid_marker_count
    return {
        system: citation_quality(
            citations=citations,
            invalid_markers=invalid,
            verified_citations=None,
        )
        for system, (citations, invalid) in totals.items()
    }


def judge_agreement_for_run(
    session: Session,
    eval_run_id: int,
    gold_by_question: Mapping[str, Sequence[Mapping[str, str]]],
) -> Agreement | None:
    """Judge-vs-human agreement for the verified system, over stored claims.

    `gold_by_question` maps a question to its hand-labelled claims (the pilot
    file's `gold_claims`). Gold labels are NOT stored by a machine run, so
    this must be supplied by the caller; when it is empty or no stored claim
    matches a gold entry, agreement is `None` rather than a number computed
    over nothing.

    Matching is exact-after-normalisation (via `match_claims_to_gold`), so a
    claim that merely resembles a gold entry is left unlabelled and excluded
    from `accuracy`. This keeps agreement from being inflated by loose
    pairing.
    """
    if not gold_by_question:
        return None

    predicted: list[str] = []
    gold: list[str] = []
    rows = (
        session.query(EvalResult)
        .filter(
            EvalResult.eval_run_id == eval_run_id,
            EvalResult.system == SYSTEM_VERIFIED,
        )
        .all()
    )
    for row in rows:
        claims = (
            session.query(VerifClaim)
            .filter(VerifClaim.eval_result_id == row.id)
            .order_by(VerifClaim.claim_index)
            .all()
        )
        gold_entries = gold_by_question.get(row.question, ())
        # Align stored judge labels to gold by claim text. Unmatched claims
        # get "" so `judge_agreement` counts them as unlabelled, not wrong.
        gold_labels = match_claims_to_gold(
            [c.claim_text for c in claims], gold_entries
        )
        for claim, matched_gold in zip(claims, gold_labels):
            predicted.append(claim.label)
            gold.append(matched_gold or "")

    if not predicted:
        return None
    return judge_agreement(predicted, gold)
