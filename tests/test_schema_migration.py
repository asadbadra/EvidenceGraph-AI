"""Tests for the Phase 1 schema migration (offline, no network).

The legacy fixture below reproduces EXACTLY the Phase 0 schema (as committed
in c49f970), so migration is tested against a faithful copy of an existing
database rather than an idealized one. Existing rows must survive untouched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db import (
    Document,
    IngestRun,
    MigrationError,
    Source,
    ensure_schema,
    init_db,
    make_engine,
    make_session_factory,
)

# Phase 0 schema, copied verbatim from the live database (see git commit c49f970).
LEGACY_SCHEMA_SQL = """
CREATE TABLE sources (
    id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    retrieved_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);
CREATE TABLE documents (
    id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    external_id VARCHAR(64) NOT NULL,
    title TEXT NOT NULL,
    published_at VARCHAR(32) NOT NULL,
    source_url TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(source_id) REFERENCES sources (id)
);
CREATE INDEX ix_documents_external_id ON documents (external_id);
CREATE TABLE chunks (
    id INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    source_url TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(document_id) REFERENCES documents (id)
);
"""

LEGACY_ROWS_SQL = """
INSERT INTO sources (id, name, url, retrieved_at) VALUES
 (1, 'CISA KEV', 'https://example.invalid/feed', '2026-10-13 00:00:00');
INSERT INTO documents
 (id, source_id, external_id, title, published_at, source_url, metadata_json)
 VALUES
 (1, 1, 'CVE-2021-44228', 'Apache Log4j2 RCE', '2021-12-10',
  'https://nvd.nist.gov/vuln/detail/CVE-2021-44228', '{}'),
 (2, 1, 'CVE-2014-0160', 'OpenSSL Info Disclosure', '2022-05-04',
  'https://nvd.nist.gov/vuln/detail/CVE-2014-0160', '{}'),
 (3, 1, 'CVE-2014-0160', 'OpenSSL duplicate row', '2022-05-04',
  'https://nvd.nist.gov/vuln/detail/CVE-2014-0160', '{}');
INSERT INTO chunks (id, document_id, position, text, source_url)
 VALUES (1, 1, 0, 'chunk text', 'https://nvd.nist.gov/vuln/detail/CVE-2021-44228');
"""


def _make_legacy_db(path: Path, *, with_duplicates: bool = True) -> None:
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA_SQL)
    if with_duplicates:
        con.executescript(LEGACY_ROWS_SQL)
    else:
        # 3 unique documents, no duplicates.
        con.executescript(LEGACY_ROWS_SQL)
        con.execute("DELETE FROM documents WHERE id = 3")
    con.commit()
    con.close()


def _raw(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def test_legacy_migration_preserves_rows_and_ids(tmp_path: Path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")

    ensure_schema(engine)

    rows = _raw(db, "SELECT id, external_id, title FROM documents ORDER BY id")
    assert rows == [
        (1, "CVE-2021-44228", "Apache Log4j2 RCE"),
        (2, "CVE-2014-0160", "OpenSSL Info Disclosure"),
    ]
    chunks = _raw(db, "SELECT COUNT(*) FROM chunks")
    assert chunks == [(1,)]


def test_migration_adds_and_backfills_retrieved_at(tmp_path: Path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")

    # Column must not exist before migration.
    cols_before = {row[1] for row in sqlite3.connect(db).execute(
        "PRAGMA table_info(documents)"
    )}
    assert "retrieved_at" not in cols_before

    ensure_schema(engine)

    cols_after = {row[1] for row in sqlite3.connect(db).execute(
        "PRAGMA table_info(documents)"
    )}
    assert "retrieved_at" in cols_after

    backfilled = _raw(db, "SELECT COUNT(*) FROM documents WHERE retrieved_at IS NULL")
    assert backfilled == [(0,)], "every legacy row must have retrieved_at backfilled"


def test_migration_replaces_legacy_index_with_unique(tmp_path: Path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")

    ensure_schema(engine)

    names = {row[0] for row in sqlite3.connect(db).execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    )}
    assert "ix_documents_external_id" not in names, "legacy index should be dropped"
    assert "uq_documents_source_external" in names


def test_migrated_unique_index_blocks_duplicates(tmp_path: Path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")
    ensure_schema(engine)

    con = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO documents (id, source_id, external_id, title, published_at,"
            " source_url, metadata_json, retrieved_at)"
            " VALUES (99, 1, 'CVE-2014-0160', 'dup', '2022-05-04', 'u', '{}',"
            " '2026-10-13 00:00:00')"
        )
    con.close()


def test_duplicate_records_abort_migration_without_changes(tmp_path: Path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=True)
    engine = make_engine(f"sqlite:///{db}")

    with pytest.raises(MigrationError) as excinfo:
        ensure_schema(engine)

    # Error must explain itself.
    assert "CVE-2014-0160" in str(excinfo.value)
    assert "No schema changes" in str(excinfo.value)

    # Nothing may have changed: rows intact, no new column, indexes untouched.
    count = _raw(db, "SELECT COUNT(*) FROM documents")[0][0]
    assert count == 3, "existing rows must not be deleted"
    cols = {row[1] for row in sqlite3.connect(db).execute(
        "PRAGMA table_info(documents)"
    )}
    assert "retrieved_at" not in cols, "structural change must not happen on abort"
    names = {row[0] for row in sqlite3.connect(db).execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    )}
    assert "ix_documents_external_id" in names, "legacy index must survive abort"


def test_retrieved_at_is_timezone_aware_on_read(tmp_path: Path):
    """Regression: SQLite drops offsets, so reads came back naive and arithmetic
    against aware datetimes raised TypeError."""
    from datetime import datetime, timezone

    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()
    session.add(Source(name="s", url="u"))
    session.commit()

    source = session.query(Source).one()
    assert source.retrieved_at.tzinfo is not None, "must read back tz-aware"
    assert source.retrieved_at.utcoffset().total_seconds() == 0, "must be UTC"
    # The operation that used to fail.
    age = datetime.now(timezone.utc) - source.retrieved_at
    assert age.total_seconds() >= 0
    session.close()


def test_utc_datetime_on_migrated_legacy_rows(tmp_path: Path):
    """Legacy rows (written before this fix) must also read back as aware UTC."""
    from datetime import datetime, timezone

    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")
    ensure_schema(engine)

    session = make_session_factory(engine)()
    for doc in session.query(Document).all():
        assert doc.retrieved_at.tzinfo is not None
        _ = datetime.now(timezone.utc) - doc.retrieved_at
    session.close()


def test_ensure_schema_is_idempotent_on_legacy_db(tmp_path: Path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")

    ensure_schema(engine)
    ensure_schema(engine)  # second run: no error, no data change

    rows = _raw(db, "SELECT COUNT(*) FROM documents")[0][0]
    assert rows == 2


def test_fresh_db_gets_phase1_schema(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)

    inspector = inspect(engine)
    doc_cols = {c["name"] for c in inspector.get_columns("documents")}
    assert "retrieved_at" in doc_cols
    assert "ingest_runs" in inspector.get_table_names()
    unique_indexes = inspector.get_indexes("documents")
    assert any(
        ix.get("unique") and ix["name"] == "uq_documents_source_external"
        for ix in unique_indexes
    )


def test_orm_reads_and_writes_migrated_legacy_db(tmp_path: Path):
    """The ORM model must work against a migrated legacy database."""
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, with_duplicates=False)
    engine = make_engine(f"sqlite:///{db}")
    ensure_schema(engine)

    session = make_session_factory(engine)()
    docs = session.query(Document).order_by(Document.id).all()
    assert [d.external_id for d in docs] == ["CVE-2021-44228", "CVE-2014-0160"]
    assert all(d.retrieved_at is not None for d in docs)

    # ORM-level insert with the same key must violate uniqueness.
    session.add(
        Source(name="s", url="u"),
    )
    session.flush()
    session.add(
        Document(
            source_id=1,
            external_id="CVE-2014-0160",
            title="dup",
            published_at="2022-05-04",
            source_url="u",
            metadata_json="{}",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.close()


def test_ingest_runs_roundtrip(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()

    source = Source(name="CISA KEV", url="https://example.invalid/feed")
    session.add(source)
    session.flush()
    session.add(
        IngestRun(
            source_id=source.id,
            fetch_url="https://example.invalid/feed",
            http_status=200,
            content_sha256="a" * 64,
            records_fetched=5,
            records_parsed=5,
            records_inserted=5,
            status="success",
        )
    )
    session.commit()

    run = session.query(IngestRun).one()
    assert run.http_status == 200
    assert run.content_sha256 == "a" * 64
    assert run.records_inserted == 5
    assert run.status == "success"
    assert run.retrieved_at is not None
    assert run.error_message is None
    session.close()


def test_ingest_run_allows_null_source_and_failure_status(tmp_path: Path):
    """A failed fetch with no identified source must still be loggable."""
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    init_db(engine)
    session = make_session_factory(engine)()

    session.add(
        IngestRun(
            source_id=None,
            fetch_url="https://example.invalid/feed",
            status="failed",
            error_message="HTTP 503 after 3 attempts",
        )
    )
    session.commit()

    run = session.query(IngestRun).one()
    assert run.source_id is None
    assert run.status == "failed"
    assert run.error_message == "HTTP 503 after 3 attempts"
    assert run.records_fetched == 0
    session.close()
