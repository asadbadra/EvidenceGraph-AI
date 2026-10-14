"""Command-line interface.

Usage:
    # Fixture ingest (offline, unchanged from Phase 0)
    python -m app.cli ingest --file data/sample/advisories.json

    # Live CISA KEV catalog (network)
    python -m app.cli ingest --source kev

    # Live NVD, explicit CVE ids (network)
    python -m app.cli ingest --source nvd --cve CVE-2021-44228 --cve CVE-2022-22965

    # Live NVD, incremental window (network; NVD requires BOTH dates, <=120 days)
    python -m app.cli ingest --source nvd --since 2026-09-01 --until 2026-10-01

    # Continue from the last successful sync (per-source watermark)
    python -m app.cli ingest --source nvd --sync
    python -m app.cli ingest --source kev --sync

    python -m app.cli ask "Which products are affected by CVE-2021-44228?"
    python -m app.cli list
    python -m app.cli runs

`--source fixture` (the default) reads a local JSON file and makes no network
requests; it is never recorded as a live fetch in the audit table. The `ask`
command uses the configured LLM provider; set LLM_PROVIDER=mock to run
offline with a deterministic stub.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.db import (
    Chunk,
    Document,
    IngestRun,
    MigrationError,
    Source,
    SyncState,
    init_db,
    make_engine,
    make_session_factory,
)
from app.ingestion.fetchers import (
    FetchError,
    KevFetcher,
    NvdFetcher,
    build_http_client,
)
from app.ingestion.http_client import HttpError
from app.ingestion.loader import load_advisories
from app.ingestion.parsers import KEV_SOURCE_NAME, NVD_SOURCE_NAME
from app.ingestion.pipeline import (
    IngestError,
    IngestReport,
    ingest_kev,
    ingest_kev_sync,
    ingest_nvd_cves,
    ingest_nvd_modifications,
    ingest_nvd_sync,
    get_sync_watermark,
)
from app.llm.client import FakeLLMClient, LLMClient, LLMError, build_llm_client
from app.pipelines.baseline import BaselineRAG
from app.retrieval.retriever import Retriever
from app.verification.judge import LLMJudge, RuleBasedJudge
from app.verification.pipeline import VerifiedRAG, make_chunk_exists


def _make_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider.lower() in {"mock", "fake", "offline"}:
        return FakeLLMClient(
            model="offline-mock",
            scripted_response=(
                "Offline mock answer: configure a real LLM provider in .env for "
                "generated responses. [1]"
            ),
        )
    return build_llm_client(settings)


def _print_result(result) -> None:
    print(f"\nModel: {result.model}")
    print(f"Retrieved passages: {len(result.retrieved)}")
    for i, chunk in enumerate(result.retrieved, start=1):
        preview = chunk.text.replace("\n", " ")[:90]
        print(f"  [{i}] {chunk.external_id} (score {chunk.score}) {chunk.source_url}")
        print(f"      {preview}...")
    print("\nAnswer:")
    print(result.answer_text)
    print("\nCitations (format/provenance validated only):")
    if not result.citations and not result.invalid_citation_markers:
        print("  (none)")
    for citation in result.citations:
        print(f"  {citation.marker} -> {citation.external_id} | {citation.title}")
        print(f"       {citation.source_url}")
    for marker in result.invalid_citation_markers:
        print(f"  {marker} -> INVALID (no retrieved chunk with that number)")
    if result.invalid_citation_markers:
        print(
            "\nWARNING: answer contains citation markers that do not match any "
            "retrieved passage. Treat those statements as unverified."
        )
    print(
        "\nNote: citations are validated for format and provenance only. "
        "Evidence-support verification is not performed by this pipeline."
    )


def _parse_cli_date(raw: str, flag: str) -> date:
    """Parse a YYYY-MM-DD CLI date, or exit with a clear message."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        print(f"ERROR: {flag} must be YYYY-MM-DD, got {raw!r}", file=sys.stderr)
        raise SystemExit(1) from None


def _report_allows_silence(report: IngestReport) -> None:
    """Print per-record problems so a partial run is never silent."""
    for problem in report.errors:
        print(f"  ! {problem}", file=sys.stderr)


def cmd_ingest(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    session = make_session_factory(engine)()

    source = args.source

    # ---- Option validation: reject combinations the chosen source cannot
    # support, rather than silently ignoring a flag the user asked for.
    if source != "nvd" and (args.since or args.until):
        print(
            "ERROR: --since/--until are only supported with --source nvd. "
            "The CISA KEV catalog is a single static snapshot with no "
            "server-side date filtering.",
            file=sys.stderr,
        )
        return 1
    if source != "nvd" and args.cves:
        print(
            "ERROR: --cve is only supported with --source nvd "
            "(NVD is queried per CVE id).",
            file=sys.stderr,
        )
        return 1
    if args.cves and (args.since or args.until):
        print(
            "ERROR: --cve and --since/--until are alternative NVD query modes; "
            "use one or the other.",
            file=sys.stderr,
        )
        return 1
    if args.sync:
        if source == "fixture":
            print(
                "ERROR: --sync is only supported with --source kev or "
                "--source nvd. A local fixture has no remote watermark to "
                "synchronize against.",
                file=sys.stderr,
            )
            return 1
        if args.cves:
            print(
                "ERROR: --sync and --cve are alternative NVD query modes; "
                "--cve fetches named records, --sync fetches everything "
                "modified since the last successful sync.",
                file=sys.stderr,
            )
            return 1
        if args.since or args.until:
            print(
                "ERROR: --sync computes its own window from the stored "
                "watermark, so it cannot be combined with --since/--until. "
                "Use one or the other.",
                file=sys.stderr,
            )
            return 1
        if args.limit is not None:
            # A limited run stops before covering the whole window, so the
            # watermark must not advance. Refusing is clearer than running
            # and silently never advancing.
            print(
                "ERROR: --sync and --limit cannot be combined. A limited run "
                "stops before covering the window, so the sync watermark "
                "could not be advanced.",
                file=sys.stderr,
            )
            return 1
    if source == "nvd" and not args.cves and not (args.since and args.until) and not args.sync:
        print(
            "ERROR: --source nvd needs either one or more --cve ids, or BOTH "
            "--since and --until (NVD requires the pair; max 120 days), or "
            "--sync to continue from the last successful sync.",
            file=sys.stderr,
        )
        return 1
    if args.limit is not None and args.limit <= 0:
        print("ERROR: --limit must be a positive integer", file=sys.stderr)
        return 1

    # ---- Fixture path: unchanged Phase 0 behaviour, no network.
    if source == "fixture":
        path = Path(args.file)
        if not path.exists():
            print(f"ERROR: fixture not found: {path}", file=sys.stderr)
            return 1
        report = load_advisories(
            session,
            path,
            chunk_max_chars=settings.chunk_max_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
        )
        print(
            f"Ingested {report.documents} documents and {report.chunks} chunks "
            f"from {path} (source_id={report.source_id})."
        )
        print("Note: this was a local fixture load, not a live fetch.")
        return 0

    # ---- Live paths: build the shared HTTP client once, close it on exit.
    client = build_http_client(settings)
    try:
        if source == "kev":
            fetcher = KevFetcher(client, feed_url=settings.kev_feed_url)
            if args.sync:
                report = ingest_kev_sync(
                    session,
                    fetcher,
                    chunk_max_chars=settings.chunk_max_chars,
                    chunk_overlap_chars=settings.chunk_overlap_chars,
                )
            else:
                report = ingest_kev(
                    session,
                    fetcher,
                    chunk_max_chars=settings.chunk_max_chars,
                    chunk_overlap_chars=settings.chunk_overlap_chars,
                    limit=args.limit,
                )
        else:  # nvd
            fetcher = NvdFetcher(
                client,
                api_url=settings.nvd_api_url,
                api_key=settings.nvd_api_key,
                min_request_interval_seconds=settings.nvd_min_request_interval_seconds,
            )
            if args.sync:
                report = ingest_nvd_sync(
                    session,
                    fetcher,
                    chunk_max_chars=settings.chunk_max_chars,
                    chunk_overlap_chars=settings.chunk_overlap_chars,
                )
            elif args.cves:
                report = ingest_nvd_cves(
                    session,
                    fetcher,
                    args.cves,
                    chunk_max_chars=settings.chunk_max_chars,
                    chunk_overlap_chars=settings.chunk_overlap_chars,
                )
            else:
                report = ingest_nvd_modifications(
                    session,
                    fetcher,
                    since=_parse_cli_date(args.since, "--since"),
                    until=_parse_cli_date(args.until, "--until"),
                    chunk_max_chars=settings.chunk_max_chars,
                    chunk_overlap_chars=settings.chunk_overlap_chars,
                    limit=args.limit,
                )
    except (HttpError, IngestError, FetchError) as exc:
        # Already audited in ingest_runs; report clearly, never as a traceback.
        print(f"INGEST ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    print(report.summary())
    _report_allows_silence(report)
    if report.errors:
        print(
            "\nWARNING: this run was partial. See the messages above and the "
            "ingest_runs table for the authoritative record.",
            file=sys.stderr,
        )
    if args.sync:
        _report_sync_watermark(session, source)
    return 0


def _report_sync_watermark(session, source: str) -> None:
    """Print the sync watermark for the source just synchronized.

    The follow-up hint is per-source because the two sources genuinely
    differ: NVD's watermark narrows the next query, KEV's only records
    freshness (KEV has no server-side date filter, so every sync re-reads
    the whole catalog).
    """
    name = KEV_SOURCE_NAME if source == "kev" else NVD_SOURCE_NAME
    watermark = get_sync_watermark(session, name)
    if watermark is None:
        print(f"\nSync watermark for {name}: NEVER SYNCED")
        return
    print(f"\nSync watermark for {name}: {watermark.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    if source == "kev":
        print(
            "  KEV is a static snapshot with no date filter, so the next "
            "`ingest --source kev --sync` re-reads the whole catalog."
        )
    else:
        print(
            "  Next `ingest --source nvd --sync` will fetch only what "
            "changed since then."
        )


def cmd_ask(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    session = make_session_factory(engine)()
    retriever = Retriever(session)
    retriever.refresh()
    if retriever.is_empty:
        print("ERROR: no documents ingested yet. Run `ingest` first.", file=sys.stderr)
        return 1
    try:
        llm = _make_llm(settings)
    except LLMError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    pipeline = BaselineRAG(retriever, llm, top_k=settings.retrieval_top_k)
    try:
        result = pipeline.run(args.question)
    except LLMError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0


def _print_verified_result(result) -> None:
    """Print the answer plus its claim-level verification record."""
    print(f"\nModel: {result.model}")
    print(f"Retrieved passages: {len(result.retrieved)}")
    for i, chunk in enumerate(result.retrieved, start=1):
        preview = chunk.text.replace("\n", " ")[:90]
        print(f"  [{i}] {chunk.external_id} (score {chunk.score}) {chunk.source_url}")
        print(f"      {preview}...")

    print("\nAnswer (reported verbatim, NOT revised by the verifier):")
    print(result.answer_text)

    if result.invalid_citation_markers:
        print("\nInvalid citation markers:")
        for marker in result.invalid_citation_markers:
            print(f"  {marker} -> no retrieved chunk with that number")

    print("\nClaim-level verification:")
    if not result.verdicts:
        print("  (no factual claims extracted from this answer)")
    for verdict in result.verdicts:
        label = verdict.label.value
        print(f"  [{label}] {verdict.claim.text}")
        if verdict.evidence_chunk_ids:
            ids = ", ".join(str(i) for i in verdict.evidence_chunk_ids)
            print(f"      evidence chunk ids: {ids}")
        if verdict.rationale:
            print(f"      rationale: {verdict.rationale}")
        for anomaly in verdict.anomalies:
            print(f"      ! {anomaly}")

    summary = result.summary
    print(
        f"\nSummary: {summary.total} claim(s) -- "
        f"{summary.supported} supported, "
        f"{summary.contradicted} contradicted, "
        f"{summary.insufficient_evidence} insufficient_evidence, "
        f"{summary.unverifiable} unverifiable, "
        f"{summary.with_anomalies} with anomalies."
    )
    if summary.total and summary.abstentions:
        print(
            "\nNote: abstention verdicts mean the corpus could not settle the "
            "claim. They are not confirmations."
        )
    print(
        "\nNote: verification is post-generation and claim-level. It does not "
        "edit the answer; it reports what the corpus supports."
    )


def cmd_verify(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    session = make_session_factory(engine)()
    retriever = Retriever(session)
    retriever.refresh()
    if retriever.is_empty:
        print("ERROR: no documents ingested yet. Run `ingest` first.", file=sys.stderr)
        return 1
    try:
        llm = _make_llm(settings)
    except LLMError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    judge = RuleBasedJudge() if args.judge == "rules" else LLMJudge(llm)
    # Real-database check: every verdict's evidence ids must resolve to
    # stored chunks, not merely be plausible integers.
    pipeline = VerifiedRAG(
        retriever,
        llm,
        top_k=settings.retrieval_top_k,
        judge=judge,
        chunk_is_known=make_chunk_exists(session),
    )
    try:
        result = pipeline.run(args.question)
    except LLMError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_verified_result(result)
    return 0


def cmd_list(settings: Settings, _args: argparse.Namespace) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    session = make_session_factory(engine)()
    docs = session.execute(
        select(Document.external_id, Document.title, Document.source_url)
        .order_by(Document.external_id)
    ).all()
    if not docs:
        print("No documents ingested yet.")
        return 0
    chunk_total = session.scalar(select(func.count()).select_from(Chunk)) or 0
    source_count = session.scalar(select(func.count()).select_from(Source)) or 0
    print(f"{len(docs)} documents, {chunk_total} chunks, {source_count} source(s):\n")
    for external_id, title, url in docs:
        print(f"  {external_id}  {title}")
        print(f"      {url}")
    return 0


def _print_sync_state(session) -> None:
    """Print one line per source's sync watermark, before the audit trail.

    A missing row is reported as "never synced" rather than omitted: the
    distinction between "we synced at time T" and "we have never synced" is
    exactly what an operator needs to judge how current the local copy is.
    """
    pairs = session.execute(
        select(Source.name, SyncState.watermark_at, SyncState.updated_at)
        .join(SyncState, SyncState.source_id == Source.id)
        .order_by(Source.name)
    ).all()
    if not pairs:
        return
    print("Sync watermarks:")
    for name, watermark, updated in pairs:
        if watermark is None:
            mark = "never synced (NULL watermark)"
        else:
            mark = watermark.strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"  {name}: watermark={mark} (row written {updated:%Y-%m-%d %H:%M:%S})")
    print()


def cmd_runs(settings: Settings, _args: argparse.Namespace) -> int:
    """Show the ingest audit trail (one row per fetch attempt)."""
    engine = make_engine(settings.database_url)
    init_db(engine)
    session = make_session_factory(engine)()
    rows = session.execute(
        select(
            IngestRun.id,
            IngestRun.retrieved_at,
            IngestRun.fetch_url,
            IngestRun.http_status,
            IngestRun.status,
            IngestRun.records_fetched,
            IngestRun.records_inserted,
            IngestRun.records_updated,
            IngestRun.content_sha256,
            IngestRun.error_message,
        ).order_by(IngestRun.id)
    ).all()

    _print_sync_state(session)

    if not rows:
        print("No ingest runs recorded yet.")
        return 0
    print(f"{len(rows)} ingest run(s):\n")
    for (
        run_id, when, url, status_code, status, fetched, inserted, updated,
        digest, error,
    ) in rows:
        stamp = when.strftime("%Y-%m-%d %H:%M:%S") if when else "?"
        http = str(status_code) if status_code is not None else "-"
        short_digest = (digest or "-")[:12]
        print(
            f"  #{run_id} {stamp} {status:<7} HTTP {http:<4} "
            f"fetched={fetched} inserted={inserted} updated={updated} "
            f"sha256={short_digest}"
        )
        print(f"      {url}")
        if error:
            print(f"      error: {error[:200]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evidencegraph", description="EvidenceGraph AI CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Load advisories from a fixture or a live source")
    p_ingest.add_argument(
        "--source",
        choices=["fixture", "kev", "nvd"],
        default="fixture",
        help="Where to ingest from: 'fixture' reads a local JSON file "
        "(offline); 'kev' fetches the CISA KEV catalog; 'nvd' queries the "
        "NVD API. Default: fixture.",
    )
    p_ingest.add_argument(
        "--file",
        default="data/sample/advisories.json",
        help="Path to advisory fixture JSON (only used with --source fixture)",
    )
    p_ingest.add_argument(
        "--cve",
        action="append",
        dest="cves",
        default=[],
        metavar="CVE-ID",
        help="NVD only: a CVE id to fetch (repeatable). "
        "NVD answers one CVE per request.",
    )
    p_ingest.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Ingest at most N source records (fixture/kev/nvd-date-window).",
    )
    p_ingest.add_argument(
        "--since",
        default=None,
        metavar="YYYY-MM-DD",
        help="NVD only: start of a 'last modified' window. Requires --until.",
    )
    p_ingest.add_argument(
        "--until",
        default=None,
        metavar="YYYY-MM-DD",
        help="NVD only: end of a 'last modified' window (max 120 days).",
    )
    p_ingest.add_argument(
        "--sync",
        action="store_true",
        help="Continue from the stored per-source sync watermark instead of "
        "an explicit window. NVD: fetch only CVEs modified since the "
        "watermark. KEV: re-fetch the whole catalog (KEV is a static "
        "snapshot with no date filter). The watermark advances only on a "
        "fully successful run, so a partial or failed sync is retried "
        "safely by running --sync again. Cannot be combined with --since/"
        "--until, --cve, or --limit.",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_ask = sub.add_parser("ask", help="Run the Baseline RAG pipeline")
    p_ask.add_argument("question", help="Research question")
    p_ask.set_defaults(func=cmd_ask)

    p_verify = sub.add_parser(
        "verify",
        help="Run the Verified RAG pipeline: baseline generation + claim verification",
    )
    p_verify.add_argument("question", help="Research question")
    p_verify.add_argument(
        "--judge",
        choices=["llm", "rules"],
        default="llm",
        help=(
            "Which judge to use. 'llm' is the NLI judge (default; needs a "
            "configured provider). 'rules' is the deterministic lexical "
            "fallback, for offline runs and as a non-LLM comparison point -- "
            "it is a test stand-in, not an accuracy claim."
        ),
    )
    p_verify.set_defaults(func=cmd_verify)

    p_list = sub.add_parser("list", help="List ingested documents")
    p_list.set_defaults(func=cmd_list)

    p_runs = sub.add_parser(
        "runs", help="Show the ingest audit trail (one row per fetch attempt)"
    )
    p_runs.set_defaults(func=cmd_runs)
    return parser


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(settings, args))
    except MigrationError as exc:
        # Migration problems must be reported clearly, never as a traceback,
        # and must not modify existing data (ensure_schema guarantees that).
        print(f"SCHEMA ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
