# Stage E1 — Annotation Quality Report (derived, read-only inputs)

- Built by `build_stage_e1_analysis.py` · 2026-10-17T15:57:34+00:00
- Source of truth: `d3_review_decisions.csv` sha256 `488ecb1497e7bbfae98f11a840495208e6e7e56b42aa6b987f78490049520b8e` (asserted, never written)
- Queue `cce025cc…`, Stage C inputs `51a9e667…` / `c5c2c426…` / `2f4ccc5f…`, questions `500ed32d…` (all asserted)
- Label authority: **single-reviewer human labels (n=46, coverage=1.0)** — one reviewer, no second pass, **not independently validated**.
- No `gold_label` was written anywhere; this report derives every number from the reviewed CSV.

## 1. Parsing ledger (fail-closed rules R1-R5)

- Rule R3 accepts: 40 (label = machine `proposed_label` endorsed by the reviewer; 26 notes
  name the label in parentheses — all 26 equal the proposed label, verified)
- Rule R1 revise prefixes: 5 (0015 `supported`, 0017 `contradicted`, 0020 `contradicted`,
  0014 `insufficient_evidence`, 0033 `supported` — the last excluded, see §3)
- Rule R2 scope mapping: 1 (`ann-d1-0030`, flag `derived_scope_mapping`, see §4)
- Rule R5 failures: **0** (the build aborts before writing if any rule fails)
- Exclusion ledger: `excluded=1` (`ann-d1-0033`, reason: unresolved label/rationale inconsistency (D3 decision note section 8); excluded from label-based metrics until the reviewer resolves it)
- Missing values: 0 (every row parsed; every reviewer field non-empty in the source)

## 2. Decision and label distributions

- Reviewer decisions: accept=40, revise=6, pending=0
- Claim labels (n=39, `ann-d1-0033` excluded): contradicted=2, insufficient_evidence=10, supported=20, unverifiable=7
- Abstention assessments, **primary** (n=6, includes scope-qualified `ann-d1-0030`): appropriate_abstention=6
- Abstention assessments, **sensitivity** (n=5, excludes `ann-d1-0030`): appropriate_abstention=5

## 3. ann-d1-0033 — excluded from label-based metrics

The recorded reviewer label `supported` conflicts with the reasoning stated in its own
reviewer note (which describes the claim as conflicting with the passages' explicit
"not independently verified" disclaimers — the basis of the machine `contradicted`
proposal). The inconsistency is unresolved and reserved to the reviewer (D3 note §8);
this analysis excludes the item from every label-based denominator (**excluded=1**) and
changes no byte of its record. Claim-label denominator: 40 -> 39.
The gate headline metrics are unaffected because `ann-d1-0033` (tier 4) is text-verified
absent from `retracted_claims_13.csv` (13) and `supported_claims_11.csv` (11), and is not
an abstention item (6).

## 4. ann-d1-0030 — scope-qualified derived abstention label

Primary analysis **includes** it with flag `derived_scope_mapping`: the reviewer's scope
ruling (retrieved passages, R1-consistent) via the mapping documented in Stage D2's
`review_summary.md` (lines 286/427) before the choice was made (passages =>
`appropriate_abstention`; catalog => `inappropriate_abstention`). The ruling is an
evaluation-scope decision only — **not** proof that CVE-2021-45046 is absent from the
complete catalog. The fixture's catalog-presence gold answer (plausible-04 gold claim
"…is present in the catalog." -> `contradicted`) diverges from this passages-scope
ruling; both are reported, neither is reconciled here. The sensitivity line in §2
repeats the abstention distribution without this item.

## 5. Gate analyses (tier files text-matched, question-constrained, exact)

- **Retraction correctness (tier 1, n=13):** correct refusals = 10/13
  (human label != `supported`); false refusals = 3/13 (ann-d1-0002, ann-d1-0003, ann-d1-0013
  — reviewer label `supported`); exact match to the retraction's stored
  `new_label` (`insufficient_evidence`) = 7/13 (the remainder are
  reviewer `unverifiable`, still non-supported).
- **Surviving-supported endorsement (tier 2, n=11):** true endorsements = 8/11;
  false endorsements = 3/11 (ann-d1-0014, ann-d1-0017, ann-d1-0020).
- **Abstention quality (tier 3):** system abstained on 6/6;
  reviewer assesses 6/6 appropriate (primary),
  5/5 (sensitivity).

## 6. System-vs-single-reviewer claim agreement (descriptive only)

Scope: 39 claim items with both a system verdict and a derived reviewer label
(`ann-d1-0033` excluded). matched=39 / total=40 /
coverage=39/40; exact agreement = 16/39.

| human \ system | contradicted | insufficient_evidence | supported | unverifiable |
|---|---|---|---|---|
| **contradicted** | 0 | 0 | 2 | 0 |
| **insufficient_evidence** | 0 | 8 | 1 | 1 |
| **supported** | 0 | 5 | 8 | 7 |
| **unverifiable** | 0 | 7 | 0 | 0 |

**Interpretation limits:** the "system" side is a machine judge from the same model
family as the generator; the "reviewer" side is one human. This is a descriptive
system-vs-single-reviewer comparison, **not** a human-human agreement statistic and not
an accuracy measurement against independent ground truth. **Human-vs-human agreement is
not computable: no second-reviewer labels exist.** No significance test is performed
(single run, clustered small-n claims — Stage C statistical restraint stands).

## 7. Metrics ledger (machine-readable; re-verified by validate_stage_e1.py)

- decision_counts=accept:40,revise:6,pending:0
- parsing=accepted_proposal:40,parsed_prefix:5,derived_scope_mapping:1,failed:0
- claim_label_total=40;claim_label_included=39;excluded=1
- abstention_primary_total=6;abstention_sensitivity_total=5
- retraction_correct_refusal=10/13;retraction_false_refusal=3/13;retraction_exact_label_match=7/13
- survivor_true_endorsement=8/11;survivor_false_endorsement=3/11
- abstention_system_abstained=6/6
- system_vs_single_reviewer_agreement=16/39;coverage=39/40
- human_vs_human_agreement=not_computable(no_second_reviewer_labels_exist)

## 8. Limitations

- Single-reviewer decisions; adjudication fields empty; no inter-rater statistics.
- AI-proposed labels remain quarantined machine values; accepting a proposal makes it a
  reviewer decision but does not convert the proposal into independent ground truth.
- `ann-d1-0030` is a pre-documented derivation, not an independently adjudicated label.
- `ann-d1-0033` remains internally inconsistent and is excluded, not resolved.
- Results derive from one run over 22 questions on a 6-chunk corpus.
- Completing annotation does not prove the research hypothesis; no accuracy,
  superiority, or publication claim follows from this report.
