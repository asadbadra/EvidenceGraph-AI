"""Minimal Streamlit frontend for EvidenceGraph AI (Phase B).

Communicates ONLY with the FastAPI backend over HTTP (API_BASE_URL env var,
default http://localhost:8000); it holds no pipeline logic and never talks
to the LLM directly. It renders exactly what the API returns -- answer,
citations, retrieved passages, and claim-level verdicts -- and surfaces
abstention and error states plainly rather than dressing them up.

Run locally:   streamlit run frontend/app.py
In Docker:     API_BASE_URL is set by docker-compose.yml.
"""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.environ.get("API_TIMEOUT_SECONDS", "300"))

LABEL_STYLE = {
    "supported": "🟢 supported",
    "contradicted": "🔴 contradicted",
    "insufficient_evidence": "🟡 insufficient_evidence",
    "unverifiable": "⚪ unverifiable",
}

st.set_page_config(page_title="EvidenceGraph AI", page_icon="🛡️", layout="wide")
st.title("EvidenceGraph AI")
st.caption(
    "Evidence-grounded OSINT answers over public cyber advisories. "
    "Research prototype — a small pilot, not a benchmark; no accuracy claim is made."
)


@st.cache_data(ttl=10)
def fetch_health() -> dict | None:
    try:
        r = httpx.get(f"{API_BASE_URL}/health", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


health = fetch_health()
if health is None:
    st.error(
        f"Backend at {API_BASE_URL} is unreachable. Start it with "
        "`uvicorn app.api:app` (or `docker compose up`). See README troubleshooting."
    )
    st.stop()

if health["status"] != "ok":
    st.warning(f"Backend degraded: {health.get('detail', 'unknown')}")
if health.get("documents_ingested") == 0:
    st.info(
        "No documents ingested yet. Load the sample corpus first: "
        "`python -m app.cli ingest --file data/sample/advisories.json`."
    )

with st.sidebar:
    st.header("Settings")
    st.write(f"Backend: `{API_BASE_URL}`")
    st.write(f"LLM: `{health['llm_provider']}` / `{health['llm_model']}`")
    if health["llm_provider"] == "mock":
        st.warning("Mock provider: answers are a deterministic stub, not model output.")
    mode_label = st.radio(
        "Mode",
        ["verified", "baseline"],
        format_func=lambda m: (
            "Verified (claim-level verification)" if m == "verified" else "Baseline RAG"
        ),
        help="Verified mode runs post-generation claim checks; it does not edit the answer.",
    )

question = st.text_area(
    "Your question", height=100, max_chars=2000,
    placeholder="e.g. Which products are affected by CVE-2021-44228?",
)

if st.button("Ask", type="primary", disabled=not question.strip()):
    with st.spinner("Querying the corpus and the model… (verification adds several seconds per claim)"):
        try:
            resp = httpx.post(
                f"{API_BASE_URL}/ask",
                json={"question": question, "mode": mode_label},
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.TimeoutException:
            st.error("The backend timed out. The model may still be loading; try again shortly.")
            st.stop()
        except Exception as exc:
            st.error(f"Could not reach the backend: {type(exc).__name__}")
            st.stop()

    if resp.status_code == 409:
        st.warning(resp.json().get("detail", "Corpus is empty."))
        st.stop()
    if resp.status_code >= 400:
        detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        st.error(f"Request failed ({resp.status_code}): {detail}")
        st.stop()

    data = resp.json()
    st.subheader("Answer")
    st.write(data["answer_text"])
    st.caption(f"Model: `{data['model']}` · mode: {data['mode']}")

    for note in data.get("notes", []):
        st.info(note)

    if data.get("invalid_citation_markers"):
        st.warning(
            "Citation markers with no matching retrieved passage: "
            + ", ".join(data["invalid_citation_markers"])
        )

    if data.get("verification"):
        v = data["verification"]
        s = v["summary"]
        st.subheader("Claim-level verification")
        st.caption(
            f"{s['total']} claim(s): {s['supported']} supported · "
            f"{s['contradicted']} contradicted · {s['insufficient_evidence']} "
            f"insufficient_evidence · {s['unverifiable']} unverifiable"
            + (f" · {s['with_anomalies']} with anomalies" if s["with_anomalies"] else "")
        )
        if not v["verdicts"]:
            st.write("_No factual claims were extracted from this answer._")
        for verdict in v["verdicts"]:
            label = verdict["label"]
            with st.expander(
                f"{LABEL_STYLE.get(label, label)} — {verdict['claim_text'][:110]}"
            ):
                st.write(verdict["claim_text"])
                if verdict["evidence_chunk_ids"]:
                    st.caption(
                        "Evidence chunk ids: "
                        + ", ".join(str(i) for i in verdict["evidence_chunk_ids"])
                        + " (see passages below)"
                    )
                else:
                    st.caption("No evidence chunks were attached to this verdict.")
                if verdict["rationale"]:
                    st.write(verdict["rationale"])
                for anomaly in verdict["anomalies"]:
                    st.warning(f"Verifier note: {anomaly}")

    st.subheader("Retrieved passages & citations")
    if data.get("citations"):
        st.caption("Cited in the answer (format-validated markers):")
        for c in data["citations"]:
            st.markdown(f"- [{c['marker']}]({c['source_url']}) — **{c['external_id']}** {c['title']}")
    else:
        st.caption("No valid citation markers in this answer.")
    for chunk in data.get("retrieved", []):
        with st.expander(f"[{chunk['marker']}] {chunk['external_id']} — {chunk['title']} (score {chunk['score']:.2f})"):
            st.write(chunk["text"])
            st.markdown(f"[source]({chunk['source_url']})")

    st.caption(
        "Citation markers confirm a passage EXISTS; claim verdicts report what "
        "the corpus supports. Neither is a guarantee of factual accuracy."
    )
