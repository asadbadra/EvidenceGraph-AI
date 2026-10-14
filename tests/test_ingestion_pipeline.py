"""Integration tests for the ingestion pipeline (Phase 1, Step 4).

All offline: fetchers are fakes injected into the pipeline, so no test opens
a socket (the autouse guard in conftest.py would fail the test if one did).

These tests exercise the *wiring* between the three layers that Step 3 built
separately:

    fake fetcher (network stand-in) -> pure parser -> validation -> SQLite

Payloads are the real committed sample fixtures (real CISA KEV and NVD data),
so the pipeline is tested against genuine source shapes rather than
hand-mangled ones.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db import Chunk, Document, IngestRun, Source, init_db, make_engine, make_session_factory
from app.ingestion.http_client import HttpTimeoutError, HttpStatusError
from app.ingestion.models import AdvisoryRecord
from app.ingestion.parsers import KEV_SOURCE_NAME, NVD_SOURCE_NAME
from app.ingestion.pipeline import (
    IngestError,
    IngestReport,
    ingest_kev,
    ingest_nvd_cves,
    ingest_nvd_modifications,
    nvd_modification_params,
    payload_digest,
)

ROOT = Path(__file__).resolve().parent.parent
KEV_FIXTURE = json.loads(
    (ROOT / "data" / "sample" / "advisories.json").read_text(encoding="utf-8")
)
NVD_FIXTURE = json.loads(
    (ROOT / "data" / "sample" / "nvd_sample.json").read_text(encoding="utf-8")
)


# --------------------------------------------------------------------------
# Fake fetchers (network stand-ins)
# --------------------------------------------------------------------------

class FakeKevFetcher:
    """Stands in for KevFetcher: hands back a canned payload, no network."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = KEV_FIXTURE if payload is None else payload
        self.error = error
        self.calls = 0
        self.feed_url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

    def fetch(self) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload


class FakeNvdFetcher:
    """Stands in for NvdFetcher: maps CVE id -> canned payload."""

    def __init__(
        self,
        payloads: dict[str, Any] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.payloads = payloads or {}
        self.errors = errors or {}
        self.calls: list[dict[str, Any] | None] = []
        self.api_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    def fetch_cve(self, cve_id: str) -> Any:
        self.calls.append({"cveId": cve_id})
        if cve_id in self.errors:
            raise self.errors[cve_id]
        if cve_id not in self.payloads:
            raise KeyError(cve_id)
        return self.payloads[cve_id]

    def fetch(self, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(params)
        return self.payloads.get("__query__", NVD_FIXTURE)


@pytest.fixture()
def session(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'ingest.db'}")
    init_db(engine)
    sess = make_session_factory(engine)()
    yield sess
    sess.close()


def _counts(session) -> dict[str, int]:
    return {
        "documents": session.scalar(select(func.count()).select_from(Document)) or 0,
        "chunks": session.scalar(select(func.count()).select_from(Chunk)) or 0,
        "sources": session.scalar(select(func.count()).select_from(Source)) or 0,
        "runs": session.scalar(select(func.count()).select_from(IngestRun)) or 0,
    }


# --------------------------------------------------------------------------
# Happy path: KEV
# --------------------------------------------------------------------------

def test_kev_ingest_writes_documents_chunks_and_audit(session) -> None:
    report = ingest_kev(session, FakeKevFetcher())

    assert report.status == "success"
    assert report.records_fetched == 5
    assert report.records_parsed == 5
    assert report.records_inserted == 5
    assert report.records_updated == 0
    assert report.records_failed == 0
    assert report.chunks > 0
    assert len(report.run_ids) == 1

    counts = _counts(session)
    assert counts["documents"] == 5
    assert counts["sources"] == 1
    assert counts["chunks"] == report.chunks
    assert counts["runs"] == 1


def test_kev_records_carry_provenance(session) -> None:
    ingest_kev(session, FakeKevFetcher())

    doc = session.scalar(select(Document).where(Document.external_id == "CVE-2021-44228"))
    assert doc is not None
    assert doc.source_url.startswith("https://")
    # published_at is verbatim from CISA's dateAdded, not today's date.
    assert doc.published_at == "2021-12-10"
    assert doc.retrieved_at is not None
    metadata = json.loads(doc.metadata_json)
    assert metadata.get("due_date") == "2021-12-24"
    assert metadata.get("known_ransomware_campaign_use") == "Known"

    # Chunks inherit the document's source_url for citation traceability.
    chunks = session.scalars(select(Chunk).where(Chunk.document_id == doc.id)).all()
    assert chunks
    assert all(c.source_url == doc.source_url for c in chunks)


def test_kev_source_row_matches_existing_convention(session) -> None:
    """Live KEV must join the same source row the fixture loader creates."""
    ingest_kev(session, FakeKevFetcher())
    names = session.scalars(select(Source.name)).all()
    assert names == [KEV_SOURCE_NAME]


def test_audit_row_records_payload_digest_and_status(session) -> None:
    report = ingest_kev(session, FakeKevFetcher())

    run = session.get(IngestRun, report.run_ids[0])
    assert run.status == "success"
    assert run.http_status == 200
    assert run.content_sha256 == payload_digest(KEV_FIXTURE)
    assert run.fetch_url.startswith("https://")
    assert run.records_fetched == 5
    assert run.records_inserted == 5
    assert run.error_message is None


# --------------------------------------------------------------------------
# Idempotency: repeated ingestion
# --------------------------------------------------------------------------

def test_repeated_kev_ingest_creates_no_duplicates(session) -> None:
    first = ingest_kev(session, FakeKevFetcher())
    second = ingest_kev(session, FakeKevFetcher())

    assert first.records_inserted == 5
    assert second.records_inserted == 0
    assert second.records_updated == 5

    counts = _counts(session)
    assert counts["documents"] == 5, "rerun must not duplicate documents"
    assert counts["sources"] == 1
    assert counts["runs"] == 2, "each fetch attempt is still audited"


def test_repeated_ingest_preserves_document_ids(session) -> None:
    """Document ids must be stable so citations pointing at them stay valid."""
    ingest_kev(session, FakeKevFetcher())
    ids_before = {
        d.external_id: d.id for d in session.scalars(select(Document)).all()
    }

    ingest_kev(session, FakeKevFetcher())
    ids_after = {
        d.external_id: d.id for d in session.scalars(select(Document)).all()
    }

    assert ids_before == ids_after


def test_repeated_ingest_does_not_duplicate_chunks(session) -> None:
    ingest_kev(session, FakeKevFetcher())
    chunks_first = _counts(session)["chunks"]

    ingest_kev(session, FakeKevFetcher())
    chunks_second = _counts(session)["chunks"]

    assert chunks_first == chunks_second, "chunks must be replaced, not appended"


def test_update_refreshes_retrieved_at_and_content(session) -> None:
    ingest_kev(session, FakeKevFetcher())
    doc = session.scalar(select(Document).where(Document.external_id == "CVE-2021-44228"))
    original_retrieved = doc.retrieved_at

    # Simulate the source changing the description for the same CVE.
    changed = json.loads(json.dumps(KEV_FIXTURE))
    for record in changed["vulnerabilities"]:
        if record["cveID"] == "CVE-2021-44228":
            record["shortDescription"] = "An updated description from the source."
    ingest_kev(session, FakeKevFetcher(payload=changed))

    session.expire_all()
    doc = session.scalar(select(Document).where(Document.external_id == "CVE-2021-44228"))
    # metadata_json is source metadata, so it must NOT contain our invented
    # sentence; the description lives in the chunk text, rebuilt from source.
    assert "updated description" not in doc.metadata_json
    assert doc.retrieved_at >= original_retrieved
    # The rebuilt chunk text reflects the new description.
    chunk_texts = session.scalars(
        select(Chunk.text).where(Chunk.document_id == doc.id)
    ).all()
    assert any("updated description" in t for t in chunk_texts)


# --------------------------------------------------------------------------
# Fetch failures: audited, nothing written
# --------------------------------------------------------------------------

def test_kev_fetch_timeout_writes_failed_audit_and_no_documents(session) -> None:
    fetcher = FakeKevFetcher(error=HttpTimeoutError("timed out after 30.0s"))

    with pytest.raises(HttpTimeoutError):
        ingest_kev(session, fetcher)

    counts = _counts(session)
    assert counts["documents"] == 0, "a failed fetch must write no documents"
    assert counts["chunks"] == 0
    assert counts["runs"] == 1, "the failure itself must be audited"

    run = session.scalars(select(IngestRun)).one()
    assert run.status == "failed"
    assert run.http_status is None, "a timeout has no HTTP status"
    assert run.content_sha256 is None, "no payload means no digest"
    assert "timed out" in run.error_message


def test_kev_fetch_http_error_records_status_code(session) -> None:
    error = HttpStatusError(
        503,
        "https://example.invalid/feed",
        "HTTP 503",
        body_snippet="",
        server_message="",
        retry_after=None,
    )
    with pytest.raises(HttpStatusError):
        ingest_kev(session, FakeKevFetcher(error=error))

    run = session.scalars(select(IngestRun)).one()
    assert run.status == "failed"
    assert run.http_status == 503


def test_failed_fetch_then_successful_rerun_leaves_consistent_state(session) -> None:
    with pytest.raises(HttpTimeoutError):
        ingest_kev(session, FakeKevFetcher(error=HttpTimeoutError("boom")))

    report = ingest_kev(session, FakeKevFetcher())

    assert report.status == "success"
    counts = _counts(session)
    assert counts["documents"] == 5
    assert counts["runs"] == 2
    statuses = session.scalars(select(IngestRun.status)).all()
    assert statuses == ["failed", "success"]


# --------------------------------------------------------------------------
# Parser failures
# --------------------------------------------------------------------------

def test_unparseable_payload_is_audited_and_raises(session) -> None:
    with pytest.raises(IngestError, match="could not be parsed"):
        ingest_kev(session, FakeKevFetcher(payload={"not": "a kev catalog"}))

    counts = _counts(session)
    assert counts["documents"] == 0
    assert counts["runs"] == 1

    run = session.scalars(select(IngestRun)).one()
    assert run.status == "failed"
    assert "parse error" in run.error_message
    assert run.http_status == 200, "a body was received; it was just unusable"
    assert run.content_sha256 is not None


def test_partly_malformed_payload_still_ingests_valid_records(session) -> None:
    """A few bad records must not sink the whole catalog."""
    payload = json.loads(json.dumps(KEV_FIXTURE))
    payload["vulnerabilities"].append({"cveID": "NOT-A-CVE"})  # no name/desc
    payload["vulnerabilities"].append(42)  # not even an object

    report = ingest_kev(session, FakeKevFetcher(payload=payload))

    assert report.records_inserted == 5, "valid records still ingested"
    assert report.records_skipped == 2
    assert report.status == "partial"
    assert len(report.errors) == 2

    run = session.get(IngestRun, report.run_ids[0])
    assert run.status == "partial"
    assert run.records_skipped == 2


def test_validation_failure_is_counted_and_not_written(session) -> None:
    """A record that parses but fails validation is counted, never coerced."""
    payload = json.loads(json.dumps(KEV_FIXTURE))
    # Valid CVE id but blank description: passes the parser's required-field
    # check only if we blank it after the fact, so build one directly.
    payload["vulnerabilities"].append(
        {
            "cveID": "CVE-2099-0001",
            "vendorProject": "X",
            "product": "Y",
            "vulnerabilityName": "Z",
            "shortDescription": "ok",
        }
    )
    report = ingest_kev(session, FakeKevFetcher(payload=payload))
    assert report.records_inserted == 6

    # Now feed a record whose external_id will fail AdvisoryRecord validation.
    bad = AdvisoryRecord(
        external_id="CVE-BAD",
        title="t",
        description="d",
        source_name=KEV_SOURCE_NAME,
        source_url="https://example.invalid",
    )
    assert bad.validation_errors(), "precondition: this record is invalid"

    from app.ingestion.pipeline import _persist_records

    inserted, updated, failed, _chunks, errors = _persist_records(
        session, [bad], source_name=KEV_SOURCE_NAME, source_url="u",
        chunk_max_chars=900, chunk_overlap_chars=150,
    )
    assert failed == 1
    assert inserted == 0
    assert errors and "invalid CVE identifier" in errors[0]
    assert session.scalar(select(func.count()).select_from(Document)) == 6


def test_limit_caps_records_and_is_applied_before_validation(session) -> None:
    report = ingest_kev(session, FakeKevFetcher(), limit=2)

    assert report.records_fetched == 5, "the source still had 5 records"
    assert report.records_parsed == 5
    assert report.records_inserted == 2
    assert _counts(session)["documents"] == 2


def test_limit_of_zero_is_rejected(session) -> None:
    with pytest.raises(IngestError, match="limit must be a positive"):
        ingest_kev(session, FakeKevFetcher(), limit=0)


# --------------------------------------------------------------------------
# NVD
# --------------------------------------------------------------------------

def _nvd_payload_for(cve_id: str) -> Any:
    """Return a minimal but genuine-shaped NVD payload for one CVE."""
    payload = json.loads(json.dumps(NVD_FIXTURE))
    payload["vulnerabilities"][0]["cve"]["id"] = cve_id
    return payload


def test_nvd_single_cve_ingest(session) -> None:
    fetcher = FakeNvdFetcher(payloads={"CVE-2021-44228": _nvd_payload_for("CVE-2021-44228")})

    report = ingest_nvd_cves(session, fetcher, ["CVE-2021-44228"])

    assert report.status == "success"
    assert report.records_inserted == 1
    assert len(report.run_ids) == 1

    doc = session.scalar(select(Document).where(Document.external_id == "CVE-2021-44228"))
    assert doc is not None
    assert doc.source_url == "https://nvd.nist.gov/vuln/detail/CVE-2021-44228"
    # NVD gives no title of its own; CISA's name is used when present.
    assert "Log4j" in doc.title


def test_nvd_source_name_is_distinct_from_kev(session) -> None:
    fetcher = FakeNvdFetcher(payloads={"CVE-2021-44228": _nvd_payload_for("CVE-2021-44228")})
    ingest_nvd_cves(session, fetcher, ["CVE-2021-44228"])

    names = set(session.scalars(select(Source.name)).all())
    assert NVD_SOURCE_NAME in names
    assert KEV_SOURCE_NAME not in names


def test_nvd_multi_cve_makes_one_request_each(session) -> None:
    fetcher = FakeNvdFetcher(
        payloads={
            "CVE-2021-44228": _nvd_payload_for("CVE-2021-44228"),
            "CVE-2014-0160": _nvd_payload_for("CVE-2014-0160"),
        }
    )
    report = ingest_nvd_cves(session, fetcher, ["CVE-2021-44228", "CVE-2014-0160"])

    assert len(fetcher.calls) == 2, "NVD answers one CVE per request"
    assert report.records_inserted == 2
    assert len(report.run_ids) == 2, "one audit row per fetch attempt"
    assert _counts(session)["documents"] == 2


def test_nvd_partial_failure_keeps_successful_records(session) -> None:
    """CVE #2 failing must not throw away CVE #1 and #3."""
    fetcher = FakeNvdFetcher(
        payloads={
            "CVE-2021-44228": _nvd_payload_for("CVE-2021-44228"),
            "CVE-2014-0160": _nvd_payload_for("CVE-2014-0160"),
        },
        errors={"CVE-9999-9999": HttpStatusError(
            404, "https://example.invalid", "not found"
        )},
    )

    report = ingest_nvd_cves(
        session, fetcher, ["CVE-2021-44228", "CVE-9999-9999", "CVE-2014-0160"]
    )

    assert report.status == "partial"
    assert report.records_inserted == 2
    assert any("CVE-9999-9999" in e for e in report.errors)

    counts = _counts(session)
    assert counts["documents"] == 2, "the two good CVEs are committed"
    # 3 fetch attempts -> 3 audit rows (2 success + 1 failed).
    assert counts["runs"] == 3
    statuses = session.scalars(select(IngestRun.status)).all()
    assert statuses.count("failed") == 1


def test_nvd_all_failures_raises_but_still_audits(session) -> None:
    fetcher = FakeNvdFetcher(
        errors={
            "CVE-1111-1111": HttpTimeoutError("timed out"),
            "CVE-2222-2222": HttpTimeoutError("timed out"),
        }
    )

    with pytest.raises(IngestError, match="failed for every requested CVE"):
        ingest_nvd_cves(session, fetcher, ["CVE-1111-1111", "CVE-2222-2222"])

    assert _counts(session)["documents"] == 0
    assert _counts(session)["runs"] == 2, "both failures are audited"


def test_nvd_empty_cve_list_is_rejected(session) -> None:
    with pytest.raises(IngestError, match="no CVE ids"):
        ingest_nvd_cves(session, FakeNvdFetcher(), [])


def test_nvd_rerun_is_idempotent(session) -> None:
    fetcher = FakeNvdFetcher(payloads={"CVE-2021-44228": _nvd_payload_for("CVE-2021-44228")})
    ingest_nvd_cves(session, fetcher, ["CVE-2021-44228"])
    second = ingest_nvd_cves(session, fetcher, ["CVE-2021-44228"])

    assert second.records_inserted == 0
    assert second.records_updated == 1
    assert _counts(session)["documents"] == 1


# --------------------------------------------------------------------------
# NVD incremental date window
# --------------------------------------------------------------------------

def test_nvd_modification_params_require_valid_range() -> None:
    params = nvd_modification_params(date(2026, 9, 1), date(2026, 10, 1))
    assert params["lastModStartDate"] == "2026-09-01T00:00:00.000Z"
    assert params["lastModEndDate"] == "2026-10-01T23:59:59.000Z"


def test_nvd_modification_range_beyond_120_days_rejected() -> None:
    with pytest.raises(IngestError, match="120"):
        nvd_modification_params(date(2026, 1, 1), date(2026, 6, 1))


def test_nvd_modification_end_before_start_rejected() -> None:
    with pytest.raises(IngestError, match="not be earlier"):
        nvd_modification_params(date(2026, 10, 1), date(2026, 9, 1))


def test_nvd_modifications_ingests_query_result(session) -> None:
    fetcher = FakeNvdFetcher(payloads={"__query__": _nvd_payload_for("CVE-2021-44228")})

    report = ingest_nvd_modifications(
        session, fetcher, since=date(2026, 9, 1), until=date(2026, 10, 1)
    )

    assert report.records_inserted == 1
    sent_params = fetcher.calls[0]
    assert "lastModStartDate" in sent_params
    assert "lastModEndDate" in sent_params
    assert _counts(session)["documents"] == 1


def test_nvd_modifications_is_incremental(session) -> None:
    """Re-running the same window updates in place (the incremental promise)."""
    fetcher = FakeNvdFetcher(payloads={"__query__": _nvd_payload_for("CVE-2021-44228")})
    ingest_nvd_modifications(session, fetcher, since=date(2026, 9, 1), until=date(2026, 10, 1))
    second = ingest_nvd_modifications(session, fetcher, since=date(2026, 9, 1), until=date(2026, 10, 1))

    assert second.records_inserted == 0
    assert second.records_updated == 1
    assert _counts(session)["documents"] == 1


def test_nvd_modifications_limit_sets_results_per_page(session) -> None:
    fetcher = FakeNvdFetcher(payloads={"__query__": _nvd_payload_for("CVE-2021-44228")})
    ingest_nvd_modifications(
        session, fetcher, since=date(2026, 9, 1), until=date(2026, 10, 1), limit=10
    )
    assert fetcher.calls[0]["resultsPerPage"] == "10"


def test_nvd_modifications_fetch_failure_is_audited(session) -> None:
    class Exploding:
        api_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

        def fetch(self, params=None):
            raise HttpStatusError(503, self.api_url, "HTTP 503")

    with pytest.raises(HttpStatusError):
        ingest_nvd_modifications(
            session, Exploding(), since=date(2026, 9, 1), until=date(2026, 10, 1)
        )

    assert _counts(session)["documents"] == 0
    run = session.scalars(select(IngestRun)).one()
    assert run.status == "failed"
    assert run.http_status == 503


# --------------------------------------------------------------------------
# Cross-source coexistence and honesty
# --------------------------------------------------------------------------

def test_kev_and_nvd_coexist_without_colliding(session) -> None:
    ingest_kev(session, FakeKevFetcher())
    fetcher = FakeNvdFetcher(payloads={"CVE-2021-44228": _nvd_payload_for("CVE-2021-44228")})
    ingest_nvd_cves(session, fetcher, ["CVE-2021-44228"])

    # The same CVE may legitimately appear under two different sources, and
    # the unique key is (source_id, external_id), so both rows survive.
    counts = _counts(session)
    assert counts["sources"] == 2
    assert counts["documents"] == 6
    rows = session.scalars(
        select(Document).where(Document.external_id == "CVE-2021-44228")
    ).all()
    assert len(rows) == 2


def test_no_dates_are_fabricated_for_records_without_one(session) -> None:
    """A source that omits a date must yield an empty published_at, not today."""
    payload = json.loads(json.dumps(KEV_FIXTURE))
    del payload["vulnerabilities"][0]["dateAdded"]

    ingest_kev(session, FakeKevFetcher(payload=payload))

    doc = session.scalar(
        select(Document).where(
            Document.external_id == payload["vulnerabilities"][0]["cveID"]
        )
    )
    assert doc.published_at == "", "missing source date must stay empty"


def test_report_status_transitions(session) -> None:
    clean = IngestReport(source_name="s", records_inserted=3)
    assert clean.status == "success"

    partial = IngestReport(source_name="s", records_inserted=3, errors=("x",))
    assert partial.status == "partial"

    failed = IngestReport(source_name="s", errors=("x",))
    assert failed.status == "failed"


def test_report_summary_is_informative(session) -> None:
    report = IngestReport(
        source_name="s", records_inserted=2, records_updated=1,
        chunks=7, errors=("bad record",),
    )
    summary = report.summary()
    assert "3 written" in summary
    assert "2 new" in summary
    assert "1 updated" in summary
    assert "7 chunks" in summary
    assert "partial" in summary


def test_merged_report_sums_counts() -> None:
    a = IngestReport(source_name="s", records_inserted=1, chunks=2, run_ids=(1,))
    b = IngestReport(source_name="s", records_inserted=2, chunks=3, run_ids=(2,))
    merged = a.merged_with(b)
    assert merged.records_inserted == 3
    assert merged.chunks == 5
    assert merged.run_ids == (1, 2)


def test_payload_digest_is_order_insensitive() -> None:
    """Digest identifies the payload content, not its key order on the wire."""
    assert payload_digest({"a": 1, "b": 2}) == payload_digest({"b": 2, "a": 1})
    assert payload_digest({"a": 1}) != payload_digest({"a": 2})
