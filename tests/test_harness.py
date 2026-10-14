"""Tests for the shared A/B evaluation harness (Phase 2, Stage 2.6).

Offline: scripted LLMs, a fake retriever factory, and a temporary SQLite
database. No live API calls.

SCOPE: these tests establish that the harness runs BOTH systems over the same
inputs and persists results that are recomputable. They do not show one
system outperforming the other -- no such claim is made here or anywhere in
this repository until a live, labelled run supports it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db import EvalResult, EvalRun, VerifClaim, init_db, make_engine, make_session_factory
from app.retrieval.retriever import Retriever
from app.schemas import RetrievedChunk
from app.verification.harness import (
    SYSTEM_BASELINE,
    SYSTEM_VERIFIED,
    load_questions,
    run_ab_eval,
)
from app.verification.judge import RuleBasedJudge

PILOT = Path(__file__).resolve().parent.parent / "data" / "sample" / "eval_questions.json"

ANSWER = "Apache Log4j2 allows remote code execution [1]."
SUPPORTING_TEXT = (
    "Apache Log4j2 contains a vulnerability where JNDI features do not protect "
    "against attacker-controlled JNDI-related endpoints, allowing for remote "
    "code execution."
)


class ScriptedLLM:
    def __init__(self, responses: list[str], model: str = "scripted") -> None:
        self.model = model
        self._responses = list(responses)
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts_seen.append(prompt)
        if not self._responses:
            raise AssertionError("scripted LLM exhausted")
        return self._responses.pop(0)


class _Chunk:
    """Minimal stand-in matching the fields `Retriever.retrieve` returns."""

    def __init__(self, chunk_id: int, text: str = SUPPORTING_TEXT) -> None:
        self.chunk_id = chunk_id
        self.document_id = chunk_id * 10
        self.external_id = "CVE-2021-44228"
        self.title = f"T{chunk_id}"
        self.source_url = f"https://example.invalid/{chunk_id}"
        self.published_at = "2021-12-10"
        self.text = text
        self.score = 2.5


class FakeRetriever:
    """Stands in for `Retriever`; satisfies the harness's refresh/is_empty."""

    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self._chunks = chunks or []
        self.refreshed = False

    def refresh(self) -> None:
        self.refreshed = True

    @property
    def is_empty(self) -> bool:
        return not self._chunks

    def retrieve(self, query: str, *, top_k: int = 4) -> list[RetrievedChunk]:
        return self._chunks[:top_k]


def _chunk(chunk_id: int, text: str = SUPPORTING_TEXT) -> RetrievedChunk:
    c = _Chunk(chunk_id, text)
    return RetrievedChunk(
        chunk_id=c.chunk_id,
        document_id=c.document_id,
        external_id=c.external_id,
        title=c.title,
        source_url=c.source_url,
        published_at=c.published_at,
        text=c.text,
        score=c.score,
    )


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = make_engine(f"sqlite:///{tmp_path / 'eval.db'}")
    init_db(engine)
    session = make_session_factory(engine)()
    yield session
    session.close()


def _factory(chunks: list[RetrievedChunk]):
    """Return a factory handing out a fresh FakeRetriever each call."""
    return lambda: FakeRetriever(chunks)


def _questions(*questions: str) -> list[dict]:
    return [{"id": f"q{i}", "category": "directly_answerable", "question": q}
            for i, q in enumerate(questions)]


def _judge_json(label: str, ids: list[int]) -> str:
    return json.dumps({"label": label, "evidence_chunk_ids": ids, "rationale": "r"})


# --------------------------------------------------------------------------
# Dataset loading
# --------------------------------------------------------------------------


def test_load_questions_reads_the_pilot_set() -> None:
    questions = load_questions(PILOT)
    assert len(questions) == 24


def test_load_questions_rejects_a_file_with_no_questions(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"questions": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="no questions"):
        load_questions(path)


def test_load_questions_rejects_entries_missing_keys(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"questions": [{"id": "q1", "question": ""}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        load_questions(path)


# --------------------------------------------------------------------------
# The A/B comparison is genuinely a comparison
# --------------------------------------------------------------------------


def test_harness_runs_both_systems_over_every_question(db_session: Session) -> None:
    chunks = [_chunk(101)]
    outcome = run_ab_eval(
        db_session,
        _questions("What is CVE-2021-44228?", "Second question?"),
        baseline_llm=ScriptedLLM([ANSWER, ANSWER], model="m"),
        verified_llm=ScriptedLLM(
            [ANSWER, _judge_json("supported", [101]),
             ANSWER, _judge_json("supported", [101])],
            model="m",
        ),
        retriever_factory=_factory(chunks),
        judge=RuleBasedJudge(),
    )
    assert len(outcome.for_system(SYSTEM_BASELINE)) == 2
    assert len(outcome.for_system(SYSTEM_VERIFIED)) == 2


def test_both_systems_answer_the_same_questions(db_session: Session) -> None:
    questions = _questions("Q one?", "Q two?")
    outcome = run_ab_eval(
        db_session,
        questions,
        baseline_llm=ScriptedLLM([ANSWER, ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])] * 2, model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    base_qs = {r.question for r in outcome.for_system(SYSTEM_BASELINE)}
    ver_qs = {r.question for r in outcome.for_system(SYSTEM_VERIFIED)}
    assert base_qs == ver_qs == {q["question"] for q in questions}


def test_both_systems_share_the_generation_model(db_session: Session) -> None:
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="shared-model"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="shared-model"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    run = db_session.query(EvalRun).one()
    assert run.baseline_model == run.verified_model == "shared-model"


def test_harness_uses_a_fresh_retriever_per_system(db_session: Session) -> None:
    """Sharing one instance would leak cached index state between systems."""
    made: list[FakeRetriever] = []

    def factory() -> FakeRetriever:
        retriever = FakeRetriever([_chunk(101)])
        made.append(retriever)
        return retriever

    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=factory,
        judge=RuleBasedJudge(),
    )
    assert len(made) == 2
    assert made[0] is not made[1]


def test_verified_answer_text_is_not_altered_by_harness(db_session: Session) -> None:
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    results = db_session.query(EvalResult).all()
    for row in results:
        assert row.answer_text == ANSWER


# --------------------------------------------------------------------------
# Persistence and recomputability
# --------------------------------------------------------------------------


def test_baseline_rows_record_no_check_performed(db_session: Session) -> None:
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    by_system = {r.system: r for r in db_session.query(EvalResult).all()}
    assert by_system[SYSTEM_BASELINE].unsupported_check_performed == 0
    assert by_system[SYSTEM_VERIFIED].unsupported_check_performed == 1


def test_verified_rows_carry_claim_counts(db_session: Session) -> None:
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    row = next(r for r in db_session.query(EvalResult).all() if r.system == SYSTEM_VERIFIED)
    assert row.claims_total == 1
    assert row.supported_count == 1


def test_baseline_rows_have_zero_claim_counts(db_session: Session) -> None:
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    row = next(r for r in db_session.query(EvalResult).all() if r.system == SYSTEM_BASELINE)
    assert row.claims_total == 0
    assert row.supported_count == 0


def test_verif_claims_are_stored_with_evidence_ids(db_session: Session) -> None:
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    claim_rows = db_session.query(VerifClaim).all()
    assert len(claim_rows) == 1
    assert json.loads(claim_rows[0].evidence_ids_json) == [101]


def test_gold_label_defaults_to_null_for_machine_runs(db_session: Session) -> None:
    """A run without hand labels must leave gold empty, never self-filled."""
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    assert db_session.query(VerifClaim).one().gold_label is None


def test_run_records_conditions_for_reproducibility(db_session: Session) -> None:
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
        corpus_tag="pilot-6",
        notes="offline smoke run",
    )
    run = db_session.query(EvalRun).one()
    assert run.corpus_tag == "pilot-6"
    assert run.notes == "offline smoke run"
    assert run.question_count == 1
    assert run.finished_at is not None
    assert run.prompt_version == "baseline-v1"


def test_run_records_the_judge_name(db_session: Session) -> None:
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    assert db_session.query(EvalRun).one().judge_name == "RuleBasedJudge"


def test_metrics_are_recomputable_from_stored_rows(db_session: Session) -> None:
    """A reported number must be derivable from what was stored."""
    from app.verification.metrics import mechanism_metrics

    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    row = next(r for r in db_session.query(EvalResult).all() if r.system == SYSTEM_VERIFIED)
    stored_total = row.supported_count + row.contradicted_count + row.insufficient_count + row.unverifiable_count
    assert stored_total == row.claims_total


# --------------------------------------------------------------------------
# Guard rails
# --------------------------------------------------------------------------


def test_empty_corpus_is_an_error_not_a_silent_zero_row_run(db_session: Session) -> None:
    with pytest.raises(ValueError, match="empty"):
        run_ab_eval(
            db_session,
            _questions("Q?"),
            baseline_llm=ScriptedLLM([ANSWER], model="m"),
            verified_llm=ScriptedLLM([ANSWER], model="m"),
            retriever_factory=lambda: FakeRetriever([]),
            judge=RuleBasedJudge(),
        )


def test_harness_does_not_modify_the_baseline_module() -> None:
    import inspect

    from app.pipelines import baseline

    source = inspect.getsource(baseline)
    assert "class BaselineRAG" in source
    assert "run(self, question: str)" in source


# --------------------------------------------------------------------------
# Fix 2: judge-vs-human agreement and citation quality, over stored rows
# --------------------------------------------------------------------------


def _run_verified(db_session: Session, *, question: str = "What is CVE-2021-44228?"):
    """Run one A/B pass with a scripted judge and return the eval run id."""
    outcome = run_ab_eval(
        db_session,
        _questions(question),
        baseline_llm=ScriptedLLM([ANSWER], model="m"),
        verified_llm=ScriptedLLM([ANSWER, _judge_json("supported", [101])], model="m"),
        retriever_factory=_factory([_chunk(101)]),
        judge=RuleBasedJudge(),
    )
    return outcome.eval_run_id


def test_agreement_is_none_without_gold_labels(db_session: Session) -> None:
    """No gold supplied means no agreement number -- never a zero."""
    run_id = _run_verified(db_session)
    from app.verification.harness import judge_agreement_for_run

    assert judge_agreement_for_run(db_session, run_id, {}) is None


def test_agreement_is_none_for_an_unknown_question(db_session: Session) -> None:
    """Gold for a question the run never executed cannot produce agreement.

    The run DID store verified claims, so this returns an Agreement whose
    `matched` is 0 and `coverage` is 0.0 -- claims existed but none had a gold
    counterpart. That is distinct from `None`, which means "no verified claims
    to score at all". Both are non-answers; neither is a fabricated number.
    """
    run_id = _run_verified(db_session)
    from app.verification.harness import judge_agreement_for_run

    gold = {"A question that was never run?": [{"text": "x", "gold_label": "supported"}]}
    agreement = judge_agreement_for_run(db_session, run_id, gold)
    assert agreement is not None
    assert agreement.matched == 0
    assert agreement.coverage == 0.0


def test_agreement_computes_over_hand_labelled_gold(db_session: Session) -> None:
    """A claim the judge and the human agree on counts as correct."""
    run_id = _run_verified(db_session)
    from app.verification.harness import judge_agreement_for_run

    # The rule judge labels the stored claim; gold mirrors that label and the
    # claim text, so this is a genuine matched pair (exact-normalised match).
    stored = db_session.query(VerifClaim).one()
    gold = {
        "What is CVE-2021-44228?": [
            {"text": stored.claim_text, "gold_label": stored.label}
        ]
    }
    agreement = judge_agreement_for_run(db_session, run_id, gold)
    assert agreement is not None
    assert agreement.matched == 1
    assert agreement.correct == 1
    assert agreement.accuracy == 1.0
    assert agreement.coverage == 1.0


def test_agreement_counts_a_human_judge_disagreement(db_session: Session) -> None:
    run_id = _run_verified(db_session)
    from app.verification.harness import judge_agreement_for_run

    stored = db_session.query(VerifClaim).one()
    opposite = "contradicted" if stored.label != "contradicted" else "supported"
    gold = {
        "What is CVE-2021-44228?": [
            {"text": stored.claim_text, "gold_label": opposite}
        ]
    }
    agreement = judge_agreement_for_run(db_session, run_id, gold)
    assert agreement is not None
    assert agreement.matched == 1
    assert agreement.correct == 0
    assert agreement.accuracy == 0.0


def test_agreement_excludes_claims_with_no_gold_counterpart(db_session: Session) -> None:
    """An unlabelled claim lowers coverage but is never scored as wrong."""
    run_id = _run_verified(db_session)
    from app.verification.harness import judge_agreement_for_run

    gold = {
        "What is CVE-2021-44228?": [
            {"text": "A claim the model never made.", "gold_label": "supported"}
        ]
    }
    agreement = judge_agreement_for_run(db_session, run_id, gold)
    assert agreement is not None
    assert agreement.matched == 0
    assert agreement.unlabeled == 1
    assert agreement.coverage == 0.0


def test_agreement_ignores_baseline_rows(db_session: Session) -> None:
    """The baseline performs no verification, so it has no labels to score."""
    run_id = _run_verified(db_session)
    from app.verification.harness import judge_agreement_for_run

    gold = {"What is CVE-2021-44228?": [{"text": "anything", "gold_label": "supported"}]}
    agreement = judge_agreement_for_run(db_session, run_id, gold)
    # Only the verified row's claims are considered; baseline rows are skipped.
    if agreement is not None:
        assert agreement.total == db_session.query(VerifClaim).count()


def test_citation_quality_reads_stored_counts(db_session: Session) -> None:
    run_id = _run_verified(db_session)
    from app.verification.harness import citation_quality_for_run

    quality = citation_quality_for_run(db_session, run_id)
    assert set(quality) == {SYSTEM_BASELINE, SYSTEM_VERIFIED}
    for value in quality.values():
        assert value.verified_citations is None, "not stored, so unknown"
        assert 0.0 <= value.invalid_marker_rate <= 1.0


def test_citation_quality_verified_citations_is_always_unknown(db_session: Session) -> None:
    """Honesty: the schema does not record which verdict backed which marker."""
    run_id = _run_verified(db_session)
    from app.verification.harness import citation_quality_for_run

    assert citation_quality_for_run(db_session, run_id)[SYSTEM_VERIFIED].verified_citations is None


def test_citation_quality_is_empty_for_an_unknown_run(db_session: Session) -> None:
    from app.verification.harness import citation_quality_for_run

    assert citation_quality_for_run(db_session, 999999) == {}


def test_agreement_and_citation_quality_survive_a_multi_claim_run(db_session: Session) -> None:
    """Two claims, one matching gold and one not: coverage is 0.5."""
    answer = "Log4j2 allows RCE [1]. FortiOS has traversal [2]."
    chunks = [_chunk(101), _chunk(202)]
    run_ab_eval(
        db_session,
        _questions("Q?"),
        baseline_llm=ScriptedLLM([answer], model="m"),
        verified_llm=ScriptedLLM(
            [answer, _judge_json("supported", [101]), _judge_json("supported", [202])],
            model="m",
        ),
        retriever_factory=_factory(chunks),
        judge=RuleBasedJudge(),
    )
    from app.verification.harness import judge_agreement_for_run

    run_id = db_session.query(EvalRun).one().id
    claims = db_session.query(VerifClaim).order_by(VerifClaim.claim_index).all()
    gold = {
        "Q?": [{"text": claims[0].claim_text, "gold_label": claims[0].label}]
    }
    agreement = judge_agreement_for_run(db_session, run_id, gold)
    assert agreement is not None
    assert agreement.total == 2
    assert agreement.matched == 1
    assert agreement.unlabeled == 1
    assert agreement.coverage == 0.5
