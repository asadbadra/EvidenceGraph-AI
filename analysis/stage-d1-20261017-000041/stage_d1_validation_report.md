# Stage D1 — Validation Report

**Directory:** `stage-d1-20261017-000041` · **Checks:** 19/19 PASS · **Run:** `python validate_stage_d1.py` (stdlib + subprocess pytest)

Scope: workspace construction integrity, proposal/human-layer separation, blind-confirmer surface,
historical-artifact immutability, no-model-call evidence, and full test suite.

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | required files exist | PASS | all 8 present |
| 2 | proposals: 46 rows, ids/order match queue, vocabulary conformance | PASS | 46/46 conform |
| 3 | every proposal has rationale + evidence reference (evidence or explicit uncertainty) | PASS | 46/46 justified |
| 4 | proposals file contains no human-layer columns | PASS | no human_label/reviewer_id/adjudicated fields; uncertainty_notes here is the machine-authored proposal note required by brief section 5 |
| 5 | workspace: identifiers, claim text, answers, evidence copied verbatim from queue | PASS | 46/46 verbatim |
| 6 | workspace: all human/adjudication fields empty (no silent promotion) | PASS | 12 columns x 46 rows all empty |
| 7 | workspace: no system-verdict / old-AI-draft column (blind confirmer) | PASS | no verdict/grounding/proposed_ai_label columns |
| 8 | workspace: review_status vocabulary + claim/abstention category split | PASS | proposed=45, needs_adjudication=1 |
| 9 | cross-file: workspace proposals == proposed_judgments.csv | PASS | 46/46 consistent |
| 10 | proposal JSON: coverage, statuses, evidence-or-uncertainty per item | PASS | 46 entries; {'proposed_unconfirmed': 45, 'needs_adjudication': 1} |
| 11 | confirmation sheet: 46 items + machine-drafted warning | PASS | 46 rows, warning present |
| 12 | builder determinism: rebuild reproduces identical bytes | PASS | 3 outputs byte-identical after rebuild |
| 13 | historical integrity: Stage C + Stage D recorded hashes unchanged | PASS | 16 recorded hashes verified |
| 14 | no file outside stage-d1 dir modified since D1 work began | PASS | scanned runs, data, app, stage-c-20261016, stage-d-20261016-213744, tests |
| 15 | git: HEAD unchanged (d4ea26d), no tracked file modified, nothing committed | PASS | HEAD=d4ea26d, untracked=1, tracked_changes=0 |
| 16 | no model calls: no .db artifacts, no network/LLM imports in D1 scripts | PASS | no databases; stdlib-only scripts (model/API calls were never made) |
| 17 | secrets scan over Stage D1 files: no keys/tokens | PASS | clean (validator source excluded: holds the patterns) |
| 18 | CSV structure: UTF-8, no BOM, uniform column count | PASS | both CSVs clean |
| 19 | test suite (plain `python -m pytest`) passes | PASS | 763 passed, 1 warning in 13.86s |

## Interpretation

- Checks 4, 6, 7 prove the layer separation required by the Stage D1 brief: proposals exist only in proposal columns, every human/adjudication field is empty, and the confirmer's surface carries no system verdict or old-AI-draft label.
- Check 13 re-verifies every SHA-256 recorded by Stage C and Stage D (source DB, both run DBs and reports, eval questions, judge/claims/prompts sources, the 56-file and 8-file review artifacts); check 14 shows nothing outside this directory was modified after Stage D1 began.
- Check 15 shows no commit was made and no tracked file changed; only untracked `analysis/` outputs exist.
- Check 16/17: scripts are stdlib-only and make no network/model calls; no key material in any output.
- Check 19 is the full repository test suite (plain invocation; `pyproject.toml` already supplies `-q`).

**Nothing in this report is a human judgment; it validates structure and integrity only.**

