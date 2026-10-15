"""Thin FastAPI layer over the existing pipelines (application layer, Phase A).

Deliberately minimal: it validates HTTP requests, wires the SAME classes the
CLI uses (`Retriever`, `BaselineRAG`, `VerifiedRAG`, `LLMJudge`,
`make_chunk_exists`, `_make_llm`), and serialises their real output. No
prompt, retrieval, or verification logic lives here -- the research pipeline
remains the single authoritative implementation, runnable unchanged via the
CLI.

Design decisions (kept deliberately boring):
- A FRESH engine/session/retriever/LLM client is built per request. The
  `Retriever` caches its index on the session it was given and SQLAlchemy
  sessions are not thread-safe; per-request construction makes concurrent
  requests safe without shared mutable state. The corpus is tiny and the
  model call dominates latency, so this costs microseconds.
- Response models mirror the pipeline's own types field-for-field
  (`AnswerResult`, `VerifiedAnswerResult`). Nothing is invented: e.g.
  `verified_citations` does not exist here because the schema does not
  record which verdict backed which citation marker.
- Error handling mirrors the CLI: empty corpus -> 409, LLM failures -> 502,
  with no secrets or stack traces in responses.
- Bindings default to localhost (API_HOST/API_PORT env vars); the app never
  configures itself for public exposure.
- The API key is never read into or returned from any response model.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.cli import _make_llm
from app.config import Settings, get_settings
from app.db import init_db, make_engine, make_session_factory
from app.llm.client import LLMError
from app.pipelines.baseline import BaselineRAG
from app.retrieval.retriever import Retriever
from app.security import validate_citations
from app.verification.judge import LLMJudge
from app.verification.pipeline import VerifiedRAG, make_chunk_exists

MAX_QUESTION_CHARS = 2000  # generous for a research question; blocks abuse


# ---- Request/response models: field-for-field mirrors of pipeline output ----


class RetrievedChunkOut(BaseModel):
    marker: int  # 1-based position, matching the answer's [n] citation markers
    chunk_id: int
    external_id: str
    title: str
    source_url: str
    text: str
    score: float


class CitationOut(BaseModel):
    marker: str  # raw marker text as extracted, e.g. "[1]" (mirrors app.schemas.Citation)
    chunk_id: int
    external_id: str
    source_url: str
    title: str


class ClaimVerdictOut(BaseModel):
    claim_index: int
    claim_text: str
    label: str  # supported | contradicted | insufficient_evidence | unverifiable
    evidence_chunk_ids: list[int]
    rationale: str
    anomalies: list[str]


class VerificationSummaryOut(BaseModel):
    total: int
    supported: int
    contradicted: int
    insufficient_evidence: int
    unverifiable: int
    with_anomalies: int
    abstentions: int


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_CHARS,
        description="OSINT question to answer from the ingested corpus.",
    )
    mode: str = Field(
        default="verified",
        description="'baseline' (plain RAG) or 'verified' (RAG + claim-level verification).",
    )


class AskResponse(BaseModel):
    question: str
    mode: str  # "baseline" | "verified"
    answer_text: str
    model: str
    retrieved: list[RetrievedChunkOut]
    citations: list[CitationOut]
    invalid_citation_markers: list[str]
    unsupported_citation_check_performed: bool
    verification: "VerificationOut | None" = None
    notes: list[str] = Field(
        default_factory=list,
        description="Honesty notes surfaced by the pipeline (abstention, post-generation check).",
    )


class VerificationOut(BaseModel):
    verdicts: list[ClaimVerdictOut]
    summary: VerificationSummaryOut


class HealthOut(BaseModel):
    status: str  # "ok" | "degraded"
    database: str
    documents_ingested: int | None = None
    llm_provider: str
    llm_model: str
    detail: str = ""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory; `settings` is injectable for offline tests."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Create tables once at startup (same init the CLI performs). This is
        # the only write the API ever makes to the database. A failure here
        # must not crash-loop the container: /health reports "degraded"
        # instead, and /ask fails with a clear 409/500 until the DB works.
        try:
            init_db(make_engine(settings.database_url))
        except Exception:
            pass
        yield

    app = FastAPI(
        title="EvidenceGraph AI",
        description=(
            "Evidence-grounded OSINT answers over public cyber advisories. "
            "Research prototype: a 24-question pilot is NOT a benchmark, and "
            "no accuracy claim is made by this API."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    def _pipeline_context():
        """Per-request engine/session/retriever/LLM (see module docstring)."""
        engine = make_engine(settings.database_url)
        session = make_session_factory(engine)()
        retriever = Retriever(session)
        retriever.refresh()
        return session, retriever

    @app.get("/health", response_model=HealthOut)
    def health() -> HealthOut:
        """Liveness + readiness. No LLM call; DB reachability only."""
        from sqlalchemy import func, select

        from app.db import Chunk, Document

        try:
            engine = make_engine(settings.database_url)
            session = make_session_factory(engine)()
            try:
                docs = session.scalar(select(func.count()).select_from(Document)) or 0
                chunks = session.scalar(select(func.count()).select_from(Chunk)) or 0
            finally:
                session.close()
        except Exception as exc:  # DB missing/corrupt: report, don't crash
            return HealthOut(
                status="degraded",
                database=settings.database_url,
                llm_provider=settings.llm_provider,
                llm_model=settings.llm_model,
                detail=f"database unreachable: {type(exc).__name__}",
            )
        return HealthOut(
            status="ok",
            database=settings.database_url,
            documents_ingested=docs,
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
            detail=f"{chunks} chunks indexed" + ("" if docs else "; no documents ingested yet"),
        )

    @app.post("/ask", response_model=AskResponse)
    def ask(req: AskRequest) -> AskResponse:
        if req.mode not in ("baseline", "verified"):
            raise HTTPException(
                status_code=422, detail="mode must be 'baseline' or 'verified'"
            )
        question = req.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="question is empty after trimming")

        try:
            session, retriever = _pipeline_context()
        except Exception as exc:  # DB missing/corrupt: honest 503, not a 500 traceback
            raise HTTPException(
                status_code=503,
                detail=f"database unavailable: {type(exc).__name__}",
            )
        try:
            if retriever.is_empty:
                raise HTTPException(
                    status_code=409,
                    detail="No documents ingested yet. Run `python -m app.cli ingest "
                    "--file data/sample/advisories.json` first.",
                )
            try:
                llm = _make_llm(settings)
            except LLMError as exc:
                raise HTTPException(status_code=502, detail=f"LLM configuration error: {exc}")

            notes: list[str] = []
            if req.mode == "baseline":
                pipeline = BaselineRAG(retriever, llm, top_k=settings.retrieval_top_k)
                try:
                    result = pipeline.run(question)
                except LLMError as exc:
                    raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")
                verification = None
                notes.append(
                    "Baseline mode performs no claim-level verification; "
                    "unsupported_citation_check_performed reflects the citation "
                    "format check only."
                )
            else:
                pipeline = VerifiedRAG(
                    retriever,
                    llm,
                    top_k=settings.retrieval_top_k,
                    judge=LLMJudge(llm),
                    chunk_is_known=make_chunk_exists(session),
                )
                try:
                    result = pipeline.run(question)
                except LLMError as exc:
                    raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")
                verdicts = [
                    ClaimVerdictOut(
                        claim_index=i,
                        claim_text=v.claim.text,
                        label=v.label.value,
                        evidence_chunk_ids=list(v.evidence_chunk_ids),
                        rationale=v.rationale,
                        anomalies=list(v.anomalies),
                    )
                    for i, v in enumerate(result.verdicts)
                ]
                s = result.summary
                verification = VerificationOut(
                    verdicts=verdicts,
                    summary=VerificationSummaryOut(
                        total=s.total,
                        supported=s.supported,
                        contradicted=s.contradicted,
                        insufficient_evidence=s.insufficient_evidence,
                        unverifiable=s.unverifiable,
                        with_anomalies=s.with_anomalies,
                        abstentions=s.abstentions,
                    ),
                )
                notes.append(
                    "Verification is post-generation and claim-level: it does not "
                    "edit the answer; it reports what the corpus supports."
                )
                if s.total and s.abstentions:
                    notes.append(
                        "Abstention verdicts (insufficient_evidence/unverifiable) "
                        "mean the corpus could not settle the claim. They are not "
                        "confirmations."
                    )
                if not result.verdicts:
                    notes.append("No factual claims were extracted from this answer.")

            retrieved = [
                RetrievedChunkOut(
                    marker=i,
                    chunk_id=c.chunk_id,
                    external_id=c.external_id,
                    title=c.title,
                    source_url=c.source_url,
                    text=c.text,
                    score=c.score,
                )
                for i, c in enumerate(result.retrieved, start=1)
            ]
            # Re-validate markers against the SAME retrieved set the pipeline
            # used, so the API never reports a citation the corpus can't back.
            citations, invalid = validate_citations(result.answer_text, result.retrieved)
            return AskResponse(
                question=result.question,
                mode=req.mode,
                answer_text=result.answer_text,
                model=result.model,
                retrieved=retrieved,
                citations=[
                    CitationOut(
                        marker=c.marker,
                        chunk_id=c.chunk_id,
                        external_id=c.external_id,
                        source_url=c.source_url,
                        title=c.title,
                    )
                    for c in citations
                ],
                invalid_citation_markers=invalid,
                unsupported_citation_check_performed=(
                    result.unsupported_citation_check_performed
                ),
                verification=verification,
                notes=notes,
            )
        finally:
            session.close()

    return app


# Uvicorn entry point: `uvicorn app.api:app` (configure via API_HOST/API_PORT).
app = create_app()
