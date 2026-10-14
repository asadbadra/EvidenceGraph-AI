"""Regression tests for the ingestion hardening (offline, no network).

Three things are covered, all driven through injected fake fetchers:

1. NVD pagination — a date-window ingest must walk every page, not silently
   keep the first one. Silent truncation is the bug this file exists to
   prevent.
2. Source-to-document traceability — every document written by a live fetch
   must name the `ingest_runs` row that produced it.
3. The legacy fixture loader must never invent a publication date.

As everywhere else in this suite, an autouse guard (tests/conftest.py) fails
any test that opens a real socket.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db import (
    Document,
    IngestRun,
    Source,
    ensure_schema,
    init_db,
    make_engine,
    make_session_factory,
)
from app.ingestion.http_client import HttpStatusError
from app.ingestion.loader import load_advisories
from app.ingestion.pipeline import (
    IngestError,
    ingest_kev,
    ingest_nvd_modifications,
)

ROOT = Path(__file__).resolve().parent.parent
KEV_FIXTURE = json.loads(
    (ROOT / "data" / "sample" / "advisories.json").read_text(encoding="utf-8")
)


# --------------------------------------------------------------------------
# Fake paginated NVD fetcher
# --------------------------------------------------------------------------

def _nvd_page(records: list[dict], *, start: int, per_page: int, total: int) -> dict:
    """Build one NVD-shaped page, honouring the real API's envelope."""
    return {
        "resultsPerPage": per_page,
        "startIndex": start,
        "totalResults": total,
        "format": "NVD_CVE",
        "vulnerabilities": records[start : start + per_page],
    }


def _cve(i: int) -> dict:
    """A minimal but genuinely NVD-shaped record."""
    cve_id = f"CVE-2026-{i:04d}"
    return {
        "cve": {
            "id": cve_id,
            "published": "2026-01-01T00:00:00.000",
            "descriptions": [{"lang": "en", "value": f"Synthetic record {i}."}],
        }
    }


class PagedNvdFetcher:
    """Serves pages of synthetic records, exactly as NVD would.

    Records `params` for every request so tests can assert on the exact
    pagination sequence (startIndex / resultsPerPage).
    """

    def __init__(
        self,
        records: list[dict],
        *,
        omit_total: bool = False,
        fail_at_start_index: dict[int, Exception] | None = None,
    ) -> None:
        self.records = records
        self.omit_total = omit_total
        self.fail_at_start_index = fail_at_start_index or {}
        self.requests: list[dict[str, str]] = []
        self.api_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    def fetch(self, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        self.requests.append(params)
        start = int(params.get("startIndex", 0))
        per_page = int(params.get("resultsPerPage", 2000))

        if start in self.fail_at_start_index:
            raise self.fail_at_start_index[start]

        total = len(self.records) if not self.omit_total else None
        envelope: dict[str, Any] = {
            "resultsPerPage": per_page,
            "startIndex": start,
            "format": "NVD_CVE",
            "vulnerabilities": self.records[start : start + per_page],
        }
        if total is not None:
            envelope["totalResults"] = total
        return envelope


@pytest.fixture()
def session(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'page.db'}")
    init_db(engine)
    sess = make_session_factory(engine)()
    yield sess
    sess.close()


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


WINDOW = {"since": date(2026, 1, 1), "until": date(2026, 1, 31)}


# --------------------------------------------------------------------------
# 1. Pagination: the bug this milestone exists to fix
# --------------------------------------------------------------------------

def test_single_page_still_works(session) -> None:
    """Baseline: a result set that fits on one page makes one request."""
    fetcher = PagedNvdFetcher([_cve(i) for i in range(3)])

    report = ingest_nvd_modifications(session, fetcher, **WINDOW)

    assert report.status == "success"
    assert report.records_inserted == 3
    assert len(fetcher.requests) == 1
    assert fetcher.requests[0]["startIndex"] == "0"
    assert _count(session, Document) == 3


def test_multi_page_ingest_pulls_every_record(session) -> None:
    """THE regression: 5 records across pages of 2 must ingest all 5.

    Before the fix this returned 2 and reported success.
    """
    fetcher = PagedNvdFetcher([_cve(i) for i in range(5)])

    report = ingest_nvd_modifications(
        session, fetcher, **WINDOW, page_size=2
    )

    assert report.records_inserted == 5, "all 5 records, not just page 1"
    assert _count(session, Document) == 5
    assert report.status == "success"


def test_start_index_advances_by_records_returned(session) -> None:
    """Each request must offset by how many records the last page yielded."""
    fetcher = PagedNvdFetcher([_cve(i) for i in range(5)])

    ingest_nvd_modifications(session, fetcher, **WINDOW, page_size=2)

    assert [r["startIndex"] for r in fetcher.requests] == ["0", "2", "4"]
    assert all(r["resultsPerPage"] == "2" for r in fetcher.requests)


def test_page_size_defaults_to_nvd_maximum(session) -> None:
    """Unset page_size must ask for NVD's documented max (2000), i.e. fewest requests."""
    fetcher = PagedNvdFetcher([_cve(1)])

    ingest_nvd_modifications(session, fetcher, **WINDOW)

    assert fetcher.requests[0]["resultsPerPage"] == "2000"


def test_every_page_gets_its_own_audit_row(session) -> None:
    fetcher = PagedNvdFetcher([_cve(i) for i in range(5)])

    report = ingest_nvd_modifications(session, fetcher, **WINDOW, page_size=2)

    # 3 pages -> 3 fetch attempts -> 3 audit rows, and the report lists them.
    assert len(report.run_ids) == 3
    assert _count(session, IngestRun) == 3


def test_documents_name_the_run_that_wrote_them(session) -> None:
    """Traceability: each document points at its own page's run row."""
    fetcher = PagedNvdFetcher([_cve(i) for i in range(5)])

    report = ingest_nvd_modifications(session, fetcher, **WINDOW, page_size=2)

    run_ids = set(session.scalars(select(Document.ingest_run_id)).all())
    assert run_ids == set(report.run_ids)
    assert None not in run_ids, "no live-fetched document may lack a run id"

    # And every referenced run id really exists in ingest_runs.
    existing = set(session.scalars(select(IngestRun.id)).all())
    assert run_ids <= existing


def test_documents_are_evenly_split_across_page_runs(session) -> None:
    fetcher = PagedNvdFetcher([_cve(i) for i in range(5)])

    ingest_nvd_modifications(session, fetcher, **WINDOW, page_size=2)

    per_run = dict(
        session.execute(
            select(Document.ingest_run_id, func.count()).group_by(
                Document.ingest_run_id
            )
        ).all()
    )
    # pages of 2,2,1
    assert sorted(per_run.values()) == [1, 2, 2]


def test_limit_stops_pagination_early(session) -> None:
    """--limit 3 with page_size 2 must not fetch page 2."""
    fetcher = PagedNvdFetcher([_cve(i) for i in range(10)])

    report = ingest_nvd_modifications(
        session, fetcher, **WINDOW, page_size=2, limit=3
    )

    assert report.records_inserted == 3
    assert _count(session, Document) == 3
    assert len(fetcher.requests) == 2, "stop once the limit is met"


def test_limit_smaller_than_page_size_asks_for_only_what_is_needed(session) -> None:
    fetcher = PagedNvdFetcher([_cve(i) for i in range(10)])

    ingest_nvd_modifications(session, fetcher, **WINDOW, page_size=2000, limit=3)

    assert fetcher.requests[0]["resultsPerPage"] == "3"
    assert _count(session, Document) == 3


def test_missing_total_results_stops_after_one_page(session) -> None:
    """If NVD omits totalResults we ingest what we got and stop.

    Guessing at further pages would risk duplicates or an unbounded loop.
    """
    fetcher = PagedNvdFetcher([_cve(i) for i in range(5)], omit_total=True)

    report = ingest_nvd_modifications(session, fetcher, **WINDOW, page_size=2)

    assert len(fetcher.requests) == 1
    assert report.records_inserted == 2
    assert report.status == "success", "one page is a complete, honest result"


def test_infinite_server_is_bounded_by_max_pages(session) -> None:
    """A server that ignores startIndex and repeats page 1 forever.

    Without the cap this loop never terminates.
    """
    first_page = [_cve(0), _cve(1)]

    class StubbornFetcher:
        api_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

        def __init__(self) -> None:
            self.requests: list[dict] = []

        def fetch(self, params=None):
            self.requests.append(dict(params or {}))
            # Always claims a large total, always returns the same page.
            return {
                "startIndex": int(params.get("startIndex", 0)),
                "resultsPerPage": int(params.get("resultsPerPage", 2000)),
                "totalResults": 10_000,
                "vulnerabilities": first_page,
            }

    fetcher = StubbornFetcher()
    report = ingest_nvd_modifications(
        session, fetcher, **WINDOW, page_size=2, max_pages=3
    )

    assert len(fetcher.requests) == 3, "must stop at max_pages"
    assert report.status == "partial"
    assert any("stopped after 3 pages" in e for e in report.errors)


def test_empty_page_terminates(session) -> None:
    """A page with no vulnerabilities ends the loop immediately."""
    fetcher = PagedNvdFetcher([])

    report = ingest_nvd_modifications(session, fetcher, **WINDOW, page_size=2)

    assert len(fetcher.requests) == 1
    assert report.records_inserted == 0
    assert report.status == "success"


def test_failure_on_later_page_keeps_earlier_records(session) -> None:
    """Page 2 of 3 fails: pages already committed must survive."""
    fetcher = PagedNvdFetcher(
        [_cve(i) for i in range(5)],
        fail_at_start_index={
            2: HttpStatusError(503, "https://example.invalid", "HTTP 503")
        },
    )

    report = ingest_nvd_modifications(session, fetcher, **WINDOW, page_size=2)

    assert report.status == "partial"
    assert report.records_inserted == 2, "page 1's two records are committed"
    assert _count(session, Document) == 2
    assert any("page 2" in e for e in report.errors)

    # 1 successful page + 1 failed fetch = 2 audit rows.
    assert _count(session, IngestRun) == 2
    statuses = session.scalars(select(IngestRun.status)).all()
    assert "failed" in statuses


def test_failure_on_first_page_raises(session) -> None:
    """Nothing committed yet, so the first-page failure is a hard error."""
    fetcher = PagedNvdFetcher(
        [_cve(i) for i in range(5)],
        fail_at_start_index={0: HttpStatusError(503, "u", "HTTP 503")},
    )

    with pytest.raises(HttpStatusError):
        ingest_nvd_modifications(session, fetcher, **WINDOW, page_size=2)

    assert _count(session, Document) == 0
    run = session.scalars(select(IngestRun)).one()
    assert run.status == "failed"


def test_zero_page_size_rejected(session) -> None:
    with pytest.raises(IngestError, match="page_size"):
        ingest_nvd_modifications(
            session, PagedNvdFetcher([]), **WINDOW, page_size=0
        )


# --------------------------------------------------------------------------
# 2. Traceability beyond pagination
# --------------------------------------------------------------------------

def test_kev_documents_carry_run_id(session) -> None:
    class FakeKev:
        feed_url = "https://example.invalid/kev.json"

        def fetch(self):
            return KEV_FIXTURE

    report = ingest_kev(session, FakeKev())

    run_ids = set(session.scalars(select(Document.ingest_run_id)).all())
    assert run_ids == {report.run_ids[0]}
    assert None not in run_ids


def test_reingest_repoints_document_to_new_run(session) -> None:
    """A re-fetched document names the fetch that last confirmed it."""
    class FakeKev:
        feed_url = "https://example.invalid/kev.json"

        def fetch(self):
            return KEV_FIXTURE

    first = ingest_kev(session, FakeKev())
    second = ingest_kev(session, FakeKev())

    doc = session.scalar(
        select(Document).where(Document.external_id == "CVE-2021-44228")
    )
    assert doc.ingest_run_id == second.run_ids[0]
    assert doc.ingest_run_id != first.run_ids[0]


def test_fixture_load_leaves_run_id_null(session) -> None:
    """A fixture load is not a live fetch, so it must claim no run."""
    report = load_advisories(
        session, ROOT / "data" / "sample" / "advisories.json"
    )
    assert report.documents == 5

    run_ids = session.scalars(select(Document.ingest_run_id)).all()
    assert set(run_ids) == {None}
    assert _count(session, IngestRun) == 0, "fixtures are not audited as fetches"


# --------------------------------------------------------------------------
# 3. Legacy loader must not invent dates
# --------------------------------------------------------------------------

def test_loader_does_not_fabricate_a_publication_date(tmp_path: Path) -> None:
    """A fixture record with no dateAdded must store ''.

    Before the fix the loader substituted today's date, inventing provenance.
    """
    payload = {
        "source": {"name": "Test Source", "url": "https://example.invalid"},
        "vulnerabilities": [
            {
                "cveID": "CVE-2026-0001",
                "vendorProject": "V",
                "product": "P",
                "vulnerabilityName": "N",
                "shortDescription": "D",
                # deliberately no dateAdded
            }
        ],
    }
    fixture = tmp_path / "no_dates.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")

    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    init_db(engine)
    session = make_session_factory(engine)()
    load_advisories(session, fixture)

    doc = session.scalar(select(Document))
    assert doc.published_at == "", "a missing source date must stay empty"
    session.close()


def test_loader_keeps_real_dates_verbatim(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    init_db(engine)
    session = make_session_factory(engine)()
    load_advisories(session, ROOT / "data" / "sample" / "advisories.json")

    doc = session.scalar(
        select(Document).where(Document.external_id == "CVE-2021-44228")
    )
    assert doc.published_at == "2021-12-10"
    session.close()


# --------------------------------------------------------------------------
# 4. Migration adds the traceability column safely
# --------------------------------------------------------------------------

# The Phase 1 schema as it existed before ingest_run_id was added.
PRE_TRACEABILITY_SCHEMA = """
CREATE TABLE sources (
    id INTEGER NOT NULL, name VARCHAR(255) NOT NULL, url TEXT NOT NULL,
    retrieved_at DATETIME NOT NULL, PRIMARY KEY (id)
);
CREATE TABLE documents (
    id INTEGER NOT NULL, source_id INTEGER NOT NULL,
    external_id VARCHAR(64) NOT NULL, title TEXT NOT NULL,
    published_at VARCHAR(32) NOT NULL, source_url TEXT NOT NULL,
    metadata_json TEXT NOT NULL, retrieved_at DATETIME NOT NULL,
    PRIMARY KEY (id), FOREIGN KEY(source_id) REFERENCES sources (id)
);
CREATE UNIQUE INDEX uq_documents_source_external ON documents (source_id, external_id);
CREATE TABLE chunks (
    id INTEGER NOT NULL, document_id INTEGER NOT NULL, position INTEGER NOT NULL,
    text TEXT NOT NULL, source_url TEXT NOT NULL,
    PRIMARY KEY (id), FOREIGN KEY(document_id) REFERENCES documents (id)
);
CREATE TABLE ingest_runs (
    id INTEGER NOT NULL, source_id INTEGER, fetch_url TEXT NOT NULL,
    retrieved_at DATETIME NOT NULL, http_status INTEGER,
    content_sha256 VARCHAR(64), records_fetched INTEGER NOT NULL,
    records_parsed INTEGER NOT NULL, records_inserted INTEGER NOT NULL,
    records_updated INTEGER NOT NULL, records_skipped INTEGER NOT NULL,
    records_failed INTEGER NOT NULL, status VARCHAR(32) NOT NULL,
    error_message TEXT, PRIMARY KEY (id), FOREIGN KEY(source_id) REFERENCES sources (id)
);
INSERT INTO sources (id, name, url, retrieved_at)
 VALUES (1, 'S', 'https://example.invalid', '2026-01-01 00:00:00');
INSERT INTO documents
 (id, source_id, external_id, title, published_at, source_url, metadata_json, retrieved_at)
 VALUES (1, 1, 'CVE-2021-44228', 'T', '2021-12-10', 'u', '{}', '2026-01-01 00:00:00');
"""


def _make_pre_trace_db(path: Path) -> None:
    import sqlite3

    con = sqlite3.connect(path)
    con.executescript(PRE_TRACEABILITY_SCHEMA)
    con.commit()
    con.close()


def test_migration_adds_run_id_and_backfills_null(tmp_path: Path) -> None:
    """Existing documents must survive; their run id stays honestly NULL."""
    import sqlite3

    db = tmp_path / "old.db"
    _make_pre_trace_db(db)
    engine = make_engine(f"sqlite:///{db}")

    ensure_schema(engine)

    rows = sqlite3.connect(db).execute(
        "SELECT id, external_id, ingest_run_id FROM documents"
    ).fetchall()
    assert rows == [(1, "CVE-2021-44228", None)]
    assert rows[0][0] == 1, "existing document id must not change"


def test_migration_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    _make_pre_trace_db(db)
    engine = make_engine(f"sqlite:///{db}")

    ensure_schema(engine)
    ensure_schema(engine)  # second run: no error

    import sqlite3

    count = sqlite3.connect(db).execute("SELECT COUNT(*) FROM documents").fetchone()
    assert count == (1,)


def test_migrated_db_accepts_new_documents_with_run_id(tmp_path: Path) -> None:
    """The ORM must be usable against a migrated database."""
    db = tmp_path / "old.db"
    _make_pre_trace_db(db)
    engine = make_engine(f"sqlite:///{db}")
    ensure_schema(engine)

    session = make_session_factory(engine)()
    session.add(IngestRun(source_id=1, fetch_url="u", status="success"))
    session.flush()
    run_id = session.scalars(select(IngestRun.id)).one()
    session.add(
        Document(
            source_id=1,
            external_id="CVE-2026-0002",
            title="t",
            published_at="2026-01-01",
            source_url="u",
            metadata_json="{}",
            ingest_run_id=run_id,
        )
    )
    session.commit()

    doc = session.scalar(select(Document).where(Document.external_id == "CVE-2026-0002"))
    assert doc.ingest_run_id == run_id
    session.close()


def test_source_row_still_unique_after_migration(tmp_path: Path) -> None:
    """The unique (source_id, external_id) index must survive the ALTER."""
    db = tmp_path / "old.db"
    _make_pre_trace_db(db)
    engine = make_engine(f"sqlite:///{db}")
    ensure_schema(engine)

    session = make_session_factory(engine)()
    session.add(
        Document(
            source_id=1,
            external_id="CVE-2021-44228",  # already present
            title="dup",
            published_at="",
            source_url="u",
            metadata_json="{}",
        )
    )
    import sqlalchemy.exc as exc

    with pytest.raises(exc.IntegrityError):
        session.commit()
    session.rollback()
    session.close()
