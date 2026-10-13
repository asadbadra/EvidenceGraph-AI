"""Retriever: lexical search over stored chunks with provenance."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Chunk, Document
from app.retrieval.bm25 import BM25Index
from app.schemas import RetrievedChunk


@dataclass
class _IndexedChunk:
    chunk: Chunk
    document: Document


class Retriever:
    """Loads chunks from the database and answers queries with top-k results."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._items: list[_IndexedChunk] | None = None
        self._index: BM25Index | None = None

    def refresh(self) -> None:
        """(Re)load the in-memory index from the database."""
        rows = self._session.execute(
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .order_by(Chunk.id)
        ).all()
        self._items = [_IndexedChunk(chunk=chunk, document=document) for chunk, document in rows]
        self._index = BM25Index.build([item.chunk.text for item in self._items])

    @property
    def is_empty(self) -> bool:
        if self._items is None:
            self.refresh()
        assert self._items is not None
        return not self._items

    def retrieve(self, query: str, *, top_k: int = 4) -> list[RetrievedChunk]:
        """Return the top-k chunks for `query`, ordered by descending score."""
        if self._items is None or self._index is None:
            self.refresh()
        assert self._items is not None and self._index is not None
        if not self._items:
            return []

        scores = self._index.scores(query)
        ranked = sorted(
            enumerate(scores), key=lambda pair: (-pair[1], pair[0])
        )[: max(top_k, 0)]

        results: list[RetrievedChunk] = []
        for index, score in ranked:
            if score <= 0:
                continue  # no lexical match: do not return irrelevant chunks
            item = self._items[index]
            results.append(
                RetrievedChunk(
                    chunk_id=item.chunk.id,
                    document_id=item.document.id,
                    external_id=item.document.external_id,
                    title=item.document.title,
                    source_url=item.document.source_url,
                    published_at=item.document.published_at,
                    text=item.chunk.text,
                    score=round(score, 4),
                )
            )
        return results
