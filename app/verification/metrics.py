"""Metrics for the A/B evaluation (Phase 2, Stage 2.6).

TWO NUMBERS THAT MUST NEVER BE CONFUSED
---------------------------------------
1. **Mechanism metrics** (unsupported rate, abstention rate, contradiction
   rate) describe what the verifier *said*. They are computable offline from
   stored verdicts and say nothing about whether the verifier was right.
2. **Agreement** (judge label vs a human gold label) describes whether the
   verifier was right *on this sample*. It requires hand labels, and on a
   24-question pilot over a 6-record corpus it is a smoke signal, not a
   generalizable accuracy figure.

A passing unit test establishes neither. These functions only compute; they
do not judge the quality of what they measure.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from app.verification.verdicts import ClaimVerdict, Verdict

# Normalisation used for claim-to-gold matching. Deliberately conservative:
# it folds case and whitespace only, so a match means the claim really does
# say what the gold label was written about. Fuzzy matching would silently
# inflate agreement, which is exactly the failure mode to avoid here.
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")

VALID_LABELS = frozenset(member.value for member in ClaimVerdict)


def normalize_claim(text: str) -> str:
    """Fold a claim to a canonical form for exact-match comparison."""
    return _WS.sub(" ", _PUNCT.sub(" ", text.lower())).strip()


@dataclass(frozen=True)
class MechanismMetrics:
    """What the verifier said, not whether it was right."""

    total_claims: int = 0
    supported: int = 0
    contradicted: int = 0
    insufficient_evidence: int = 0
    unverifiable: int = 0
    with_anomalies: int = 0
    claims_with_evidence: int = 0

    @property
    def abstentions(self) -> int:
        return self.insufficient_evidence + self.unverifiable

    @property
    def unsupported_rate(self) -> float:
        """Fraction of claims the corpus did NOT support."""
        if self.total_claims == 0:
            return 0.0
        return (self.total_claims - self.supported) / self.total_claims

    @property
    def abstention_rate(self) -> float:
        if self.total_claims == 0:
            return 0.0
        return self.abstentions / self.total_claims

    @property
    def contradiction_rate(self) -> float:
        if self.total_claims == 0:
            return 0.0
        return self.contradicted / self.total_claims


def mechanism_metrics(verdicts: Iterable[Verdict]) -> MechanismMetrics:
    counts: Counter[str] = Counter()
    total = anomalies = with_evidence = 0
    for verdict in verdicts:
        total += 1
        counts[verdict.label.value] += 1
        if verdict.anomalies:
            anomalies += 1
        if verdict.evidence_chunk_ids:
            with_evidence += 1
    return MechanismMetrics(
        total_claims=total,
        supported=counts["supported"],
        contradicted=counts["contradicted"],
        insufficient_evidence=counts["insufficient_evidence"],
        unverifiable=counts["unverifiable"],
        with_anomalies=anomalies,
        claims_with_evidence=with_evidence,
    )


@dataclass(frozen=True)
class CitationQuality:
    """Format-validity vs actual support, which are different things."""

    citations: int = 0
    invalid_markers: int = 0
    # Citations whose marker points at a chunk the verifier judged supporting
    # or contradicting the claim it sits on. None when the system performed
    # no verification, so "unknown" never reads as "zero problems".
    verified_citations: int | None = None

    @property
    def invalid_marker_rate(self) -> float:
        total = self.citations + self.invalid_markers
        if total == 0:
            return 0.0
        return self.invalid_markers / total


def citation_quality(
    citations: int,
    invalid_markers: int,
    verified_citations: int | None = None,
) -> CitationQuality:
    return CitationQuality(
        citations=citations,
        invalid_markers=invalid_markers,
        verified_citations=verified_citations,
    )


@dataclass(frozen=True)
class Agreement:
    """Judge label vs human gold label, over the claims that could be matched.

    `matched` is deliberately reported alongside `total`: a low match rate
    means most claims were never compared to a human label, and an accuracy
    figure computed over a handful of claims must not be read as if it were
    computed over all of them.
    """

    total: int = 0
    matched: int = 0
    correct: int = 0
    unlabeled: int = 0
    # Per gold label, the tuple is (gold occurrences, correct, incorrect):
    # the count of claims a human labelled with that value, how many the
    # judge agreed with, and how many it did not. correct + incorrect ==
    # gold occurrences for every label.
    per_label: Mapping[str, tuple[int, int, int]] = field(default_factory=dict)
    confusion: Mapping[tuple[str, str], int] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.correct / self.matched if self.matched else 0.0

    @property
    def coverage(self) -> float:
        """Fraction of claims that had a gold label to compare against."""
        return self.matched / self.total if self.total else 0.0


def judge_agreement(
    predicted: Sequence[str],
    gold: Sequence[str],
) -> Agreement:
    """Compute judge-vs-human agreement for two aligned label sequences.

    Only aligned, comparable entries count. Entries where either side is
    missing or unlabelled are recorded in `unlabeled` and excluded from
    `accuracy`, so abstaining on an unlabelled claim cannot inflate the
    score.
    """
    if len(predicted) != len(gold):
        raise ValueError(
            f"predicted ({len(predicted)}) and gold ({len(gold)}) must align "
            "claim-by-claim; silently truncating would corrupt the metric"
        )

    total = len(predicted)
    matched = correct = unlabeled = 0
    per_label: dict[str, list[int]] = {}
    confusion: Counter[tuple[str, str]] = Counter()

    for pred_raw, gold_raw in zip(predicted, gold):
        pred = (pred_raw or "").strip().lower()
        truth = (gold_raw or "").strip().lower()
        comparable = pred in VALID_LABELS and truth in VALID_LABELS
        if not comparable:
            unlabeled += 1
            continue

        matched += 1
        confusion[(truth, pred)] += 1
        entry = per_label.setdefault(truth, [0, 0, 0])
        entry[0] += 1  # gold occurrences
        entry[1] += 1 if pred == truth else 0  # correct
        if pred == truth:
            correct += 1

    return Agreement(
        total=total,
        matched=matched,
        correct=correct,
        unlabeled=unlabeled,
        per_label={
            label: (value[0], value[1], value[0] - value[1])
            for label, value in per_label.items()
        },
        confusion=dict(confusion),
    )


def match_claims_to_gold(
    extracted: Sequence[str],
    gold_claims: Sequence[Mapping[str, str]],
) -> list[str | None]:
    """Align extracted claims to gold claims by normalised text.

    A claim with no gold counterpart maps to None and is excluded from
    agreement -- it is unlabelled, not wrong.

    Exact normalised match only. Fuzzy matching would pair a claim with a
    gold label it merely resembles, which inflates agreement -- the single
    most misleading outcome this module could produce.
    """
    lookup = {
        normalize_claim(str(entry.get("text", ""))): str(entry.get("gold_label", ""))
        for entry in gold_claims
    }
    return [lookup.get(normalize_claim(claim)) for claim in extracted]
