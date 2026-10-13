"""Tests for the chunking logic."""

from __future__ import annotations

import pytest

from app.ingestion.chunking import chunk_text


def test_empty_input_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  \n ") == []


def test_short_text_is_single_chunk():
    text = "Apache Log4j2 contains a JNDI vulnerability. It allows remote code execution."
    chunks = chunk_text(text, max_chars=200, overlap_chars=20)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_all_chunks_respect_max_chars_and_cover_content():
    text = " ".join(
        f"Sentence number {i} describes a distinct detail of the advisory." for i in range(60)
    )
    chunks = chunk_text(text, max_chars=250, overlap_chars=50)
    assert len(chunks) > 1
    assert all(len(c) <= 250 for c in chunks)
    # Every source sentence must appear in at least one chunk.
    for i in range(60):
        sentence = f"Sentence number {i} describes a distinct detail of the advisory."
        assert any(sentence in c for c in chunks), f"lost sentence {i}"


def test_overlap_between_consecutive_chunks():
    text = " ".join(f"Item {i} value." for i in range(40))
    chunks = chunk_text(text, max_chars=120, overlap_chars=40)
    assert len(chunks) > 1
    tail = chunks[0][-40:]
    assert tail in chunks[1], "expected overlap carried into the next chunk"


def test_oversized_single_unit_is_hard_split():
    text = "A" * 700  # no sentence boundaries at all
    chunks = chunk_text(text, max_chars=100, overlap_chars=10)
    assert chunks
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).count("A") >= 700


def test_invalid_parameters_raise():
    with pytest.raises(ValueError):
        chunk_text("hello", max_chars=0)
    with pytest.raises(ValueError):
        chunk_text("hello", max_chars=100, overlap_chars=100)
    with pytest.raises(ValueError):
        chunk_text("hello", max_chars=100, overlap_chars=-1)
