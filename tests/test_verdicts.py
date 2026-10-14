"""Tests for verdict types and the no-fabrication invariant (Stage 2.1).

SCOPE NOTE, stated plainly: these tests prove the *invariant holds*, not
that the verifier is accurate. They show that a verdict cannot claim support
without naming evidence, and cannot name evidence outside the candidate set
it was handed. Whether a real judge applies the right label to real text is
a separate question, answerable only against the manually labelled set in
Stage 2.6. Do not read green tests here as evidence of verifier quality.
"""

from __future__ import annotations

import pytest

from app.verification.claims import Claim, extract_claims
from app.verification.verdicts import (
    ClaimVerdict,
    Verdict,
    VerdictSummary,
    make_verdict,
    summarize,
)


def _claim(text: str = "Log4j2 allows remote code execution.") -> Claim:
    return Claim(text=text, start=0, end=len(text), markers=("[1]",))


CANDIDATES = [3, 7, 11]


# --------------------------------------------------------------------------
# Label semantics
# --------------------------------------------------------------------------

def test_labels_are_strings_so_they_serialize_cleanly() -> None:
    assert ClaimVerdict.SUPPORTED == "supported"
    assert ClaimVerdict.CONTRADICTED == "contradicted"
    assert ClaimVerdict.INSUFFICIENT_EVIDENCE == "insufficient_evidence"
    assert ClaimVerdict.UNVERIFIABLE == "unverifiable"


def test_exactly_four_labels_exist() -> None:
    assert len(ClaimVerdict) == 4


def test_requires_and_forbids_evidence_are_disjoint_and_exhaustive() -> None:
    """Every label is exactly one of the two; the sets never overlap."""
    for label in ClaimVerdict:
        assert label.requires_evidence != label.forbids_evidence
        assert label.requires_evidence or label.forbids_evidence


def test_both_abstention_labels_report_as_abstentions() -> None:
    assert ClaimVerdict.INSUFFICIENT_EVIDENCE.is_abstention
    assert ClaimVerdict.UNVERIFIABLE.is_abstention
    assert not ClaimVerdict.SUPPORTED.is_abstention
    assert not ClaimVerdict.CONTRADICTED.is_abstention


# --------------------------------------------------------------------------
# Happy path: legal verdicts pass through untouched
# --------------------------------------------------------------------------

def test_supported_with_evidence_is_kept() -> None:
    v = make_verdict(_claim(), ClaimVerdict.SUPPORTED, evidence_chunk_ids=[7])
    assert v.label is ClaimVerdict.SUPPORTED
    assert v.evidence_chunk_ids == (7,)
    assert v.anomalies == ()
    assert not v.has_anomalies


def test_contradicted_with_evidence_is_kept() -> None:
    v = make_verdict(_claim(), ClaimVerdict.CONTRADICTED, evidence_chunk_ids=[3])
    assert v.label is ClaimVerdict.CONTRADICTED
    assert v.anomalies == ()


def test_abstentions_with_no_evidence_need_no_correction() -> None:
    for label in (ClaimVerdict.INSUFFICIENT_EVIDENCE, ClaimVerdict.UNVERIFIABLE):
        v = make_verdict(_claim(), label)
        assert v.label is label
        assert v.evidence_chunk_ids == ()
        assert v.anomalies == (), f"{label} with no evidence is legal, not anomalous"


def test_rationale_and_claim_are_preserved() -> None:
    claim = _claim()
    v = make_verdict(claim, ClaimVerdict.SUPPORTED, evidence_chunk_ids=[7], rationale="matches")
    assert v.claim is claim
    assert v.rationale == "matches"


# --------------------------------------------------------------------------
# Rule 1: support/contradiction require named evidence
# --------------------------------------------------------------------------

def test_supported_without_evidence_is_downgraded_not_passed_through() -> None:
    """The core rule: an evidence-free 'supported' verdict is impossible."""
    v = make_verdict(_claim(), ClaimVerdict.SUPPORTED)
    assert v.label is ClaimVerdict.UNVERIFIABLE
    assert v.has_anomalies
    assert "requires evidence" in v.anomalies[0]


def test_contradicted_without_evidence_is_downgraded() -> None:
    v = make_verdict(_claim(), ClaimVerdict.CONTRADICTED)
    assert v.label is ClaimVerdict.UNVERIFIABLE
    assert v.has_anomalies


def test_downgraded_verdict_records_why() -> None:
    v = make_verdict(_claim(), ClaimVerdict.SUPPORTED)
    assert "downgraded" in v.anomalies[0]
    assert "supported" in v.anomalies[0]


def test_downgraded_verdict_never_claims_evidence() -> None:
    v = make_verdict(_claim(), ClaimVerdict.SUPPORTED)
    assert v.evidence_chunk_ids == ()
    assert not v.carries_evidence


# --------------------------------------------------------------------------
# Rule 2: no evidence outside the candidate set
# --------------------------------------------------------------------------

def test_stray_evidence_id_is_dropped_and_recorded() -> None:
    v = make_verdict(
        _claim(), ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=[7, 999], candidate_chunk_ids=CANDIDATES,
    )
    assert v.evidence_chunk_ids == (7,)
    assert "999" in v.anomalies[0]
    assert v.has_anomalies


def test_evidence_entirely_outside_candidates_forces_downgrade() -> None:
    """Fabricated-only basis: remove the stray ids and rule 1 must fire.

    Order matters in `make_verdict`; this is the test that pins it. Drop the
    ids first, then the now-empty evidence list downgrades the label.
    """
    v = make_verdict(
        _claim(), ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=[999, 1000], candidate_chunk_ids=CANDIDATES,
    )
    assert v.evidence_chunk_ids == ()
    assert v.label is ClaimVerdict.UNVERIFIABLE
    assert len(v.anomalies) == 2


def test_ids_inside_candidates_are_kept() -> None:
    v = make_verdict(
        _claim(), ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=[3, 11], candidate_chunk_ids=CANDIDATES,
    )
    assert v.evidence_chunk_ids == (3, 11)
    assert v.anomalies == ()


def test_no_candidate_set_skips_membership_check() -> None:
    """Before Stage 2.2 supplies candidates, only rule 1 applies."""
    v = make_verdict(_claim(), ClaimVerdict.SUPPORTED, evidence_chunk_ids=[999])
    assert v.evidence_chunk_ids == (999,)
    assert v.anomalies == ()


def test_empty_candidate_set_rejects_everything() -> None:
    v = make_verdict(
        _claim(), ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=[3], candidate_chunk_ids=[],
    )
    assert v.label is ClaimVerdict.UNVERIFIABLE
    assert v.evidence_chunk_ids == ()


def test_non_list_candidate_sequences_are_accepted() -> None:
    v = make_verdict(
        _claim(), ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=(3, 7), candidate_chunk_ids=iter([3, 7]),
    )
    assert v.evidence_chunk_ids == (3, 7)


# --------------------------------------------------------------------------
# Rule 3: abstention labels must not carry evidence
# --------------------------------------------------------------------------

def test_insufficient_evidence_with_ids_clears_them() -> None:
    v = make_verdict(
        _claim(), ClaimVerdict.INSUFFICIENT_EVIDENCE,
        evidence_chunk_ids=[7], candidate_chunk_ids=CANDIDATES,
    )
    assert v.label is ClaimVerdict.INSUFFICIENT_EVIDENCE, "label itself is correct"
    assert v.evidence_chunk_ids == ()
    assert v.has_anomalies


def test_unverifiable_with_ids_clears_them() -> None:
    v = make_verdict(_claim(), ClaimVerdict.UNVERIFIABLE, evidence_chunk_ids=[7])
    assert v.label is ClaimVerdict.UNVERIFIABLE
    assert v.evidence_chunk_ids == ()
    assert v.has_anomalies


# --------------------------------------------------------------------------
# Deduplication
# --------------------------------------------------------------------------

def test_duplicate_ids_collapse_to_one_piece_of_evidence() -> None:
    """The same chunk cited twice is one piece of evidence, not two."""
    v = make_verdict(_claim(), ClaimVerdict.SUPPORTED, evidence_chunk_ids=[7, 7, 7])
    assert v.evidence_chunk_ids == (7,)


def test_duplicates_are_removed_before_the_candidate_check() -> None:
    v = make_verdict(
        _claim(), ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=[999, 999], candidate_chunk_ids=CANDIDATES,
    )
    assert v.evidence_chunk_ids == ()
    assert v.label is ClaimVerdict.UNVERIFIABLE


# --------------------------------------------------------------------------
# THE INVARIANT: exhaustive postcondition check
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label", list(ClaimVerdict))
@pytest.mark.parametrize(
    "ids",
    [(), (3,), (3, 7), (999,), (3, 999), (3, 3), (7, 11, 999)],
)
@pytest.mark.parametrize("candidates", [None, [], [3], [3, 7], [999], [3, 7, 999]])
def test_invariant_holds_for_every_combination(
    label: ClaimVerdict, ids: tuple[int, ...], candidates: list[int] | None
) -> None:
    """Postcondition, checked over the full cross-product.

    For every verdict `make_verdict` can produce:

    1. A label that asserts support/contradiction names >= 1 evidence chunk.
    2. A label that asserts the evidence is silent names 0 evidence chunks.
    3. Every named id belongs to the candidate set, when one was supplied.

    These three together are the no-fabrication guarantee: there is no input
    for which the function returns `supported` without real, in-set evidence.
    """
    v = make_verdict(
        _claim(), label, evidence_chunk_ids=ids, candidate_chunk_ids=candidates
    )

    if v.label.requires_evidence:
        assert len(v.evidence_chunk_ids) >= 1, (
            f"{v.label} returned with no evidence for input ids={ids}"
        )
    if v.label.forbids_evidence:
        assert v.evidence_chunk_ids == (), (
            f"{v.label} returned carrying evidence {v.evidence_chunk_ids}"
        )
    if candidates is not None:
        assert set(v.evidence_chunk_ids) <= set(candidates), (
            f"evidence {v.evidence_chunk_ids} escaped the candidate set {candidates}"
        )


def test_invariant_is_satisfied_by_a_supported_verdict_with_real_evidence() -> None:
    """Positive control: the exhaustive test is not passing vacuously."""
    v = make_verdict(
        _claim(), ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=[7], candidate_chunk_ids=CANDIDATES,
    )
    assert v.label is ClaimVerdict.SUPPORTED
    assert v.evidence_chunk_ids == (7,)
    assert v.anomalies == ()


# --------------------------------------------------------------------------
# Summary tallies
# --------------------------------------------------------------------------

def _verdicts() -> list[Verdict]:
    return [
        make_verdict(_claim(), ClaimVerdict.SUPPORTED, evidence_chunk_ids=[3]),
        make_verdict(_claim(), ClaimVerdict.CONTRADICTED, evidence_chunk_ids=[7]),
        make_verdict(_claim(), ClaimVerdict.INSUFFICIENT_EVIDENCE),
        make_verdict(_claim(), ClaimVerdict.UNVERIFIABLE),
        make_verdict(_claim(), ClaimVerdict.SUPPORTED),  # downgraded
    ]


def test_summarize_counts_each_label() -> None:
    s = summarize(_verdicts())
    assert s.total == 5
    assert s.supported == 1
    assert s.contradicted == 1
    assert s.insufficient_evidence == 1
    assert s.unverifiable == 2, "the downgraded 'supported' lands here"
    assert s.with_anomalies == 1


def test_summary_abstentions_and_with_evidence_helpers() -> None:
    s = summarize(_verdicts())
    assert s.abstentions == 3
    assert s.with_evidence == 2


def test_summarize_of_empty_list_is_all_zeroes() -> None:
    s = summarize([])
    assert s == VerdictSummary()
    assert s.abstentions == 0 and s.with_evidence == 0


def test_summary_counts_match_input_length() -> None:
    s = summarize(_verdicts())
    assert s.supported + s.contradicted + s.insufficient_evidence + s.unverifiable == s.total


# --------------------------------------------------------------------------
# Integration with real extracted claims
# --------------------------------------------------------------------------

def test_verdicts_operate_on_actually_extracted_claims() -> None:
    """Not a fabricated Claim object -- extract, then verify."""
    result = extract_claims("Log4j2 allows RCE [1]. What about DoS?")
    assert len(result.claims) == 1
    claim = result.claims[0]
    v = make_verdict(claim, ClaimVerdict.SUPPORTED, evidence_chunk_ids=[7])
    assert v.claim.markers == ("[1]",)
    assert v.claim.text == "Log4j2 allows RCE."


def test_verdict_type_is_importable_from_the_package_root() -> None:
    from app.verification import ClaimVerdict as CV, Verdict as V, make_verdict as mv

    assert CV is ClaimVerdict
    assert V is Verdict
    assert mv is make_verdict


# --------------------------------------------------------------------------
# Defense in depth: direct construction cannot bypass the invariant
# --------------------------------------------------------------------------

def test_direct_construction_rejects_supported_without_evidence() -> None:
    """The invariant holds on the direct path too, not only via make_verdict."""
    with pytest.raises(ValueError, match="requires evidence"):
        Verdict(claim=_claim(), label=ClaimVerdict.SUPPORTED)


def test_direct_construction_rejects_abstention_with_evidence() -> None:
    with pytest.raises(ValueError, match="cannot carry evidence"):
        Verdict(
            claim=_claim(),
            label=ClaimVerdict.UNVERIFIABLE,
            evidence_chunk_ids=(7,),
        )


def test_direct_construction_accepts_a_legal_verdict() -> None:
    v = Verdict(claim=_claim(), label=ClaimVerdict.SUPPORTED, evidence_chunk_ids=(7,))
    assert v.label is ClaimVerdict.SUPPORTED


def test_make_verdict_never_triggers_the_post_init_guard() -> None:
    """Consistency: the correcting path always yields a buildable Verdict."""
    for label in ClaimVerdict:
        for ids in [(), (3,), (999,), (3, 999)]:
            for candidates in [None, [3], []]:
                make_verdict(
                    _claim(), label,
                    evidence_chunk_ids=ids, candidate_chunk_ids=candidates,
                )  # must not raise


# --------------------------------------------------------------------------
# Regression: rule 2 (candidate membership) on direct construction
# --------------------------------------------------------------------------

def test_direct_construction_rejects_id_outside_an_explicit_candidate_set() -> None:
    """Rule 2 now holds on the direct path when a candidate set is supplied."""
    with pytest.raises(ValueError, match="outside the candidate set"):
        Verdict(
            claim=_claim(),
            label=ClaimVerdict.SUPPORTED,
            evidence_chunk_ids=(999,),
            candidate_chunk_ids=(3,),
        )


def test_direct_construction_accepts_id_inside_the_candidate_set() -> None:
    v = Verdict(
        claim=_claim(),
        label=ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=(3,),
        candidate_chunk_ids=(3, 4),
    )
    assert v.evidence_chunk_ids == (3,)


def test_direct_construction_without_candidate_set_skips_membership_check() -> None:
    """No candidate set means nothing to check against -- not an error.

    This is the honest behaviour: the membership rule can only be enforced
    when the verifier was handed a candidate set. Omitting it is allowed and
    is documented as skipping rule 2.
    """
    v = Verdict(claim=_claim(), label=ClaimVerdict.SUPPORTED, evidence_chunk_ids=(7,))
    assert v.evidence_chunk_ids == (7,)
    assert v.candidate_chunk_ids is None


def test_direct_construction_still_guards_rules_one_and_three_with_candidates() -> None:
    """Adding the candidate set must not weaken the existing guards."""
    with pytest.raises(ValueError, match="requires evidence"):
        Verdict(
            claim=_claim(),
            label=ClaimVerdict.SUPPORTED,
            candidate_chunk_ids=(3,),
        )
    with pytest.raises(ValueError, match="cannot carry evidence"):
        Verdict(
            claim=_claim(),
            label=ClaimVerdict.UNVERIFIABLE,
            evidence_chunk_ids=(3,),
            candidate_chunk_ids=(3,),
        )


def test_make_verdict_records_the_candidate_set_on_the_built_verdict() -> None:
    """The correcting path carries the set forward so rule 2 is re-checkable."""
    v = make_verdict(
        _claim(), ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=[3], candidate_chunk_ids=[3, 4],
    )
    assert v.candidate_chunk_ids == (3, 4)
    assert v.evidence_chunk_ids == (3,)


def test_make_verdict_passes_none_through_when_no_candidates_supplied() -> None:
    v = make_verdict(_claim(), ClaimVerdict.SUPPORTED, evidence_chunk_ids=[3])
    assert v.candidate_chunk_ids is None


def test_make_verdict_dropped_ids_never_trip_the_built_object_guard() -> None:
    """A fabricated id is dropped before construction, so the guard is quiet."""
    v = make_verdict(
        _claim(), ClaimVerdict.SUPPORTED,
        evidence_chunk_ids=[999], candidate_chunk_ids=[3],
    )
    assert v.label is ClaimVerdict.UNVERIFIABLE
    assert v.evidence_chunk_ids == ()
    assert any("outside the candidate set" in a for a in v.anomalies)
