"""Baseline RAG pipeline: retrieve -> generate with citations -> validate.

Scope note: this pipeline validates citation *format/provenance* only (a
marker must refer to a retrieved chunk). It does not verify that the cited
passage actually supports the surrounding claim; that is the Verified RAG
phase (not implemented yet).
"""

from __future__ import annotations

from app.llm.client import LLMClient
from app.llm.prompts import build_baseline_prompt
from app.retrieval.retriever import Retriever
from app.schemas import AnswerResult
from app.security import validate_citations


class BaselineRAG:
    """Run the baseline retrieval-augmented generation pipeline."""

    def __init__(self, retriever: Retriever, llm: LLMClient, *, top_k: int = 4) -> None:
        self._retriever = retriever
        self._llm = llm
        self._top_k = top_k

    def run(self, question: str) -> AnswerResult:
        retrieved = self._retriever.retrieve(question, top_k=self._top_k)
        prompt = build_baseline_prompt(question, retrieved)
        answer_text = self._llm.complete(prompt).strip()
        citations, invalid = validate_citations(answer_text, retrieved)
        return AnswerResult(
            question=question,
            answer_text=answer_text,
            citations=citations,
            invalid_citation_markers=invalid,
            retrieved=retrieved,
            model=getattr(self._llm, "model", "unknown"),
            # Explicit: format validation happened, support verification did not.
            unsupported_citation_check_performed=False,
        )
