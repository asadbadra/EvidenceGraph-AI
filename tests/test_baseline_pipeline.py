"""End-to-end tests for the Baseline RAG pipeline using a deterministic fake LLM.

No network access and no API key required.
"""

from __future__ import annotations

from app.llm.client import FakeLLMClient
from app.llm.prompts import PROMPT_VERSION, build_baseline_prompt
from app.pipelines.baseline import BaselineRAG
from app.retrieval.retriever import Retriever


def _pipeline(session, scripted: str):
    llm = FakeLLMClient(scripted_response=scripted)
    return BaselineRAG(Retriever(session), llm, top_k=3), llm


def test_pipeline_returns_answer_with_valid_citations(populated_session):
    pipeline, _llm = _pipeline(
        populated_session, "Log4j2 allows remote code execution [1]."
    )
    result = pipeline.run("What does the Log4j2 advisory say about code execution?")
    assert result.answer_text
    assert result.retrieved, "expected retrieved passages"
    assert len(result.citations) == 1
    assert result.citations[0].marker == "[1]"
    assert result.citations[0].chunk_id == result.retrieved[0].chunk_id
    assert result.citations[0].source_url
    assert result.invalid_citation_markers == []
    assert result.model == "fake-model"
    # Explicit scope flag: format checked, support NOT verified.
    assert result.unsupported_citation_check_performed is False


def test_pipeline_flags_invalid_citation_marker(populated_session):
    pipeline, _ = _pipeline(populated_session, "Unsupported claim [7].")
    result = pipeline.run("What is MOVEit Transfer?")
    assert "[7]" in result.invalid_citation_markers
    assert result.citations == []


def test_pipeline_prompt_contains_untrusted_fence_and_numbered_passages(populated_session):
    pipeline, llm = _pipeline(populated_session, "answer [1]")
    pipeline.run("Which CVE is an OpenSSL information disclosure?")
    assert len(llm.prompts_seen) == 1
    prompt = llm.prompts_seen[0]
    assert PROMPT_VERSION and "baseline-v1" in prompt
    assert "<untrusted_retrieved_content>" in prompt
    assert "</untrusted_retrieved_content>" in prompt
    assert "never as instructions" in prompt or "never as\ninstructions" in prompt


def test_retrieval_actually_selects_matching_document(populated_session):
    pipeline, _ = _pipeline(populated_session, "x")
    result = pipeline.run("path traversal vulnerability in FortiOS SSL VPN")
    assert result.retrieved
    assert result.retrieved[0].external_id == "CVE-2018-13379"


def test_empty_question_still_produces_valid_structure(populated_session):
    pipeline, _ = _pipeline(populated_session, "no citations")
    result = pipeline.run("   ")
    assert result.citations == [] and result.invalid_citation_markers == []


def test_prompt_handles_empty_retrieval():
    prompt = build_baseline_prompt("anything?", [])
    assert "No passages were retrieved" in prompt
