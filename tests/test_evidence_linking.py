"""Tests for evidence linking (Phase 2, Stage 2.2).

Offline: a fake retriever stands in for `Retriever`, so no test opens a
socket (the autouse guard in conftest.py would fail one that did).

SCOPE NOTE: these tests prove candidate-set *mechanics* -- marker resolution,
deduplication, limit enforcement, provenance, id validation. They do not show
the verifier labels real text correctly; that is Stage 2.6.
"""

from __future__ import annotations

import pytest

from app.schemas import RetrievedChunk
from app.verification.claims import Claim, extract_claims
from app.verification.evidence import (
    CLAIM_RETRIEVAL_TOP_K,
    DEFAULT_CANDIDATE_LIMIT,
    ORIGIN_CITED,
    ORIGIN_RETRIEVED,
    EvidenceSet,
    link_evidence,
    make_evidence_verdict,
    resolve_cited_chunks,
)
from app.verification.verdicts import ClaimVerdict


def _chunk(chunk_id: int, *, external_id: str = "CVE-2021-44228", text: str = "body") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=chunk_id * 10,
        external_id=external_id,
        title=f"T{chunk_id}",
        source_url=f"https://example.invalid/{chunk_id}",
        published_at="2021-12-10",
        text=text,
        score=1.0,
    )


class FakeRetriever:
    """Stands in for `Retriever`; records calls and returns canned chunks."""

    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self.chunks = chunks or []
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, *, top_k: int = 4) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        return self.chunks[:top_k]


def _claim(markers: tuple[str, ...] = ("[1]",), text: str = "Log4j2 allows RCE.") -> Claim:
    return Claim(text=text, start=0, end=len(text), markers=markers)


# --------------------------------------------------------------------------
# Marker resolution
# --------------------------------------------------------------------------

def test_resolve_maps_markers_to_generation_passages() -> None:
    retrieved = [_chunk(101), _chunk(202), _chunk(303)]
    chunks, unresolved = resolve_cited_chunks(_claim(("[1]", "[3]")), retrieved)
    assert [c.chunk_id for c in chunks] == [101, 303]
    assert unresolved == ()


def test_resolve_records_out_of_range_markers() -> None:
    chunks, unresolved = resolve_cited_chunks(_claim(("[1]", "[9]")), [_chunk(101)])
    assert [c.chunk_id for c in chunks] == [101]
    assert unresolved == ("[9]",), "an unresolvable citation is a reportable defect"


def test_resolve_handles_zero_marker_as_unresolved() -> None:
    _chunks, unresolved = resolve_cited_chunks(_claim(("[0]",)), [_chunk(101)])
    assert unresolved == ("[0]",)


def test_resolve_dedupes_repeated_markers_on_one_claim() -> None:
    chunks, _ = resolve_cited_chunks(_claim(("[1]", "[1]")), [_chunk(101)])
    assert [c.chunk_id for c in chunks] == [101]


def test_resolve_with_no_markers_returns_empty() -> None:
    chunks, unresolved = resolve_cited_chunks(_claim(()), [_chunk(101)])
    assert chunks == [] and unresolved == ()


# --------------------------------------------------------------------------
# Candidate set assembly
# --------------------------------------------------------------------------

def test_cited_only_when_no_retriever_supplied() -> None:
    retrieved = [_chunk(101), _chunk(202)]
    result = link_evidence(_claim(("[2]",)), retrieved)
    assert [c.chunk_id for c in result.candidates] == [202]
    assert result.candidates[0].origin == ORIGIN_CITED


def test_retrieved_evidence_added_when_retriever_supplied() -> None:
    retrieved = [_chunk(101)]
    fake = FakeRetriever([_chunk(505), _chunk(606)])
    result = link_evidence(_claim(("[1]",)), retrieved, retriever=fake)

    assert [c.chunk_id for c in result.candidates] == [101, 505, 606]
    assert result.candidates[0].origin == ORIGIN_CITED
    assert result.candidates[1].origin == ORIGIN_RETRIEVED


def test_retrieval_uses_the_claim_text_not_the_full_question() -> None:
    """Claim-level retrieval must query the claim, which is the whole point."""
    fake = FakeRetriever([_chunk(505)])
    link_evidence(_claim((), text="FortiOS path traversal."), [], retriever=fake)
    assert fake.calls[0][0] == "FortiOS path traversal."


def test_independently_retrieved_evidence_alone_yields_candidates() -> None:
    """A claim citing nothing can still find support via re-retrieval."""
    fake = FakeRetriever([_chunk(707)])
    result = link_evidence(_claim(()), [], retriever=fake)
    assert [c.chunk_id for c in result.candidates] == [707]
    assert result.candidates[0].origin == ORIGIN_RETRIEVED


def test_empty_result_is_distinguishable_from_no_candidates() -> None:
    """An empty set means 'no evidence exists' -- a meaningful signal."""
    result = link_evidence(_claim(("[1]",)), [], retriever=FakeRetriever([]))
    assert result.is_empty
    assert result.chunk_ids == ()


# --------------------------------------------------------------------------
# Deduplication
# --------------------------------------------------------------------------

def test_chunk_retrieved_and_cited_is_deduplicated_as_cited() -> None:
    """Cited must win: it is the passage the citation actually points at."""
    retrieved = [_chunk(101)]
    fake = FakeRetriever([_chunk(101), _chunk(505)])
    result = link_evidence(_claim(("[1]",)), retrieved, retriever=fake)

    assert [c.chunk_id for c in result.candidates] == [101, 505]
    assert result.candidates[0].origin == ORIGIN_CITED


def test_duplicate_ids_across_retrieved_passages_collapse() -> None:
    fake = FakeRetriever([_chunk(505), _chunk(505), _chunk(606)])
    result = link_evidence(_claim(()), [], retriever=fake)
    assert [c.chunk_id for c in result.candidates] == [505, 606]


def test_deduplication_never_inflates_the_limit() -> None:
    retrieved = [_chunk(101), _chunk(101), _chunk(101)]
    result = link_evidence(_claim(("[1]", "[1]")), retrieved)
    assert len(result.candidates) == 1


# --------------------------------------------------------------------------
# Limit enforcement
# --------------------------------------------------------------------------

def test_limit_is_enforced() -> None:
    retrieved = [_chunk(i) for i in range(1, 11)]
    result = link_evidence(_claim(("[1]", "[2]", "[3]", "[4]")), retrieved, limit=3)
    assert len(result.candidates) == 3


def test_cited_passages_survive_the_limit_over_retrieved_ones() -> None:
    """Slots go to cited passages first; retrieved ones fill the remainder."""
    retrieved = [_chunk(101), _chunk(202)]
    fake = FakeRetriever([_chunk(i) for i in range(500, 510)])
    result = link_evidence(_claim(("[1]", "[2]")), retrieved, retriever=fake, limit=3)
    assert [c.chunk_id for c in result.candidates] == [101, 202, 500]


def test_cited_beyond_limit_are_truncated_not_errors() -> None:
    retrieved = [_chunk(101), _chunk(202), _chunk(303)]
    result = link_evidence(_claim(("[1]", "[2]", "[3]")), retrieved, limit=2)
    assert [c.chunk_id for c in result.candidates] == [101, 202]


def test_default_limit_matches_documented_value() -> None:
    assert DEFAULT_CANDIDATE_LIMIT == 8
    assert CLAIM_RETRIEVAL_TOP_K >= DEFAULT_CANDIDATE_LIMIT


def test_non_positive_limit_raises() -> None:
    with pytest.raises(ValueError, match="limit"):
        link_evidence(_claim(()), [], limit=0)


def test_negative_top_k_raises() -> None:
    with pytest.raises(ValueError, match="top_k"):
        link_evidence(_claim(()), [], retriever=FakeRetriever([]), top_k=-1)


def test_retriever_not_called_once_limit_already_satisfied() -> None:
    retrieved = [_chunk(101), _chunk(202), _chunk(303)]
    fake = FakeRetriever([_chunk(505)])
    link_evidence(
        _claim(("[1]", "[2]", "[3]")), retrieved, retriever=fake, limit=3
    )
    assert fake.calls == [], "no need to re-retrieve when cited already fills the set"


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def test_candidate_preserves_full_provenance() -> None:
    retrieved = [_chunk(101, external_id="CVE-2018-13379")]
    result = link_evidence(_claim(("[1]",)), retrieved)
    c = result.candidates[0]
    assert c.chunk_id == 101
    assert c.document_id == 1010
    assert c.external_id == "CVE-2018-13379"
    assert c.source_url == "https://example.invalid/101"
    assert c.title == "T101"
    assert c.published_at == "2021-12-10"
    assert c.text == "body"


def test_cited_property_separates_the_two_origins() -> None:
    fake = FakeRetriever([_chunk(505)])
    result = link_evidence(_claim(("[1]",)), [_chunk(101)], retriever=fake)
    assert [c.chunk_id for c in result.cited] == [101]
    assert len(result.candidates) == 2


def test_evidence_set_is_immutable() -> None:
    result = link_evidence(_claim(("[1]",)), [_chunk(101)])
    with pytest.raises(Exception):
        result.candidates = ()  # type: ignore[misc]


# --------------------------------------------------------------------------
# Validation of candidate ids against known records
# --------------------------------------------------------------------------

def test_unknown_chunk_ids_are_rejected_and_recorded() -> None:
    """Candidates must be real database records, not just integers."""
    fake = FakeRetriever([_chunk(101), _chunk(999)])
    result = link_evidence(
        _claim(()), [], retriever=fake, chunk_is_known=lambda cid: cid != 999
    )
    assert result.chunk_ids == (101,)
    assert result.rejected_chunk_ids == (999,)


def test_all_candidates_rejected_yields_empty_set() -> None:
    result = link_evidence(
        _claim(("[1]",)), [_chunk(101)], chunk_is_known=lambda _cid: False
    )
    assert result.is_empty
    assert result.rejected_chunk_ids == (101,)


def test_no_validator_skips_the_check() -> None:
    result = link_evidence(_claim(("[1]",)), [_chunk(101)])
    assert result.chunk_ids == (101,)
    assert result.rejected_chunk_ids == ()


def test_validator_applies_to_retrieved_candidates_too() -> None:
    fake = FakeRetriever([_chunk(505), _chunk(606)])
    result = link_evidence(
        _claim(()), [], retriever=fake, chunk_is_known=lambda cid: cid == 505
    )
    assert result.chunk_ids == (505,)
    assert result.rejected_chunk_ids == (606,)


def test_a_rejected_id_appearing_in_both_sources_is_recorded_once() -> None:
    """The anomaly concerns the id, not each occurrence of it."""
    retrieved = [_chunk(101)]
    fake = FakeRetriever([_chunk(101)])
    result = link_evidence(
        _claim(("[1]",)), retrieved, retriever=fake, chunk_is_known=lambda _cid: False
    )
    assert result.rejected_chunk_ids == (101,)


# --------------------------------------------------------------------------
# The no-fabrication invariant, enforced against the candidate set
# --------------------------------------------------------------------------

def test_evidence_verdict_accepts_ids_drawn_from_the_candidate_set() -> None:
    """The judge selects candidates; the wrapper accepts in-set ids."""
    evidence = link_evidence(_claim(("[1]",)), [_chunk(101)])
    verdict = make_evidence_verdict(
        evidence, ClaimVerdict.SUPPORTED, evidence_chunk_ids=[101]
    )
    assert verdict.label is ClaimVerdict.SUPPORTED
    assert verdict.evidence_chunk_ids == (101,)
    assert verdict.anomalies == ()


def test_evidence_verdict_drops_judge_ids_outside_the_candidate_set() -> None:
    """Rule 2, active for the first time: no id the judge was never shown."""
    evidence = link_evidence(_claim(("[1]",)), [_chunk(101)])
    verdict = make_evidence_verdict(
        evidence, ClaimVerdict.SUPPORTED, evidence_chunk_ids=[101, 999]
    )
    assert verdict.evidence_chunk_ids == (101,)
    assert "999" in verdict.anomalies[0]


def test_judge_citing_only_fabricated_ids_forces_a_downgrade() -> None:
    """Strip the bogus ids and the label cannot stand."""
    evidence = link_evidence(_claim(("[1]",)), [_chunk(101)])
    verdict = make_evidence_verdict(
        evidence, ClaimVerdict.SUPPORTED, evidence_chunk_ids=[999]
    )
    assert verdict.label is ClaimVerdict.UNVERIFIABLE
    assert verdict.evidence_chunk_ids == ()


def test_empty_evidence_set_forces_supported_to_downgrade() -> None:
    """No candidates means no evidence, so 'supported' is impossible."""
    evidence = link_evidence(_claim(()), [], retriever=FakeRetriever([]))
    verdict = make_evidence_verdict(evidence, ClaimVerdict.SUPPORTED)
    assert verdict.label is ClaimVerdict.UNVERIFIABLE
    assert verdict.evidence_chunk_ids == ()


def test_verdict_can_only_cite_candidates_not_arbitrary_ids() -> None:
    """The wrapper exposes no way to inject an id from outside the set."""
    evidence = link_evidence(_claim(("[1]",)), [_chunk(101)])
    assert set(evidence.chunk_ids) == {101}


def test_abstention_verdict_over_evidence_set_carries_no_ids() -> None:
    evidence = link_evidence(_claim(("[1]",)), [_chunk(101)])
    verdict = make_evidence_verdict(evidence, ClaimVerdict.INSUFFICIENT_EVIDENCE)
    assert verdict.label is ClaimVerdict.INSUFFICIENT_EVIDENCE
    assert verdict.evidence_chunk_ids == ()


def test_rationale_is_forwarded() -> None:
    evidence = link_evidence(_claim(("[1]",)), [_chunk(101)])
    verdict = make_evidence_verdict(evidence, ClaimVerdict.SUPPORTED, rationale="ok")
    assert verdict.rationale == "ok"


# --------------------------------------------------------------------------
# Integration with real extraction
# --------------------------------------------------------------------------

def test_link_evidence_operates_on_actually_extracted_claims() -> None:
    answer = "Log4j2 allows RCE [1]. FortiOS has path traversal [2]."
    extracted = extract_claims(answer)
    retrieved = [_chunk(101), _chunk(202)]
    fake = FakeRetriever([_chunk(505)])

    second = extracted.claims[1]
    result = link_evidence(second, retrieved, retriever=fake)

    assert second.markers == ("[2]",)
    assert result.chunk_ids == (202, 505)


def test_every_candidate_in_an_evidence_set_is_unique() -> None:
    fake = FakeRetriever([_chunk(i) for i in [1, 2, 3, 3, 4, 5, 6, 7, 8, 9]])
    result = link_evidence(_claim(("[1]",)), [_chunk(1, text="x")], retriever=fake)
    assert len(set(result.chunk_ids)) == len(result.chunk_ids)


def test_package_exports_stage_2_2_symbols() -> None:
    from app import verification

    assert verification.link_evidence is link_evidence
    assert verification.EvidenceSet is EvidenceSet
    assert verification.make_evidence_verdict is make_evidence_verdict
