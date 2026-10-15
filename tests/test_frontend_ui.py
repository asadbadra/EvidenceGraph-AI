"""Offline tests for the frontend's research-transparency decisions.

These exercise `frontend/ui_logic` only: pure functions with no streamlit
import, so the suite stays fully offline and no UI dependency leaks into
the backend test environment. Assertions target message presence, adapted
wording, and verbatim metric pass-through -- never CSS formatting.
"""

from __future__ import annotations

from app.verification.verdicts import ClaimVerdict
from frontend.ui_logic import (
    MAIN_CLAIM_PROXY_NOTE,
    VERDICT_LEGEND,
    cited_chunk_ids,
    evidence_limitation_warning,
    preview,
    provider_display,
    summary_card_specs,
)


def _verdict(index: int, label: str, claim: str = "The claim under test.") -> dict:
    return {
        "claim_index": index,
        "claim_text": claim,
        "label": label,
        "evidence_chunk_ids": [3],
        "rationale": "",
        "anomalies": [],
    }


def _summary(**overrides) -> dict:
    base = {
        "total": 3,
        "supported": 1,
        "contradicted": 0,
        "insufficient_evidence": 1,
        "unverifiable": 1,
        "with_anomalies": 0,
        "abstentions": 2,
    }
    base.update(overrides)
    return base


# --- Evidence-limitation warning: visibility -------------------------------


def test_warning_shown_when_broad_conclusion_insufficient() -> None:
    verdicts = [
        _verdict(0, "insufficient_evidence", "Open source models can easily be hacked."),
        _verdict(1, "supported", "A second, established claim."),
    ]
    msg = evidence_limitation_warning(verdicts)
    assert isinstance(msg, str)
    assert msg.startswith("Evidence limitation:")
    assert "was not established by the retrieved evidence" in msg
    assert "Review the claim-level verdicts below" in msg
    # Adapted wording names the actual verdict for the reader.
    assert 'Claim (insufficient evidence): "Open source models can easily be hacked."' in msg


def test_warning_shown_for_unverifiable_with_adapted_wording() -> None:
    msg = evidence_limitation_warning(
        [_verdict(0, "unverifiable", "A claim with no checkable candidates.")]
    )
    assert isinstance(msg, str)
    assert "could not be verified against the retrieved evidence" in msg
    assert "was not established by" not in msg
    assert 'Claim (unverifiable): "A claim with no checkable candidates."' in msg


# --- Evidence-limitation warning: non-visibility ---------------------------


def test_no_warning_when_broad_conclusion_supported() -> None:
    # Supported main conclusion with abstaining later claims: condition
    # is not met, so the warning must stay hidden.
    verdicts = [
        _verdict(0, "supported", "The main conclusion the corpus states."),
        _verdict(1, "insufficient_evidence", "A later claim nobody checked."),
        _verdict(2, "unverifiable", "Another abstained claim."),
    ]
    assert evidence_limitation_warning(verdicts) is None


def test_no_warning_when_broad_conclusion_contradicted() -> None:
    verdicts = [_verdict(0, "contradicted", "A claim the corpus refutes.")]
    assert evidence_limitation_warning(verdicts) is None


def test_no_warning_without_claims() -> None:
    # Zero extracted claims: nothing to warn about (empty-state territory).
    assert evidence_limitation_warning([]) is None


def test_no_warning_when_first_claim_missing() -> None:
    # Verdicts exist but none is claim_index 0: no identifiable main claim.
    verdicts = [_verdict(1, "insufficient_evidence", "Not the opening claim.")]
    assert evidence_limitation_warning(verdicts) is None


def test_no_warning_for_unknown_label() -> None:
    verdicts = [_verdict(0, "some_future_label", "A claim with an unmapped label.")]
    assert evidence_limitation_warning(verdicts) is None


def test_warning_quotes_a_long_claim_verbatim_but_truncated() -> None:
    long_claim = "x" * 200
    msg = evidence_limitation_warning([_verdict(0, "insufficient_evidence", long_claim)])
    assert isinstance(msg, str)
    quoted = preview(long_claim, 160)
    assert quoted in msg
    assert long_claim not in msg


# --- Compact research summary: cards ---------------------------------------


def test_summary_cards_absent_when_no_claims_extracted() -> None:
    # Zero-claim runs must not render misleading zero-valued cards.
    assert summary_card_specs(_summary(total=0)) is None


def test_summary_cards_pass_api_counts_through_verbatim() -> None:
    summary = _summary(
        total=7, supported=2, contradicted=1, insufficient_evidence=3, unverifiable=1
    )
    specs = summary_card_specs(summary)
    assert specs == [
        ("total", 7),
        ("supported", 2),
        ("contradicted", 1),
        ("insufficient_evidence", 3),
        ("unverifiable", 1),
    ]


# --- Shared preview helper --------------------------------------------------


def test_preview_truncates_only_when_needed() -> None:
    assert preview("short claim", 110) == "short claim"
    cut = preview("y" * 111, 110)
    assert cut == "y" * 110 + "…"
    assert preview("  padded  ", 110) == "padded"


# --- Verdict legend (UI glosses pinned to the real label semantics) ---------


def test_verdict_legend_matches_api_label_vocabulary() -> None:
    labels = [label for label, _kind, _gloss in VERDICT_LEGEND]
    assert labels == [member.value for member in ClaimVerdict]


def test_verdict_legend_kinds_follow_label_semantics() -> None:
    abstentions = {label for label, kind, _ in VERDICT_LEGEND if kind == "abstention"}
    assert abstentions == {
        member.value for member in ClaimVerdict if member.is_abstention
    }
    engaged = {label for label, kind, _ in VERDICT_LEGEND if kind == "engaged"}
    assert engaged == {member.value for member in ClaimVerdict if member.requires_evidence}


def test_verdict_legend_glosses_are_present_and_distinct() -> None:
    glosses = [gloss for _label, _kind, gloss in VERDICT_LEGEND]
    assert all(gloss.strip() for gloss in glosses)
    assert len(set(glosses)) == len(glosses)


# --- Main-claim proxy disclosure ---------------------------------------------


def test_proxy_note_discloses_positional_proxy() -> None:
    # The warning's "broad conclusion" must never be presented as a
    # guaranteed semantic conclusion detector.
    assert "claim index 0" in MAIN_CLAIM_PROXY_NOTE
    assert "positional proxy" in MAIN_CLAIM_PROXY_NOTE
    assert "not a semantic conclusion detector" in MAIN_CLAIM_PROXY_NOTE


# --- Honest provider display + cited/retrieved distinction --------------------


def test_provider_display_names_interface_not_destination() -> None:
    # "openai" names the OpenAI-compatible client interface; the UI must
    # not imply the OpenAI API is being called (deployment: local Ollama).
    assert provider_display("openai") == "openai-compatible"
    assert provider_display("mock") == "mock (stub)"
    assert provider_display("vllm") == "vllm"  # unknown values pass through


def test_cited_chunk_ids_come_from_citations_only() -> None:
    citations = [
        {"marker": "[1]", "chunk_id": 3},
        {"marker": "[2]", "chunk_id": 5},
    ]
    assert cited_chunk_ids(citations) == {3, 5}
    assert cited_chunk_ids([]) == set()
