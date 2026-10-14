# EvidenceGraph AI

Research-oriented OSINT tool that answers research questions from public cyber
advisories with traceable citations. Under phased development.

- **Phase 0** — Baseline RAG over a committed sample corpus.
- **Phase 1** — a real ingestion pipeline: public feeds → normalized records →
  SQLite, with provenance, an audit trail, and incremental sync.
- **Phase 2** — claim-level evidence verification (`verify` command), plus a
  24-question hand-labelled evaluation pilot.

> **Scope note (important for honesty):** two pipelines exist and they do
> different things. `ask` runs the **baseline**, which validates citation
> *format and provenance* only — a marker must refer to a passage that was
> actually retrieved — and does **not** check that a cited passage supports
> the claim beside it. `verify` runs the **verified** pipeline, which adds a
> post-generation claim-level check and reports per-claim verdicts alongside
> the unchanged answer text.
>
> That check is a mechanism, not a demonstrated improvement. No experiment
> has been run showing it makes reports more accurate, and no accuracy,
> cost, or performance figure should be inferred from this repository. The
> unit tests prove the mechanism behaves as specified; whether the verifier
> agrees with a human on real text is unmeasured beyond the 24-question
> pilot, which is too small to support any general claim. Do not describe
> this tool as verified, accurate, or benchmarked.

## What works

**Corpus & retrieval (Phase 0)**
- Deterministic sentence-aware chunking with overlap.
- Lexical retrieval (BM25, dependency-free) with scores and provenance.
- Baseline RAG: prompt → configurable LLM provider → answer with citations.
- Citation validation against the retrieved set (invalid markers flagged).
- Offline mode via a deterministic mock LLM — no API key needed.

**Ingestion (Phase 1, Steps 1–5)**
- SQLite schema with additive, data-safe migrations: `documents.retrieved_at`,
  a unique `(source_id, external_id)` index, an `ingest_runs` audit table,
  `documents.ingest_run_id` linking each row to the fetch that wrote it, and a
  `sync_state` table holding one last-successful-sync watermark per source.
  `ensure_schema()` refuses to migrate rather than risk duplicates, and never
  deletes or rebuilds existing tables.
- Normalized `AdvisoryRecord` model plus pure parsers for two official sources:
  the **CISA KEV catalog** and the **NVD API 2.0**. Parsers do no I/O.
- HTTP fetchers with explicit timeouts, bounded retries, exponential backoff,
  and `Retry-After` handling. Typed errors for timeouts, network failures,
  403/503, and malformed JSON.
- An ingestion pipeline that fetches, parses, validates, and persists —
  recording one audit row per fetch attempt, including failed ones.
- **Idempotent** re-ingestion: reruns UPSERT on the unique index, preserving
  document IDs (so existing citations stay valid) and never duplicating rows.
- CLI live ingest for KEV, and for NVD by explicit CVE id or by
  "last modified" date window (NVD requires both dates, max 120 days).
  Date-window ingests follow NVD pagination to completion rather than
  stopping at the first 2,000-record page.
- **Incremental synchronization (`--sync`)** with a per-source watermark.
  NVD fetches only what changed since the last successful sync; KEV re-reads
  its whole catalog (KEV is a static snapshot with no date filter). The
  watermark advances **only** on a fully successful run, so a partial or
  failed sync is safe to retry with `--sync` and loses nothing.

**Claim-level verification (Phase 2, Stages 2.1–2.6)**
- Claim extraction from a generated answer, with a character span back to the
  exact source sentence and the citation markers each sentence carried.
- Four verdict labels: `supported`, `contradicted`, `insufficient_evidence`
  (we looked and the corpus is silent), and `unverifiable` (not a factual
  assertion, or nothing to check).
- A **no-fabrication invariant**: support and contradiction require at least
  one evidence id, every id must belong to that claim's candidate set, and
  abstentions carry no ids at all. It is enforced on construction, so an
  unsupported `supported` verdict is structurally impossible rather than
  merely discouraged.
- Candidate evidence sets built from two independent sources — the passages a
  sentence cited, plus a fresh retrieval on the sentence's own text —
  deduplicated by chunk id, validated against real database records, and
  capped in size.
- Two interchangeable judges: an LLM NLI judge (temperature 0, sees only the
  claim and the evidence, never the generated answer) and a deterministic
  rule-based fallback that exists for offline testing and as a non-LLM
  comparison point. The fallback approximates **support** by token overlap and
  detects a mismatched CVE id; it deliberately **never** produces
  `contradicted`, because it cannot read polarity in the evidence. A claim
  containing a negation always abstains.
- **Safe degradation**: malformed judge output, an unknown label, a provider
  failure, or a judge citing chunks it was never shown all resolve to
  `unverifiable` — never to `supported`. Ids outside the candidate set are
  dropped before the evidence check.
- A `VerifiedRAG` pipeline that generates **exactly** as the baseline does
  (same retriever, same prompt, same model) and then verifies each claim
  after the fact. It reports the answer verbatim and never rewrites it.
- An additive evaluation schema (`eval_runs`, `eval_results`, `verif_claims`)
  plus a shared A/B harness that runs both systems over the same questions
  and stores results so every reported number is recomputable.
- A 24-question hand-labelled **pilot** set covering six categories, with
  metrics that keep "what the verifier said" separate from "whether the
  verifier was right".

Not built yet: Streamlit UI, evidence graph, Docker, FastAPI routes. Token
usage is captured from the provider when it reports any (Stage 2.8); when it
does not, the record says "unavailable" rather than zero, and no cost is
estimated unless explicit prices are configured.

## Requirements

- Python 3.11+ (developed on 3.13.8)
- Runtime: `pydantic`, `pydantic-settings`, `sqlalchemy`, `httpx`
  (FastAPI/uvicorn are declared for later phases).
- Tests: `pytest`

```bash
pip install -e ".[dev]"     # or: pip install pydantic pydantic-settings sqlalchemy httpx pytest
```

## Quick start (offline, no API key)

```bash
python -m app.cli ingest        # load data/sample/advisories.json (local fixture)
python -m app.cli list          # show ingested documents
python -m app.cli runs          # show the ingest audit trail
LLM_PROVIDER=mock python -m app.cli ask "What does the Log4j2 advisory say?"
LLM_PROVIDER=mock python -m app.cli verify "What does the Log4j2 advisory say?" --judge rules
```

The `verify` command runs the same generation as `ask` and then checks each
claim. `--judge rules` swaps only the *judge* for the deterministic lexical
one — generation still calls the configured provider, so a key (or
`LLM_PROVIDER=mock`) is still required. The default `--judge llm` uses the
NLI judge and likewise needs a configured provider (or `LLM_PROVIDER=mock`,
whose fixed output will parse as malformed and be reported as `unverifiable`
— an honest outcome, not an error).

The default `ingest` reads a **local file** and makes no network requests. It
is labeled as a fixture load in the output and is *not* recorded as a live
fetch in `ingest_runs` — bundled sample data is never presented as newly
fetched.

`LLM_PROVIDER=mock` works as an inline shell variable (bash/zsh) or as a line
inside `.env` (recommended on Windows PowerShell, where inline `VAR=x cmd`
syntax is not supported).

## Live ingestion (network)

Copying `.env.example` to `.env` is recommended first; the NVD API key is
optional but raises your rate limit.

```bash
cp .env.example .env

# CISA KEV catalog — one static JSON file, no auth, CC0 1.0.
python -m app.cli ingest --source kev

# NVD — one request per CVE id (NVD answers a single CVE per request).
python -m app.cli ingest --source nvd --cve CVE-2021-44228 --cve CVE-2022-22965

# NVD — incremental "last modified" window. BOTH dates are required and the
# span may not exceed 120 consecutive days.
python -m app.cli ingest --source nvd --since 2026-09-01 --until 2026-09-30

# Continue from the last successful sync (per-source watermark). NVD fetches
# only CVEs modified since that point; KEV re-reads its whole catalog.
python -m app.cli ingest --source nvd --sync
python -m app.cli ingest --source kev --sync

# Ingest at most N records from the source.
python -m app.cli ingest --source kev --limit 10
```

Flags that a source cannot honor are rejected with an explanation rather than
silently ignored: `--since/--until` and `--cve` are NVD-only, because the KEV
catalog is a single static snapshot with no server-side date filtering and no
per-record query.

`--sync` cannot be combined with `--since/--until` (it computes its own
window), `--cve` (a different NVD query mode), or `--limit` (a limited run
stops before covering the window, so the watermark could not advance).

### Incremental sync & watermarks

Each source has a **last-successful-sync watermark** in the `sync_state`
table. For NVD it is the `lastModEndDate` covered by the last all-successful
window, so the next `--sync` asks only for what changed since then — exactly
the incremental recipe NIST documents. For KEV it records *when the catalog
was last read successfully*; KEV is one static snapshot with no server-side
date filter, so its watermark cannot narrow a query and every KEV sync
re-reads the whole catalog.

The watermark advances **only on a fully successful run**:

- **Not on `partial`.** NVD pages are ordered by publication date, not
  modification date, so after a failed page there is no safe point in the
  window to resume from. Advancing would silently and permanently skip the
  records on the pages that failed.
- **Not on `failed`.** Obviously nothing was covered.
- **Not on `--limit`.** A limited run stops before covering the window.

Because ingestion is an idempotent UPSERT, *not* advancing is safe and free:
the next `--sync` re-covers the same window and updates rows in place. That
is what makes a failed sync retryable with no data loss and no manual
bookkeeping — just run `--sync` again.

Two deliberate details:

- **Inclusive boundary.** The next window starts *at* the watermark, so a
  record modified at that exact instant is re-fetched. Harmless, and the
  asymmetry is the point: a duplicate costs nothing, whereas a miss costs a
  record permanently absent from an evidence corpus.
- **Watermarks are monotonically non-decreasing.** A clock that jumps
  backwards, or a retried older window, cannot lower the mark.

An **empty** window *does* advance the watermark: "nothing changed in this
window" is a successful, complete answer, and refusing to record it would
leave the watermark stuck forever on a quiet source.

A watermark older than NVD's 120-day per-query limit is **refused with an
actionable message** rather than silently clamped. Clamping would drop every
record older than the clamp point — a quiet data loss in a tool whose thesis
is traceability. Catch up with explicit `--since/--until` windows of at most
120 days each until `--sync` has a short enough window.

```bash
python -m app.cli runs   # also prints each source's sync watermark
```

### Rate limits

Verified against vendor documentation (October 2026):

- **NVD API 2.0** — 5 requests/rolling 30 s without an API key, 50 with one
  (`NVD_API_KEY`, sent in the `apiKey` header). NIST asks clients to sleep
  ~6 s between requests; `NvdFetcher` paces requests accordingly (6 s unkeyed,
  1 s keyed) and honors `Retry-After` on HTTP 429.
- **CISA KEV** — a single static file with no published cap. It is fetched
  once per run with an identifiable User-Agent. The catalog is CC0 1.0;
  reuse must not imply CISA/DHS endorsement, and the CISA logo and DHS seal
  are not used anywhere in this project.

## Using a real LLM provider

```bash
python -m app.cli ask "Which products are affected by CVE-2023-34362?"
```

Any OpenAI-compatible `/chat/completions` endpoint works (`LLM_BASE_URL`,
`LLM_API_KEY`, `LLM_MODEL`). Check the provider's current pricing and rate
limits yourself — nothing here assumes a free tier. A local Ollama model
works the same way: `LLM_BASE_URL=http://localhost:11434/v1` plus any
non-placeholder `LLM_API_KEY` (Ollama ignores it; the client merely refuses
an empty one).

## Token usage & cost estimation (Stage 2.8)

`app/verification/usage.py` records what a completion actually cost in
tokens, and keeps three things strictly apart:

- **Measured** — input/output/total tokens, copied only from the `usage`
  block the provider returns. Never inferred, never defaulted to zero.
- **Estimated** — USD cost, computed only when *both*
  `LLM_PRICE_INPUT_PER_MILLION` and `LLM_PRICE_OUTPUT_PER_MILLION` are
  configured *and* the tokens were provider-reported. It is labelled an
  estimate because it is arithmetic on a price list, not an invoice.
- **Unknowable** — anything the provider omits. A response with no `usage`
  block is recorded as `unavailable` with null counts. Recording `0` would
  look like a measurement while understating spend.

Partial pricing (one price set, not both) is refused rather than silently
applied, and a run's totals are null unless *every* call in it reported
usage — a partial sum must never read as a total. Self-hosted models such
as Ollama have no per-token API charge, so leave both prices unset; cost is
then reported as unavailable, which is correct, because local
electricity/hardware cost is real but is not measured here. No API key,
prompt, or response body is ever stored in a usage record.

The mock provider (`LLM_PROVIDER=mock`) surfaces no usage; offline runs
therefore record `unavailable` and no cost, which is the honest outcome.

## Reproducibility & audit

Every fetch attempt writes one `ingest_runs` row, **including failures**:
fetch URL, timestamp, HTTP status, a SHA-256 of the payload, and counts of
records fetched / parsed / inserted / updated / skipped / failed. A failed
fetch logs the error and writes no documents.

```bash
python -m app.cli runs
```

The SHA-256 is computed over the *canonicalized decoded JSON* (sorted keys),
not the raw bytes on the wire — the fetch layer hands the pipeline decoded
JSON. It still identifies the exact payload version a report was built from.

**Document-to-run traceability.** Each `documents` row records the
`ingest_runs` id of the fetch that last wrote it (`documents.ingest_run_id`),
so you can answer *"which fetch produced this exact row?"* rather than only
*"how many rows did that fetch produce?"*. Rows loaded from a bundled fixture
or predating this column keep a `NULL` run id — they were not live fetches,
and assigning one would be a false provenance claim.

Dates are never invented: if a source omits a publication date, the field
stays empty rather than defaulting to today. This applies to both the live
pipeline and the fixture loader.

### NVD pagination

NVD paginates every response: a single request returns at most 2,000 records
even when `totalResults` is larger. A date-window ingest walks all pages by
advancing `startIndex`, so a window matching 5,000 CVEs ingests all 5,000
rather than silently keeping the first 2,000. Each page is its own
transaction and its own audit row — if page 3 fails, pages 1–2 are already
committed and the run reports `partial`.

## How claim verification works

Verification is **post-generation**. The verified pipeline produces the exact
same answer the baseline would, then checks it; it never rewrites text. This
is a deliberate constraint, because the research question is whether a
*check* improves citation quality — a system that generates differently
cannot answer it.

For each extracted claim the pipeline builds a candidate evidence set from
two independent sources:

1. the passages the sentence actually cited, resolved from the generation-time
   retrieval via its citation markers, and
2. a fresh retrieval on the sentence's own text.

Both matter. Checking only the cited passages cannot tell "the model cited
the wrong passage" from "the corpus is silent on this", and cannot notice
support the model failed to cite at all. Candidates are deduplicated by
chunk id (cited first, since those are the passages under scrutiny),
validated against real database records, and capped so judge cost stays
bounded.

The judge then sees only the claim and those candidates — never the
generated answer, so it cannot anchor on the model's own framing — and
returns one of the four labels with the ids it relied on. Its output is
constrained by construction: an id it was never shown is dropped, and a
`supported` label with no remaining basis downgrades to `unverifiable`.

**What this does not establish.** Unit tests prove the mechanics fire
correctly. They say nothing about whether the verifier agrees with a human
on real text. That is measured, if at all, by judge-vs-human agreement on the
labelled pilot set, reported as its own number.

## The evaluation pilot

`data/sample/eval_questions.json` holds 24 hand-labelled questions — 6
categories × 4: directly answerable, multi-hop, not-in-corpus,
plausible-but-absent, contradiction/misattribution, and non-factual. Gold
labels are at the proposition level and drawn only from the committed
fixtures.

**This is a pilot, not a benchmark.** 24 questions over a 6-record corpus
cannot support generalizable claims, and no accuracy, cost, or performance
figure should be inferred from it. It exists so the harness, the schema, and
the metrics are runnable, reproducible, and honest about what they measure.

Two categories of number are kept strictly apart:

- **Mechanism metrics** (unsupported rate, abstention rate, contradiction
  rate) describe what the verifier *said*. Computable offline; no quality
  claim attaches.
- **Agreement** (judge label vs human gold label) describes whether the
  verifier was *right*, and only over claims that actually have a gold label.
  Claims with no counterpart are excluded from accuracy and reported as
  unmatched, so abstaining on an unlabelled claim cannot inflate the score.

Claims are matched to gold labels by exact normalised text only. Fuzzy
matching would pair a claim with a label it merely resembles — the single most
misleading outcome this system could produce.

Results land in the additive `eval_runs` / `eval_results` / `verif_claims`
tables, so any number in a writeup can be recomputed from stored rows rather
than taken on trust. `gold_label` is nullable and left null by machine runs,
because defaulting it to the judge's own output would make agreement look
perfect by construction.

**What is and is not computed automatically.** Mechanism metrics and citation
quality are computed by the harness from stored rows. Judge-vs-human
agreement is *not* — a machine run stores no gold labels, so
`judge_agreement_for_run` requires the caller to pass the hand-labelled gold
for the run's questions. With no gold (or none that matches) it returns an
`Agreement` whose `matched` is 0 and whose `accuracy` must not be quoted;
with no verified claims at all it returns `None`. Citation quality reports
`verified_citations=None` for **both** systems: the schema records that a
citation exists and is format-valid, but not which verdict backed the
sentence it sits on, so that field stays "unknown" rather than being inferred.

No agreement number has been produced for this repository. Producing one
requires a live run plus hand labels matched to its output.

## Tests

```bash
python -m pytest -v
```

699 tests, all offline. An autouse fixture **fails any test that opens a
real socket**, so the suite cannot silently depend on the network. Integration
tests inject fake fetchers into the real pipeline; fetch-layer tests use
`httpx.MockTransport`.

## Security posture

- API keys come from environment variables only; `.env` is git-ignored and
  `.env.example` contains placeholders. Keys are never printed in errors or
  logs (they travel in headers, not URLs).
- Retrieved document text is treated as untrusted: it is fenced in
  `<untrusted_retrieved_content>` tags with explicit instructions to ignore
  instructions found inside, and embedded fence terminators are stripped.
- The model cannot invent citation IDs: markers outside the retrieved range are
  reported as invalid and surfaced as a warning.
- Only public advisory data is stored; no personal data is collected.
- The claim judge is fenced the same way: retrieved evidence is wrapped as
  untrusted data, the judge sees the claim and candidates but never the
  generated answer, and any unreadable or out-of-range judge output resolves
  to `unverifiable` rather than to a positive verdict. Evidence ids are
  checked against that claim's candidate set and against real database
  records, so a judge cannot cite a chunk it was never shown.

## Repository layout

```
app/
  config.py            env-driven settings (pydantic-settings)
  db.py                SQLite schema + additive migrations (sources,
                       documents, chunks, ingest_runs, sync_state, and the
                       eval_runs/eval_results/verif_claims evaluation tables)
  schemas.py           shared pydantic models (chunks, citations, results)
  security.py          citation validation + untrusted-input fencing
  cli.py               command-line entry point (ingest, ask, verify, list, runs)
  ingestion/
    models.py          normalized AdvisoryRecord (source-agnostic)
    parsers.py         pure parsers: KEV + NVD payloads -> records
    http_client.py     retrying HTTP client (timeouts, backoff, Retry-After)
    fetchers.py        KevFetcher / NvdFetcher (network only)
    pipeline.py        fetch -> parse -> validate -> persist, with auditing
    loader.py          Phase 0 fixture loader (offline, unchanged)
    chunking.py        deterministic sentence-aware chunking
  retrieval/           BM25 index + retriever
  llm/                 provider abstraction + prompt templates
  pipelines/           baseline.py (Baseline RAG)
  verification/
    claims.py          claim extraction with spans back to the source text
    verdicts.py        four verdict labels + the no-fabrication invariant
    evidence.py        candidate sets (cited + claim-level retrieval)
    judge.py           LLM NLI judge + deterministic rule-based fallback
    pipeline.py        VerifiedRAG (baseline generation, then verify)
    metrics.py         mechanism metrics vs judge-human agreement
    harness.py         shared A/B evaluation runner
    usage.py           provider-reported token usage + optional cost estimate
data/sample/           committed CISA KEV + NVD records, and the 24-question
                       pilot set (eval_questions.json)
tests/                 pytest suite (offline)
```

## Data sources & licensing

- **CISA Known Exploited Vulnerabilities Catalog** — public, CC0 1.0.
  https://www.cisa.gov/known-exploited-vulnerabilities-catalog
- **NIST National Vulnerability Database (API 2.0)** — public API; use is
  subject to NVD's published rate limits and terms.
  https://nvd.nist.gov/developers

Records are stored with their source URL and publication date verbatim so any
claim in a generated report can be traced back to the exact public record.
