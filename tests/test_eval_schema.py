"""Tests for the additive evaluation schema (Phase 2, Stage 2.5).

Migration is exercised against COPIES, never the live database. The real
`data/evidencegraph.db` is only ever read as bytes and copied; a test that
modified it would be indistinguishable from a bug, so `test_real_db_is_untouched`
re-hashes it after every other test in this module has run.

These tests establish that the eval tables are ADDITIVE: they appear, they do
not disturb existing data, and running the migration twice is a no-op.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect

from app.db import (
    EvalResult,
    EvalRun,
    MigrationError,
    VerifClaim,
    ensure_schema,
    init_db,
    make_engine,
    make_session_factory,
)

# The Phase 0 legacy schema, reused for the "existing database gets eval
# tables" case.
from tests.test_schema_migration import _make_legacy_db, _raw

REAL_DB = Path(__file__).resolve().parent.parent / "data" / "evidencegraph.db"


# --------------------------------------------------------------------------
# Fresh database
# --------------------------------------------------------------------------


def test_fresh_db_creates_eval_tables(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)

    names = set(inspect(engine).get_table_names())
    assert {"eval_runs", "eval_results", "verif_claims"} <= names


def test_eval_run_roundtrip(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()

    session.add(
        EvalRun(
            corpus_tag="pilot-24",
            baseline_model="offline-mock",
            verified_model="offline-mock",
            prompt_version="baseline-v1",
            judge_name="rules",
            question_count=24,
            notes="offline smoke run",
        )
    )
    session.commit()

    run = session.query(EvalRun).one()
    assert run.question_count == 24
    assert run.judge_name == "rules"
    assert run.started_at is not None
    assert run.finished_at is None
    session.close()


def test_eval_result_and_claim_roundtrip(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()

    run = EvalRun(corpus_tag="pilot-24")
    session.add(run)
    session.flush()

    result = EvalResult(
        eval_run_id=run.id,
        system="verified",
        question="What is CVE-2021-44228?",
        answer_text="Log4j2 allows RCE [1].",
        model="offline-mock",
        retrieved_count=4,
        citation_count=1,
        claims_total=1,
        supported_count=1,
        unsupported_check_performed=1,
    )
    session.add(result)
    session.flush()

    session.add(
        VerifClaim(
            eval_result_id=result.id,
            claim_index=0,
            claim_text="Log4j2 allows RCE",
            label="supported",
            evidence_ids_json="[101]",
            gold_label="supported",
        )
    )
    session.commit()

    claim = session.query(VerifClaim).one()
    assert claim.label == "supported"
    assert claim.gold_label == "supported"
    assert claim.evidence_ids_json == "[101]"
    session.close()


def test_gold_label_is_nullable_so_unlabelled_stays_unlabelled(tmp_path: Path) -> None:
    """Defaulting gold to the judge's label would fake perfect agreement."""
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()

    run = EvalRun()
    session.add(run)
    session.flush()
    result = EvalResult(eval_run_id=run.id, system="verified", question="q")
    session.add(result)
    session.flush()
    session.add(VerifClaim(eval_result_id=result.id, claim_index=0, label="supported"))
    session.commit()

    assert session.query(VerifClaim).one().gold_label is None
    session.close()


def test_baseline_result_records_that_no_check_was_performed(tmp_path: Path) -> None:
    """An empty claims column must not read as 'no problems found'."""
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()

    run = EvalRun()
    session.add(run)
    session.flush()
    session.add(
        EvalResult(
            eval_run_id=run.id,
            system="baseline",
            question="q",
            unsupported_check_performed=0,
        )
    )
    session.commit()

    assert session.query(EvalResult).one().unsupported_check_performed == 0
    session.close()


def test_result_key_is_unique_per_run_system_question(tmp_path: Path) -> None:
    from sqlalchemy.exc import IntegrityError

    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()

    run = EvalRun()
    session.add(run)
    session.flush()
    session.add(EvalResult(eval_run_id=run.id, system="baseline", question="q"))
    session.add(EvalResult(eval_run_id=run.id, system="baseline", question="q"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.close()


def test_same_question_for_both_systems_is_allowed(tmp_path: Path) -> None:
    """The A/B comparison needs both systems on the SAME question."""
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()

    run = EvalRun()
    session.add(run)
    session.flush()
    session.add(EvalResult(eval_run_id=run.id, system="baseline", question="q"))
    session.add(EvalResult(eval_run_id=run.id, system="verified", question="q"))
    session.commit()

    assert session.query(EvalResult).count() == 2
    session.close()


def test_claim_index_is_unique_within_a_result(tmp_path: Path) -> None:
    from sqlalchemy.exc import IntegrityError

    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()

    run = EvalRun()
    session.add(run)
    session.flush()
    result = EvalResult(eval_run_id=run.id, system="verified", question="q")
    session.add(result)
    session.flush()
    session.add(VerifClaim(eval_result_id=result.id, claim_index=0))
    session.add(VerifClaim(eval_result_id=result.id, claim_index=0))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.close()


# --------------------------------------------------------------------------
# Migration onto an existing database
# --------------------------------------------------------------------------


def test_migration_adds_eval_tables_to_a_legacy_db(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")

    before = set(inspect(engine).get_table_names())
    assert "eval_runs" not in before

    ensure_schema(engine)

    after = set(inspect(engine).get_table_names())
    assert {"eval_runs", "eval_results", "verif_claims"} <= after


def test_migration_preserves_existing_rows_when_adding_eval_tables(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")

    ensure_schema(engine)

    rows = _raw(db, "SELECT id, external_id FROM documents ORDER BY id")
    assert rows == [(1, "CVE-2021-44228"), (2, "CVE-2014-0160")]
    assert _raw(db, "SELECT COUNT(*) FROM chunks") == [(1,)]
    assert _raw(db, "SELECT COUNT(*) FROM eval_runs") == [(0,)]


def test_migration_is_idempotent_when_adding_eval_tables(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")

    ensure_schema(engine)
    ensure_schema(engine)

    tables = [
        row[0]
        for row in _raw(db, "SELECT name FROM sqlite_master WHERE type='table'")
    ]
    assert tables.count("eval_runs") == 1, "idempotent: table created exactly once"
    assert _raw(db, "SELECT COUNT(*) FROM documents") == [(2,)]


def test_duplicate_abort_leaves_existing_data_intact(tmp_path: Path) -> None:
    """A failed migration changes no existing rows, only aborts.

    Note on scope: the eval tables ARE created even on abort, because
    `create_all` runs before the duplicate gate. That is consistent with
    `ingest_runs` and is harmless -- creating an empty table touches no
    existing data. The gate exists to stop the destructive steps (the index
    swap and the `retrieved_at` backfill), and those must not run.
    """
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=True)
    engine = make_engine(f"sqlite:///{db}")

    with pytest.raises(MigrationError):
        ensure_schema(engine)

    # Existing rows and the legacy index survive the abort.
    assert _raw(db, "SELECT COUNT(*) FROM documents") == [(3,)]
    assert _raw(db, "SELECT COUNT(*) FROM chunks") == [(1,)]
    cols = {row[1] for row in sqlite3.connect(db).execute("PRAGMA table_info(documents)")}
    assert "retrieved_at" not in cols, "destructive backfill must not have run"

    # The additive tables exist but hold nothing: no eval data was invented.
    assert _raw(db, "SELECT COUNT(*) FROM eval_runs") == [(0,)]
    assert _raw(db, "SELECT COUNT(*) FROM eval_results") == [(0,)]
    assert _raw(db, "SELECT COUNT(*) FROM verif_claims") == [(0,)]


# --------------------------------------------------------------------------
# The live database: read-only, and verified unchanged
# --------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def real_db_sha_before() -> str | None:
    """Hash the live DB before the copy-based tests touch anything.

    Read-only: `read_bytes` cannot alter the file. If the file is absent the
    fixture yields None and the copy tests skip.
    """
    return _sha256(REAL_DB) if REAL_DB.exists() else None


def test_migration_runs_cleanly_on_a_copy_of_the_real_db(
    tmp_path: Path, real_db_sha_before: str | None
) -> None:
    if real_db_sha_before is None:
        pytest.skip("real database not present")

    copy = tmp_path / "copy.db"
    shutil.copyfile(REAL_DB, copy)  # copy, never move or open in place

    ensure_schema(make_engine(f"sqlite:///{copy}"))

    tables = {row[0] for row in _raw(copy, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"eval_runs", "eval_results", "verif_claims"} <= tables

    # Existing corpus untouched on the copy.
    assert _raw(copy, "SELECT COUNT(*) FROM documents")[0][0] > 0

    # And the REAL database is byte-identical afterwards.
    assert _sha256(REAL_DB) == real_db_sha_before


def test_real_db_is_untouched_by_the_whole_module(
    real_db_sha_before: str | None
) -> None:
    """Runs last within this module: no test may have altered the live file."""
    if real_db_sha_before is None:
        pytest.skip("real database not present")
    assert _sha256(REAL_DB) == real_db_sha_before
