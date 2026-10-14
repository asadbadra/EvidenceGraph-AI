"""Claim verdicts and the no-fabrication invariant.

A verdict answers one question: *does the retrieved evidence support this
single claim?* Four labels, chosen so the boundaries survive questioning:

    supported              An evidence passage entails the claim.
    contradicted           An evidence passage conflicts with the claim.
    insufficient_evidence  The claim IS a checkable factual assertion and
                           candidates were inspected, but none entail or
                           contradict it. This is the honest abstention
                           signal -- "we looked and the corpus is silent".
    unverifiable           Verification could not be performed at all: no
                           candidates, or the claim is not a factual
                           proposition (opinion, recommendation, hedge,
                           methodology). "This was never answerable."

The `insufficient_evidence` / `unverifiable` split is the load-bearing
distinction. Collapsing them would hide whether an abstention is a retrieval
failure (fixable) or a scope limit (not).

THE NO-FABRICATION INVARIANT
----------------------------
`make_verdict` is the only way to construct a `Verdict`, and it enforces two
rules by construction rather than by convention:

1. A verdict asserting support or contradiction MUST name at least one piece
   of evidence. One that does not is downgraded to `unverifiable` with the
   anomaly recorded -- never silently passed through.

2. Every evidence chunk id MUST appear in the candidate set the verifier was
   handed, when that set is supplied. An id outside the candidates was never
   available to the verifier, so accepting it would let evidence be
   invented. Stray ids are dropped and recorded.

`unverifiable` and `insufficient_evidence` must name NO evidence: claiming
"the corpus is silent" while pointing at a passage is self-contradictory.

SCOPE NOTE: these are *invariant* tests, not accuracy claims. They prove the
mechanism cannot fabricate evidence; they say nothing about whether a real
judge labels correctly. Judge accuracy is measured against manually labelled
data in Stage 2.6 and reported separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from app.verification.claims import Claim


class ClaimVerdict(str, Enum):
    """The four labels a claim can receive.

    Subclasses `str` so values serialize cleanly to JSON and to the
    `verif_claims` table in Stage 2.5 without a custom encoder.
    """

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNVERIFIABLE = "unverifiable"

    @property
    def requires_evidence(self) -> bool:
        """True when the label makes a factual assertion about the evidence."""
        return self in (ClaimVerdict.SUPPORTED, ClaimVerdict.CONTRADICTED)

    @property
    def forbids_evidence(self) -> bool:
        """True when the label asserts the evidence does NOT settle the claim.

        Opposite of `requires_evidence`; the two are disjoint by construction.
        """
        return self in (ClaimVerdict.INSUFFICIENT_EVIDENCE, ClaimVerdict.UNVERIFIABLE)

    @property
    def is_abstention(self) -> bool:
        """True for both abstention labels (used heavily by the metrics)."""
        return self in (ClaimVerdict.INSUFFICIENT_EVIDENCE, ClaimVerdict.UNVERIFIABLE)


@dataclass(frozen=True)
class Verdict:
    """One claim's verification outcome.

    Construct via `make_verdict`, which enforces the invariant by *correcting*
    impossible input. Direct construction is guarded too, but by *raising*,
    because at that point there is no judge output to attribute the problem to.

    WHICH LAYER ENFORCES WHICH RULE
    --------------------------------
    - Rules 1 (support/contradiction need evidence) and 3 (abstention labels
      carry none) are enforced here in `__post_init__`, so they hold on BOTH
      the `make_verdict` path and the direct path.
    - Rule 2 (evidence ids must come from the candidate set) can only be
      checked when a candidate set is available, so it is enforced here
      whenever `candidate_chunk_ids` is supplied. `make_verdict` and
      `make_evidence_verdict` always supply it; a direct constructor that
      omits it (the default `None`) skips the check, which is the honest
      behaviour -- there is nothing to check membership against. Direct
      construction with an out-of-set id AND an explicit candidate set now
      raises rather than silently producing a verdict that cites evidence the
      verifier was never shown.

    `anomalies` records every rule that had to fire to make this verdict
    legal. An empty tuple means the judge's raw output was already
    consistent; a non-empty one means the judge said something impossible
    and the invariant corrected it. Either way the correction is visible
    rather than silent.
    """

    claim: Claim
    label: ClaimVerdict
    evidence_chunk_ids: tuple[int, ...] = ()
    rationale: str = ""
    anomalies: tuple[str, ...] = ()
    candidate_chunk_ids: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        """Enforce the invariant on direct construction too.

        `make_verdict` is the supported path and corrects impossible input.
        But a frozen dataclass can still be built directly, and an invariant
        that holds only on one code path is a convention, not an invariant.
        These checks make an impossible verdict unrepresentable either way;
        they raise rather than correct, because at this point there is no
        judge output to attribute the problem to.
        """
        if self.label.requires_evidence and not self.evidence_chunk_ids:
            raise ValueError(
                f"label {self.label.value!r} requires evidence, but none was "
                "given. Build verdicts with make_verdict(), which downgrades "
                "instead of raising."
            )
        if self.label.forbids_evidence and self.evidence_chunk_ids:
            raise ValueError(
                f"label {self.label.value!r} cannot carry evidence, got "
                f"{list(self.evidence_chunk_ids)}. Build verdicts with "
                "make_verdict(), which drops them instead of raising."
            )
        # Rule 2, when a candidate set is available to check against.
        if self.candidate_chunk_ids is not None:
            allowed = {int(c) for c in self.candidate_chunk_ids}
            stray = [i for i in self.evidence_chunk_ids if int(i) not in allowed]
            if stray:
                raise ValueError(
                    f"evidence id(s) {stray} are outside the candidate set "
                    f"{sorted(allowed)}. Build verdicts with make_verdict(), "
                    "which drops them instead of raising."
                )

    @property
    def has_anomalies(self) -> bool:
        return bool(self.anomalies)

    @property
    def is_abstention(self) -> bool:
        return self.label.is_abstention

    @property
    def carries_evidence(self) -> bool:
        return bool(self.evidence_chunk_ids)


def make_verdict(
    claim: Claim,
    label: ClaimVerdict,
    *,
    evidence_chunk_ids: Sequence[int] = (),
    rationale: str = "",
    candidate_chunk_ids: Sequence[int] | None = None,
) -> Verdict:
    """Build a `Verdict`, downgrading rather than ever fabricating evidence.

    `candidate_chunk_ids` is the set the verifier was actually given (Stage
    2.2 fills it). Passing `None` skips membership checking, which is only
    correct before evidence linking exists; Stage 2.2 always supplies it, so
    the "no id outside the candidates" rule is active from that stage on.

    Downgrade order matters and is deliberate:

    - Stray ids are dropped FIRST, so a `supported` verdict whose entire
      basis was fabricated becomes empty and is then caught by rule 1.
      Handling them in the other order would let a bogus id satisfy the
      evidence requirement before being removed.
    - The `requires_evidence` downgrade happens BEFORE the `forbids_evidence`
      check. Since the downgrade only fires when the id list is already
      empty, the subsequent check is a no-op and cannot re-mangle the label.
    """
    # Dedupe while preserving order: the same chunk cited twice is still one
    # piece of evidence, and metrics must not double-count it.
    ids = tuple(dict.fromkeys(int(i) for i in evidence_chunk_ids))
    anomalies: list[str] = []

    # Materialize the candidate set ONCE. It may be a single-use iterator
    # (e.g. `iter([...])`), and it is read twice below: for the stray-id check
    # and again when the built Verdict re-checks membership. Consuming it once
    # up front keeps both readers consistent.
    allowed: set[int] | None = None
    if candidate_chunk_ids is not None:
        allowed = {int(c) for c in candidate_chunk_ids}

    # Rule 2: no evidence id may come from outside the candidate set.
    if allowed is not None:
        stray = [i for i in ids if i not in allowed]
        if stray:
            anomalies.append(
                "dropped evidence id(s) outside the candidate set: "
                + ", ".join(str(i) for i in stray)
            )
            ids = tuple(i for i in ids if i in allowed)

    # Rule 1: support/contradiction require named evidence.
    if label.requires_evidence and not ids:
        anomalies.append(
            f"label {label.value!r} requires evidence, none remained; "
            "downgraded to 'unverifiable'"
        )
        label = ClaimVerdict.UNVERIFIABLE

    # Rule 3: abstention labels must not carry evidence.
    if label.forbids_evidence and ids:
        anomalies.append(
            f"label {label.value!r} cannot carry evidence, dropped {list(ids)}"
        )
        ids = ()

    return Verdict(
        claim=claim,
        label=label,
        evidence_chunk_ids=ids,
        rationale=rationale,
        anomalies=tuple(anomalies),
        # Carry the candidate set so rule 2 is re-checked on the built object,
        # not only during construction. Stray ids were already dropped above,
        # so this never raises for a `make_verdict`-built verdict. `allowed`
        # was materialized once at the top, so this does not re-consume a
        # single-use iterator; it is sorted for a deterministic repr.
        candidate_chunk_ids=(
            None if allowed is None else tuple(sorted(allowed))
        ),
    )


@dataclass(frozen=True)
class VerdictSummary:
    """Tallies over a list of verdicts.

    Kept as explicit fields rather than a dict so the metrics stage cannot
    silently mis-key a count, and so a missing category is a visible 0
    rather than a missing key.
    """

    total: int = 0
    supported: int = 0
    contradicted: int = 0
    insufficient_evidence: int = 0
    unverifiable: int = 0
    with_anomalies: int = 0

    @property
    def abstentions(self) -> int:
        """Both abstention labels combined."""
        return self.insufficient_evidence + self.unverifiable

    @property
    def with_evidence(self) -> int:
        """Verdicts that made a positive claim about the evidence."""
        return self.supported + self.contradicted


def summarize(verdicts: Iterable[Verdict]) -> VerdictSummary:
    """Tally verdicts by label, plus how many needed invariant correction."""
    counts = {label: 0 for label in ClaimVerdict}
    anomalies = 0
    total = 0
    for verdict in verdicts:
        total += 1
        counts[verdict.label] += 1
        if verdict.has_anomalies:
            anomalies += 1
    return VerdictSummary(
        total=total,
        supported=counts[ClaimVerdict.SUPPORTED],
        contradicted=counts[ClaimVerdict.CONTRADICTED],
        insufficient_evidence=counts[ClaimVerdict.INSUFFICIENT_EVIDENCE],
        unverifiable=counts[ClaimVerdict.UNVERIFIABLE],
        with_anomalies=anomalies,
    )
