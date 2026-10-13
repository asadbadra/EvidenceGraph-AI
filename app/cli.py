"""Simple CLI for Phase 0.

Usage:
    python -m app.cli ingest [--file data/sample/advisories.json]
    python -m app.cli ask "Which products are affected by CVE-2021-44228?"
    python -m app.cli list

The `ask` command uses the configured LLM provider. Set LLM_PROVIDER=mock
in the environment to run offline with a deterministic stub (useful for demos
without API keys; the stub returns a fixed placeholder answer).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.db import Chunk, Document, Source, init_db, make_engine, make_session_factory
from app.ingestion.loader import load_advisories
from app.llm.client import FakeLLMClient, LLMClient, LLMError, build_llm_client
from app.pipelines.baseline import BaselineRAG
from app.retrieval.retriever import Retriever


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


def cmd_ingest(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings.database_url)
    init_db(engine)
    session = make_session_factory(engine)()
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
    return 0


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evidencegraph", description="EvidenceGraph AI CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Load a JSON fixture into SQLite")
    p_ingest.add_argument(
        "--file",
        default="data/sample/advisories.json",
        help="Path to advisory fixture JSON",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_ask = sub.add_parser("ask", help="Run the Baseline RAG pipeline")
    p_ask.add_argument("question", help="Research question")
    p_ask.set_defaults(func=cmd_ask)

    p_list = sub.add_parser("list", help="List ingested documents")
    p_list.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    args = build_parser().parse_args(argv)
    return int(args.func(settings, args))


if __name__ == "__main__":
    raise SystemExit(main())
