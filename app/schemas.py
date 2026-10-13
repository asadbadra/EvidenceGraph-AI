"""Pydantic request/response schemas shared across the app and CLI."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """A chunk retrieved for a query, with provenance."""

    chunk_id: int
    document_id: int
    external_id: str
    title: str
    source_url: str
    published_at: str
    text: str
    score: float


class Citation(BaseModel):
    """A citation reference validated for *format* only.

    IMPORTANT: a citation being "valid" means only that its identifier exists
    among the retrieved chunks. It does NOT mean the cited passage actually
    supports the sentence it is attached to. Evidence-support verification is
    a separate, later phase (Verified RAG).
    """

    marker: str
    chunk_id: int
    external_id: str
    source_url: str
    title: str


class AnswerResult(BaseModel):
    """Output of the Baseline RAG pipeline."""

    question: str
    answer_text: str
    citations: list[Citation]
    invalid_citation_markers: list[str] = Field(default_factory=list)
    retrieved: list[RetrievedChunk]
    model: str
    unsupported_citation_check_performed: bool = False
