# Stage D1 — Review Progress

**Directory:** `analysis/stage-d1-20261017-000041/` · **Dataset:** `d1` · **Schema:** v1.0.0
**Stage status:** review workspace prepared — **machine proposals only, 0 human confirmations**
**Prepared by:** OpenCode AI assistant (MiMo-V2.6-Flash). **No item below is a human label.**

---

## 1. What has been done

1. Re-verified the Stage D package (`analysis/stage-d-20261016-213744/`) before use: 46 items, all human fields empty, all `review_status = not_reviewed`, manifest honesty statements present. **Stage D files were read, never written.**
2. Read the full corpus actually shown to the system (6 chunks / 5 CISA KEV advisory records) and all 46 items (claims, paired baseline/verified answers, evidence, stored citations).
3. Read and applied the governing documents: `human_annotation_guidelines.md`, `annotation_schema.json`, `annotation_data_dictionary.md`, `stage_d_protocol.md`, `stage_d_provenance_audit.md`, `stage_d_manifest.json`, both queue CSVs.
4. Independently checked corpus-level facts used in rationales (direct read-only DB scans): no dates, no CVSS, no severity, no version strings, no KB numbers, no endpoint counts, no `CVE-2021-45046`, no `Conti`/`Cisco`/`Heartbleed`/`Log4Shell`/`overhyped` anywhere in the run's 6-chunk corpus; the NVD fixture is not indexed in the eval run and carries no CVSS metrics.
5. Authored evidence-first proposals for all 46 items (`d1_proposed_judgments.json`) and built the workspace files deterministically from the queue (`build_workspace.py`).

## 2. Counts (all machine-generated; nothing human-confirmed)

| Category | Count |
|---|---|
| Items with a proposal | **46 / 46** (tier 1 retracted: 13 · tier 2 surviving supported: 11 · tier 3 abstentions: 6 · tier 4 stratified: 16) |
| `proposal_status = proposed_unconfirmed` | 45 |
| `proposal_status = needs_adjudication` | 1 (ann-d1-0030, plausible-04 scope question) |
| Human-confirmed labels | **0** |
| Human-written rationales / reviewer fields filled | **0** (all human columns emitted empty) |

**Proposed labels — claim items (n=40):** `supported` 20 · `insufficient_evidence` 11 · `unverifiable` 8 · `contradicted` 1
**Proposed assessments — abstention items (n=6):** `appropriate_abstention` 5 · `uncertain` 1

- Every item has a non-empty rationale, an evidence-sufficiency rationale, a citation-support judgment, and an explicit `evidence_reference`: **46/46**.
- Items carrying uncertainty/flag notes: **44/46**.
- Items carrying a `policy_alternative_label` (the other defensible reading): **19**, of which **12** come from the single guideline-§1.A interpretation question — one reviewer ruling covers all 12 (see `unresolved_evidence.md` §D).
- Items asserting values absent from the corpus (dates/severity/version/publicity): **11 claim items + 4 abstentions**, all recorded in `unresolved_evidence.md` §A.
- Items with a direct evidence conflict: **1** (ann-d1-0033, `contradicted`).
- Extraction-artifact items (labeled as stored, never repaired): **7** (0003, 0004, 0015, 0016, 0031, 0032, 0039 + attribution phrasing in 0001).

## 3. Visibility record (required by protocol §3)

- **Proposal drafter (this AI assistant): system verdicts VISIBLE.** The working dump included `SYSTEM VERDICT` lines. Mitigation actually applied: proposals were derived from claim + evidence text first; **no rationale cites a system verdict as justification**; agreement with verdicts is computed only afterwards, as a descriptive output. Verdicts were never used as ground truth, and the old 56-file AI draft labels were not consulted for any rationale.
- **Human confirmer: BLIND by default.** `review_workspace.csv` and `proposed_judgments.csv` contain **no system-verdict column and no old-AI-draft column** (validated by column scan). If the confirmer opens `human_review_queue.json`/`.csv` for a post-hoc self-check, record that visibility change here: `_ (to be filled by reviewer: when verdicts were seen)_`.

## 4. Post-hoc descriptive comparison — proposals vs system verdicts

**These are NOT agreement statistics.** They compare two machine artifacts; no human label exists yet. Never report these as judge-vs-human agreement.

| Set | Proposal == system verdict |
|---|---|
| All claim items (n=40) | 16 / 40 |
| Tier 1 (system `insufficient_evidence` ×13) | 7 / 13 (proposals: 7 insufficient, 3 supported, 3 unverifiable) |
| Tier 2 (system `supported` ×11) | 8 / 11 (proposals: 8 supported, 2 insufficient, 1 unverifiable) |
| Tier 4 (system mixed ×16) | 1 / 16 (proposals: 9 supported, 4 unverifiable, 2 insufficient, 1 contradicted) |
| Tier 3 (system abstained ×6) | assessments: 5 `appropriate_abstention`, 1 `uncertain` |

Divergence runs **both ways** (proposals upgrade several verdicts to `supported` and downgrade others to `unverifiable`/`insufficient_evidence`), which is the expected behavior of independent evidence-first drafting. Highest-value divergences to confirm carefully: **ann-d1-0033** (proposal `contradicted` vs system `insufficient_evidence`), **ann-d1-0014** (proposal `insufficient_evidence` vs system `supported` — candidate false endorsement), **ann-d1-0002/0003/0013** (proposal `supported` vs retraction).

## 5. Limitations (must travel with any use of these files)

1. **Nothing here is a human judgment.** Every label is `proposed_unconfirmed` until a person confirms or revises it in `review_workspace.csv`.
2. **Confirming AI proposals is not independent blind labeling.** Any later judge-vs-human agreement computed on confirmed-from-proposal labels must be reported as *"AI-proposed, human-confirmed"* and may be **upward-biased** relative to independent annotation (protocol §5.6 circularity caution). For a genuinely independent number, a second reviewer should annotate the untouched blind file `../stage-d-20261016-213744/human_review_queue_blind.csv` without seeing these proposals or the verdicts.
3. **Single-reviewer output is never "independently validated."**
4. **The guideline-§1.A ruling is unresolved** (`unresolved_evidence.md` §D): the committed reading labels passage-content claims checkable; the strict reading would flip 12 items. One written ruling, made before any agreement statistic is computed, settles them.
5. **ann-d1-0030 needs adjudication**, not a vote: the scope rule (retrieved passages vs catalog) decides it.

## 6. Fastest confirmation path for the reviewer (~10–15 min for all 46)

1. Open `review_confirmation_sheet.md` (compact: claim/question, proposed label, one-line why).
2. For each row, open the evidence in `review_workspace.csv` (`evidence_text` column) and verify the rationale. Read `../stage-d-20261016-213744/human_annotation_guidelines.md` first if it has been a while.
3. Record in `review_workspace.csv`: `reviewer_decision` = `accept` / `revise` / `reject`, then fill the corresponding `human_*` fields (and set `review_status` = `confirmed`, or `uncertain` if you genuinely cannot decide — blanks are data, guesses are not).
4. Apply the §1.A ruling once (`unresolved_evidence.md` §D), then confirm the 12 affected items as a group.
5. Adjudicate `ann-d1-0030` by writing the scope rule + your decision (`adjudicated_label` / `adjudication_rationale`).
6. Optionally record `reviewer_id` and `review_timestamp`. Optional second reviewer: independent pass on the blind Stage D file.
7. Do **not** copy any proposal into a human field without reading the evidence; do not treat any proposal as correct because the system verdict agrees with it.

## 7. Deliverables in this directory

| File | Role |
|---|---|
| `d1_proposed_judgments.json` | Authored proposal data (single source of truth; honesty block at top) |
| `build_workspace.py` | Deterministic builder (queue read-only → CSVs; asserts 46/46 coverage) |
| `review_workspace.csv` | **Main confirmation file** — 46 rows × 36 cols; evidence + proposals; all human columns empty |
| `proposed_judgments.csv` | Proposal layer only — 46 rows × 17 cols (§5 fields + provenance) |
| `review_confirmation_sheet.md` | Compact accept/revise/reject view |
| `unresolved_evidence.md` | Missing/conflicting/borderline/policy/adjudication catalog |
| `validate_stage_d1.py` + `stage_d1_validation_report.md` | Integrity validation |
| `stage_d1_manifest.json` | Provenance, hashes, honesty statements |
| `review_progress.md` | This file |

## 8. Integrity statements

- **No model/API calls** were made in Stage D1 (no prompt, model, gate, or evaluation change; no new runs).
- **No historical artifact was modified:** Stage D package, Stage C outputs, both `runs/` databases and reports, `data/evidencegraph.db`, `data/sample/eval_questions.json`, and application code are verified unchanged by hash/mtime checks in `validate_stage_d1.py`.
- **No proposal was written into any human-label field**, in this directory or in the Stage D queue; `gold_label` untouched; no commit, push, deploy, or Docker activity.

**Stop point:** Stage D1 stops here. Next steps belong to a human (confirmation/adjudication) and require separate authorization (Stage E, any commit).
