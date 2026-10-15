"""Streamlit frontend for EvidenceGraph AI.

Identity: an evidence-grounded cybersecurity research and analysis
workspace -- ask a question, get an answer retrieved from public cyber
advisories with citation markers, and (in Verified mode) a claim-level
verdict for every checkable claim in that answer. Communicates ONLY with
the FastAPI backend over HTTP (API_BASE_URL env var, default
http://localhost:8000); it holds no pipeline logic and never talks to the
LLM directly.

HONESTY RULES FOR THIS FILE
- Every displayed field is a real field of the API schema (AskResponse,
  HealthOut): no score, accuracy, or benchmark number is ever invented
  here. Verdict counts come verbatim from `verification.summary`
  (ordering/absence decided by frontend/ui_logic.py, which is pure and
  offline-tested).
- The evidence-limitation warning is additive and rendered as ONE panel:
  the original generated answer is always shown verbatim in its own
  container and is never edited, rewritten, or suppressed. The panel's
  positional basis is disclosed inline via ui_logic.MAIN_CLAIM_PROXY_NOTE
  (opening-claim proxy, not a semantic conclusion detector).
- The backend's `llm_provider` value names the CLIENT INTERFACE, not the
  destination API; ui_logic.provider_display labels it accordingly so the
  UI never implies the OpenAI API is called (deployment: local Ollama).
- Citations (markers the answer used) and retrieved passages (the full
  result set) are presented as different things; a citation marker never
  reads as evidence of claim support -- that is the verdicts' job.
- Baseline mode renders the ABSENCE of verification as one explicit
  notice; explanations are stated once, not repeated across boxes.
- Colors are semantic and restrained; verdict identity is always carried
  by text, never color alone. CSS uses theme-aware variables plus
  contrast-checked accents so light and dark Streamlit themes both stay
  readable. No metric, chart, score, or activity feed is fabricated: the
  only numbers on screen are API fields.

Run locally:   streamlit run frontend/app.py
In Docker:     API_BASE_URL is set by docker-compose.yml.
"""

from __future__ import annotations

import html
import os
import sys
from pathlib import Path

import httpx
import streamlit as st

# Make sibling modules importable regardless of the launcher's working
# directory (streamlit run frontend/app.py from the repo root, or the
# container's WORKDIR /srv/frontend).
_FRONTEND_DIR = str(Path(__file__).resolve().parent)
if _FRONTEND_DIR not in sys.path:
    sys.path.insert(0, _FRONTEND_DIR)

from ui_logic import (  # noqa: E402  (path bootstrap must run first)
    MAIN_CLAIM_PROXY_NOTE,
    VERDICT_LEGEND,
    cited_chunk_ids,
    evidence_limitation_warning,
    preview,
    provider_display,
    summary_card_specs,
)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.environ.get("API_TIMEOUT_SECONDS", "300"))

# Label -> (marker, display text). These four strings are the entire verdict
# vocabulary of the API; unknown labels fall back to verbatim rendering.
LABEL_STYLE = {
    "supported": ("\U0001f7e2", "supported"),
    "contradicted": ("\U0001f534", "contradicted"),
    "insufficient_evidence": ("\U0001f7e1", "insufficient evidence"),
    "unverifiable": ("⚪", "unverifiable"),
}

# Summary-card field -> CSS accent class / display label. The first four
# mirror LABEL_STYLE; "total" is the card for summary.total.
_CARD_CLS = {
    "total": "total",
    "supported": "supported",
    "contradicted": "contradicted",
    "insufficient_evidence": "insufficient",
    "unverifiable": "unverifiable",
}
_CARD_DISPLAY = {
    "total": "total claims",
    "supported": "supported",
    "contradicted": "contradicted",
    "insufficient_evidence": "insufficient evidence",
    "unverifiable": "unverifiable",
}

# Brand mark: a three-node evidence graph (nodes + edges), drawn inline --
# a logo, not a chart. currentColor inherits the teal below, which stays
# >= 3:1 on light and dark backgrounds (graphics + large text only).
_MARK_SVG = (
    '<svg class="eg-mark" width="34" height="34" viewBox="0 0 34 34" '
    'fill="none" role="img" aria-label="EvidenceGraph mark">'
    '<path d="M7 24.5 L17 7.5 L27 24.5 Z" stroke="currentColor" '
    'stroke-width="1.7" stroke-linejoin="round"/>'
    '<circle cx="7" cy="24.5" r="3.2" fill="currentColor"/>'
    '<circle cx="27" cy="24.5" r="3.2" fill="currentColor"/>'
    '<circle cx="17" cy="7.5" r="3.2" fill="none" stroke="currentColor" '
    'stroke-width="1.7"/>'
    "</svg>"
)

_CSS = """
<style>
/* ---- Design tokens -------------------------------------------------- */
:root {
    --eg-teal: #0d9488;          /* graphics, large text, borders (both themes) */
    --eg-teal-deep: #0f766e;     /* filled surfaces carrying white text */
    --eg-teal-line: rgba(13, 148, 136, 0.45);
    --eg-teal-soft: rgba(13, 148, 136, 0.08);
    --eg-rule: var(--border-color, rgba(120, 125, 135, 0.30));
}

/* ---- Brand header ---------------------------------------------------- */
.eg-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    flex-wrap: wrap;
}
.eg-brand {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;
}
.eg-mark { color: var(--eg-teal); flex: 0 0 auto; }
.eg-titlebox { min-width: 0; }
.eg-wordmark {
    margin: 0;
    font-size: 1.9rem;
    font-weight: 760;
    letter-spacing: -0.015em;
    line-height: 1.12;
}
.eg-wa { color: var(--eg-teal); }
.eg-sub {
    margin: 0.15rem 0 0 0;
    font-size: 0.95rem;
    color: var(--secondary-text-color, inherit);
}
.eg-badge {
    display: inline-block;
    padding: 3px 12px;
    border: 1px solid var(--eg-teal-line);
    border-radius: 999px;
    color: var(--secondary-text-color, inherit);
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 0.35rem;
    white-space: nowrap;
}
.eg-desc {
    max-width: 76ch;
    margin: 0.4rem 0 0.25rem 0;
    padding-bottom: 0.6rem;
    line-height: 1.55;
    border-bottom: 1px solid var(--eg-rule);
    color: var(--secondary-text-color, inherit);
}

/* ---- Eyebrows and section-number badges -------------------------------
   Section headers use Streamlit columns (badge column + native
   subheader), so the number and the heading can never collide at any
   viewport width; the badge CSS here only styles the marker itself. */
.eg-eyebrow {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--secondary-text-color, inherit);
    margin-top: 0.6rem;
}
.eg-eyebrow::before {
    content: "";
    width: 3px;
    height: 0.9em;
    background: var(--eg-teal);
    border-radius: 2px;
}
.eg-secnum {
    display: inline-block;
    white-space: nowrap;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: var(--secondary-text-color, inherit);
    background: var(--eg-teal-soft);
    border: 1px solid var(--eg-teal-line);
    border-radius: 6px;
    padding: 2px 7px;
}

/* ---- Research workspace (question form): the page's focal element,
   framed in the brand teal so it reads first on the empty screen. */
div[data-testid="stForm"] {
    border: 1px solid var(--eg-teal-line);
    border-top: 3px solid var(--eg-teal);
    border-radius: 12px;
    background: var(--secondary-background-color,
                    rgba(120, 125, 135, 0.05));
    padding: 16px 16px 12px 16px;
}
div[data-testid="stTextArea"] textarea:focus {
    border-color: var(--eg-teal) !important;
    box-shadow: 0 0 0 1px var(--eg-teal-line) !important;
    outline: none;
}
div[data-testid="stFormSubmitButton"] > button {
    background-color: var(--eg-teal-deep) !important;
    border-color: var(--eg-teal-deep) !important;
    color: #ffffff !important;
    font-weight: 650;
    letter-spacing: 0.01em;
}
div[data-testid="stFormSubmitButton"] > button:hover {
    background-color: #115e59 !important;
    border-color: #115e59 !important;
}
div[data-testid="stFormSubmitButton"] > button:focus-visible {
    outline: 2px solid var(--eg-teal-deep);
    outline-offset: 2px;
}

/* ---- Answer metadata pills (real API fields) ------------------------- */
.eg-metarow {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 0.1rem 0 0.7rem 0;
}
.eg-meta {
    display: inline-block;
    border: 1px solid var(--eg-rule);
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 0.78rem;
    color: var(--secondary-text-color, inherit);
    white-space: nowrap;
}
.eg-metak {
    font-size: 0.62rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-right: 6px;
    color: var(--secondary-text-color, inherit);
}

/* ---- Bordered containers (answer, empty states, status panel):
   comfortable reading measure and paragraph rhythm ----------------- */
div[data-testid="stVerticalBlockBorderWrapper"] .stMarkdown p {
    line-height: 1.65;
    max-width: 74ch;
}
div[data-testid="stVerticalBlockBorderWrapper"] .stMarkdown p + p {
    margin-top: 0.85em;
}

/* ---- Research summary cards: one responsive grid, five cells ---------
   Accent = left border + tint + large number. Number colors are
   mid-tones verified >= 3:1 on light AND dark themes (large text);
   the small label line uses theme text, and the label wording itself
   carries the meaning (never color alone). ------------------------- */
.eg-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 10px;
    margin: 0.4rem 0 0.2rem 0;
}
.eg-card {
    border: 1px solid rgba(120, 125, 135, 0.30);
    border-left: 3px solid var(--eg-accent, rgba(120, 125, 135, 0.75));
    border-radius: 10px;
    background: rgba(120, 125, 135, 0.06);
    padding: 10px 14px 9px 14px;
    height: 100%;
}
.eg-card .eg-num {
    display: block;
    font-size: 1.5rem;
    font-weight: 700;
    line-height: 1.15;
}
.eg-card .eg-lab {
    display: block;
    margin-top: 2px;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--secondary-text-color, inherit);
}
.eg-card-total {
    --eg-accent: #6e7681;
    background: rgba(110, 118, 129, 0.07);
}
.eg-card-total .eg-num { color: #6e7681; }
.eg-card-supported {
    --eg-accent: #2da44e;
    background: rgba(45, 164, 78, 0.08);
}
.eg-card-supported .eg-num { color: #2da44e; }
.eg-card-contradicted {
    --eg-accent: #f85149;
    background: rgba(248, 81, 73, 0.08);
}
.eg-card-contradicted .eg-num { color: #f85149; }
.eg-card-insufficient {
    --eg-accent: #b8860b;
    background: rgba(184, 134, 11, 0.09);
}
.eg-card-insufficient .eg-num { color: #b8860b; }
.eg-card-unverifiable {
    --eg-accent: #7d8590;
    background: rgba(125, 133, 144, 0.08);
}
.eg-card-unverifiable .eg-num { color: #7d8590; }

/* ---- Verdict legend + chips ------------------------------------------
   Chips are self-contained light tints (readable on both themes); the
   chip text IS the verdict label, so color never carries meaning
   alone. ------------------------------------------------------------- */
.eg-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 18px;
    margin: 0.45rem 0 0.1rem 0;
    font-size: 0.84rem;
    line-height: 1.5;
    color: var(--secondary-text-color, inherit);
}
.eg-leg-item {
    display: inline-flex;
    align-items: center;
    gap: 7px;
}
.eg-chip {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    border: 1px solid transparent;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.02em;
}
.eg-chip-supported { background: #e6f4ea; color: #1a7f37; border-color: #b7dfc2; }
.eg-chip-contradicted { background: #fdeceb; color: #b42318; border-color: #f3c1bd; }
.eg-chip-insufficient { background: #fff4d6; color: #9a6700; border-color: #ecd9a0; }
.eg-chip-unverifiable { background: #eef0f2; color: #57606a; border-color: #d8dce0; }
.eg-chip-cited {
    background: var(--eg-teal-soft);
    border-color: var(--eg-teal-line);
    color: inherit;
}
.eg-chip-plain {
    background: rgba(125, 133, 144, 0.12);
    border-color: var(--eg-rule);
    color: inherit;
}
.eg-id {
    display: inline-block;
    padding: 1px 7px;
    margin-right: 4px;
    border: 1px solid var(--eg-teal-line);
    background: var(--eg-teal-soft);
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 650;
    color: inherit;
}
.eg-key-note {
    font-size: 0.8rem;
    color: var(--secondary-text-color, inherit);
}

/* ---- Citation source rows --------------------------------------------- */
.eg-src {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 4px 10px;
    padding: 0.35rem 0;
    border-bottom: 1px solid var(--eg-rule);
    font-size: 0.9rem;
    line-height: 1.5;
}
.eg-src:last-of-type { border-bottom: none; }
.eg-srcmark {
    flex: 0 0 auto;
    font-size: 0.72rem;
    font-weight: 700;
    color: var(--secondary-text-color, inherit);
    border: 1px solid var(--eg-rule);
    border-radius: 6px;
    padding: 0 6px;
}
.eg-src a { font-weight: 600; color: var(--primary-color, var(--eg-teal-deep)); }
.eg-srctitle { color: var(--secondary-text-color, inherit); }

/* ---- Sidebar status panel: aligned definition list -------------------- */
.eg-dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.35rem 1rem;
    margin: 0 0 0.2rem 0;
    font-size: 0.85rem;
    line-height: 1.5;
}
.eg-dl dt {
    margin: 0;
    align-self: center;
    font-size: 0.66rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--secondary-text-color, inherit);
    white-space: nowrap;
}
.eg-dl dd { margin: 0; }

/* ---- Empty-state steps ----------------------------------------------- */
.eg-empty { color: var(--secondary-text-color, inherit); font-size: 0.94rem; }
.eg-empty .eg-empty-lede { color: inherit; margin-bottom: 0.3rem; }
.eg-steps {
    margin: 0.25rem 0 0.25rem 1.15rem;
    padding: 0;
    line-height: 1.55;
}
.eg-steps li { margin-bottom: 0.2rem; color: inherit; }
</style>
"""

st.set_page_config(page_title="EvidenceGraph AI", page_icon="\U0001f6e1\ufe0f", layout="wide")
st.markdown(_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Helpers (all inputs are API fields; nothing is computed or invented here)
# --------------------------------------------------------------------------


@st.cache_data(ttl=10)
def fetch_health() -> dict | None:
    try:
        r = httpx.get(f"{API_BASE_URL}/health", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _chip(label: str) -> str:
    """HTML chip for a verdict label; unknown labels render verbatim."""
    if label in LABEL_STYLE:
        _marker, display = LABEL_STYLE[label]
        cls = _CARD_CLS.get(label, "unverifiable")
    else:
        display, cls = label, "unverifiable"
    return f'<span class="eg-chip eg-chip-{cls}">{html.escape(display)}</span>'


def _card(count: int, field: str) -> str:
    """Summary card for one API summary field (value rendered verbatim)."""
    cls = _CARD_CLS.get(field, "unverifiable")
    display = _CARD_DISPLAY.get(field, field)
    return (
        f'<div class="eg-card eg-card-{cls}">'
        f'<span class="eg-num">{int(count)}</span>'
        f'<span class="eg-lab">{html.escape(display)}</span></div>'
    )


def _sechead(num: str, title: str) -> None:
    """Numbered section header via Streamlit columns.

    The badge and the native subheader live in separate columns
    (Streamlit's own horizontal layout), so they cannot merge or overlap
    at any viewport width -- no whitespace tricks or positional CSS.
    """
    num_col, title_col = st.columns([1.5, 10.5], vertical_alignment="center")
    with num_col:
        st.markdown(
            f'<span class="eg-secnum">{html.escape(num)}</span>',
            unsafe_allow_html=True,
        )
    with title_col:
        st.subheader(title)


def _metapill(key: str, value: str) -> str:
    return (
        f'<span class="eg-meta"><span class="eg-metak">{html.escape(key)}</span>'
        f"{html.escape(value)}</span>"
    )


def _legend() -> str:
    """Verdict legend: chip (label) + its documented meaning, verbatim."""
    items = []
    for label, _kind, gloss in VERDICT_LEGEND:
        items.append(
            f'<span class="eg-leg-item">{_chip(label)}'
            f'<span class="eg-leg-gloss">{html.escape(gloss)}</span></span>'
        )
    return '<div class="eg-legend">' + "".join(items) + "</div>"


def _src_row(c: dict) -> str:
    """Compact citation source row: marker, linked id, title."""
    return (
        '<div class="eg-src">'
        f'<span class="eg-srcmark">{html.escape(c["marker"])}</span>'
        f'<a href="{html.escape(c["source_url"])}" target="_blank" '
        f'rel="noopener noreferrer">{html.escape(c["external_id"])}</a>'
        f'<span class="eg-srctitle">{html.escape(c["title"])}</span>'
        "</div>"
    )


def _error_detail(resp: httpx.Response) -> str:
    """Human-readable error detail from a failed /ask response."""
    try:
        payload = resp.json()
    except Exception:
        return resp.text[:400]
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    if isinstance(detail, list):  # FastAPI 422 validation errors
        parts = []
        for item in detail[:3]:
            if isinstance(item, dict):
                loc = ".".join(str(p) for p in item.get("loc", ()))
                parts.append(f"{loc}: {item.get('msg', '')}".strip(". "))
        return "; ".join(parts) or str(detail)[:400]
    return str(detail)[:600]


_STATUS_HINTS = {
    422: "The question failed request validation (length or missing field).",
    502: "The model provider call failed -- local Ollama must be running (see README).",
    503: "The backend database is unavailable -- check the backend logs.",
}


def _spinner_text(mode: str) -> str:
    if mode == "verified":
        return (
            "Generating the answer, then checking each extracted claim "
            "(one model call per claim)…"
        )
    return "Generating the answer…"


# --------------------------------------------------------------------------
# Result rendering (stable section order: answer, verification, citations,
# passages). The asked question stays visible in the workspace above.
# --------------------------------------------------------------------------


def render_result(data: dict) -> None:
    # --- 01 Answer --------------------------------------------------------
    _sechead("01", "Answer")
    check = (
        "performed" if data["unsupported_citation_check_performed"]
        else "not performed"
    )
    st.markdown(
        '<div class="eg-metarow">'
        + _metapill("model", data["model"])
        + _metapill("mode", data["mode"])
        + _metapill("citation format check", check)
        + "</div>",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.write(data["answer_text"])  # verbatim; never rewritten here

    # Evidence limitation: ONE small labelled panel directly below the
    # answer, combining the verdict-adapted message and the proxy
    # disclosure (no duplicate boxes elsewhere).
    verification = data.get("verification")
    verdicts = (verification or {}).get("verdicts", [])
    limitation = evidence_limitation_warning(verdicts)
    if limitation:
        st.warning(f"{limitation}\n\n*{MAIN_CLAIM_PROXY_NOTE}*")

    for note in data.get("notes", []):
        st.info(note)

    # --- 02 Claim-level verification --------------------------------------
    _sechead("02", "Claim-level verification")
    if verification is None:
        # Baseline mode: absence stated once, as the only notice.
        st.info(
            "Baseline mode performs no claim-level verification: this run "
            "is answer-only. Choose “Verified” in the sidebar for "
            "per-claim verdicts."
        )
    else:
        summary = verification["summary"]
        verdicts = verification["verdicts"]
        card_specs = summary_card_specs(summary)
        if card_specs is None or not verdicts:
            # One concise explanation; no empty metric cards.
            st.info(
                "No factual claims were extracted from this answer, so "
                "verification had nothing to check. This is an empty "
                "verification run, not a passed one."
            )
        else:
            st.caption(
                "Verification runs after generation and never rewrites the "
                "answer. `insufficient_evidence` and `unverifiable` are "
                "abstentions, not confirmations."
            )
            # One responsive grid: wraps instead of cramming on narrow
            # screens (five rigid columns would not).
            cards_html = "".join(_card(count, field) for field, count in card_specs)
            st.markdown(
                f'<div class="eg-cards">{cards_html}</div>', unsafe_allow_html=True
            )
            st.caption(
                f"{summary['abstentions']} abstention(s) · "
                f"{summary['with_anomalies']} verdict(s) with verifier anomalies"
            )
            st.markdown(_legend(), unsafe_allow_html=True)

        for verdict in verdicts:
            label = verdict["label"]
            marker, display = LABEL_STYLE.get(label, ("", label))
            claim_text = verdict["claim_text"]
            with st.expander(f"{marker} {display} — {preview(claim_text)}"):
                # Claim, verdict, evidence, rationale clearly separated;
                # details stay inside the expander.
                st.markdown(_chip(label), unsafe_allow_html=True)
                st.write(claim_text)
                ids = verdict["evidence_chunk_ids"]
                if ids:
                    pills = "".join(
                        f'<span class="eg-id">#{int(i)}</span>' for i in ids
                    )
                    st.markdown(
                        '<span class="eg-key-note">Evidence chunks:</span> '
                        f"{pills}"
                        '<span class="eg-key-note"> — listed under '
                        "Retrieved passages</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("No evidence chunks were attached to this verdict.")
                if verdict["rationale"]:
                    st.caption("Rationale — the verifier's explanation")
                    st.write(verdict["rationale"])
                for anomaly in verdict["anomalies"]:
                    st.warning(f"Verifier note: {anomaly}")

    # --- 03 Citations ------------------------------------------------------
    _sechead("03", "Citations")
    citations = data.get("citations", [])
    if citations:
        st.caption(
            "Citations are the markers the answer used: they confirm a "
            "referenced passage exists, not that it supports a claim."
        )
        for c in citations:
            st.markdown(_src_row(c), unsafe_allow_html=True)
    else:
        st.caption("No valid citation markers in this answer.")
    invalid = data.get("invalid_citation_markers", [])
    if invalid:
        st.warning(
            "Citation markers with no matching retrieved passage: "
            + ", ".join(invalid)
        )

    # --- 04 Retrieved passages --------------------------------------------
    _sechead("04", "Retrieved passages")
    retrieved = data.get("retrieved", [])
    if not retrieved:
        st.caption(
            "The retrieval step returned no passages for this question, so "
            "the citations above cannot be cross-checked here."
        )
    else:
        st.caption(
            "The full retrieval result set for this question; passages the "
            "answer actually cited are marked below."
        )
        cited = cited_chunk_ids(citations)
        for chunk in retrieved:
            with st.expander(
                f"[{chunk['marker']}] {chunk['external_id']} — {chunk['title']} "
                f"(score {chunk['score']:.2f})"
            ):
                if chunk["chunk_id"] in cited:
                    st.markdown(
                        '<span class="eg-chip eg-chip-cited">cited in answer'
                        "</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<span class="eg-chip eg-chip-plain">retrieved, not '
                        "cited</span>",
                        unsafe_allow_html=True,
                    )
                st.write(chunk["text"])
                st.markdown(f"[source]({chunk['source_url']})")

    st.divider()
    st.caption(
        "Research prototype — neither citation markers nor claim verdicts "
        "guarantee factual accuracy."
    )


# --------------------------------------------------------------------------
# Page: brand header, health, sidebar, research workspace
# --------------------------------------------------------------------------

st.markdown(
    '<div class="eg-head">'
    '<div class="eg-brand">'
    + _MARK_SVG
    + '<div class="eg-titlebox">'
    '<h1 class="eg-wordmark">Evidence<span class="eg-wa">Graph</span> AI</h1>'
    '<p class="eg-sub">Evidence-grounded cybersecurity intelligence.</p>'
    "</div></div>"
    '<span class="eg-badge">research prototype</span>'
    "</div>"
    '<p class="eg-desc">Retrieve cited answers over public cyber advisories, '
    "then verify each extracted claim against the retrieved evidence — "
    "reported beside the answer, never written into it.</p>",
    unsafe_allow_html=True,
)

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
    st.markdown('<div class="eg-eyebrow">System status</div>', unsafe_allow_html=True)
    with st.container(border=True):
        docs = health.get("documents_ingested")
        docs_text = str(docs) if docs is not None else "unknown"
        rows = [
            ("Health", html.escape(str(health["status"]))),
            ("Interface", html.escape(provider_display(health["llm_provider"]))),
            ("Model", html.escape(str(health["llm_model"]))),
            ("Corpus", f"{html.escape(docs_text)} document(s)"),
        ]
        dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
        st.markdown(f'<dl class="eg-dl">{dl}</dl>', unsafe_allow_html=True)
        if health["status"] != "ok":
            # Failures stay visible; never collapsed.
            st.caption(f"Detail: {health.get('detail', '')}")
        if health["llm_provider"] == "mock":
            st.warning(
                "Mock provider: answers are a deterministic stub, not model output."
            )
        with st.expander("Configuration details"):
            st.markdown(f"Backend: `{html.escape(API_BASE_URL)}`")
            st.markdown(
                "The provider value names the client interface, not the "
                "destination: “openai” is the OpenAI-compatible interface. "
                "As shipped, LLM_BASE_URL points at a local Ollama server "
                "(see README); no OpenAI API is called."
            )
    st.divider()
    mode = st.radio(
        "Mode",
        ["verified", "baseline"],
        format_func=lambda m: (
            "Verified — answer, then verify each claim (slower)"
            if m == "verified"
            else "Baseline — answer only, no claim checks"
        ),
        help=(
            "Verified runs post-generation claim checks; it reports verdicts "
            "alongside the answer and never edits the answer itself."
        ),
    )
    st.caption(
        "Verified mode adds one model call per extracted claim on top of "
        "generation, so it takes noticeably longer."
    )

st.markdown(
    '<div class="eg-eyebrow">Research workspace</div>', unsafe_allow_html=True
)
with st.form("ask_form"):
    question = st.text_area(
        "Research question",
        height=110,
        max_chars=2000,
        placeholder="e.g. Which products are affected by CVE-2021-44228?",
    )
    submitted = st.form_submit_button(
        "Ask", type="primary", use_container_width=True
    )

st.caption(
    f"Mode: **{mode}** — answers are grounded in retrieved passages only; "
    "abstention is an expected outcome."
)

if submitted and not question.strip():
    st.warning("Type a question before asking.")

if submitted and question.strip():
    with st.spinner(_spinner_text(mode)):
        try:
            resp = httpx.post(
                f"{API_BASE_URL}/ask",
                json={"question": question, "mode": mode},
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.TimeoutException:
            st.error(
                "The backend timed out. The model may still be loading; "
                "try again shortly."
            )
            st.stop()
        except Exception as exc:
            st.error(f"Could not reach the backend: {type(exc).__name__}")
            st.stop()

    if resp.status_code == 409:
        st.warning(_error_detail(resp) or "Corpus is empty.")
        st.stop()
    if resp.status_code >= 400:
        hint = _STATUS_HINTS.get(resp.status_code)
        message = f"Request failed ({resp.status_code}): {_error_detail(resp)}"
        if hint:
            message += f"\n\n{hint}"
        st.error(message)
        st.stop()

    # Persist so the result survives unrelated reruns (mode toggles, etc.).
    st.session_state["result"] = {"question": question, "data": resp.json()}

result = st.session_state.get("result")
if result is None:
    with st.container(border=True):
        st.markdown(
            '<div class="eg-empty">'
            '<p class="eg-empty-lede"><strong>Ask a question</strong> to get '
            "an evidence-grounded answer.</p>"
            '<ol class="eg-steps">'
            "<li><strong>Retrieve</strong> the advisory passages closest to "
            "the question.</li>"
            "<li><strong>Answer</strong> from those passages, with citation "
            "markers.</li>"
            "<li><strong>Claim-level verification</strong> (Verified mode): "
            "extract the answer's claims and verdict each one against the "
            "evidence, reported beside the answer instead of rewriting "
            "it.</li>"
            "</ol></div>",
            unsafe_allow_html=True,
        )
else:
    render_result(result["data"])
