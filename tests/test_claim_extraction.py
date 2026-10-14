"""Tests for claim extraction (Phase 2, Stage 2.1).

Deterministic and offline: no LLM, no network, no clock.

SCOPE NOTE: these tests prove the *mechanics* of segmentation -- spans,
marker handling, skip rules. They do NOT show that any verifier labels
claims correctly; that is measured against manually labelled data in Stage
2.6 and must be reported separately from unit-test results.
"""

from __future__ import annotations

import pytest

from app.verification.claims import (
    ABSTENTION_SENTENCES,
    Claim,
    ClaimExtraction,
    extract_claims,
)

ANSWER = (
    "Apache Log4j2 contains a JNDI vulnerability that allows remote code "
    "execution [1]. FortiOS SSL VPN has a path traversal flaw [2]. "
    "Progress MOVEit Transfer has a SQL injection issue [3]."
)


# --------------------------------------------------------------------------
# Basic segmentation
# --------------------------------------------------------------------------

def test_single_sentence_becomes_one_claim() -> None:
    result = extract_claims("Log4j2 allows remote code execution [1].")
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.text == "Log4j2 allows remote code execution."
    assert claim.markers == ("[1]",)


def test_multiple_sentences_become_multiple_claims() -> None:
    result = extract_claims(ANSWER)
    assert len(result.claims) == 3
    assert [c.text for c in result.claims] == [
        "Apache Log4j2 contains a JNDI vulnerability that allows remote code execution.",
        "FortiOS SSL VPN has a path traversal flaw.",
        "Progress MOVEit Transfer has a SQL injection issue.",
    ]
    assert [c.markers for c in result.claims] == [("[1]",), ("[2]",), ("[3]",)]


def test_empty_and_whitespace_inputs_yield_no_claims() -> None:
    assert extract_claims("").claims == ()
    assert extract_claims("   \n\t  ").claims == ()


def test_determinism_same_input_same_output() -> None:
    assert extract_claims(ANSWER) == extract_claims(ANSWER)


# --------------------------------------------------------------------------
# Character spans: the traceability property
# --------------------------------------------------------------------------

def test_span_recovers_the_exact_original_sentence() -> None:
    """`answer_text[start:end]` must return the raw sentence, markers intact.

    This is the property that makes a verdict traceable to the exact source
    wording rather than only to a normalised paraphrase.
    """
    result = extract_claims(ANSWER)
    for claim in result.claims:
        assert claim.raw(ANSWER) in ANSWER
        assert "[" in claim.raw(ANSWER), "raw() must keep the original marker"
    assert result.claims[0].raw(ANSWER).endswith("[1].")


def test_span_excludes_leading_whitespace() -> None:
    text = "First sentence.\n\n   Second sentence."
    result = extract_claims(text)
    assert len(result.claims) == 2
    for claim in result.claims:
        raw = text[claim.start : claim.end]
        assert raw == raw.strip(), "span must not include surrounding whitespace"
        assert raw[0].isupper() or raw[0].isdigit()


def test_span_is_exact_offset_not_just_membership() -> None:
    text = "Alpha one. Beta two."
    result = extract_claims(text)
    assert (result.claims[0].start, result.claims[0].end) == (0, 10)
    assert (result.claims[1].start, result.claims[1].end) == (11, 20)


def test_span_property_matches_fields() -> None:
    claim = extract_claims("Only one here.").claims[0]
    assert claim.span == (claim.start, claim.end)


# --------------------------------------------------------------------------
# Citation marker handling
# --------------------------------------------------------------------------

def test_markers_are_stripped_from_text_but_recorded() -> None:
    claim = extract_claims("MOVEit has SQL injection [2].").claims[0]
    assert "[2]" not in claim.text
    assert claim.text == "MOVEit has SQL injection."
    assert claim.markers == ("[2]",)


def test_multiple_markers_on_one_claim_all_recorded() -> None:
    claim = extract_claims("Cross-referenced finding [2][3].").claims[0]
    assert claim.markers == ("[2]", "[3]")
    assert claim.text == "Cross-referenced finding."


def test_no_markers_yields_empty_marker_tuple() -> None:
    claim = extract_claims("A plain uncorroborated statement.").claims[0]
    assert claim.markers == ()


def test_marker_only_fragment_is_skipped_not_kept() -> None:
    """A bare `[1]` asserts nothing, so it must not become a claim."""
    result = extract_claims("Some text [1]. [2]")
    assert len(result.claims) == 1
    assert any("no text after removing citation markers" in s.reason for s in result.skipped)


# --------------------------------------------------------------------------
# Skip rules: only justified removals
# --------------------------------------------------------------------------

def test_question_fragments_are_skipped() -> None:
    result = extract_claims("What is the CVE identifier? A real statement.")
    assert [c.text for c in result.claims] == ["A real statement."]
    assert any(s.reason == "question, not an assertion" for s in result.skipped)


def test_question_with_trailing_marker_is_skipped() -> None:
    result = extract_claims("Is this exploitable [1]?")
    assert result.claims == ()
    assert len(result.skipped) == 1


def test_canned_abstention_is_skipped() -> None:
    result = extract_claims("Insufficient evidence in the retrieved passages.")
    assert result.claims == ()
    assert any(s.reason == "abstention statement" for s in result.skipped)


@pytest.mark.parametrize(
    "variant",
    [
        "insufficient evidence in the retrieved passages.",
        "Insufficient evidence in the retrieved passages",
        "INSUFFICIENT EVIDENCE IN THE RETRIEVED PASSAGES.",
        "  Insufficient evidence in the retrieved passages!  ",
    ],
)
def test_abstention_is_recognised_despite_case_and_punctuation(variant: str) -> None:
    result = extract_claims(variant)
    assert result.claims == (), f"expected abstention recognition for {variant!r}"


def test_abstention_constant_is_lower_case_with_full_stop() -> None:
    """Guards the contract `_is_abstention` relies on."""
    for phrase in ABSTENTION_SENTENCES:
        assert phrase == phrase.lower().strip()
        assert phrase.endswith(".")


def test_a_statement_that_merely_mentions_insufficient_evidence_is_kept() -> None:
    """The skip must match the canned sentence, not the concept."""
    result = extract_claims("Insufficient evidence exists for several CVEs in scope.")
    assert len(result.claims) == 1
    assert result.claims[0].text.startswith("Insufficient evidence exists")


# --------------------------------------------------------------------------
# Permissiveness: extraction must not pre-judge
# --------------------------------------------------------------------------

def test_hedges_and_recommendations_are_kept_as_claims() -> None:
    """Judging opinion vs fact is the classifier's job, not the segmenter's."""
    text = "You should probably upgrade soon. This is likely nation-state activity."
    result = extract_claims(text)
    assert len(result.claims) == 2


def test_fragment_without_terminal_punctuation_is_kept() -> None:
    """Dropping it would silently lose content the model actually said."""
    result = extract_claims("A trailing fragment with no full stop [1]")
    assert len(result.claims) == 1
    assert result.claims[0].text == "A trailing fragment with no full stop"


def test_no_fragment_is_dropped_silently() -> None:
    """Every non-whitespace fragment is either a claim or a recorded skip."""
    text = "Real claim here [1]. What about this? [3]"
    result = extract_claims(text)
    covered = len(result.claims) + len(result.skipped)
    assert covered == 3


def test_skipped_fragments_carry_span_and_reason() -> None:
    result = extract_claims("What is it? It is a flaw.")
    skipped = result.skipped[0]
    assert skipped.reason == "question, not an assertion"
    assert (skipped.start, skipped.end) == (0, 11)
    assert "What is it?" == skipped.text


# --------------------------------------------------------------------------
# Multi-line answers and structures
# --------------------------------------------------------------------------

def test_multiline_answer_is_segmented_by_sentence_not_by_line() -> None:
    text = "Line one sentence. Line two\nsentence continues here."
    result = extract_claims(text)
    assert len(result.claims) == 2
    assert result.claims[1].text == "Line two sentence continues here."


def test_bullet_style_answer_keeps_each_assertion() -> None:
    text = "- CVE-2021-44228 allows RCE [1].\n- CVE-2014-0160 is info disclosure [2]."
    result = extract_claims(text)
    assert len(result.claims) == 2
    assert result.claims[0].text.startswith("- CVE-2021-44228 allows RCE")
    assert result.claims[1].markers == ("[2]",)


def test_claim_text_is_normalised_to_a_single_line() -> None:
    text = "A claim that\nwraps across   lines [1]."
    claim = extract_claims(text).claims[0]
    assert "\n" not in claim.text
    assert "  " not in claim.text
    assert claim.text == "A claim that wraps across lines."


# --------------------------------------------------------------------------
# Return type contract
# --------------------------------------------------------------------------

def test_return_type_is_claim_extraction_with_both_lists() -> None:
    result = extract_claims("A claim [1]. What?")
    assert isinstance(result, ClaimExtraction)
    assert isinstance(result.claims[0], Claim)
    assert isinstance(result.skipped[0].reason, str)


def test_skipped_defaults_to_empty_tuple() -> None:
    result = extract_claims("Only a claim [1].")
    assert result.skipped == ()


# --------------------------------------------------------------------------
# Smoke-test regressions (Stage 2.9): failures observed in the live local
# run recorded at runs/smoke-20261014-143159/. `SMOKE_ANSWER` is the
# verbatim answer llama3.2:latest produced for pilot question direct-02;
# the expectations below are what extraction should have produced from it.
# --------------------------------------------------------------------------

SMOKE_ANSWER = (
    "Based on the provided passages, CVE-2023-34362 is related to a SQL "
    "injection vulnerability in Progress MOVEit Transfer.\n\n"
    "According to [1] and [2], Progress MOVEit Transfer contains a SQL "
    "injection vulnerability that could allow an unauthenticated attacker "
    "to gain unauthorized access to MOVEit Transfer's database. This "
    "vulnerability is also mentioned in the CISA advisory [1] and [2], "
    "which provides additional information on the vulnerability and its "
    "associated IOCs.\n\n"
    "Therefore, the type of vulnerability CVE-2023-34362 is a SQL "
    "injection vulnerability.\n\n"
    "References:\n"
    "[1] Progress MOVEit Transfer SQL Injection Vulnerability | "
    "CVE-2023-34362 | published 2023-06-02 | "
    "https://nvd.nist.gov/vuln/detail/CVE-2023-34362\n"
    "[2] Progress MOVEit Transfer SQL Injection Vulnerability | "
    "CVE-2023-34362 | published 2023-06-02 | "
    "https://nvd.nist.gov/vuln/detail/CVE-2023-34362"
)


def test_smoke_answer_yields_four_claims_and_one_recorded_skip() -> None:
    result = extract_claims(SMOKE_ANSWER)
    assert len(result.claims) == 4
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == "bibliography reference list"


def test_smoke_answer_every_fragment_is_claim_or_recorded_skip() -> None:
    """The no-silent-drop invariant holds on the smoke answer too."""
    result = extract_claims(SMOKE_ANSWER)
    assert len(result.claims) + len(result.skipped) == 5


def test_smoke_answer_bibliography_is_never_a_claim() -> None:
    result = extract_claims(SMOKE_ANSWER)
    for claim in result.claims:
        assert "References:" not in claim.text
        assert "https://" not in claim.text


def test_smoke_answer_attribution_scaffold_is_removed() -> None:
    result = extract_claims(SMOKE_ANSWER)
    claim = next(c for c in result.claims if c.text.startswith("Progress MOVEit"))
    assert claim.text == (
        "Progress MOVEit Transfer contains a SQL injection vulnerability "
        "that could allow an unauthenticated attacker to gain unauthorized "
        "access to MOVEit Transfer's database."
    )
    assert "According to" not in claim.text
    assert claim.markers == ("[1]", "[2]")
    # Traceability: the span still recovers the sentence as written.
    assert claim.raw(SMOKE_ANSWER).startswith("According to [1] and [2],")


def test_smoke_answer_marker_joiner_is_not_stranded() -> None:
    result = extract_claims(SMOKE_ANSWER)
    claim = next(c for c in result.claims if c.text.startswith("This vulnerability"))
    assert claim.text == (
        "This vulnerability is also mentioned in the CISA advisory, which "
        "provides additional information on the vulnerability and its "
        "associated IOCs."
    )
    assert "advisory and," not in claim.text
    assert claim.markers == ("[1]", "[2]")


def test_smoke_answer_legitimate_claims_survive_verbatim() -> None:
    result = extract_claims(SMOKE_ANSWER)
    texts = [c.text for c in result.claims]
    assert (
        "Based on the provided passages, CVE-2023-34362 is related to a SQL "
        "injection vulnerability in Progress MOVEit Transfer."
    ) in texts
    assert (
        "Therefore, the type of vulnerability CVE-2023-34362 is a SQL "
        "injection vulnerability."
    ) in texts


# --- Over-filtering guards: the repairs must stay marker-keyed -------------


def test_named_attribution_is_not_treated_as_scaffold() -> None:
    text = "According to the CISA advisory, CVE-2021-44228 was added on 2021-12-10."
    result = extract_claims(text)
    assert [c.text for c in result.claims] == [text]


def test_prose_and_comma_clause_is_not_rewritten() -> None:
    """The joiner repair fires on markers, never on bare prose."""
    text = "The exploit is weaponized and, according to CISA, actively used."
    result = extract_claims(text)
    assert [c.text for c in result.claims] == [text]


def test_short_legitimate_claim_is_still_kept() -> None:
    """Guards against solving extraction quality by dropping short claims."""
    result = extract_claims("CVE-2021-44228 was added on 2021-12-10 [1].")
    assert [c.text for c in result.claims] == [
        "CVE-2021-44228 was added on 2021-12-10."
    ]
    assert result.skipped == ()


def test_marker_led_assertion_without_url_is_not_dropped() -> None:
    """A claim opening with [n] is only a reference entry when it carries a URL."""
    result = extract_claims("[1] confirms the date was 2021-12-10.")
    assert [c.text for c in result.claims] == ["confirms the date was 2021-12-10."]
    assert result.skipped == ()


def test_heading_followed_by_prose_is_not_dropped() -> None:
    text = "Sources: CISA added the CVE on 2021-12-10."
    result = extract_claims(text)
    assert [c.text for c in result.claims] == [text]


def test_bibliography_heading_alone_is_recorded_skip() -> None:
    result = extract_claims("Some claim. References:")
    assert [c.text for c in result.claims] == ["Some claim."]
    assert any(s.reason == "bibliography heading" for s in result.skipped)


def test_conjunct_joining_real_words_keeps_and() -> None:
    """An 'and' between real words is prose, not scaffold: it must survive."""
    result = extract_claims("The advisory [1] and the notes [2] confirm the finding.")
    assert [c.text for c in result.claims] == [
        "The advisory and the notes confirm the finding."
    ]
    assert result.claims[0].markers == ("[1]", "[2]")


def test_single_marker_before_comma_is_untouched() -> None:
    """Only multi-marker runs are repaired; a lone '[1],' is already clean."""
    result = extract_claims("Listed in the CISA advisory [1], which documents it.")
    assert [c.text for c in result.claims] == [
        "Listed in the CISA advisory, which documents it."
    ]
