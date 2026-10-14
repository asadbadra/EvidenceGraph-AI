"""Tests for the Verified RAG pipeline and `verify` CLI (Phase 2, Stage 2.4).

Offline: scripted LLM output, a fake retriever, and a temporary SQLite file.
No live API calls.

SCOPE NOTE: these tests establish two things and no more --
1. FAIRNESS: `VerifiedRAG` and `BaselineRAG` produce the same answer text for
   the same question, retriever, and generation responses.
2. MECHANICS: the verification pass extracts claims, links candidates, judges
   them, and keeps every evidence id inside the candidate set / real records.

They do NOT show the verified pipeline answers better than the baseline. That
is the empirical question for Stage 2.6 and is not settled here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Chunk
from app.pipelines.baseline import BaselineRAG
from app.retrieval.retriever import Retriever
from app.schemas import RetrievedChunk
from app.verification.judge import RuleBasedJudge
from app.verification.pipeline import (
    VerifiedAnswerResult,
    VerifiedRAG,
    make_chunk_exists,
)
from app.verification.verdicts import ClaimVerdict

ANSWER = "Apache Log4j2 2.14.1 allows remote code execution [1]."

SUPPORTING_TEXT = (
    "Apache Log4j2 2.14.1 allows remote code execution in the log message "
    "lookup feature."
)


# --------------------------------------------------------------------------
# Test doubles
# --------------------------------------------------------------------------


class ScriptedLLM:
    """Queue-based LLM double. Lives here so `app/llm/` stays untouched."""

    def __init__(self, responses: list[str]) -> None:
        self.model = "scripted"
        self._responses = list(responses)
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts_seen.append(prompt)
        if not self._responses:
            raise AssertionError("scripted LLM exhausted")
        return self._responses.pop(0)


class FakeRetriever:
    """Stands in for `Retriever`."""

    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self.chunks = chunks or []
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, *, top_k: int = 4) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        return self.chunks[:top_k]


def _chunk(chunk_id: int, *, text: str = SUPPORTING_TEXT) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=chunk_id * 10,
        external_id="CVE-2021-44228",
        title=f"T{chunk_id}",
        source_url=f"https://example.invalid/{chunk_id}",
        published_at="2021-12-10",
        text=text,
        score=2.5,
    )


def _judge_json(label: str, ids: list[int], rationale: str = "r") -> str:
    return json.dumps({"label": label, "evidence_chunk_ids": ids, "rationale": rationale})


# --------------------------------------------------------------------------
# Fairness: same generation path as the baseline
# --------------------------------------------------------------------------


def test_verified_pipeline_returns_the_same_answer_text_as_baseline() -> None:
    chunks = [_chunk(101)]
    baseline = BaselineRAG(
        FakeRetriever(chunks), ScriptedLLM([ANSWER]), top_k=4
    )
    verified = VerifiedRAG(
        FakeRetriever(chunks),
        ScriptedLLM([ANSWER, _judge_json("supported", [101])]),
        top_k=4,
    )

    assert baseline.run("What is CVE-2021-44228?").answer_text == verified.run(
        "What is CVE-2021-44228?"
    ).answer_text


def test_verified_pipeline_does_not_revise_the_answer() -> None:
    """Verification reports alongside; it never edits what was generated."""
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER, _judge_json("contradicted", [101])]),
    ).run("q")
    assert result.answer_text == ANSWER


def test_verified_pipeline_uses_the_same_prompt_as_baseline() -> None:
    """Both pipelines send an identical generation prompt for the same input."""
    chunks = [_chunk(101)]
    baseline_llm = ScriptedLLM([ANSWER])
    verified_llm = ScriptedLLM([ANSWER, _judge_json("supported", [101])])

    BaselineRAG(FakeRetriever(chunks), baseline_llm).run("What is CVE-2021-44228?")
    VerifiedRAG(FakeRetriever(chunks), verified_llm).run("What is CVE-2021-44228?")

    # Baseline sends exactly one prompt; the verified pipeline's first is the
    # same generation prompt, and the second is the judge's NLI prompt.
    assert len(baseline_llm.prompts_seen) == 1
    assert verified_llm.prompts_seen[0] == baseline_llm.prompts_seen[0]
    assert verified_llm.prompts_seen[1] != baseline_llm.prompts_seen[0]


def test_same_generation_prompt_by_construction() -> None:
    """Both pipelines call `build_baseline_prompt` -- verified by import."""
    import inspect

    from app.llm.prompts import build_baseline_prompt
    from app.pipelines import baseline as baseline_module
    from app.verification import pipeline as verified_module

    assert "build_baseline_prompt" in inspect.getsource(baseline_module)
    assert "build_baseline_prompt" in inspect.getsource(verified_module)
    assert verified_module.build_baseline_prompt is baseline_module.build_baseline_prompt is build_baseline_prompt


def test_generation_retrieval_is_passed_through_unchanged() -> None:
    retriever = FakeRetriever([_chunk(101)])
    result = VerifiedRAG(
        retriever, ScriptedLLM([ANSWER, _judge_json("supported", [101])]), top_k=3
    ).run("q")
    assert retriever.calls[0] == ("q", 3)
    assert [c.chunk_id for c in result.retrieved] == [101]


# --------------------------------------------------------------------------
# Result shape and the check-performed flag
# --------------------------------------------------------------------------


def test_result_records_that_the_check_was_performed() -> None:
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER, _judge_json("supported", [101])]),
    ).run("q")
    assert result.unsupported_citation_check_performed is True


def test_result_is_a_verified_answer_result() -> None:
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER, _judge_json("supported", [101])]),
    ).run("q")
    assert isinstance(result, VerifiedAnswerResult)
    assert result.question == "q"
    assert result.model == "scripted"


def test_one_verdict_per_extracted_claim() -> None:
    answer = "Log4j2 allows remote code execution [1]. Something else happened [2]."
    result = VerifiedRAG(
        FakeRetriever([_chunk(101), _chunk(202)]),
        ScriptedLLM(
            [
                answer,
                _judge_json("supported", [101]),
                _judge_json("supported", [202]),
            ]
        ),
    ).run("q")
    assert len(result.verdicts) == len(result.extraction.claims) == 2


def test_answer_with_no_claims_yields_no_verdicts() -> None:
    answer = "Insufficient evidence in the retrieved passages."
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]), ScriptedLLM([answer])
    ).run("q")
    assert result.verdicts == ()
    assert result.summary.total == 0


def test_summary_counts_match_verdicts() -> None:
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM(
            [
                ANSWER,
                _judge_json("supported", [101]),
            ]
        ),
    ).run("q")
    assert result.summary.supported == 1
    assert result.summary.total == len(result.verdicts)


def test_unsupported_claims_lists_everything_not_supported() -> None:
    answer = "Log4j2 allows RCE [1]. FortiOS has traversal [2]."
    result = VerifiedRAG(
        FakeRetriever([_chunk(101), _chunk(202)]),
        ScriptedLLM(
            [
                answer,
                _judge_json("supported", [101]),
                _judge_json("insufficient_evidence", []),
            ]
        ),
    ).run("q")
    assert len(result.unsupported_claims) == 1
    assert result.unsupported_claims[0].label is ClaimVerdict.INSUFFICIENT_EVIDENCE


def test_evidence_sets_are_retained_for_inspection() -> None:
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER, _judge_json("supported", [101])]),
    ).run("q")
    assert len(result.evidence_sets) == len(result.verdicts)
    assert result.evidence_sets[0].chunk_ids == (101,)


# --------------------------------------------------------------------------
# Verification is post-generation and claim-level
# --------------------------------------------------------------------------


def test_verdicts_come_from_claim_level_retrieval_not_just_cited() -> None:
    """Independently retrieved evidence reaches the judge too."""
    retriever = FakeRetriever([_chunk(101), _chunk(505)])
    result = VerifiedRAG(
        retriever,
        ScriptedLLM([ANSWER, _judge_json("supported", [505])]),
        claim_retrieval_top_k=2,
    ).run("q")

    # One call for the question, one per claim for re-retrieval -- and the
    # re-retrieval queries the CLAIM text, not the whole answer.
    assert retriever.calls[0][0] == "q"
    assert retriever.calls[1][0] == result.verdicts[0].claim.text
    assert result.evidence_sets[0].chunk_ids == (101, 505)


def test_judge_never_receives_the_generated_answer() -> None:
    llm = ScriptedLLM([ANSWER, _judge_json("supported", [101])])
    result = VerifiedRAG(FakeRetriever([_chunk(101)]), llm).run("q")

    # The generation prompt cannot contain the answer: it does not exist yet.
    # The judge prompt is the one that must not inherit the model's framing.
    generation_prompt, judge_prompt = llm.prompts_seen[0], llm.prompts_seen[1]
    assert "research question" in generation_prompt.lower()
    assert result.answer_text not in generation_prompt
    assert result.answer_text not in judge_prompt
    assert judge_prompt != generation_prompt


def test_default_judge_is_the_llm_judge() -> None:
    from app.verification.judge import LLMJudge

    pipeline = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER, _judge_json("supported", [101])]),
    )
    assert isinstance(pipeline._judge, LLMJudge)


def test_injected_rule_judge_is_used() -> None:
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER]),
        judge=RuleBasedJudge(),
    ).run("q")
    # The rule judge never calls the LLM, so only the generation prompt exists.
    assert len(result.verdicts) == len(result.extraction.claims)


# --------------------------------------------------------------------------
# No-fabrication invariant enforced end to end
# --------------------------------------------------------------------------


def test_malformed_judge_output_never_produces_supported() -> None:
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER, "not json at all"]),
    ).run("q")
    assert all(v.label is not ClaimVerdict.SUPPORTED for v in result.verdicts)


def test_judge_ids_outside_candidates_are_dropped_end_to_end() -> None:
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER, _judge_json("supported", [101, 999])]),
    ).run("q")
    assert result.verdicts[0].evidence_chunk_ids == (101,)


def test_rule_judge_cannot_cite_a_chunk_it_was_not_shown() -> None:
    """Rule judge is constrained by the same candidate set."""
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER]),
        judge=RuleBasedJudge(),
    ).run("q")
    for verdict in result.verdicts:
        assert set(verdict.evidence_chunk_ids) <= {101}


# --------------------------------------------------------------------------
# `make_chunk_exists`: candidate ids must be real database records
# --------------------------------------------------------------------------


def test_chunk_exists_accepts_a_stored_chunk(populated_session: Session) -> None:
    from sqlalchemy import select

    real_id = populated_session.scalar(select(Chunk.id).limit(1))
    assert real_id is not None
    assert make_chunk_exists(populated_session)(real_id) is True


def test_chunk_exists_rejects_an_unstored_id(populated_session: Session) -> None:
    assert make_chunk_exists(populated_session)(999999) is False


def test_chunk_exists_is_case_consistent_on_repeated_calls(populated_session: Session) -> None:
    predicate = make_chunk_exists(populated_session)
    assert predicate(999999) is False
    assert predicate(999999) is False


def test_pipeline_drops_candidates_missing_from_the_database() -> None:
    """A judge citing a chunk that is not a real record cannot survive."""
    predicate = make_chunk_exists(_session_without(101))
    result = VerifiedRAG(
        FakeRetriever([_chunk(101)]),
        ScriptedLLM([ANSWER, _judge_json("supported", [101])]),
        chunk_is_known=predicate,
    ).run("q")
    # 101 is not in that database, so it is rejected as a candidate.
    assert result.evidence_sets[0].chunk_ids == ()
    assert result.evidence_sets[0].rejected_chunk_ids == (101,)


def _session_without(*_absent_ids: int):
    """An empty in-memory DB: a `chunk_is_known` that rejects every id.

    The arguments are ignored on purpose -- the point is that no chunk row
    exists, so any candidate the pipeline tries to keep is not a real record.
    """
    from app.db import init_db, make_engine, make_session_factory

    engine = make_engine("sqlite://")  # in-memory
    init_db(engine)
    return make_session_factory(engine)()


def test_pipeline_keeps_candidates_that_are_real_records(populated_session: Session) -> None:
    from sqlalchemy import select

    real_id = populated_session.scalar(select(Chunk.id).limit(1))
    assert real_id is not None
    chunk = _chunk(int(real_id))
    result = VerifiedRAG(
        FakeRetriever([chunk]),
        ScriptedLLM([ANSWER, _judge_json("supported", [real_id])]),
        chunk_is_known=make_chunk_exists(populated_session),
    ).run("q")
    assert result.evidence_sets[0].chunk_ids == (int(real_id),)


# --------------------------------------------------------------------------
# CLI: `verify` subcommand
# --------------------------------------------------------------------------


@pytest.fixture()
def settings_with_corpus(tmp_path: Path) -> Settings:
    """A settings object pointing at a temp DB, corpus already ingested."""
    from tests.conftest import FIXTURE

    from app.db import init_db, make_engine, make_session_factory
    from app.ingestion.loader import load_advisories

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'cli.db'}", llm_provider="mock"
    )
    engine = make_engine(settings.database_url)
    init_db(engine)
    session = make_session_factory(engine)()
    load_advisories(session, FIXTURE)
    session.commit()
    session.close()
    return settings


def test_cli_verify_is_registered() -> None:
    from app.cli import build_parser

    args = build_parser().parse_args(["verify", "What is CVE-2021-44228?"])
    assert args.func.__name__ == "cmd_verify"
    assert args.judge == "llm"


def test_cli_verify_accepts_rules_judge() -> None:
    from app.cli import build_parser

    args = build_parser().parse_args(["verify", "q", "--judge", "rules"])
    assert args.judge == "rules"


def test_cli_verify_runs_offline_with_rules_judge(
    settings_with_corpus: Settings, capsys
) -> None:
    from app.cli import cmd_verify

    code = cmd_verify(settings_with_corpus, _verify_args("What is CVE-2021-44228?"))
    assert code == 0
    out = capsys.readouterr().out
    assert "Claim-level verification:" in out
    assert "Summary:" in out


def test_cli_verify_reports_empty_corpus(tmp_path: Path, capsys) -> None:
    from app.cli import cmd_verify

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'empty.db'}")
    code = cmd_verify(settings, _verify_args("q"))
    assert code == 1
    assert "ingest" in capsys.readouterr().err


def _verify_args(question: str, judge: str = "rules"):
    from app.cli import build_parser

    return build_parser().parse_args(["verify", question, "--judge", judge])
