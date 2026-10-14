"""Tests for incremental synchronization (`--sync`) and per-source watermarks.

All offline: fetchers are fakes injected into the pipeline, so no test opens
a socket (the autouse guard in conftest.py would fail the test if one did).

The central invariant these tests defend:

    The sync watermark advances ONLY on a fully successful run, and never
    backwards.

Everything else follows from that. A partial run (page 3 of 5 failed) must
not advance, because NVD pages are ordered by publication date, not
modification date, so there is no safe intermediate point to resume from —
advancing would silently and permanently skip the records on the failed
pages. Because ingestion is an idempotent upsert, simply NOT advancing is
safe: the next `--sync` re-covers the same window for free. That is what
makes a failed sync retryable with zero data loss and no manual bookkeeping.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.db import (
    Document,
    IngestRun,
    Source,
    SyncState,
    ensure_schema,
    init_db,
    make_engine,
    make_session_factory,
)
from app.ingestion.http_client import HttpStatusError
from app.ingestion.parsers import KEV_FEED_URL, KEV_SOURCE_NAME, NVD_SOURCE_NAME
from app.ingestion.pipeline import (
    IngestError,
    _advance_watermark,
    get_sync_watermark,
    ingest_kev_sync,
    ingest_nvd_modifications,
    ingest_nvd_sync,
)

ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"


# --------------------------------------------------------------------------
# Synthetic payloads
# --------------------------------------------------------------------------

def _nvd_payload(cve_ids: list[str], *, total: int | None = None) -> dict[str, Any]:
    """Build an NVD 2.0 shaped payload containing exactly `cve_ids`."""
    return {
        "totalResults": len(cve_ids) if total is None else total,
        "vulnerabilities": [
            {
                "cve": {
                    "id": cve_id,
                    "published": "2026-01-01T00:00:00.000",
                    "lastModified": "2026-01-02T00:00:00.000",
                    "vulnStatus": "Analyzed",
                    "descriptions": [
                        {
                            "lang": "en",
                            "value": f"A test advisory describing {cve_id}.",
                        }
                    ],
                }
            }
            for cve_id in cve_ids
        ],
    }


def _kev_entry(cve_id: str, name: str = "Test vuln") -> dict[str, Any]:
    return {
        "cveID": cve_id,
        "vendorProject": "TestVendor",
        "product": "TestProduct",
        "vulnerabilityName": name,
        "dateAdded": "2026-01-01",
        "shortDescription": f"Short description of {cve_id}.",
        "requiredAction": "Apply updates.",
        "knownRansomwareCampaignUse": "Unknown",
        "notes": "https://nvd.nist.gov/vuln/detail/" + cve_id,
    }


def _kev_catalog(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"title": "Test KEV", "catalogVersion": "1", "vulnerabilities": entries}


# --------------------------------------------------------------------------
# Fake fetchers
# --------------------------------------------------------------------------

class FakeKevFetcher:
    """Stands in for KevFetcher. Returns `payload` or raises `error`."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload if payload is not None else _kev_catalog([])
        self.error = error
        self.calls = 0
        self.feed_url = (
            "https://www.cisa.gov/sites/default/files/feeds/"
            "known_exploited_vulnerabilities.json"
        )

    def fetch(self) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload


class ScriptedNvdFetcher:
    """Stands in for NvdFetcher: serves a list of CVE ids as NVD pages.

    Honours `startIndex`/`resultsPerPage` like the real API, and can be told
    to fail on the Nth call (1-based) to simulate a mid-pagination outage.
    """

    def __init__(
        self,
        cve_ids: list[str],
        *,
        fail_on_call: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self.cve_ids = list(cve_ids)
        self.fail_on_call = fail_on_call
        self.error = error or HttpStatusError(
            503, API_URL, "503 Service Unavailable: upstream timed out"
        )
        self.calls: list[dict[str, Any]] = []
        self.api_url = API_URL

    def fetch(self, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        self.calls.append(params)
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise self.error
        start = int(params.get("startIndex", 0))
        per_page = int(params.get("resultsPerPage", 2000))
        page = self.cve_ids[start : start + per_page]
        return _nvd_payload(page, total=len(self.cve_ids))


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

@pytest.fixture()
def session(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'sync.db'}")
    init_db(engine)
    sess = make_session_factory(engine)()
    yield sess
    sess.close()


def _document_ids(session) -> list[str]:
    from sqlalchemy import select

    return sorted(session.scalars(select(Document.external_id)).all())


def _seed_watermark(session, source_name: str, when: datetime) -> None:
    """Directly set a watermark, as if a prior successful sync had run."""
    _advance_watermark(
        session, source_name, KEV_FEED_URL, watermark_at=when, run_id=None
    )


# --------------------------------------------------------------------------
# Seeding: an explicit window establishes the watermark
# --------------------------------------------------------------------------

def test_explicit_window_seeds_watermark_on_success(session) -> None:
    """A successful explicit window sets the watermark to its end.

    This is what `--sync`'s error message tells the user to do first, so the
    behaviour must actually exist. Uses calendar dates, which is what the
    CLI's `--since`/`--until` actually parse into.
    """
    fetcher = ScriptedNvdFetcher(["CVE-2026-0001"])
    report = ingest_nvd_modifications(
        session,
        fetcher,
        since=date(2026, 1, 1),
        until=date(2026, 2, 1),
    )

    assert report.status == "success"
    watermark = get_sync_watermark(session, NVD_SOURCE_NAME)
    assert watermark == datetime(2026, 2, 1, 23, 59, 59, tzinfo=timezone.utc)


def test_explicit_window_accepts_instant_precision(session) -> None:
    """A `datetime` bound is used exactly, not widened to its whole day.

    Day precision at the resume point would either re-fetch or skip an
    entire day on every sync, so the watermark must be able to hold the
    exact instant we queried with.
    """
    ingest_nvd_modifications(
        session,
        ScriptedNvdFetcher(["CVE-2026-0001"]),
        since=datetime(2026, 1, 1, 6, 30, tzinfo=timezone.utc),
        until=datetime(2026, 2, 1, 9, 15, 42, tzinfo=timezone.utc),
    )

    assert get_sync_watermark(session, NVD_SOURCE_NAME) == datetime(
        2026, 2, 1, 9, 15, 42, tzinfo=timezone.utc
    )


def test_sync_without_watermark_refuses_with_clear_error(session) -> None:
    """`--sync` on a never-synced source must refuse, not guess a start."""
    fetcher = ScriptedNvdFetcher(["CVE-2026-0001"])

    with pytest.raises(IngestError) as excinfo:
        ingest_nvd_sync(session, fetcher, until=datetime(2026, 3, 1, tzinfo=timezone.utc))

    assert "no sync watermark" in str(excinfo.value)
    assert "--since" in str(excinfo.value), "the error must say how to fix it"
    assert fetcher.calls == [], "refusing must not make a network request"
    assert get_sync_watermark(session, NVD_SOURCE_NAME) is None


# --------------------------------------------------------------------------
# The core rule: advance only on full success
# --------------------------------------------------------------------------

def test_successful_sync_advances_watermark(session) -> None:
    _seed_watermark(session, NVD_SOURCE_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))
    fetcher = ScriptedNvdFetcher(["CVE-2026-0002"])

    report = ingest_nvd_sync(
        session, fetcher, until=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    )

    assert report.status == "success"
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == datetime(
        2026, 1, 15, 12, 0, tzinfo=timezone.utc
    )


def test_sync_uses_watermark_as_window_start(session) -> None:
    """`lastModStartDate` must be the stored watermark, exactly."""
    _seed_watermark(session, NVD_SOURCE_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))
    fetcher = ScriptedNvdFetcher([])

    ingest_nvd_sync(
        session, fetcher, until=datetime(2026, 1, 20, tzinfo=timezone.utc)
    )

    params = fetcher.calls[0]
    assert params["lastModStartDate"] == "2026-01-01T00:00:00.000Z"
    assert params["lastModEndDate"] == "2026-01-20T00:00:00.000Z"


def test_failed_fetch_does_not_advance_watermark(session) -> None:
    """A run that never reached the data leaves the watermark untouched."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_watermark(session, NVD_SOURCE_NAME, start)
    fetcher = ScriptedNvdFetcher(
        ["CVE-2026-0003"],
        fail_on_call=1,
        error=HttpStatusError(503, API_URL, "503 Service Unavailable"),
    )

    with pytest.raises(HttpStatusError):
        ingest_nvd_sync(
            session, fetcher, until=datetime(2026, 2, 1, tzinfo=timezone.utc)
        )

    assert get_sync_watermark(session, NVD_SOURCE_NAME) == start


def test_partial_sync_does_not_advance_watermark(session) -> None:
    """Page 1 committed, page 2 failed -> the window is NOT marked covered."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_watermark(session, NVD_SOURCE_NAME, start)
    fetcher = ScriptedNvdFetcher(
        ["CVE-2026-0004", "CVE-2026-0005"], fail_on_call=2
    )

    report = ingest_nvd_sync(
        session,
        fetcher,
        until=datetime(2026, 2, 1, tzinfo=timezone.utc),
        page_size=1,
    )

    assert report.status == "partial", "a failed page must make the run partial"
    assert report.records_written == 1, "page 1's record is kept, not discarded"
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == start, (
        "advancing here would permanently skip the record on the failed page"
    )


def test_retry_after_partial_covers_same_window_then_advances(session) -> None:
    """The headline property: a failed sync is retryable with no data loss."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_watermark(session, NVD_SOURCE_NAME, start)
    until = datetime(2026, 2, 1, tzinfo=timezone.utc)

    # First attempt: page 2 dies.
    partial = ingest_nvd_sync(
        session,
        ScriptedNvdFetcher(["CVE-2026-0006", "CVE-2026-0007"], fail_on_call=2),
        until=until,
        page_size=1,
    )
    assert partial.status == "partial"
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == start

    # Retry: identical window, fully succeeds.
    fetcher = ScriptedNvdFetcher(["CVE-2026-0006", "CVE-2026-0007"])
    retry = ingest_nvd_sync(session, fetcher, until=until, page_size=1)

    assert retry.status == "success"
    assert fetcher.calls[0]["lastModStartDate"] == "2026-01-01T00:00:00.000Z", (
        "the retry must re-cover the whole window, not resume mid-way"
    )
    assert sorted(_document_ids(session)) == ["CVE-2026-0006", "CVE-2026-0007"]
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == until


def test_empty_result_still_advances_watermark(session) -> None:
    """"Nothing changed" is a complete answer, not a failure.

    If an empty window did not advance, a quiet source would leave the
    watermark stuck and the window would grow without bound.
    """
    _seed_watermark(session, NVD_SOURCE_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))
    fetcher = ScriptedNvdFetcher([])

    report = ingest_nvd_sync(
        session, fetcher, until=datetime(2026, 1, 10, tzinfo=timezone.utc)
    )

    assert report.status == "success"
    assert report.records_written == 0
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == datetime(
        2026, 1, 10, tzinfo=timezone.utc
    )


def test_sync_with_nothing_new_makes_no_request(session) -> None:
    """Re-running `--sync` immediately is a no-op, not a wasted request."""
    at = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    _seed_watermark(session, NVD_SOURCE_NAME, at)
    fetcher = ScriptedNvdFetcher(["CVE-2026-0008"])
    runs_before = session.query(IngestRun).count()

    report = ingest_nvd_sync(session, fetcher, until=at)

    assert report.status == "success"
    assert report.records_written == 0
    assert fetcher.calls == [], "nothing new means nothing to fetch"
    assert session.query(IngestRun).count() == runs_before, (
        "no fetch attempt -> no audit row; inventing one would be dishonest"
    )
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == at


# --------------------------------------------------------------------------
# Watermark is monotonic
# --------------------------------------------------------------------------

def test_watermark_never_moves_backwards(session) -> None:
    """A backwards clock or a retried older window cannot lower the mark."""
    high = datetime(2026, 3, 1, tzinfo=timezone.utc)
    _seed_watermark(session, NVD_SOURCE_NAME, high)

    _advance_watermark(
        session, NVD_SOURCE_NAME, API_URL, watermark_at=high - timedelta(days=5),
        run_id=None,
    )
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == high

    # An explicit window ending before the watermark must not lower it either.
    ingest_nvd_modifications(
        session,
        ScriptedNvdFetcher(["CVE-2026-0009"]),
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == high


def test_sync_ignores_sub_second_clock_creep(session) -> None:
    """Whole-second truncation keeps the stored mark equal to what we queried."""
    at = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)
    _seed_watermark(session, NVD_SOURCE_NAME, at)
    fetcher = ScriptedNvdFetcher([])

    # 400ms later: below the wire format's resolution, so nothing to do.
    ingest_nvd_sync(session, fetcher, until=at + timedelta(milliseconds=400))

    assert fetcher.calls == []
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == at


# --------------------------------------------------------------------------
# Stale watermarks
# --------------------------------------------------------------------------

def test_stale_watermark_is_refused_with_actionable_error(session) -> None:
    """Beyond NVD's 120-day limit we refuse rather than silently clamp.

    Clamping would drop every record older than the clamp point — a quiet
    data loss in a tool whose whole thesis is traceability.
    """
    _seed_watermark(session, NVD_SOURCE_NAME, datetime(2025, 1, 1, tzinfo=timezone.utc))
    fetcher = ScriptedNvdFetcher(["CVE-2026-0010"])

    with pytest.raises(IngestError) as excinfo:
        ingest_nvd_sync(session, fetcher, until=datetime(2026, 6, 1, tzinfo=timezone.utc))

    message = str(excinfo.value)
    assert "120" in message
    assert "--since" in message, "the error must say how to catch up"
    assert fetcher.calls == [], "a refused sync must not make a request"
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == datetime(
        2025, 1, 1, tzinfo=timezone.utc
    )


def test_watermark_just_inside_limit_is_accepted(session) -> None:
    """The boundary case: 120 days exactly is still allowed."""
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_watermark(session, NVD_SOURCE_NAME, since)
    fetcher = ScriptedNvdFetcher([])

    ingest_nvd_sync(session, fetcher, until=since + timedelta(days=120))

    assert fetcher.calls, "a 120-day window is inside NVD's limit"
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == since + timedelta(days=120)


# --------------------------------------------------------------------------
# Limit and repeated runs
# --------------------------------------------------------------------------

def test_limited_run_does_not_advance_watermark(session) -> None:
    """`--limit` stops before covering the window, so it must not advance.

    The CLI rejects `--sync --limit` outright; this test defends the
    underlying rule in case a caller reaches the function directly.
    """
    fetcher = ScriptedNvdFetcher(["CVE-2026-0011", "CVE-2026-0012", "CVE-2026-0013"])

    report = ingest_nvd_modifications(
        session,
        fetcher,
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 2, 1, tzinfo=timezone.utc),
        limit=1,
    )

    assert report.status == "success"
    assert report.records_written == 1
    assert get_sync_watermark(session, NVD_SOURCE_NAME) is None, (
        "a truncated run covered only part of the window"
    )


def test_repeated_sync_updates_in_place_not_duplicate(session) -> None:
    """A CVE modified twice appears in two windows; the row must be updated.

    This is the real overlap scenario: NVD re-reports a CVE as modified in
    the next window, so the same external id lands in two consecutive
    syncs. Idempotent upsert keeps it one row.
    """
    _seed_watermark(session, NVD_SOURCE_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))

    first = ingest_nvd_sync(
        session,
        ScriptedNvdFetcher(["CVE-2026-0014", "CVE-2026-0015"]),
        until=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    assert first.records_inserted == 2
    assert first.records_updated == 0

    # Next window: CVE-2026-0014 was modified again, CVE-2026-0017 is new.
    second = ingest_nvd_sync(
        session,
        ScriptedNvdFetcher(["CVE-2026-0014", "CVE-2026-0017"]),
        until=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    assert second.records_inserted == 1, "only the genuinely new CVE is inserted"
    assert second.records_updated == 1, "the re-reported CVE is updated in place"

    assert sorted(_document_ids(session)) == [
        "CVE-2026-0014",
        "CVE-2026-0015",
        "CVE-2026-0017",
    ]
    assert session.query(Source).where(Source.name == NVD_SOURCE_NAME).count() == 1


def test_watermark_is_monotonic_across_successive_syncs(session) -> None:
    """Each successful sync advances the mark; none ever moves it back."""
    _seed_watermark(session, NVD_SOURCE_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))
    marks = []
    for day in (10, 20, 28):
        ingest_nvd_sync(
            session,
            ScriptedNvdFetcher([]),
            until=datetime(2026, 1, day, tzinfo=timezone.utc),
        )
        marks.append(get_sync_watermark(session, NVD_SOURCE_NAME))

    assert marks == sorted(marks), "watermarks must be non-decreasing"
    assert marks[-1] == datetime(2026, 1, 28, tzinfo=timezone.utc)


def test_overlapping_boundary_is_refetched_not_skipped(session) -> None:
    """The next window starts AT the watermark, so boundaries overlap.

    Deliberate: a duplicate costs nothing (idempotent upsert), whereas a
    miss costs a record permanently absent from an evidence corpus.
    """
    boundary = datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    _seed_watermark(session, NVD_SOURCE_NAME, boundary)

    fetcher = ScriptedNvdFetcher(["CVE-2026-0016"])
    ingest_nvd_sync(session, fetcher, until=datetime(2026, 2, 10, tzinfo=timezone.utc))

    assert fetcher.calls[0]["lastModStartDate"] == "2026-02-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# Provenance and audit trail survive synchronization
# --------------------------------------------------------------------------

def test_sync_documents_carry_ingest_run_id(session) -> None:
    """Watermark bookkeeping must not weaken document provenance."""
    _seed_watermark(session, NVD_SOURCE_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))

    report = ingest_nvd_sync(
        session,
        ScriptedNvdFetcher(["CVE-2026-0017"]),
        until=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    doc = session.query(Document).one()
    assert doc.ingest_run_id is not None
    assert doc.ingest_run_id in report.run_ids

    run = session.get(IngestRun, doc.ingest_run_id)
    assert run.status == "success"
    assert run.http_status == 200
    assert run.content_sha256, "the payload digest must still be recorded"


def test_watermark_points_at_the_run_that_earned_it(session) -> None:
    """`sync_state.last_run_id` makes the resume point itself auditable."""
    _seed_watermark(session, NVD_SOURCE_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))

    report = ingest_nvd_sync(
        session,
        ScriptedNvdFetcher(["CVE-2026-0018"]),
        until=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    row = session.query(SyncState).one()
    assert row.last_run_id == report.run_ids[-1]
    assert row.watermark_at == datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert row.updated_at is not None


def test_failed_sync_still_writes_audit_rows(session) -> None:
    """The audit trail must record the failure, not just the successes."""
    _seed_watermark(session, NVD_SOURCE_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))

    with pytest.raises(HttpStatusError):
        ingest_nvd_sync(
            session,
            ScriptedNvdFetcher(
                ["CVE-2026-0019"],
                fail_on_call=1,
                error=HttpStatusError(403, API_URL, "403 Forbidden"),
            ),
            until=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

    runs = session.query(IngestRun).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].http_status == 403


# --------------------------------------------------------------------------
# KEV: freshness watermark (KEV cannot narrow a query)
# --------------------------------------------------------------------------

def test_kev_sync_advances_watermark_on_success(session) -> None:
    fetcher = FakeKevFetcher(_kev_catalog([_kev_entry("CVE-2026-0020")]))

    report = ingest_kev_sync(session, fetcher)

    assert report.status == "success"
    assert get_sync_watermark(session, KEV_SOURCE_NAME) is not None


def test_kev_sync_does_not_advance_on_failure(session) -> None:
    fetcher = FakeKevFetcher(
        error=HttpStatusError(500, "https://example.invalid/kev", "500 Server Error")
    )

    with pytest.raises(HttpStatusError):
        ingest_kev_sync(session, fetcher)

    assert get_sync_watermark(session, KEV_SOURCE_NAME) is None


def test_kev_sync_does_not_advance_on_partial(session) -> None:
    """A record the parser rejects makes the run partial -> no advance."""
    catalog = _kev_catalog(
        [
            _kev_entry("CVE-2026-0021"),
            {"cveID": "CVE-2026-0022", "shortDescription": "no name"},
        ]
    )
    fetcher = FakeKevFetcher(catalog)

    report = ingest_kev_sync(session, fetcher)

    assert report.status == "partial"
    assert report.records_written == 1
    assert get_sync_watermark(session, KEV_SOURCE_NAME) is None


def test_kev_sync_is_idempotent(session) -> None:
    entry = _kev_entry("CVE-2026-0023")
    ingest_kev_sync(session, FakeKevFetcher(_kev_catalog([entry])))
    ingest_kev_sync(session, FakeKevFetcher(_kev_catalog([entry])))

    assert session.query(Document).count() == 1
    assert session.query(Source).where(Source.name == KEV_SOURCE_NAME).count() == 1


def test_kev_and_nvd_watermarks_are_independent(session) -> None:
    """One row per source; syncing one must not touch the other."""
    nvd_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_watermark(session, NVD_SOURCE_NAME, nvd_start)

    ingest_kev_sync(session, FakeKevFetcher(_kev_catalog([_kev_entry("CVE-2026-0024")])))

    kev_mark = get_sync_watermark(session, KEV_SOURCE_NAME)
    assert kev_mark is not None
    assert get_sync_watermark(session, NVD_SOURCE_NAME) == nvd_start, (
        "syncing KEV must not move NVD's watermark"
    )


def test_kev_catalog_reingest_is_a_full_snapshot_not_incremental(session) -> None:
    """KEV's watermark records freshness; it cannot narrow the next fetch.

    The whole point of honesty here: KEV has no server-side date filter, so
    every KEV sync re-reads the entire catalog.
    """
    fetcher = FakeKevFetcher(_kev_catalog([_kev_entry("CVE-2026-0025")]))
    ingest_kev_sync(session, fetcher)
    first_mark = get_sync_watermark(session, KEV_SOURCE_NAME)

    ingest_kev_sync(session, fetcher)
    assert fetcher.calls == 2, "every KEV sync re-fetches the whole catalog"
    assert get_sync_watermark(session, KEV_SOURCE_NAME) >= first_mark


# --------------------------------------------------------------------------
# Schema migration: additive, safe on an existing database
# --------------------------------------------------------------------------

REAL_DB = ROOT / "data" / "evidencegraph.db"


@pytest.mark.skipif(not REAL_DB.exists(), reason="real database not present")
def test_migration_adds_sync_state_to_copy_without_touching_real_db(
    tmp_path: Path,
) -> None:
    """Migrate a COPY; the real database must stay byte-identical."""
    before = hashlib.sha256(REAL_DB.read_bytes()).hexdigest()

    copy = tmp_path / "copy.db"
    shutil.copyfile(REAL_DB, copy)

    engine = make_engine(f"sqlite:///{copy}")
    ensure_schema(engine)  # must not raise
    ensure_schema(engine)  # idempotent

    tables = {
        row[0]
        for row in sqlite3.connect(copy).execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "sync_state" in tables, "the new table must be created additively"

    # Existing data is intact.
    con = sqlite3.connect(copy)
    assert con.execute("SELECT COUNT(*) FROM documents").fetchone()[0] > 0
    assert con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
    con.close()

    after = hashlib.sha256(REAL_DB.read_bytes()).hexdigest()
    assert before == after, "the real database must never be modified by a test"


def test_migration_creates_sync_state_on_pre_phase_db(tmp_path: Path) -> None:
    """A database without `sync_state` gains it, and stays usable."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                              url TEXT NOT NULL, retrieved_at DATETIME);
        CREATE TABLE ingest_runs (id INTEGER PRIMARY KEY,
            source_id INTEGER REFERENCES sources (id),
            fetch_url TEXT NOT NULL, retrieved_at DATETIME,
            http_status INTEGER, content_sha256 TEXT,
            records_fetched INTEGER, records_parsed INTEGER,
            records_inserted INTEGER, records_updated INTEGER,
            records_skipped INTEGER, records_failed INTEGER,
            status TEXT NOT NULL, error_message TEXT);
        CREATE TABLE documents (id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources (id),
            external_id TEXT NOT NULL, title TEXT NOT NULL,
            published_at TEXT NOT NULL, source_url TEXT NOT NULL,
            metadata_json TEXT NOT NULL, retrieved_at DATETIME,
            ingest_run_id INTEGER REFERENCES ingest_runs (id));
        CREATE TABLE chunks (id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents (id),
            position INTEGER NOT NULL, text TEXT NOT NULL,
            source_url TEXT NOT NULL);
        INSERT INTO sources (id, name, url) VALUES (1, 's', 'u');
        INSERT INTO documents (id, source_id, external_id, title, published_at,
                              source_url, metadata_json)
            VALUES (1, 1, 'CVE-2021-44228', 'T', '2021-12-10', 'u', '{}');
        """
    )
    con.commit()
    con.close()

    ensure_schema(make_engine(f"sqlite:///{db}"))

    con = sqlite3.connect(db)
    tables = {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "sync_state" in tables
    # Existing row untouched.
    assert con.execute("SELECT external_id FROM documents").fetchall() == [
        ("CVE-2021-44228",)
    ]
    con.close()

    # The ORM must be usable against the migrated database.
    session = make_session_factory(make_engine(f"sqlite:///{db}"))()
    _advance_watermark(
        session, "s", "u", watermark_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        run_id=None,
    )
    assert get_sync_watermark(session, "s") == datetime(
        2026, 1, 1, tzinfo=timezone.utc
    )
    session.close()


# --------------------------------------------------------------------------
# CLI option validation (offline: these return before any network)
# --------------------------------------------------------------------------

@pytest.fixture()
def cli_settings(tmp_path: Path) -> Settings:
    return Settings(database_url=f"sqlite:///{tmp_path / 'cli.db'}")


def test_cli_rejects_sync_with_limit(cli_settings, capsys) -> None:
    from app.cli import build_parser, cmd_ingest

    args = build_parser().parse_args(["ingest", "--source", "nvd", "--sync", "--limit", "5"])
    code = cmd_ingest(cli_settings, args)

    assert code == 1
    assert "--limit" in capsys.readouterr().err


def test_cli_rejects_sync_with_since_until(cli_settings, capsys) -> None:
    from app.cli import build_parser, cmd_ingest

    args = build_parser().parse_args(
        ["ingest", "--source", "nvd", "--sync", "--since", "2026-01-01"]
    )
    code = cmd_ingest(cli_settings, args)

    assert code == 1
    assert "watermark" in capsys.readouterr().err


def test_cli_rejects_sync_with_cve(cli_settings, capsys) -> None:
    from app.cli import build_parser, cmd_ingest

    args = build_parser().parse_args(
        ["ingest", "--source", "nvd", "--sync", "--cve", "CVE-2021-44228"]
    )
    code = cmd_ingest(cli_settings, args)

    assert code == 1
    assert "--cve" in capsys.readouterr().err


def test_cli_rejects_sync_with_fixture(cli_settings, capsys) -> None:
    from app.cli import build_parser, cmd_ingest

    args = build_parser().parse_args(["ingest", "--sync"])
    code = cmd_ingest(cli_settings, args)

    assert code == 1
    assert "fixture" in capsys.readouterr().err


def test_cli_runs_command_shows_sync_state(cli_settings, capsys) -> None:
    """`runs` must surface watermarks, including the honest NULL case."""
    from app.cli import build_parser, cmd_runs

    engine = make_engine(cli_settings.database_url)
    init_db(engine)
    session = make_session_factory(engine)()
    _seed_watermark(session, KEV_SOURCE_NAME, datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc))
    session.close()

    args = build_parser().parse_args(["runs"])
    assert cmd_runs(cli_settings, args) == 0

    out = capsys.readouterr().out
    assert "Sync watermarks:" in out
    assert KEV_SOURCE_NAME in out
    assert "2026-03-04 05:06:07" in out
    assert "never synced" not in out


def test_cli_runs_command_reports_never_synced(cli_settings, capsys) -> None:
    """A NULL watermark is reported as never synced, not omitted."""
    from app.cli import build_parser, cmd_runs

    engine = make_engine(cli_settings.database_url)
    init_db(engine)
    session = make_session_factory(engine)()
    session.add(Source(name=KEV_SOURCE_NAME, url="u"))
    session.flush()
    source_id = session.query(Source.id).scalar()
    # A row exists but its watermark is NULL: "attempted, never completed".
    session.add(SyncState(source_id=source_id, watermark_at=None))
    session.commit()
    session.close()

    args = build_parser().parse_args(["runs"])
    assert cmd_runs(cli_settings, args) == 0

    out = capsys.readouterr().out
    assert "never synced" in out
