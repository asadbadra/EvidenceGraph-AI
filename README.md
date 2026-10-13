# EvidenceGraph AI

Research-oriented OSINT tool that answers research questions from public cyber
advisories with traceable citations. This repository is under phased
development; **Phase 0** (current) implements a minimal, working **Baseline RAG**
pipeline over a small committed sample corpus.

> **Scope note (important for honesty):** Phase 0 validates citation *format and
> provenance* only — a citation marker must refer to a passage that was actually
> retrieved. It does **not** verify that the cited passage supports the claim
> around it. Claim-level evidence verification is a later phase.

## What works in Phase 0

- Ingest 5 real advisory records (from the public CISA KEV feed) into SQLite
  with full provenance (source URL, published date, metadata).
- Deterministic sentence-aware chunking with overlap.
- Lexical retrieval (BM25, dependency-free) with scores and provenance.
- Baseline RAG: prompt → configurable LLM provider → answer with citations.
- Citation validation against the retrieved set (invalid markers flagged).
- Offline mode via a deterministic mock LLM — no API key needed.
- Pytest suite: 34 tests, no network access required.

Not built yet: Streamlit UI, evidence graph, claim extraction/verification,
evaluation harness, Docker, FastAPI routes.

## Requirements

- Python 3.11+ (developed on 3.13.8)
- Only needed at runtime: `pydantic`, `pydantic-settings`, `sqlalchemy`, `httpx`
  (FastAPI/uvicorn are declared for later phases).
- Tests: `pytest`

```bash
pip install -e ".[dev]"     # or: pip install pydantic pydantic-settings sqlalchemy httpx pytest
```

## Quick start (offline, no API key)

```bash
python -m app.cli ingest                    # load data/sample/advisories.json
python -m app.cli list                      # show ingested documents
LLM_PROVIDER=mock python -m app.cli ask "What does the Log4j2 advisory say?"
```

`LLM_PROVIDER=mock` works as an inline shell variable (bash/zsh) or as a line
inside `.env` (recommended on Windows PowerShell, where inline `VAR=x cmd`
syntax is not supported).

## Using a real LLM provider

```bash
cp .env.example .env        # then edit values; .env is git-ignored
python -m app.cli ask "Which products are affected by CVE-2023-34362?"
```

Any OpenAI-compatible `/chat/completions` endpoint works (`LLM_BASE_URL`,
`LLM_API_KEY`, `LLM_MODEL`). Check the provider's current pricing and rate
limits yourself — nothing here assumes a free tier.

## Tests

```bash
python -m pytest -v
```

## Security posture (Phase 0)

- API keys come from environment variables only; `.env` is git-ignored and
  `.env.example` contains placeholders.
- Retrieved document text is treated as untrusted: it is fenced in
  `<untrusted_retrieved_content>` tags with explicit instructions to ignore
  instructions found inside, and embedded fence terminators are stripped.
- The model cannot invent citation IDs: markers outside the retrieved range are
  reported as invalid and surfaced as a warning.
- Only public advisory data is stored; no personal data is collected.

## Repository layout

```
app/
  config.py          env-driven settings (pydantic-settings)
  db.py              SQLite schema (sources, documents, chunks)
  schemas.py         shared pydantic models (chunks, citations, results)
  security.py        citation validation + untrusted-input fencing
  cli.py             command-line entry point
  ingestion/         fixture loader + chunking
  retrieval/         BM25 index + retriever
  llm/               provider abstraction + prompt templates
  pipelines/         baseline.py (Baseline RAG)
data/sample/         5 committed CISA KEV records (real public data)
tests/               pytest suite (offline)
```
