"""Minimal BM25 implementation (no external dependency).

Used for Phase 0 lexical retrieval over the small committed corpus. Scores
are deterministic given the same corpus and query.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class BM25Index:
    """Immutable BM25 index over a list of documents."""

    doc_tokens: list[list[str]]
    doc_freqs: list[dict[str, int]]
    avg_len: float
    k1: float = 1.5
    b: float = 0.75

    @classmethod
    def build(cls, texts: list[str], *, k1: float = 1.5, b: float = 0.75) -> "BM25Index":
        doc_tokens = [tokenize(t) for t in texts]
        doc_freqs: list[dict[str, int]] = []
        for tokens in doc_tokens:
            freqs: dict[str, int] = {}
            for token in tokens:
                freqs[token] = freqs.get(token, 0) + 1
            doc_freqs.append(freqs)
        total = sum(len(t) for t in doc_tokens)
        avg_len = (total / len(doc_tokens)) if doc_tokens else 0.0
        return cls(doc_tokens=doc_tokens, doc_freqs=doc_freqs, avg_len=avg_len, k1=k1, b=b)

    def _idf(self, term: str) -> float:
        n = len(self.doc_tokens)
        df = sum(1 for freqs in self.doc_freqs if term in freqs)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> list[float]:
        """Return a BM25 score for every indexed document."""
        terms = tokenize(query)
        if not terms or not self.doc_tokens:
            return [0.0] * len(self.doc_tokens)
        out: list[float] = []
        for i, freqs in enumerate(self.doc_freqs):
            score = 0.0
            length = len(self.doc_tokens[i]) or 1
            norm = self.k1 * (1 - self.b + self.b * length / (self.avg_len or 1.0))
            for term in terms:
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                score += self._idf(term) * tf * (self.k1 + 1) / (tf + norm)
            out.append(score)
        return out
