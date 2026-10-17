# Stage D3 — Reviewer Decision Note (recorded 2026-10-17)

**Status:** reviewer decisions captured in `d3_review_decisions.csv` from statements the
reviewer supplied directly in the project conversation. This note documents the shared
ruling and its scope. It records no decision by itself beyond transcribing the reviewer's
stated choices.

## 1. Provenance and honesty boundaries

- **Source of all decisions:** the reviewer's own instructions in the project
  conversation (Stage D3 "Record My Confirmed Review Decisions" brief). Nothing else.
- **Not fabricated:** no reviewer identity, no reviewer timestamp, no reviewer-claimed
  evidence inspection. The CSV schema has no `reviewer_id` / `review_timestamp` columns
  and none were invented. Every reviewer note restates only a basis the reviewer
  explicitly supplied (the R1 ruling, the scope choice, or the accept /
  needs-adjudication instruction) — no additional rationale was authored on their behalf.
- **Machine vs human separation:** machine columns (`proposed_label`,
  `proposed_abstention_assessment`, `explanation`, `evidence_status`,
  `recommended_action`, `suggested_revised_label`, `confidence`) are untouched and still
  carry the machine recommendations, including where they now diverge from the reviewer
  (listed in §3). Only `reviewer_decision` and `reviewer_note` were written.
- **No label transfer:** nothing was written to `gold_label`, to any database, or to any
  historical artifact. Stage E has not started.

## 2. Decision A — R1 shared guideline ruling: **A (committed reading)**

The reviewer's scope statements, transcribed:

1. The evaluation concerns whether the system's answer is supported by the evidence it
   actually retrieved.
2. Absence from retrieved passages does not establish absence from the complete
   underlying catalog or the real world.
3. This ruling resolves the documented ambiguity between the relevant guideline
   sections for this evaluation.
4. This must not be described as proof that the system's answer is factually correct.

**Scope of application:** this ruling applies only to the 12 items below. The mapping was
recalculated from the actual files before application, from three independent sources —
`R1_FAMILY` in `build_d3_review.py`, the "Items covered:" list in the R1 section of
`d3_review_cards.md`, and the section-4 table of `r1_explainer.md` — all three agree on
the same 12 IDs. The card-number change/keep arithmetic previously flagged as incorrect
in `r1_explainer.md` §6 was **not** used.

| Annotation ID | Card # | Proposed label | Action under ruling A |
|---|---|---|---|
| ann-d1-0013 | 8 | `supported` | `accept` |
| ann-d1-0017 | 4 | `supported` | **left unresolved** (see below) |
| ann-d1-0018 | 9 | `supported` | `accept` |
| ann-d1-0019 | 10 | `supported` | `accept` |
| ann-d1-0036 | 11 | `unverifiable` | `accept` |
| ann-d1-0037 | 12 | `supported` | `accept` |
| ann-d1-0038 | 13 | `supported` | `accept` |
| ann-d1-0040 | 14 | `supported` | `accept` |
| ann-d1-0042 | 15 | `supported` | `accept` |
| ann-d1-0043 | 16 | `unverifiable` | `accept` |
| ann-d1-0044 | 17 | `unverifiable` | `accept` |
| ann-d1-0045 | 18 | `unverifiable` | `accept` |

- **11 rows → `reviewer_decision = accept`**: the ruling endorses the interpretation the
  proposals were drafted under, so the proposals stand. The row notes state that the
  basis is the shared ruling only and that per-item reviewer inspection is not claimed.
- **ann-d1-0017 → left unresolved (`needs_adjudication` marker, no label)**: ruling A does
  not settle this item's separate literal-vs-scoped wording question (Card 4). Recording
  it as unresolved with the reason is this schema's representation of "unresolved where
  necessary"; no label was chosen for it.
- Absence-based claims accepted under this ruling remain evaluations of the retrieved
  evidence only, per scope statement 2.

## 3. Decisions B–E as recorded, and divergences from machine recommendations

| Item | Reviewer decision recorded | Machine recommendation (unchanged, still visible) | Divergence? |
|---|---|---|---|
| ann-d1-0033 | `needs_adjudication` (not accepted, not rejected; further review required) | `accept_proposal` | **yes** — machine said accept; reviewer withheld |
| ann-d1-0014 | `needs_adjudication` (not accepted, not rejected; further review required) | `accept_proposal` | **yes** — machine said accept; reviewer withheld |
| ann-d1-0030 | `revise`; scope = **retrieved passages**; reviewer's label `appropriate_abstention` documented in the row note (no reviewer-label column exists; machine `suggested_revised_label` left empty) | `needs_adjudication` | **yes** — reviewer made the scope ruling the machine deferred |
| ann-d1-0032 | `accept` — existing proposed label `supported` stands per the schema's documented meaning of `accept` | `revise_proposal` → candidate `insufficient_evidence` | **yes** — machine suggested revision; reviewer accepted |

No prior reviewer values were overwritten: every `reviewer_decision` cell was blank
before this recording (verified against the preserved pre-decision snapshot
`d3_review_decisions_predecision_snapshot.csv`), so no decision conflicts with an earlier
reviewer value.

**Derived value disclosure:** for ann-d1-0030, `appropriate_abstention` is derived from
the reviewer's explicit scope choice ("retrieved passages") via the mapping documented in
Stage D3 materials *before* the choice was made ("passages" → `appropriate_abstention`,
"catalog" → `inappropriate_abstention`). It is recorded in the row note rather than in a
label column. If the reviewer disputes that derivation, it is a single-cell correction.

## 4. Items left unresolved

1. **ann-d1-0033** — `needs_adjudication` per reviewer; proposal neither accepted nor
   rejected.
2. **ann-d1-0014** — `needs_adjudication` per reviewer; proposal neither accepted nor
   rejected.
3. **ann-d1-0017** — R1 applied, wording question (Card 4) not ruled → unresolved.
4. **30 further rows** — untouched and blank pending the reviewer's own pass
   (Group A straightforward items, the interpretation items 0015/0020, and the remaining
   abstentions 0025–0029 and tier-2/tier-4 items not covered by these decisions).
5. **ann-d1-0030 claim label** — no claim-label decision was supplied by the reviewer, so
   none was invented; `proposed_label` remains `not_applicable`.

## 5. Validation results (exact)

Command run (the existing, unmodified script):
`python analysis/stage-d3-20261017-011614/validate_stage_d3.py`

- Result: **26/27 checks PASS, 1 FAIL** — written to `d3_validation_report.md`.
- **FAIL = check B6 "reviewer columns 100% blank"**, with violations exactly
  `('ann-d1-0033','reviewer_decision'), ('ann-d1-0033','reviewer_note'), ('ann-d1-0014','reviewer_decision')` (first three of the 32 authorized cells).
- **Explanation:** B6 encodes the *pre-decision* invariant (nothing pre-authorized while
  the interface is empty). Its failure is the direct, expected consequence of recording
  the 16 authorized reviewer decisions. Per the review brief the check was **not weakened
  and the script was not modified** — it remains byte-identical to the hash recorded in
  `stage_d3_manifest.json`, which the audit verifies. All other 26 checks pass, including
  row/column integrity (B1, B8), claim wording (B2), excerpt traceability (B3/B4),
  proposal preservation (B5), vocabulary (B7), cards (C1–C7), D1+D2 unchanged (35
  manifest hashes), historical hashes (E1), no external modification (E2), git unchanged
  (E3/E4), hygiene (F1–F4b), and the test suite (F5: **763 passed**).

## 6. What was not done

No Stage E work, no commit, no push, no deploy, no Docker, no model/API calls, no
prompt or gate changes, no edits to Stage B/C/D/D1/D2 files, no database writes, no
`gold_label` transfer, no human-agreement statistics computed, and no other review rows
filled.

## 7. Update 2026-10-17 — ann-d1-0017 explicit ruling (supersedes §3–§4 for this item only)

The reviewer supplied an explicit ruling for ann-d1-0017 in the project conversation,
resolving the literal-vs-scoped wording question that ruling R1 = A had left open:

- `reviewer_decision` = **`revise`**
- Reviewer label = **`contradicted`**. The schema has **no `reviewer_label` column**
  (only `reviewer_decision` / `reviewer_note` carry human authority), so the label is
  carried in `reviewer_note` as the structured prefix `Reviewer label: contradicted | `
  followed by the reviewer's verbatim note: *"Under the adopted R1 ruling, evaluate the
  claim as written against the retrieved passages. The wording says the passages only
  mention the FortiOS vulnerability, but the displayed retrieved set also includes Log4j,
  OpenSSL, and MOVEit. Therefore, the literal first clause conflicts with the shown
  evidence. This is a corpus-grounded judgment about the wording and retrieved set only;
  it does not establish anything about the complete corpus or the real world."*
- Machine columns untouched, including the empty `suggested_revised_label`: the cards'
  revise procedure (line 7) points to that column, but the cards' own integrity statement
  (line 10) classifies it as a machine column and validator check B7 couples it to the
  machine `recommended_action` (which is `needs_adjudication` for this row). The same
  note-only handling already used for ann-d1-0030 (§3) was therefore applied. If the
  reviewer prefers the label also written into `suggested_revised_label`, that is a
  one-cell change whose consequence (validator B7 failure; human value in a machine
  column) must be reported with it.

**Change record:** `reviewer_decision` needs_adjudication → `revise` — an informed update
by the reviewer, who had just seen the row's state in the read-only inspection. The
pre-update file bytes are preserved in `d3_review_decisions_pre0017update_snapshot.csv`;
the earlier blank-state snapshot `d3_review_decisions_predecision_snapshot.csv` is
untouched. This ruling is the reviewer's own corpus-grounded judgment; it transfers no
label to any database, `gold_label`, or historical artifact, and no independent
validation is claimed (single reviewer, no second pass).

Sections 3–6 remain the record as of the first recording. For ann-d1-0017 only, this
section supersedes them. Other open items are unchanged: ann-d1-0033 and ann-d1-0014
remain `needs_adjudication`, and 30 rows remain blank pending the reviewer's pass.

## 8. Update 2026-10-17 — ann-d1-0033 explicit ruling (supersedes §3 row 1; §4 item 1 resolved)

The reviewer supplied an explicit ruling for ann-d1-0033:

- `reviewer_decision` = **`revise`**
- Human-selected label = **`supported`**, carried in `reviewer_note` as the structured
  prefix `Reviewer label: supported | ` (the schema has no `reviewer_label` column; same
  convention as ann-d1-0030 §3 and ann-d1-0017 §7), followed by the reviewer's verbatim
  note: *"The retrieved passages mark both Log4j2 and Microsoft Exchange as Known, but each
  explicitly states that this is per the source record and was not independently verified
  here. The claim's inference of independent verification conflicts with those explicit
  disclaimers. This decision is limited to the retrieved passages and does not establish
  real-world truth."*
- Machine columns untouched: `proposed_label` stays `contradicted`, `recommended_action`
  stays `accept_proposal`, `suggested_revised_label` stays empty — the human label was not
  written into any machine-generated field (per instruction and validator check B7).

**REVIEWER-FLAGGED INCONSISTENCY — documented, deliberately NOT resolved.** The selected
label `supported` conflicts with the reasoning stated in the reviewer's own note, which
describes the independent-verification inference as conflicting with the explicit
disclaimers (the basis of the machine's `contradicted` proposal). Per the reviewer's
explicit instruction, the label is recorded exactly as selected and the note preserved
verbatim as supplied: no label substitution, no note rewriting, no silent reconciliation
of the two, and the machine proposal remains unchanged for comparison. This row therefore
carries an open internal inconsistency owned by the reviewer — its correction paths are
(a) revise the label, (b) revise the note, or (c) confirm both as intentional — and it
must not be silently resolved by any machine-side action.

**Change record:** `reviewer_decision` needs_adjudication → `revise` (informed update; the
pre-update bytes are preserved in `d3_review_decisions_pre0033update_snapshot.csv`; the
blank-state snapshot and `d3_review_decisions_pre0017update_snapshot.csv` remain
untouched). No gold-label transfer, no database write, no independent-validation claim
(single reviewer).

For ann-d1-0033 only, this section supersedes the §3 row and §4 item 1 above. Remaining
open: ann-d1-0014 (`needs_adjudication`) and 30 blank/pending rows.

## 9. Update 2026-10-17 — ann-d1-0014 explicit ruling (supersedes §3 row 2; §4 item 2 resolved)

The reviewer supplied an explicit ruling for ann-d1-0014:

- `reviewer_decision` = **`revise`**
- Human-selected label = **`insufficient_evidence`**, carried in `reviewer_note` as the
  structured prefix `Reviewer label: insufficient_evidence | ` (the schema has no
  `reviewer_label` column; same convention as ann-d1-0030 §3, ann-d1-0017 §7 and
  ann-d1-0033 §8), followed by the reviewer's verbatim note: *"The retrieved passages
  identify Microsoft Exchange Server Remote Code Execution Vulnerability
  (CVE-2021-34473), but none contains the claimed addition date 2021-11-03. The date
  appears only in separately inspected document metadata that was not shown to the
  system. No retrieved passage gives a conflicting date, so the claim is not
  contradicted; however, its date component is not established by the retrieved
  evidence. This decision is limited to the retrieved passages and does not establish
  real-world truth."*
- Machine columns untouched: `proposed_label` stays `insufficient_evidence`,
  `recommended_action` stays `accept_proposal`, `suggested_revised_label` stays empty —
  the human label was not written into any machine-generated field (per instruction and
  validator check B7).

**Observation (documented, not acted upon):** the reviewer's selected label equals the
machine-proposed label for this row (`insufficient_evidence`), while `reviewer_decision`
is `revise` although the machine recommended `accept_proposal`. Both values are recorded
exactly as the reviewer supplied them; no field was aligned in either direction.

**Change record:** `reviewer_decision` needs_adjudication → `revise` (informed update; the
pre-update bytes are preserved in `d3_review_decisions_pre0014update_snapshot.csv`,
sha256 `303f7f609443a464f619ef423660e7481f9e115d11e512064a3d6ee970ef3451`; the blank-state
snapshot, `d3_review_decisions_pre0017update_snapshot.csv` and
`d3_review_decisions_pre0033update_snapshot.csv` remain untouched). No gold-label
transfer, no database write, no independent-validation claim (single reviewer).

For ann-d1-0014 only, this section supersedes the §3 row and §4 item 2 above. Decision
state: 16 of 46 rows carry reviewer decisions (accept=12; revise=4: 0030, 0017, 0033,
0014; needs_adjudication=0); 30 rows remain blank pending the reviewer's pass (§4 item 4
open; §4 item 5 unchanged).

## 10. Update 2026-10-17 — approved batch decisions on 26 of the 30 pending rows

The reviewer approved a batch of decisions from the Stage D3 batch review package
(`../stage-d3-batch-review-20261017-150516/`: approval sheet, proposal CSV, and 14/14
package validation report). Recorded by `record_d3_batch30_update.py` under the established
guarded workflow; audited by `audit_d3_batch30_update.py`.

- **25 items — `reviewer_decision` = `accept`:** the existing machine-proposed label stands
  as the reviewer-approved label for each (supported = 9: 0002, 0003, 0016, 0021, 0022,
  0024, 0031, 0034, 0041; insufficient_evidence = 8: 0001, 0004, 0008, 0009, 0010, 0011,
  0039, 0046; unverifiable = 3: 0005, 0006, 0007; not_applicable + abstention assessment
  `appropriate_abstention` = 5: 0025, 0026, 0027, 0028, 0029). Each `reviewer_note` names
  the accepted label explicitly; machine columns untouched.
- **ann-d1-0020 — `reviewer_decision` = `revise`:** human label **`contradicted`**, carried
  in `reviewer_note` with the structured prefix `Reviewer label: contradicted | ` (same
  convention as §3, §7, §8, §9), followed by the reviewer's note: *"Under the
  retrieved-passage evaluation scope, the claim presents the product list as exhaustive,
  while the retrieved passages positively identify additional products. This is a judgment
  about the retrieved evidence and wording only; it does not establish anything about the
  complete corpus or the real world."* Machine `proposed_label` stays
  `insufficient_evidence`, `suggested_revised_label` stays empty (validator B7).
- **4 items explicitly held, left blank and pending (no decision, no note):**
  ann-d1-0012, ann-d1-0015, ann-d1-0023, ann-d1-0035 — the four medium-confidence reading
  forks from the batch package; the reviewer reserved them for individual rulings.

**Change record:** 52 cells changed — `reviewer_decision` and `reviewer_note` only, on the
26 authorized ids (25 blank → `accept`; 1 blank → `revise`). The pre-update bytes are
preserved in `d3_review_decisions_prebatch30update_snapshot.csv`, sha256
`95ad984d4c7f37d1eeb01b76f5af2dbe4ee5866758534a316ee847821a22286e`. The blank-state snapshot
and the `pre0017`/`pre0033`/`pre0014` snapshots remain untouched; the 16 decisions from §3–§9
are byte-identical. No gold-label transfer, no database write, no independent-validation
claim (single reviewer).

Decision state: 42 of 46 rows carry reviewer decisions (accept=37; revise=5: 0030, 0017,
0033, 0014, 0020; needs_adjudication=0); 4 rows remain blank pending the reviewer's
individual rulings (ann-d1-0012, 0015, 0023, 0035).

## 11. Update 2026-10-17 — final four rulings (the former HOLD set)

The reviewer ruled individually on the four held items after the per-item review cards were
presented. Recorded by `record_d3_final4_update.py` under the established guarded workflow;
audited by `audit_d3_final4_update.py`.

- **ann-d1-0012 — `reviewer_decision` = `needs_adjudication` (held):** note: *"Held for
  adjudication. The unsupported evaluative significance is the weakest part of the compound
  claim. No final claim label is approved at this time."* No final claim label assigned;
  machine `proposed_label` stays `insufficient_evidence`, `suggested_revised_label` stays
  empty. This row remains the open adjudication item.
- **ann-d1-0015 — `reviewer_decision` = `revise`:** human label **`supported`**, carried in
  the reviewer's own note with the structured prefix `Reviewer label: supported | ` (same
  convention as §3, §7–§10), followed by: *"The retrieved passages support the intended
  two-product list (Log4j2 and Exchange Server), but the stored claim is truncated after
  \"are: 1.\". This decision evaluates the intended substance rather than the incomplete
  stored fragment; the truncation remains a claim-storage/extraction defect."* Machine
  `proposed_label` stays `unverifiable` (machine/human separation intact per validator B7).
- **ann-d1-0023 — `reviewer_decision` = `accept`** (proposed `supported` stands). Note:
  *"Reviewer decision: accept. The claim's core statement is supported by the retrieved
  passage, and \"significant security concern\" is read in its natural context as describing
  the documented impact, not as an independent severity rating."*
- **ann-d1-0035 — `reviewer_decision` = `accept`** (proposed `supported` stands). Note:
  *"Reviewer decision: accept. Under the natural contextual reading, the retrieved Exchange
  advisory pairs CWE-918 with the RCE advisory and states that the vulnerability allows
  remote code execution. No external CWE taxonomy knowledge is used."*

**Change record:** 8 cells changed — `reviewer_decision` and `reviewer_note` only, on the
4 authorized ids (all blank → recorded). The pre-update bytes are preserved in
`d3_review_decisions_prefixhold4_snapshot.csv`, sha256
`2ba3f58409db5714d67c8ac67a5b61cfab6ef80656b10608df8ce9c0f3d290da`. The blank-state snapshot
and the `pre0017`/`pre0033`/`pre0014`/`prebatch30` snapshots remain untouched; the 42 prior
decisions are byte-identical. No gold-label transfer, no database write, no
independent-validation claim (single reviewer).

Decision state: all 46 rows now carry a reviewer decision (accept=39; revise=6: 0030, 0017,
0033, 0014, 0020, 0015; needs_adjudication=1: 0012, held for adjudication; blank=0).
ann-d1-0012 remains open pending a final label ruling.

## 12. Update 2026-10-17 — ann-d1-0012 correction (supersedes the §11 hold for this item)

The reviewer explicitly authorized correcting their own §11 decision for ann-d1-0012.
Recorded by `record_d3_0012_correction.py` under the established guarded workflow; audited
by `audit_d3_0012_correction.py`.

- **Change:** `reviewer_decision` `needs_adjudication` → **`accept`** — the existing
  machine-proposed label **`insufficient_evidence`** stands as the reviewer-approved label
  (named in the note; no reviewer-label column exists, same convention as §3, §7–§11).
- **Reviewer note (verbatim):** *"Reviewer decision: accept (corrects the earlier
  needs_adjudication hold for this item). The reviewer accepts the existing proposed label,
  insufficient_evidence: the evaluative 'significant' clause is the unsupported weakest
  part of the compound claim, and no passage assigns severity or ranking to any product.
  Machine-proposed fields preserved unchanged."*
- **Audit history preserved, not erased:** the superseded hold ruling lives byte-exact in
  `d3_review_decisions_pre0012correction_snapshot.csv` and in §11 above.

**Change record:** 2 cells changed — `reviewer_decision` and `reviewer_note` of
ann-d1-0012 only. Pre-correction bytes preserved in
`d3_review_decisions_pre0012correction_snapshot.csv`, sha256
`3ef6fae315634c970d259888c67c15f7d01f9184d23113e0d671884eb84ec5ad`. All six earlier
snapshots untouched; the other 45 rows byte-identical; machine columns untouched
(`proposed_label` stays `insufficient_evidence`, `suggested_revised_label` stays empty).
No gold-label transfer, no database write, no independent-validation claim (single
reviewer).

Decision state: all 46 rows carry a final reviewer decision (accept=40; revise=6: 0030,
0017, 0033, 0014, 0020, 0015; needs_adjudication=0; blank=0). No item remains open.
