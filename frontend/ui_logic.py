"""Pure decision logic for the EvidenceGraph AI Streamlit frontend.

Kept import-light on purpose: standard library only, no streamlit and no
httpx. This lets the offline test suite exercise the frontend's
research-integrity decisions on the host without installing the UI stack
(`python -m pytest tests/test_frontend_ui.py`), while `app.py` imports the
same functions at runtime.

Research-integrity rules encoded here:

- The evidence-limitation warning is ADDITIVE: app.py renders it next to
  the original answer, which is never edited, rewritten, or suppressed.
- It fires only for the abstention labels (`insufficient_evidence`,
  `unverifiable`) on the answer's main conclusion. `supported` and
  `contradicted` mean the evidence engaged the claim, so the condition is
  not met and no warning is returned.
- Summary-card counts are passed through verbatim from the API's
  `verification.summary`; nothing here recalculates or infers metrics.

Two render inputs live here so the honesty wording is testable offline:

- `VERDICT_LEGEND` glosses are condensed from the `ClaimVerdict` label
  docstring in `app/verification/verdicts.py` (the source of truth).
- `MAIN_CLAIM_PROXY_NOTE` discloses next to the warning that the
  "broad conclusion" is a positional proxy, not a semantic detector.

Two small display mappings also live here because they carry honesty
weight and must stay offline-testable:

- `provider_display`: the backend's `llm_provider` value names the
  CLIENT INTERFACE, not the destination API. `openai` means the
  OpenAI-compatible client interface -- this deployment routes it at a
  local Ollama server -- so the UI must never present it as "the
  OpenAI API".
- `cited_chunk_ids`: the cited/retrieved distinction (a passage the
  answer actually referenced vs. one merely retrieved) is derived from
  the API's citation list, never inferred.

Honest limitation (documented, not hidden): the API schema has no field
marking which claim is the answer's broad/main conclusion. Claim
extraction preserves answer order, so `claim_index 0` -- the answer's
opening assertion -- is used as the deterministic proxy. The returned
warning quotes that claim verbatim so the reader sees exactly which
claim triggered it, and `MAIN_CLAIM_PROXY_NOTE` states the proxy
plainly wherever the warning is shown.
"""

from __future__ import annotations

WARNING_PREFIX = "Evidence limitation"

# Disclosure rendered directly under every evidence-limitation warning:
# the warning's "broad conclusion" is claim_index 0, a positional proxy,
# never a semantic conclusion detector. Wording is pinned by tests so the
# UI cannot silently drop the caveat.
MAIN_CLAIM_PROXY_NOTE = (
    'Main-claim note: "broad conclusion" = the answer\'s opening claim '
    "(claim index 0) — a positional proxy, not a semantic conclusion "
    "detector."
)

# Reader-facing legend: (api_label, kind, gloss). Glosses are condensed
# from the `ClaimVerdict` label docstring in
# app/verification/verdicts.py -- the source of truth for what each
# label means. `kind` separates labels that make an assertion about the
# evidence ("engaged") from abstentions (never confirmations).
VERDICT_LEGEND: tuple[tuple[str, str, str], ...] = (
    ("supported", "engaged", "an evidence passage entails the claim"),
    ("contradicted", "engaged", "an evidence passage conflicts with the claim"),
    (
        "insufficient_evidence",
        "abstention",
        "candidates were inspected, but none settles it — the corpus is silent",
    ),
    (
        "unverifiable",
        "abstention",
        "no usable candidates, or the claim is not a factual proposition",
    ),
)

# Reader-facing form of the backend's `llm_provider` value. The field
# names the CLIENT INTERFACE, not the destination API: "openai" is the
# OpenAI-compatible interface, which this deployment points at a local
# Ollama server (LLM_BASE_URL, see README/docker-compose.yml). Showing
# it verbatim would imply the OpenAI API is being called; it is not.
_PROVIDER_DISPLAY = {
    "openai": "openai-compatible",
    "mock": "mock (stub)",
}


def provider_display(provider: str) -> str:
    """Interface name for the status panel; unknown values pass through."""
    return _PROVIDER_DISPLAY.get(provider, provider)


def cited_chunk_ids(citations: list[dict]) -> set[int]:
    """Chunk ids the answer actually cited (from the API citation list).

    Used to separate cited sources from retrieved-but-uncited passages;
    derived only from real `citations` fields, never inferred from text.
    """
    return {int(c["chunk_id"]) for c in citations}

# Verdict label -> verb phrase describing what the evidence failed to do.
# Only abstention labels belong here: these are the labels under which
# the corpus could NOT answer the claim.
_LIMITATION_PHRASES = {
    "insufficient_evidence": "was not established by",
    "unverifiable": "could not be verified against",
}

# Reader-facing form of the two abstention labels inside messages.
_DISPLAY = {
    "insufficient_evidence": "insufficient evidence",
    "unverifiable": "unverifiable",
}


def preview(text: str, limit: int = 110) -> str:
    """Shorten `text` for titles/messages; appends an ellipsis when cut."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\u2026"


def evidence_limitation_warning(verdicts: list[dict]) -> str | None:
    """Warning text when the answer's broad conclusion is unestablished.

    Returns `None` when the condition is not met: no verdicts, no
    `claim_index 0`, or a main-claim verdict of `supported` /
    `contradicted` (or any label outside the abstention pair).
    """
    main = next((v for v in verdicts if v.get("claim_index") == 0), None)
    if main is None:
        return None
    phrase = _LIMITATION_PHRASES.get(main.get("label", ""))
    if phrase is None:
        return None
    claim = preview(main.get("claim_text", ""), 160)
    display = _DISPLAY.get(main["label"], main["label"])
    return (
        f"{WARNING_PREFIX}: The generated answer's broad conclusion "
        f"{phrase} the retrieved evidence. "
        "Review the claim-level verdicts below.\n\n"
        f'Claim ({display}): "{claim}"'
    )


def summary_card_specs(summary: dict) -> list[tuple[str, int]] | None:
    """`(api_field, count)` pairs for the research summary cards.

    Field order: total, supported, contradicted, insufficient_evidence,
    unverifiable. Values come verbatim from the API summary. Returns
    `None` when no claims were extracted, so an empty run cannot render
    misleading zero-valued cards (app.py shows an explanatory empty state
    instead).
    """
    total = summary["total"]
    if not total:
        return None
    return [
        ("total", total),
        ("supported", summary["supported"]),
        ("contradicted", summary["contradicted"]),
        ("insufficient_evidence", summary["insufficient_evidence"]),
        ("unverifiable", summary["unverifiable"]),
    ]
