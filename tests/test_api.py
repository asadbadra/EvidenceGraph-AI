"""Offline tests for the FastAPI layer (Phase A).

No model calls, no sockets: the app is constructed with a Settings pointing
at a temporary SQLite database and LLM_PROVIDER=mock (FakeLLMClient, which
the CLI's `_make_llm` builds deterministically). FastAPI's TestClient runs
the ASGI app in-process, so the suite's socket blocker stays satisfied.

SCOPE: these tests pin the API's contract -- request validation, status
codes, response shape mirroring the real pipeline types, and honesty rules
(no invented fields, mock mode visible). They make no quality claim.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import MAX_QUESTION_CHARS, create_app
from app.config import Settings
from app.db import init_db, make_engine, make_session_factory
from app.ingestion.loader import load_advisories

FIXTURE = Path(__file__).resolve().parent.parent / "data" / "sample" / "advisories.json"


def _settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "database_url": f"sqlite:///{tmp_path / 'api.db'}",
        "llm_provider": "mock",
        "llm_base_url": "http://localhost:11434/v1",
        "llm_api_key": "test-dummy",
        "llm_model": "offline-mock",
    }
    base.update(overrides)
    return Settings(**base)


def _client(tmp_path: Path, *, ingest: bool = True, **overrides) -> TestClient:
    settings = _settings(tmp_path, **overrides)
    if ingest:
        engine = make_engine(settings.database_url)
        init_db(engine)
        session = make_session_factory(engine)()
        load_advisories(session, FIXTURE)
        session.close()
    return TestClient(create_app(settings))


def test_health_reports_ok_and_counts(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["documents_ingested"] == 5
        assert body["llm_provider"] == "mock"
        assert body["llm_model"] == "offline-mock"
        # Honesty: the key must never appear in any response.
        assert "test-dummy" not in resp.text


def test_health_degraded_when_database_unreachable(tmp_path: Path) -> None:
    # make_engine creates missing parent directories, so to make the
    # database genuinely unreachable, place a FILE where a parent directory
    # should be: mkdir then fails and the DB cannot open.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    settings = _settings(tmp_path)
    settings = settings.model_copy(
        update={"database_url": f"sqlite:///{blocker / 'x.db'}"}
    )
    with TestClient(create_app(settings)) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert "database unreachable" in body["detail"]


def test_ask_baseline_mode_returns_pipeline_shape(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.post("/ask", json={"question": "What does the corpus say?", "mode": "baseline"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "baseline"
        assert body["verification"] is None  # baseline performs no claim check
        assert body["answer_text"]  # FakeLLMClient scripted answer
        assert body["model"] == "offline-mock"
        assert isinstance(body["retrieved"], list) and body["retrieved"]
        first = body["retrieved"][0]
        assert set(first) == {"marker", "chunk_id", "external_id", "title", "source_url", "text", "score"}
        assert first["marker"] == 1
        assert isinstance(body["citations"], list)
        assert isinstance(body["invalid_citation_markers"], list)
        assert body["unsupported_citation_check_performed"] is False or body["unsupported_citation_check_performed"] is True
        assert any("Baseline mode performs no claim-level verification" in n for n in body["notes"])


def test_ask_verified_mode_returns_verdicts_and_summary(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.post("/ask", json={"question": "Which product does CVE-2018-13379 affect?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "verified"  # default
        assert body["verification"] is not None
        v = body["verification"]
        assert set(v["summary"]) == {
            "total", "supported", "contradicted", "insufficient_evidence",
            "unverifiable", "with_anomalies", "abstentions",
        }
        # Mock judge output is not JSON: LLMJudge degrades honestly to
        # unverifiable + anomaly; the API must surface that, not hide it.
        for verdict in v["verdicts"]:
            assert set(verdict) == {
                "claim_index", "claim_text", "label",
                "evidence_chunk_ids", "rationale", "anomalies",
            }
            assert verdict["label"] in {
                "supported", "contradicted", "insufficient_evidence", "unverifiable",
            }
        assert any("post-generation" in n for n in body["notes"])


def test_ask_rejects_unknown_mode(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.post("/ask", json={"question": "x?", "mode": "fancy"})
        assert resp.status_code == 422


def test_ask_rejects_empty_and_oversized_questions(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.post("/ask", json={"question": "   "}).status_code == 422
        assert client.post("/ask", json={"question": ""}).status_code == 422
        big = "x" * (MAX_QUESTION_CHARS + 1)
        assert client.post("/ask", json={"question": big}).status_code == 422
        assert client.post("/ask", json={}).status_code == 422


def test_ask_conflict_when_corpus_empty(tmp_path: Path) -> None:
    with _client(tmp_path, ingest=False) as client:
        resp = client.post("/ask", json={"question": "Anything?"})
        assert resp.status_code == 409
        assert "ingest" in resp.json()["detail"]


def test_ask_returns_502_when_llm_configuration_fails(tmp_path, monkeypatch) -> None:
    """Provider misconfiguration surfaces as 502 with no stack-trace leak."""
    import app.api as api_mod
    from app.llm.client import LLMError

    def _boom(settings):
        raise LLMError("provider not reachable")

    monkeypatch.setattr(api_mod, "_make_llm", _boom)
    with _client(tmp_path) as client:
        resp = client.post("/ask", json={"question": "What is CVE-2021-44228?"})
        assert resp.status_code == 502
        assert "provider not reachable" in resp.json()["detail"]
        assert "Traceback" not in resp.text


def test_ask_returns_502_when_pipeline_call_fails(tmp_path, monkeypatch) -> None:
    """A runtime LLM failure mid-pipeline surfaces as 502, not a 500."""
    from app.llm.client import LLMError
    from app.pipelines.baseline import BaselineRAG

    def _run(self, question):
        raise LLMError("connection reset by provider")

    monkeypatch.setattr(BaselineRAG, "run", _run)
    with _client(tmp_path) as client:
        resp = client.post(
            "/ask", json={"question": "Anything?", "mode": "baseline"}
        )
        assert resp.status_code == 502
        assert "connection reset by provider" in resp.json()["detail"]


def test_ask_returns_503_when_database_unavailable(tmp_path: Path) -> None:
    # A FILE where the parent directory should be makes the DB unopenable.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    settings = _settings(tmp_path).model_copy(
        update={"database_url": f"sqlite:///{blocker / 'x.db'}"}
    )
    with TestClient(create_app(settings)) as client:
        resp = client.post("/ask", json={"question": "Anything?"})
        assert resp.status_code == 503
        assert "database unavailable" in resp.json()["detail"]


def test_ask_notes_explain_abstention_only_when_present(tmp_path: Path) -> None:
    """The abstention note must appear only when abstention verdicts exist."""
    with _client(tmp_path) as client:
        body = client.post("/ask", json={"question": "What is in the corpus?"}).json()
        notes = " ".join(body["verification"]["summary"] and body["notes"] or [])
        s = body["verification"]["summary"]
        has_abstention = s["abstentions"] > 0
        mentions = any("Abstention verdicts" in n for n in body["notes"])
        assert mentions == has_abstention


def test_no_prompt_or_key_leakage_in_response(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.post("/ask", json={"question": "List all CVEs."})
        assert resp.status_code == 200
        assert "test-dummy" not in resp.text
