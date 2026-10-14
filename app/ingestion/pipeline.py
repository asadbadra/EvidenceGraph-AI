"""Ingestion pipeline: fetch -> parse -> validate -> persist, with auditing.

This is the only module that talks to BOTH the network layer and the
database layer, and it keeps them apart from each other:

    fetchers.py   network only   -> decoded JSON payload (no parsing)
    parsers.py    pure functions -> ParseResult of AdvisoryRecords (no I/O)
    THIS FILE     orchestration  -> validated Documents/Chunks + IngestRun rows

Neither `fetchers.py` nor `parsers.py` imports this module or the ORM, so
the pure parsing tests stay network- and database-free.

Provenance and honesty rules enforced here:

- Every HTTP fetch attempt writes exactly one `IngestRun` row, including
  attempts that failed. A run that never reached the network logs
  `http_status=None` and the error text; nothing is invented.
- `content_sha256` is a SHA-256 over the *canonicalised decoded JSON*, not
  the raw bytes on the wire (the fetch layer hands us decoded JSON). It
  still identifies the exact payload version a report was built from.
- `documents.published_at` is copied verbatim from the source record. An
  empty source date stays empty; we never substitute today's date.
- Re-running the same records is an UPSERT on the DB-enforced unique key
  `(source_id, external_id)`: existing rows are updated in place, keeping
  their original `id` so citations pointing at them stay stable. Document
  IDs are never recycled, and no duplicate rows are created.
- Bundled fixtures are a separate, explicitly-labeled entry point
  (`app.ingestion.loader`) and are never recorded as a live fetch.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import Chunk, Document, IngestRun, Source, SyncState
from app.ingestion.chunking import chunk_text
from app.ingestion.http_client import HttpError
from app.ingestion.models import AdvisoryRecord
from app.ingestion.parsers import (
    KEV_FEED_URL,
    KEV_SOURCE_NAME,
    NVD_API_URL,
    NVD_SOURCE_NAME,
    ParseError,
    ParseResult,
    parse_kev,
    parse_nvd,
)

# NVD's published constraint on any date-range query (verified against
# https://nvd.nist.gov/developers/vulnerabilities).
NVD_MAX_RANGE_DAYS = 120

# NVD paginates every CVE response. 2,000 is both the documented default and
# the documented maximum for `resultsPerPage`, so it is the fewest-requests
# choice for bulk pulls.
NVD_PAGE_SIZE = 2000

# Hard stop on the pagination loop. A well-behaved server ends the loop long
# before this via `totalResults`; the cap exists so a server that ignores
# `startIndex` cannot spin us forever on a repeated page.
NVD_MAX_PAGES = 100


class IngestError(RuntimeError):
    """An ingest request could not be carried out (misuse or total failure)."""


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class IngestReport:
    """Summary of one ingest operation (possibly several fetch attempts)."""

    source_name: str
    records_fetched: int = 0
    records_parsed: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0  # parser rejected (structural problem in payload)
    records_failed: int = 0   # parsed but failed our validation; not written
    chunks: int = 0
    run_ids: tuple[int, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def records_written(self) -> int:
        return self.records_inserted + self.records_updated

    @property
    def status(self) -> str:
        if self.errors:
            return "partial" if self.records_written else "failed"
        return "success"

    def merged_with(self, other: "IngestReport") -> "IngestReport":
        """Combine two reports for the same logical ingest operation."""
        return IngestReport(
            source_name=self.source_name,
            records_fetched=self.records_fetched + other.records_fetched,
            records_parsed=self.records_parsed + other.records_parsed,
            records_inserted=self.records_inserted + other.records_inserted,
            records_updated=self.records_updated + other.records_updated,
            records_skipped=self.records_skipped + other.records_skipped,
            records_failed=self.records_failed + other.records_failed,
            chunks=self.chunks + other.chunks,
            run_ids=self.run_ids + other.run_ids,
            errors=self.errors + other.errors,
        )

    def summary(self) -> str:
        """One-line human-readable summary for the CLI."""
        parts = [
            f"{self.records_written} written "
            f"({self.records_inserted} new, {self.records_updated} updated)",
            f"{self.chunks} chunks",
        ]
        if self.records_skipped:
            parts.append(f"{self.records_skipped} skipped by parser")
        if self.records_failed:
            parts.append(f"{self.records_failed} failed validation")
        if self.errors:
            parts.append(f"status={self.status}")
        return f"[{self.source_name}] " + ", ".join(parts)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def payload_digest(payload: Any) -> str:
    """SHA-256 of the canonicalised decoded payload.

    Canonical = sorted keys, no insignificant whitespace, non-ASCII kept
    verbatim. Two payloads that decode to the same JSON structure produce
    the same digest regardless of key order or formatting on the wire.
    """
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_source(session: Session, name: str, url: str) -> Source:
    """Return the existing source row for `name`, creating it if absent.

    The URL of an existing row is left untouched: `sources.url` records the
    canonical feed location, and re-fetching must not rewrite history. This
    also means live KEV ingestion joins the same source row the fixture
    loader created, because `parsers.KEV_SOURCE_NAME` is byte-identical to
    the fixture's source name.
    """
    source = session.scalar(select(Source).where(Source.name == name))
    if source is None:
        source = Source(name=name, url=url or "")
        session.add(source)
        session.flush()
    return source


def _write_document(
    session: Session,
    source_id: int,
    record: AdvisoryRecord,
    *,
    chunk_max_chars: int,
    chunk_overlap_chars: int,
    existing: Document | None,
    ingest_run_id: int | None = None,
) -> tuple[str, int]:
    """Insert or update one record and its chunks. Returns (kind, chunk_count).

    `kind` is "inserted" or "updated". Chunks are always rebuilt from the
    current record text so a document can never carry stale passages that
    no longer match its metadata. `ingest_run_id` ties the row to the fetch
    that produced it; None means "no live fetch" (fixture or legacy import).
    """
    body = record.body_text()
    texts = chunk_text(
        body, max_chars=chunk_max_chars, overlap_chars=chunk_overlap_chars
    )

    if existing is None:
        document = Document(
            source_id=source_id,
            external_id=record.external_id,
            title=record.title,
            # Verbatim from the source; "" means the source gave no date.
            published_at=record.published_at,
            source_url=record.source_url,
            metadata_json=json.dumps(record.metadata, ensure_ascii=False),
            retrieved_at=_utcnow(),
            ingest_run_id=ingest_run_id,
        )
        session.add(document)
        session.flush()
        kind = "inserted"
    else:
        document = existing
        document.title = record.title
        document.published_at = record.published_at
        document.source_url = record.source_url
        document.metadata_json = json.dumps(record.metadata, ensure_ascii=False)
        document.retrieved_at = _utcnow()
        # Re-point at the fetch that last confirmed this record. Leaving the
        # original id would claim the row reflects a fetch it does not.
        document.ingest_run_id = ingest_run_id
        # Replace chunks so text and metadata cannot drift apart.
        session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        session.flush()
        kind = "updated"

    for position, text in enumerate(texts):
        session.add(
            Chunk(
                document_id=document.id,
                position=position,
                text=text,
                source_url=document.source_url,
            )
        )
    return kind, len(texts)


def _persist_records(
    session: Session,
    records: Sequence[AdvisoryRecord],
    *,
    source_name: str,
    source_url: str,
    chunk_max_chars: int,
    chunk_overlap_chars: int,
    ingest_run_id: int | None = None,
) -> tuple[int, int, int, int, tuple[str, ...]]:
    """Write validated records. Returns (inserted, updated, failed, chunks, errors).

    Runs inside the caller's transaction; does NOT commit. Validation happens
    here (not in the parser) because persistence is the last gate before data
    becomes citable: anything failing `validation_errors()` is counted and
    left unwritten rather than being coerced into shape.
    """
    source = _get_or_create_source(session, source_name, source_url)

    # Resolve existing rows once, up front: this is what makes re-ingestion
    # an update instead of an insert, and it is the only place the unique
    # index is relied upon for idempotency.
    existing_ids: dict[str, int] = {}
    if records:
        wanted = [r.external_id for r in records]
        existing_ids = dict(
            session.execute(
                select(Document.external_id, Document.id).where(
                    Document.source_id == source.id,
                    Document.external_id.in_(wanted),
                )
            ).all()
        )

    inserted = 0
    updated = 0
    failed = 0
    chunks = 0
    errors: list[str] = []

    for record in records:
        problems = record.validation_errors()
        if problems:
            failed += 1
            errors.append(f"{record.external_id or '<no id>'}: {'; '.join(problems)}")
            continue
        existing_id = existing_ids.get(record.external_id)
        existing = (
            session.get(Document, existing_id) if existing_id is not None else None
        )
        kind, chunk_count = _write_document(
            session,
            source.id,
            record,
            chunk_max_chars=chunk_max_chars,
            chunk_overlap_chars=chunk_overlap_chars,
            existing=existing,
            ingest_run_id=ingest_run_id,
        )
        if kind == "inserted":
            inserted += 1
        else:
            updated += 1
        chunks += chunk_count

    return inserted, updated, failed, chunks, tuple(errors)


def _log_run(
    session: Session,
    *,
    source_id: int | None,
    fetch_url: str,
    http_status: int | None,
    content_sha256: str | None,
    records_fetched: int,
    records_parsed: int,
    records_inserted: int,
    records_updated: int,
    records_skipped: int,
    records_failed: int,
    status: str,
    error_message: str | None,
) -> int:
    """Write one `ingest_runs` audit row and commit it.

    Committed in its own transaction on purpose: an audit row must survive
    even when the data transaction it describes was rolled back, otherwise
    a failed ingest would leave no trace at all.
    """
    run = IngestRun(
        source_id=source_id,
        fetch_url=fetch_url,
        retrieved_at=_utcnow(),
        http_status=http_status,
        content_sha256=content_sha256,
        records_fetched=records_fetched,
        records_parsed=records_parsed,
        records_inserted=records_inserted,
        records_updated=records_updated,
        records_skipped=records_skipped,
        records_failed=records_failed,
        status=status,
        error_message=error_message,
    )
    session.add(run)
    session.commit()
    return int(run.id)


def _source_id_by_name(session: Session, name: str) -> int | None:
    return session.scalar(select(Source.id).where(Source.name == name))


def _to_whole_second(dt: datetime) -> datetime:
    """Normalise to an aware UTC instant truncated to whole seconds.

    NVD's wire format pins the fraction to `.000`, so a sub-second watermark
    would claim precision the request never had. Truncating makes the stored
    watermark exactly the timestamp we queried with, which keeps the resume
    point honest.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def get_sync_watermark(session: Session, source_name: str) -> datetime | None:
    """Return the last-successful-sync watermark for `source_name`, or None.

    None means "never synced". That is deliberately distinct from a real
    timestamp: a sync needs a starting point, and there is none here.
    """
    source_id = _source_id_by_name(session, source_name)
    if source_id is None:
        return None
    state = session.get(SyncState, source_id)
    if state is None:
        return None
    return state.watermark_at


def _advance_watermark(
    session: Session,
    source_name: str,
    source_url: str,
    *,
    watermark_at: datetime,
    run_id: int | None,
) -> None:
    """Move the sync watermark forward for `source_name`, then commit.

    Called ONLY by a sync that ended `status == "success"`. Three deliberate
    properties:

    - **Monotonic.** It never moves backwards, so a retried older window or
      a clock that jumped backwards cannot lower the mark.
    - **Its own transaction, after the documents.** A crash in between
      leaves the watermark where it was, so the next sync re-covers a window
      we already ingested — harmless, because ingestion is an idempotent
      upsert. The reverse order would be unsafe: a crash after advancing but
      before writing would permanently skip a window.
    - **Traceable.** `last_run_id` names the ingest_runs row that earned the
      watermark, so the resume point is auditable like everything else.
    """
    watermark = _to_whole_second(watermark_at)
    source = _get_or_create_source(session, source_name, source_url)
    state = session.get(SyncState, source.id)
    if state is None:
        session.add(
            SyncState(
                source_id=source.id,
                watermark_at=watermark,
                updated_at=_utcnow(),
                last_run_id=run_id,
            )
        )
    elif state.watermark_at is None or watermark > state.watermark_at:
        state.watermark_at = watermark
        state.updated_at = _utcnow()
        state.last_run_id = run_id
    # else: a backwards or identical move is ignored, keeping the mark monotonic.
    session.commit()


# --------------------------------------------------------------------------
# Shared ingest-from-payload path
# --------------------------------------------------------------------------

def _ingest_payload(
    session: Session,
    payload: Any,
    *,
    parse,  # callable(payload) -> ParseResult
    source_name: str,
    source_url: str,
    fetch_url: str,
    chunk_max_chars: int,
    chunk_overlap_chars: int,
    limit: int | None,
) -> IngestReport:
    """Parse one payload, persist its records, and write the audit row.

    The HTTP fetch already succeeded by the time we get here, so a parse
    failure is logged as a `failed` run with `http_status=200` (we did get
    a body; it was not usable) and re-raised as `IngestError`.

    Ordering matters for traceability: the `ingest_runs` row is created and
    flushed BEFORE any document, so every document can carry the id of the
    fetch that produced it. The run row is not committed at that point —
    run row and documents commit together, so a database failure rolls back
    both and never leaves a dangling "success" row pointing at nothing.
    """
    try:
        result: ParseResult = parse(payload)
    except ParseError as exc:
        _log_run(
            session,
            source_id=_source_id_by_name(session, source_name),
            fetch_url=fetch_url,
            http_status=200,
            content_sha256=payload_digest(payload),
            records_fetched=0,
            records_parsed=0,
            records_inserted=0,
            records_updated=0,
            records_skipped=0,
            records_failed=0,
            status="failed",
            error_message=f"parse error: {exc}",
        )
        raise IngestError(f"{source_name}: payload could not be parsed: {exc}") from exc

    records = list(result.records)
    if limit is not None:
        # Applied before validation, so `--limit N` reliably means "at most N
        # of the source's records are considered", never more.
        records = records[:limit]

    digest = payload_digest(payload)
    skipped_errors = [
        f"record {s.index} ({s.identifier or 'no id'}): {s.reason}"
        for s in result.skipped
    ]

    # Placeholder row: gets its id now, finalized just before the commit.
    # "pending" is never visible in the database — it is overwritten in the
    # same transaction, so a reader only ever sees the final status.
    run = IngestRun(
        source_id=_source_id_by_name(session, source_name),
        fetch_url=fetch_url,
        retrieved_at=_utcnow(),
        http_status=200,
        content_sha256=digest,
        records_fetched=result.fetched,
        records_parsed=len(result.records),
        records_inserted=0,
        records_updated=0,
        records_skipped=len(result.skipped),
        records_failed=0,
        status="pending",
        error_message=None,
    )
    session.add(run)
    session.flush()
    run_id = int(run.id)

    try:
        inserted, updated, failed, chunks, errors = _persist_records(
            session,
            records,
            source_name=source_name,
            source_url=source_url,
            chunk_max_chars=chunk_max_chars,
            chunk_overlap_chars=chunk_overlap_chars,
            ingest_run_id=run_id,
        )
        all_errors = list(errors) + skipped_errors
        run.records_inserted = inserted
        run.records_updated = updated
        run.records_failed = failed
        run.status = "success" if not all_errors else "partial"
        run.error_message = "; ".join(all_errors)[:2000] or None
        session.commit()
    except Exception as exc:  # noqa: BLE001 - any DB error must not half-write
        session.rollback()  # takes the pending run row with it
        _log_run(
            session,
            source_id=_source_id_by_name(session, source_name),
            fetch_url=fetch_url,
            http_status=200,
            content_sha256=digest,
            records_fetched=result.fetched,
            records_parsed=len(result.records),
            records_inserted=0,
            records_updated=0,
            records_skipped=len(result.skipped),
            records_failed=0,
            status="failed",
            error_message=f"database error: {exc}",
        )
        raise IngestError(
            f"{source_name}: ingestion aborted, no records were written: {exc}"
        ) from exc

    return IngestReport(
        source_name=source_name,
        records_fetched=result.fetched,
        records_parsed=len(result.records),
        records_inserted=inserted,
        records_updated=updated,
        records_skipped=len(result.skipped),
        records_failed=failed,
        chunks=chunks,
        run_ids=(run_id,),
        errors=tuple(all_errors),
    )


def _audit_fetch_failure(
    session: Session,
    *,
    source_name: str,
    fetch_url: str,
    exc: Exception,
) -> int:
    """Record a fetch that never produced a usable payload, then re-raise path.

    `http_status` is taken from the typed HTTP error when available; a
    timeout or DNS failure genuinely has no status, so it stays NULL.
    """
    status_code: int | None = None
    if isinstance(exc, HttpError) and hasattr(exc, "status_code"):
        status_code = getattr(exc, "status_code")
    return _log_run(
        session,
        source_id=_source_id_by_name(session, source_name),
        fetch_url=fetch_url,
        http_status=status_code,
        content_sha256=None,
        records_fetched=0,
        records_parsed=0,
        records_inserted=0,
        records_updated=0,
        records_skipped=0,
        records_failed=0,
        status="failed",
        error_message=str(exc)[:2000],
    )


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------

def ingest_kev(
    session: Session,
    fetcher,
    *,
    chunk_max_chars: int = 900,
    chunk_overlap_chars: int = 150,
    limit: int | None = None,
) -> IngestReport:
    """Fetch the CISA KEV catalog and ingest it.

    `fetcher` is any object with `.fetch()` returning decoded JSON (see
    `app.ingestion.fetchers.KevFetcher`). Tests inject a fake here.
    """
    if limit is not None and limit <= 0:
        raise IngestError("limit must be a positive integer")

    try:
        payload = fetcher.fetch()
    except HttpError as exc:
        _audit_fetch_failure(
            session,
            source_name=KEV_SOURCE_NAME,
            fetch_url=getattr(fetcher, "feed_url", KEV_FEED_URL),
            exc=exc,
        )
        raise

    return _ingest_payload(
        session,
        payload,
        parse=parse_kev,
        source_name=KEV_SOURCE_NAME,
        source_url=KEV_FEED_URL,
        fetch_url=getattr(fetcher, "feed_url", KEV_FEED_URL),
        chunk_max_chars=chunk_max_chars,
        chunk_overlap_chars=chunk_overlap_chars,
        limit=limit,
    )


def ingest_nvd_cves(
    session: Session,
    fetcher,
    cve_ids: Sequence[str],
    *,
    chunk_max_chars: int = 900,
    chunk_overlap_chars: int = 150,
) -> IngestReport:
    """Fetch each CVE individually from NVD and ingest the results.

    NVD accepts at most one `cveId` per request, so N ids cost N requests
    (paced by `NvdFetcher`). Each request is its own transaction and its own
    audit row: if the third of five fetches fails, the first two are already
    committed and the report comes back `partial` rather than losing work.

    Raises the underlying error only if EVERY request failed.
    """
    if not cve_ids:
        raise IngestError("no CVE ids given for NVD ingest")

    api_url = getattr(fetcher, "api_url", NVD_API_URL)
    total = IngestReport(source_name=NVD_SOURCE_NAME)
    failures: list[str] = []

    for cve_id in cve_ids:
        try:
            payload = fetcher.fetch_cve(cve_id)
        except HttpError as exc:
            failures.append(f"{cve_id}: {exc}")
            _audit_fetch_failure(
                session,
                source_name=NVD_SOURCE_NAME,
                fetch_url=api_url,
                exc=exc,
            )
            continue
        except Exception as exc:  # e.g. FetchError for a malformed id
            failures.append(f"{cve_id}: {exc}")
            continue

        report = _ingest_payload(
            session,
            payload,
            parse=parse_nvd,
            source_name=NVD_SOURCE_NAME,
            source_url=api_url,
            fetch_url=api_url,
            chunk_max_chars=chunk_max_chars,
            chunk_overlap_chars=chunk_overlap_chars,
            limit=None,
        )
        total = total.merged_with(report)

    if failures and not total.records_written:
        raise IngestError(
            "NVD ingest failed for every requested CVE:\n  " + "\n  ".join(failures)
        )
    if failures:
        total = IngestReport(
            source_name=total.source_name,
            records_fetched=total.records_fetched,
            records_parsed=total.records_parsed,
            records_inserted=total.records_inserted,
            records_updated=total.records_updated,
            records_skipped=total.records_skipped,
            records_failed=total.records_failed,
            chunks=total.chunks,
            run_ids=total.run_ids,
            errors=total.errors + tuple(failures),
        )
    return total


def _nvd_window_params(since: datetime, until: datetime) -> dict[str, str]:
    """Build NVD `lastModStartDate`/`lastModEndDate` from aware UTC instants.

    NVD requires BOTH parameters and rejects ranges over 120 consecutive
    days, so those are checked here to produce a clear local error instead
    of an opaque remote one. Timestamps use extended ISO-8601 with a UTC
    zero offset, which is what the API documents.
    """
    if until < since:
        raise IngestError("--until must not be earlier than --since")
    if (until - since) > timedelta(days=NVD_MAX_RANGE_DAYS):
        span_days = math.ceil((until - since).total_seconds() / 86400)
        raise IngestError(
            f"NVD allows at most {NVD_MAX_RANGE_DAYS} consecutive days per "
            f"date-range query; this request spans {span_days} days"
        )
    return {
        "lastModStartDate": since.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "lastModEndDate": until.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }


def _as_utc_instant(value: date | datetime, *, end: bool) -> datetime:
    """Interpret `value` as an aware UTC instant.

    A `datetime` is used as the exact instant it names. A plain `date`
    expands to the whole UTC day: `end=False` gives 00:00:00 and `end=True`
    gives 23:59:59, which is what the CLI's `--since`/`--until` mean.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if end:
        return datetime(
            value.year, value.month, value.day, 23, 59, 59, tzinfo=timezone.utc
        )
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def nvd_modification_params(since: date, until: date) -> dict[str, str]:
    """Build NVD `lastModStartDate`/`lastModEndDate` params from calendar dates.

    Each date expands to its full UTC day, so `since`..`until` covers every
    instant of both end days.
    """
    return _nvd_window_params(
        _as_utc_instant(since, end=False), _as_utc_instant(until, end=True)
    )


def ingest_nvd_modifications(
    session: Session,
    fetcher,
    *,
    since: date | datetime,
    until: date | datetime,
    chunk_max_chars: int = 900,
    chunk_overlap_chars: int = 150,
    limit: int | None = None,
    page_size: int = NVD_PAGE_SIZE,
    max_pages: int = NVD_MAX_PAGES,
) -> IngestReport:
    """Fetch CVEs NVD reports as modified in [since, until] and ingest them.

    `since`/`until` accept either calendar dates or precise UTC instants. A
    date covers its whole day (what the CLI's `--since`/`--until` mean); an
    instant is used exactly (what a stored sync watermark needs, because
    day precision there would either re-fetch or skip an entire day).

    NVD paginates every response: a single request returns at most
    `resultsPerPage` records (max 2000) even when `totalResults` is larger.
    This walks the pages by advancing `startIndex` until the advertised
    total is covered, so a window matching 5,000 CVEs ingests all 5,000
    rather than silently keeping the first 2,000.

    Each page is its own transaction and its own audit row, so a failure
    on page 3 keeps pages 1-2 and reports `partial`. The loop always
    terminates: it stops at `totalResults`, when a page comes back empty,
    or at `max_pages` (a guard against a server that ignores `startIndex`
    and would otherwise spin forever on identical pages).

    This is the incremental path: re-running a window updates existing
    documents in place instead of duplicating them.

    On full success the sync watermark advances to the end of this window,
    so a later `--sync` can continue from it. Two guards keep that honest:

    - The watermark never moves backwards, so fetching a window that ends
      before the stored mark leaves it untouched.
    - `--limit` truncates the run before the window is covered, so a
      limited run never advances the watermark. Advancing would claim the
      rest of the window was seen when it was not.
    """
    if limit is not None and limit <= 0:
        raise IngestError("limit must be a positive integer")
    if page_size <= 0:
        raise IngestError("page_size must be a positive integer")

    api_url = getattr(fetcher, "api_url", NVD_API_URL)
    window_end = _as_utc_instant(until, end=True)
    base_params = _nvd_window_params(
        _as_utc_instant(since, end=False), window_end
    )

    total = IngestReport(source_name=NVD_SOURCE_NAME)
    remaining = limit  # None means "no cap"
    start_index = 0
    completed = False  # did we reach a legitimate stop condition?

    for page_no in range(1, max_pages + 1):
        if remaining is not None and remaining <= 0:
            completed = True
            break

        # Ask for only what we still need, so --limit does not pull whole
        # pages we would then throw away.
        this_page = page_size if remaining is None else min(page_size, remaining)
        params = dict(base_params)
        params["startIndex"] = str(start_index)
        params["resultsPerPage"] = str(this_page)

        try:
            payload = fetcher.fetch(params)
        except HttpError as exc:
            _audit_fetch_failure(
                session, source_name=NVD_SOURCE_NAME, fetch_url=api_url, exc=exc
            )
            if total.records_written:
                # Earlier pages are already committed; surface them as
                # partial rather than discarding finished work.
                return _with_failure(
                    total, f"page {page_no} (startIndex={start_index}): {exc}"
                )
            raise

        # NVD reports the full match count; trust it for the stop condition
        # but never let it force an unbounded loop.
        total_results = _total_results(payload)
        page_records = len(payload.get("vulnerabilities") or [])
        page_limit = page_records if remaining is None else min(page_records, remaining)

        report = _ingest_payload(
            session,
            payload,
            parse=parse_nvd,
            source_name=NVD_SOURCE_NAME,
            source_url=api_url,
            fetch_url=api_url,
            chunk_max_chars=chunk_max_chars,
            chunk_overlap_chars=chunk_overlap_chars,
            limit=page_limit,
        )
        total = total.merged_with(report)
        if remaining is not None:
            remaining -= report.records_written

        # Empty page: nothing more to read (also breaks a server that
        # ignores startIndex and would return the same page forever).
        if page_records == 0:
            completed = True
            break
        start_index += page_records
        if total_results is None:
            # No usable total: one page is all we can trust. Stopping is
            # honest; guessing at further pages is not.
            completed = True
            break
        if start_index >= total_results:
            completed = True
            break

    if not completed:
        # Exhausted max_pages without meeting a stop condition.
        total = _with_failure(
            total,
            f"stopped after {max_pages} pages (startIndex={start_index}); "
            "raise max_pages to continue",
        )

    if total.status == "success" and limit is None:
        _advance_watermark(
            session,
            NVD_SOURCE_NAME,
            api_url,
            watermark_at=window_end,
            run_id=total.run_ids[-1] if total.run_ids else None,
        )

    return total


# --------------------------------------------------------------------------
# Incremental synchronization (--sync)
# --------------------------------------------------------------------------

def ingest_kev_sync(
    session: Session,
    fetcher,
    *,
    chunk_max_chars: int = 900,
    chunk_overlap_chars: int = 150,
) -> IngestReport:
    """Re-fetch the whole KEV catalog and advance the watermark on success.

    The KEV catalog is one static snapshot with no server-side date filter,
    so "sync" cannot mean "fetch what changed". It means "fetch the catalog
    again and upsert it", which is idempotent: re-fetching updates rows in
    place and creates no duplicates.

    The watermark here therefore records *freshness* — when the catalog was
    last successfully read in full — not a resume point. It still advances
    only on a fully successful run, so `--sync` after a failure tells you the
    truth about how current your local copy is.
    """
    report = ingest_kev(
        session,
        fetcher,
        chunk_max_chars=chunk_max_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )
    if report.status == "success":
        _advance_watermark(
            session,
            KEV_SOURCE_NAME,
            KEV_FEED_URL,
            watermark_at=_utcnow(),
            run_id=report.run_ids[-1] if report.run_ids else None,
        )
    return report


def ingest_nvd_sync(
    session: Session,
    fetcher,
    *,
    until: datetime | None = None,
    chunk_max_chars: int = 900,
    chunk_overlap_chars: int = 150,
    page_size: int = NVD_PAGE_SIZE,
    max_pages: int = NVD_MAX_PAGES,
) -> IngestReport:
    """Fetch every CVE NVD modified since the stored watermark, then advance it.

    `lastModStartDate` is the stored watermark and `lastModEndDate` is now,
    which is exactly the incremental recipe NIST documents. Both ends are
    inclusive, so a record modified at the exact boundary is re-fetched on
    the next run. That is deliberate: the cost of a duplicate is zero
    (idempotent upsert) whereas the cost of a miss is a record permanently
    absent from an evidence corpus.

    The watermark advances ONLY when the run reports `success`:

    - **Not on `partial`.** NVD pages are ordered by publication date, not
      modification date, so after a failed page there is no safe point in
      the window to resume from. Advancing would silently and permanently
      skip the records on the pages that failed. Leaving it put means the
      next `--sync` re-covers the same window, which costs nothing.
    - **Not on `failed`.** Obviously nothing was covered.

    `--limit` is rejected rather than accepted-and-ignored: a limited run
    stops before covering the window, so advancing would skip the remainder.
    (The CLI enforces that; this function takes no `limit` at all.)

    An empty result DOES advance the watermark. "No CVEs changed in this
    window" is a successful, complete answer, and refusing to record it
    would leave the watermark stuck forever on a quiet source.
    """
    if (until is not None) and (until.tzinfo is None):
        until = until.replace(tzinfo=timezone.utc)

    watermark = get_sync_watermark(session, NVD_SOURCE_NAME)
    if watermark is None:
        raise IngestError(
            f"no sync watermark recorded for {NVD_SOURCE_NAME} yet; --sync has "
            "no starting point. Seed one with an explicit window first, e.g. "
            "`ingest --source nvd --since 2026-01-01 --until 2026-04-01`, then "
            "--sync can continue from it."
        )

    now = _to_whole_second(until) if until is not None else _to_whole_second(_utcnow())

    if now <= watermark:
        # Nothing new since the last successful sync. Skipping the fetch is
        # both correct and honest: no request was made, so no audit row is
        # written (there is no fetch attempt to audit), and the watermark is
        # left where it is.
        return IngestReport(source_name=NVD_SOURCE_NAME)

    if (now - watermark) > timedelta(days=NVD_MAX_RANGE_DAYS):
        raise IngestError(
            f"sync watermark is {math.ceil((now - watermark).total_seconds() / 86400)} "
            f"days old ({watermark.date()} -> {now.date()}), beyond NVD's "
            f"{NVD_MAX_RANGE_DAYS}-day per-query limit. Catch up with explicit "
            "--since/--until windows of at most 120 days until the watermark "
            "is recent, after which --sync will work again."
        )

    # The watermark advance happens inside ingest_nvd_modifications, on
    # full success only. Doing it here too would double-advance; keeping it
    # in one place keeps the rule easy to point at during review.
    return ingest_nvd_modifications(
        session,
        fetcher,
        since=watermark,
        until=now,
        chunk_max_chars=chunk_max_chars,
        chunk_overlap_chars=chunk_overlap_chars,
        page_size=page_size,
        max_pages=max_pages,
    )


def _total_results(payload: Any) -> int | None:
    """Return NVD's advertised total match count, or None if unusable."""
    if not isinstance(payload, dict):
        return None
    value = payload.get("totalResults")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _with_failure(report: IngestReport, message: str) -> IngestReport:
    """Return `report` with an extra failure message attached."""
    return IngestReport(
        source_name=report.source_name,
        records_fetched=report.records_fetched,
        records_parsed=report.records_parsed,
        records_inserted=report.records_inserted,
        records_updated=report.records_updated,
        records_skipped=report.records_skipped,
        records_failed=report.records_failed,
        chunks=report.chunks,
        run_ids=report.run_ids,
        errors=report.errors + (message,),
    )
