"""SQLite schema and migrations.

Phase 0 created sources / documents / chunks. Phase 1 adds, additively:
- documents.retrieved_at      -> when THIS tool ingested the record
- UNIQUE (source_id, external_id) -> duplicate prevention guaranteed by the DB
- ingest_runs                 -> one row per fetch attempt (reproducibility/audit)

`ensure_schema()` never rebuilds or deletes tables. It checks for existing
duplicate records BEFORE making any structural change; if duplicates would
break the unique index it raises MigrationError and leaves the database
untouched, so existing data is always protected.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    bindparam,
    create_engine,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


class MigrationError(RuntimeError):
    """Schema migration cannot proceed safely. The database is left unchanged."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC timestamps for SQLite.

    SQLite has no native aware-datetime type: SQLAlchemy writes the wall time
    and drops the offset, so reads come back naive and arithmetic against aware
    datetimes fails ("can't subtract offset-naive and offset-aware"). This
    decorator normalizes both directions: aware input is converted to UTC
    before storage, and naive stored values are labeled UTC on read (all rows
    in this database were written from UTC, so that label is truthful).
    No existing data needs rewriting.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Source(Base):
    """A public origin of documents (e.g. CISA KEV feed)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, nullable=False
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class Document(Base):
    """A single advisory record with metadata."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # When WE ingested this record (published_at is the source's own date).
    retrieved_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, nullable=False
    )
    # The ingest_runs row that wrote this document. NULL is honest for rows
    # that predate this column or came from a fixture load (which is not a
    # live fetch and is deliberately not audited as one).
    ingest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingest_runs.id"), nullable=True
    )

    # Idempotent ingestion is enforced by the database, not just by app logic.
    __table_args__ = (
        Index(
            "uq_documents_source_external",
            "source_id",
            "external_id",
            unique=True,
        ),
    )

    source: Mapped[Source] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """A retrievable passage with provenance back to its document."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")


class IngestRun(Base):
    """Audit record for one fetch attempt.

    Stores the fetch URL, timestamp, HTTP status, and a SHA-256 of the raw
    payload so a report can be traced back to the exact data version used.
    """

    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nullable: a run that failed before identifying a source is still logged.
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id"), nullable=True
    )
    fetch_url: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, nullable=False
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_parsed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyncState(Base):
    """Last-successful-synchronization watermark, one row per source.

    `watermark_at` is the high-water mark of data we have *fully* ingested:

    - For NVD it is the `lastModEndDate` covered by the last all-successful
      window, so the next sync can ask only for what changed since then.
    - For the CISA KEV catalog it is simply the time of the last successful
      full fetch. KEV is one static snapshot with no server-side date
      filter, so its watermark records freshness but cannot narrow a query.

    NULL means "never synced", which is distinct from a real timestamp.

    It advances ONLY on a fully successful run. A partial run must not move
    it: NVD returns records sorted by publication date, not modification
    date, so after a partial fetch there is no safe intermediate point to
    resume from — advancing would silently and permanently skip the records
    on the pages that failed. Not advancing means the next sync re-covers
    the same window, which is free because ingestion is idempotent.

    `last_run_id` names the ingest_runs row that earned the watermark, so
    the watermark is itself traceable to a specific audited fetch.
    """

    __tablename__ = "sync_state"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id"), primary_key=True
    )
    watermark_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, nullable=False
    )
    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingest_runs.id"), nullable=True
    )


class EvalRun(Base):
    """One A/B evaluation run: both systems over the same question set.

    Deliberately records the *conditions* rather than a verdict on them. The
    baseline and verified pipelines must share corpus, retriever, generation
    prompt, and model for the comparison to mean anything, so those are
    stored per run and can be checked rather than assumed.

    `notes` is free text for an operator to record that a run was, say, a
    smoke test rather than a reported result.
    """

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    corpus_tag: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    baseline_model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    verified_model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    judge_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class EvalResult(Base):
    """One system's output for one question within an `EvalRun`.

    Counts are denormalised on purpose: the point of storing them is that a
    reported metric can be recomputed from the row without replaying the
    pipeline, so a number in a writeup is traceable to stored data.

    `system` is "baseline" or "verified". The baseline row's claim counts
    are all zero and `unsupported_check_performed` is 0 -- it does not
    perform the check, and recording that explicitly prevents a later reader
    from misreading an empty column as "no problems found".
    """

    __tablename__ = "eval_results"
    __table_args__ = (
        UniqueConstraint("eval_run_id", "system", "question", name="uq_eval_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    eval_run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id"), nullable=False)
    system: Mapped[str] = mapped_column(String(16), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    retrieved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_marker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claims_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradicted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    insufficient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unverifiable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    with_anomalies: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_check_performed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )


class VerifClaim(Base):
    """One claim-level record within an `EvalResult`.

    This is where judge-vs-human agreement becomes computable: `label` is
    what the judge said, `gold_label` is what a person labelled, and both
    live on the same row so disagreement is a query rather than a guess.

    `gold_label` is nullable because the pilot set is labelled by hand and
    an unlabelled claim must stay unlabelled -- never defaulted to the
    judge's own output, which would make agreement look perfect by
    construction.
    """

    __tablename__ = "verif_claims"
    __table_args__ = (
        UniqueConstraint("eval_result_id", "claim_index", name="uq_verif_claim"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    eval_result_id: Mapped[int] = mapped_column(
        ForeignKey("eval_results.id"), nullable=False
    )
    claim_index: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    label: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    anomalies_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    gold_label: Mapped[str | None] = mapped_column(String(32), nullable=True)


# Name of the non-unique index created by Phase 0; replaced by the unique one.
_LEGACY_INDEX = "ix_documents_external_id"
_UNIQUE_INDEX = "uq_documents_source_external"


def _table_columns(conn, table: str) -> set[str]:
    """Return the set of column names for `table` via PRAGMA."""
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _index_names(conn) -> set[str]:
    rows = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()
    return {row[0] for row in rows}


def ensure_schema(engine: Engine) -> None:
    """Create missing tables and apply additive Phase 1 migrations.

    Order matters: the duplicate check runs BEFORE any structural change, so a
    failing migration never leaves the database half-modified or loses data.
    """
    # Creates sources/documents/chunks (if absent), ingest_runs (always new),
    # and the unique index when the documents table is created fresh.
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        # 1) Safety gate: refuse to proceed if duplicates exist.
        duplicates = conn.execute(
            text(
                "SELECT source_id, external_id, COUNT(*) AS c FROM documents "
                "GROUP BY source_id, external_id HAVING c > 1"
            )
        ).fetchall()
        if duplicates:
            sample = ", ".join(
                f"(source_id={row[0]}, external_id={row[1]})" for row in duplicates[:5]
            )
            raise MigrationError(
                f"Cannot enforce uniqueness: {len(duplicates)} duplicated "
                f"(source_id, external_id) group(s) found: {sample}. "
                "No schema changes were made and no data was modified. "
                "Inspect the database and resolve duplicates manually, or use a "
                "fresh database file."
            )

        # 2) Additive column for legacy databases (no-op on fresh ones).
        if "retrieved_at" not in _table_columns(conn, "documents"):
            conn.exec_driver_sql(
                "ALTER TABLE documents ADD COLUMN retrieved_at DATETIME"
            )
            # Backfill legacy rows with the migration time. Honest labeling: for
            # pre-Phase-1 rows this is an approximation of the original ingest
            # time, recorded at migration time rather than invented.
            conn.execute(
                text(
                    "UPDATE documents SET retrieved_at = :ts "
                    "WHERE retrieved_at IS NULL"
                ).bindparams(bindparam("ts", type_=UTCDateTime())),
                {"ts": _utcnow()},
            )

        # 3) Swap the non-unique Phase 0 index for the unique Phase 1 index.
        existing = _index_names(conn)
        if _LEGACY_INDEX in existing:
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {_LEGACY_INDEX}")
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            f"{_UNIQUE_INDEX} ON documents (source_id, external_id)"
        )

        # 4) Additive link from a document to the fetch that wrote it.
        #    Legacy rows are left NULL: we do not know which fetch wrote them,
        #    and inventing one would be a false provenance claim.
        if "ingest_run_id" not in _table_columns(conn, "documents"):
            conn.exec_driver_sql(
                "ALTER TABLE documents ADD COLUMN ingest_run_id INTEGER "
                "REFERENCES ingest_runs (id)"
            )


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine, creating parent directories for SQLite files."""
    if database_url.startswith("sqlite:///"):
        path = database_url.removeprefix("sqlite:///")
        if path and path != ":memory:":
            from pathlib import Path

            Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, echo=echo, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker bound to the given engine."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all tables and apply additive migrations (see ensure_schema)."""
    ensure_schema(engine)
