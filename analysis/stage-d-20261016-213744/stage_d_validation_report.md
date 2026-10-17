# Stage D — Validation Report

**Generated:** 2026-10-16T16:54:32.530886+00:00  
**Validator:** `analysis/stage-d-20261016-213744/validate_stage_d.py` (re-runnable; stdlib only)  
**Overall:** PASS (14/14 checks passed)

| # | Check | Status | Detail |
|---|---|---|---|
| 1 | 1 builder re-run determinism | **PASS** | items content hash across 2 runs: ['85d34fdee5984496ca7ac3acc784203f2c0bee98b53fd08133980b75a66b97be', '85d34fdee5984496ca7ac3acc784203f2c0bee98b53fd08133980b75a66b97be'] |
| 2 | 2 schema conformance (all items, nested objects, enums, patterns) | **PASS** | all items conform to schema v1.0.0 |
| 3 | 3 every claim maps to an existing source claim row (byte-identical) | **PASS** | all 40 claim items verified against source DB |
| 4 | 4 every question_id exists in eval_questions.json | **PASS** | all question ids resolve |
| 5 | 5 ID uniqueness + csv/json/blind row agreement (46/46/46, same order) | **PASS** | items=46 csv=46 blind=46 dup_ann=0 dup_claim=0 dup_abs=0 |
| 6 | 6 evidence references (verbatim chunk texts, recovered ids re-derived, 13/13 historical cross-check) | **PASS** | recovered citations re-verified: 13/13; all chunk texts verbatim |
| 7 | 7 abstention items (verbatim stored abstention, claims_total=0, retrieval == stored retrieved_count) | **PASS** | 6/6 abstention items verified |
| 8 | 8 all human-judgment fields null; review_status=not_reviewed everywhere | **PASS** | non-null human fields: NONE |
| 9 | 9 AI-label separation (blind file has no verdict/AI columns or recovery leaks; provenance strings present) | **PASS** | leak_cols=[] leak_vals=0 src_missing=[] |
| 10 | 10 historical artifacts unchanged (Stage C baseline + review files + gold_label NULL + run-dir mtimes) | **PASS** | changed=NONE; files modified after Stage D start=NONE |
| 11 | 11 git: no tracked-file changes; HEAD matches manifest | **PASS** | tracked_dirty=NONE; HEAD=d4ea26db3e27; untracked=['?? analysis/'] |
| 12 | 12 no credential-like secrets in generated files | **PASS** | no secret-like patterns in any Stage D file |
| 13 | 13 manifest self-consistency (hashes recomputed, counts match queue, honesty statements) | **PASS** | manifest verified against recomputed hashes and live queue |
| 14 | 14 full existing test suite passes | **PASS** | 763 passed, 1 warning in 13.86s |

## Interpretation

- A PASS here means the package is mechanically consistent with the immutable artifacts: every queued item maps to a real stored claim/question, evidence text is byte-verbatim, recovered citations were re-derived independently of the builder, human fields are empty, AI labels are quarantined, no historical artifact or source DB changed, and no secret-like material was written.
- **No check here evaluates any human label** — none exist yet. This report certifies readiness for review, not review quality.
- If any row is FAIL, the package must not be used for review until the cause is fixed and this validator is re-run.
