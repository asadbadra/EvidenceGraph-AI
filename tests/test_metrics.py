"""Tests for the evaluation metrics (Phase 2, Stage 2.6).

SCOPE: these tests prove the metric FUNCTIONS compute correctly. They are not
an evaluation result and they are not evidence that the verifier is accurate.
The pilot set is 24 hand-labelled questions over a 6-record corpus; any
agreement figure computed on it is a smoke signal, not a benchmark.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas import RetrievedChunk
from app.verification.claims import Claim
from app.verification.judge import RuleBasedJudge
from app.verification.metrics import (
    Agreement,
    citation_quality,
    judge_agreement,
    match_claims_to_gold,
    mechanism_metrics,
    normalize_claim,
)
from app.verification.verdicts import ClaimVerdict, make_verdict

PILOT = Path(__file__).resolve().parent.parent / "data" / "sample" / "eval_questions.json"


def _verdict(text: str, label: ClaimVerdict, ids: tuple[int, ...] = ()) -> object:
    """Build a verdict, supplying evidence ids where the invariant requires them."""
    claim = Claim(text=text, start=0, end=len(text))
    if label.requires_evidence and not ids:
        # The invariant downgrades support/contradiction with no evidence, so
        # a counting test must supply a real basis rather than trip it.
        ids = (1,)
    return make_verdict(
        claim, label, evidence_chunk_ids=ids, candidate_chunk_ids=(1, 2)
    )


# --------------------------------------------------------------------------
# Pilot dataset
# --------------------------------------------------------------------------


def test_pilot_dataset_exists_and_loads() -> None:
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    assert len(payload["questions"]) == 24, "6 categories x 4 questions"


def test_pilot_has_six_categories_of_four() -> None:
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    categories: dict[str, int] = {}
    for entry in payload["questions"]:
        categories[entry["category"]] = categories.get(entry["category"], 0) + 1
    assert categories == {
        "directly_answerable": 4,
        "multi_hop": 4,
        "not_in_corpus": 4,
        "plausible_but_absent": 4,
        "contradiction_misattribution": 4,
        "non_factual": 4,
    }


def test_pilot_question_ids_are_unique() -> None:
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    ids = [entry["id"] for entry in payload["questions"]]
    assert len(set(ids)) == 24


def test_pilot_gold_labels_are_within_the_vocabulary() -> None:
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    valid = {"supported", "contradicted", "insufficient_evidence", "unverifiable"}
    for entry in payload["questions"]:
        for gold in entry.get("gold_claims", []):
            assert gold["gold_label"] in valid, entry["id"]


def test_pilot_non_factual_questions_label_unverifiable() -> None:
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    for entry in payload["questions"]:
        if entry["category"] == "non_factual":
            for gold in entry["gold_claims"]:
                assert gold["gold_label"] == "unverifiable", entry["id"]


def test_pilot_not_in_corpus_questions_never_label_supported() -> None:
    """An absent fact must not be labelled as supported."""
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    for entry in payload["questions"]:
        if entry["category"] == "not_in_corpus":
            for gold in entry["gold_claims"]:
                assert gold["gold_label"] != "supported", entry["id"]


def test_pilot_file_declares_itself_a_pilot() -> None:
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    assert "PILOT" in payload["scope_note"].upper()


# --------------------------------------------------------------------------
# Mechanism metrics
# --------------------------------------------------------------------------


def test_mechanism_metrics_counts_labels() -> None:
    verdicts = [
        _verdict("a", ClaimVerdict.SUPPORTED, (1,)),
        _verdict("b", ClaimVerdict.CONTRADICTED),
        _verdict("c", ClaimVerdict.INSUFFICIENT_EVIDENCE),
        _verdict("d", ClaimVerdict.UNVERIFIABLE),
    ]
    m = mechanism_metrics(verdicts)
    assert m.total_claims == 4
    assert (m.supported, m.contradicted, m.insufficient_evidence, m.unverifiable) == (1, 1, 1, 1)
    # Supported and contradicted both carry a basis; abstentions carry none.
    assert m.claims_with_evidence == 2


def test_mechanism_metrics_rates() -> None:
    verdicts = [
        _verdict("a", ClaimVerdict.SUPPORTED, (1,)),
        _verdict("b", ClaimVerdict.SUPPORTED),
        _verdict("c", ClaimVerdict.CONTRADICTED),
        _verdict("d", ClaimVerdict.INSUFFICIENT_EVIDENCE),
    ]
    m = mechanism_metrics(verdicts)
    assert m.unsupported_rate == 0.5
    assert m.abstention_rate == 0.25
    assert m.contradiction_rate == 0.25


def test_mechanism_metrics_over_no_claims_is_zero_not_divide_error() -> None:
    m = mechanism_metrics([])
    assert m.total_claims == 0
    assert m.unsupported_rate == 0.0


def test_mechanism_metrics_counts_anomalies() -> None:
    verdict = make_verdict(
        Claim(text="x", start=0, end=1),
        ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=[999],
        candidate_chunk_ids=[1],
    )
    m = mechanism_metrics([verdict])
    assert m.with_anomalies == 1


# --------------------------------------------------------------------------
# Citation quality
# --------------------------------------------------------------------------


def test_invalid_marker_rate() -> None:
    q = citation_quality(citations=3, invalid_markers=1)
    assert q.invalid_marker_rate == 0.25


def test_verified_citations_is_none_when_no_check_was_performed() -> None:
    """Baseline: 'unknown' must not read as 'zero problems'."""
    q = citation_quality(citations=3, invalid_markers=0)
    assert q.verified_citations is None


def test_no_citations_yields_zero_rate() -> None:
    assert citation_quality(0, 0).invalid_marker_rate == 0.0


# --------------------------------------------------------------------------
# Judge vs human agreement
# --------------------------------------------------------------------------


def test_agreement_perfect_when_labels_match() -> None:
    a = judge_agreement(["supported", "contradicted"], ["supported", "contradicted"])
    assert a.matched == 2 and a.correct == 2
    assert a.accuracy == 1.0
    assert a.coverage == 1.0


def test_agreement_counts_disagreement() -> None:
    a = judge_agreement(["supported"], ["contradicted"])
    assert a.accuracy == 0.0
    assert a.confusion[("contradicted", "supported")] == 1


def test_agreement_excludes_unlabelled_entries() -> None:
    """An unlabelled claim must not count as agreement or disagreement."""
    a = judge_agreement(["supported", ""], ["supported", "supported"])
    assert a.matched == 1
    assert a.unlabeled == 1
    assert a.accuracy == 1.0
    assert a.coverage == 0.5


def test_agreement_rejects_misaligned_sequences() -> None:
    """Silently truncating would corrupt the metric."""
    with pytest.raises(ValueError, match="align"):
        judge_agreement(["supported"], ["supported", "contradicted"])


def test_agreement_per_label_reports_correct_and_incorrect() -> None:
    a = judge_agreement(
        ["supported", "supported", "contradicted"],
        ["supported", "contradicted", "contradicted"],
    )
    # (gold_total, correct, incorrect)
    assert a.per_label["supported"] == (1, 1, 0)
    assert a.per_label["contradicted"] == (2, 1, 1)


def test_agreement_over_empty_input_is_zero() -> None:
    a = judge_agreement([], [])
    assert a.matched == 0 and a.accuracy == 0.0 and a.coverage == 0.0


def test_agreement_tolerates_case_and_whitespace() -> None:
    a = judge_agreement(["  Supported "], ["supported"])
    assert a.accuracy == 1.0


# --------------------------------------------------------------------------
# Claim-to-gold matching
# --------------------------------------------------------------------------


def test_matching_is_exact_after_normalisation() -> None:
    gold = [{"text": "Log4j2 allows RCE.", "gold_label": "supported"}]
    assert match_claims_to_gold(["log4j2 allows rce"], gold) == ["supported"]


def test_matching_returns_none_for_unmatched_claims() -> None:
    gold = [{"text": "Log4j2 allows RCE.", "gold_label": "supported"}]
    assert match_claims_to_gold(["Something else entirely"], gold) == [None]


def test_matching_does_not_pair_a_merely_similar_claim() -> None:
    """Fuzzy matching would inflate agreement; exact matching must not."""
    gold = [{"text": "CVE-2018-13379 allows RCE.", "gold_label": "supported"}]
    assert match_claims_to_gold(["CVE-2018-13379 allows RCE via JNDI"], gold) == [None]


def test_normalization_folds_case_punctuation_and_whitespace() -> None:
    assert normalize_claim("  Log4j2,  allows   RCE! ") == "log4j2 allows rce"


def test_end_to_end_agreement_from_matching() -> None:
    gold = [{"text": "FortiOS is affected.", "gold_label": "supported"}]
    extracted = ["fortios is affected", "an unrelated claim"]
    labels = match_claims_to_gold(extracted, gold)
    predicted = ["supported", "supported"]
    comparable = [p for p, g in zip(predicted, labels) if g is not None]
    gold_aligned = [g for g in labels if g is not None]
    a = judge_agreement(comparable, gold_aligned)
    assert a.matched == 1
    assert a.accuracy == 1.0
