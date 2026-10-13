"""Tests for BM25 scoring and the Retriever over the sample corpus."""

from __future__ import annotations

from app.retrieval.bm25 import BM25Index, tokenize
from app.retrieval.retriever import Retriever


def test_tokenize_normalizes_case_and_punctuation():
    assert tokenize("CVE-2021-44228: JNDI!") == ["cve", "2021", "44228", "jndi"]


def test_bm25_ranks_relevant_document_first():
    corpus = [
        "Apache Log4j2 JNDI remote code execution vulnerability.",
        "OpenSSL Heartbeat Extension information disclosure.",
        "MOVEit Transfer SQL injection in database queries.",
    ]
    index = BM25Index.build(corpus)
    scores = index.scores("SQL injection database")
    assert scores.index(max(scores)) == 2


def test_bm25_zero_score_for_non_matching_query():
    index = BM25Index.build(["Apache Log4j2 vulnerability."])
    assert index.scores("completely unrelated zebras") == [0.0]


def test_retriever_returns_top_k_with_provenance(populated_session):
    retriever = Retriever(populated_session)
    results = retriever.retrieve("Log4j2 remote code execution JNDI", top_k=2)
    assert 1 <= len(results) <= 2
    top = results[0]
    assert top.external_id == "CVE-2021-44228"
    assert top.source_url.startswith("https://nvd.nist.gov/vuln/detail/")
    assert top.title
    assert top.score > 0
    # Provenance fields are populated for every result.
    for r in results:
        assert r.chunk_id > 0 and r.document_id > 0 and r.published_at


def test_retriever_orders_by_descending_score(populated_session):
    retriever = Retriever(populated_session)
    results = retriever.retrieve("path traversal SSL VPN FortiOS", top_k=3)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_retriever_no_lexical_match_returns_empty(populated_session):
    retriever = Retriever(populated_session)
    assert retriever.retrieve("xylophone quantum knitting") == []
