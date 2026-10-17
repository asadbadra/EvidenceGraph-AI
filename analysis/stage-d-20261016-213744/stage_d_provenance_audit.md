# Stage D — Annotation Provenance Audit

**Date:** 2026-10-16
**Auditor:** OpenCode (automated inspection; read-only; no files modified)
**Scope:** The two pre-existing claim-review artifacts identified by the Stage C report (`analysis/stage-c-20261016/stage_c_report.md`, §7 threat 9 and §8 item 1).

**Purpose.** Establish, from evidence rather than filenames or field names, whether any existing label in these artifacts may legitimately be treated as an independent human judgment. Only labels with established human provenance may ever enter human-ground-truth calculations.

---

## 1. Artifact A — `runs/eval-pilot22-20261014-181354/human_claim_review56.md`

### 1.1 File facts (recorded, not inferred)

| Property | Value |
|---|---|
| Path | `runs/eval-pilot22-20261014-181354/human_claim_review56.md` |
| SHA-256 | `86787635c4ba04a03ebfe52c9bc1d1e90397826740049470e0cc12c6700ae947` |
| Size | 65,605 bytes / 3,172 lines |
| Last modified (UTC) | 2026-10-14T17:42:03Z |
| Git-tracked? | **No.** `git log --all` and `git ls-files` return nothing for this path (run directories are gitignored). No commit history exists. |
| Co-located generator | `runs/eval-pilot22-20261014-181354/generate_review56.py`, SHA-256 `1e583d9cc77097dd309c92d15ba46ddb8b08c6ccbdbdc64b8532d6f10e378df4`, mtime 2026-10-14T17:16:48Z (≈25 min before the review file's final mtime) |

### 1.2 Content inventory

- **56 claim sections**, claim ids 1–56 sequential, matching table `verif_claims` (verified arm) of the run's database copy.
- **Label fields:** 56 present, **56 filled, 0 blank**. Distribution: `supported` 25, `insufficient_evidence` 20, `contradicted` 3, `unverifiable` 8.
- **Rationale fields:** 56 present, **56 filled**.
- **Judge-verdict reference blocks:** 56 (in collapsed `<details>` sections marked "not ground truth").
- Filled labels equal the judge's stored verdict in **23/56** cases (41%) — the draft does not merely mirror the judge.

### 1.3 Claim-text fidelity vs. the run database

All 56 claim texts were extracted from the file and compared to `verif_claims.claim_text`: **55/56 byte-identical** (whitespace-normalized); 1 difference at claim id 26 where the file contains markdown-escaped asterisks (`\*`) against the database's literal `*`. This is the signature of a programmatic markdown-escaping pass, not editorial rewriting.

### 1.4 Provenance determination: **AI-generated (model-assisted draft); NOT human**

Evidence establishing this conclusion (multiple independent lines):

1. **The file declares itself.** Lines 1–3 open with "**AI-Assisted Preliminary Claim Review**" and: *"The labels and rationales below are an AI-assisted draft … They are **not independent human labels** and must not be reported as human ground truth or used to claim judge-versus-human agreement."*
2. **The generator emits blanks by design.** `generate_review56.py` line 6 states "Fills no labels: every human field is emitted blank"; its template (lines 114–116) emits `**Your human label:** `_``. The current file's structure (bold-escaped markdown, disclaimer header) **does not match the generator's output template**, and every field is filled. The file was therefore post-processed after generation — by a model session, per its own header.
3. **Machine-transformation signature** in the claim texts (§1.3: markdown escaping at id 26) and in the file-wide markdown escaping.
4. **No human identity, timestamp, or attestation** appears anywhere in the file. The generator's own footer (lines 201–207) anticipates a human editor; none is recorded.
5. **Timeline:** generator mtime 17:16:48Z → review file mtime 17:42:03Z, consistent with generate-then-draft-in-one-session; no later modification window is evidenced.

### 1.5 Disposition

- **Classification:** `ai_generated_draft`.
- **May these 56 labels be treated as independent human judgments?** **No — explicitly forbidden by the artifact's own integrity note, and unsupported by any contrary evidence.**
- **Permitted future use:** retained in the review queue as `proposed_ai_label` with an explicit non-ground-truth marker, for a *secondary* comparison view only (e.g., analyzing how an AI draft differs from a later human label). They must never be counted as human labels, never be used in agreement statistics presented as human agreement, and never be transferred to any `gold_label` field.
- **The original file is not modified, moved, or rewritten by Stage D.**

---

## 2. Artifact B — `runs/eval-mini-20261014-165641/human_claim_review.md`

### 2.1 File facts (recorded, not inferred)

| Property | Value |
|---|---|
| Path | `runs/eval-mini-20261014-165641/human_claim_review.md` |
| SHA-256 | `f3522f9e34e1647ecfff441faf8b0791952f77a2a794071c8750e6a3ebfe0bc7` |
| Size | 13,126 bytes / 284 lines |
| Last modified (UTC) | 2026-10-14T12:33:40Z (≈58 min after the mini run completed at 11:35:23Z) |
| Git-tracked? | **No.** No history exists. |
| Generator script? | **None found.** A repo-wide scan of all `*.py` files (excluding caches) found **zero** files referencing `human_claim_review.md` or the template string `Your independent label`. The mini runner `run_eval_mini.py` does not mention the review file. |

### 2.2 Content inventory

- 8 claim sections (`direct-02` claims 1–4, `wrong-04` claims 5–8), from the mini run's database copy.
- **Label fields:** 8 present, **8 filled, 0 blank**: `supported` ×6 (one with a stray leading space, `` ` supported` ``), `insufficient_evidence` ×1, `unverifiable` ×1.
- **Rationale fields:** 8 present, **8 filled**.
- Filled labels equal the model's stored verdict in **5/8** cases (disagreements at claims 1, 2, 6).
- **The optional tally section is entirely blank** (`_` ×5) despite all eight labels being filled.

### 2.3 Observations relevant to origin (recorded, weight assessed below)

1. **Template-filling artifact.** Claim 4's rationale value literally begins with its own field prompt: `` `Your rationale: Evidence E3 explicitly identifies …` ``. A rationale containing the string "Your rationale:" is the signature of a template being filled programmatically (the field label copied into the value), which is atypical of human authorship.
2. **Blank tally with full labels** — inconsistent with a careful human completing the file as instructed (the file asks the reviewer to fill the tally after labeling), though not impossible.
3. **No reviewer identity, no review timestamp, no attestation, no provenance note.** The file is a *request* for human labels (its header: "This file asks for your **independent, human** label"); nothing in it records who, if anyone, answered.
4. Filled labels disagree with model verdicts on 3/8 claims — superficially "human-like," but a model asked to label independently would also disagree sometimes; this is **not** evidence of human authorship.
5. One label has a stray leading space (`` ` supported` ``) — consistent with either hasty manual entry or automated filling; not discriminating.
6. No generator exists in the repository, so the filling was done either by editing the file directly (by a person or a model session) — **the artifacts cannot distinguish these**.

### 2.4 Provenance determination: **`provenance_unknown`**

- **Can the origin of these 8 labels be established from the available evidence?** **No.** There is no attestation, no generator, no history, and no identifying metadata. The evidence leans toward programmatic filling (the "Your rationale:" prefix artifact; the blank tally) but does not **establish** it, and equally does not establish human authorship.
- **Per the Stage D rules:** these labels are classified **`provenance_unknown`** and are **excluded from all human-ground-truth calculations**. They are not deleted, not rewritten, and not counted as human labels anywhere in Stage D outputs.
- **Only path to reclassification:** the actual person, if any, explicitly attesting that they authored these eight labels (and accepting reviewer identity going forward). Absent that attestation the exclusion stands. *(This question is put to the project owner in the Stage D final report; it does not block the review queue, because `direct-02` and `wrong-04` are outside the 22-question Stage B set.)*

---

## 3. Summary table

| Artifact | Claims | Fields filled | Determination | Basis | Usable as human ground truth? |
|---|---|---|---|---|---|
| `human_claim_review56.md` | 56 | 56/56 labels + 56/56 rationales | **AI-generated draft** | Self-declared header; generator emits blanks; markdown-escaping signature; no attestation | **No** (queue use: `proposed_ai_label`, secondary view only) |
| `human_claim_review.md` (mini) | 8 | 8/8 labels + 8/8 rationales | **`provenance_unknown`** | No generator, no history, no attestation; template-filling artifact suggests but does not prove automated filling | **No** (excluded pending explicit human attestation) |

## 4. Consequences for Stage D

1. **No pre-existing label in the repository qualifies as independent human ground truth.** All `gold_label` columns remain NULL in both run databases; Stage D does not change this.
2. The human-review queue (Phase D of Stage D) therefore starts from **zero human labels**: every `human_label` field is emitted empty with `review_status = not_reviewed`.
3. The 56-file's labels are carried into the queue only as clearly-marked `proposed_ai_label` values (secondary view; hidden in the blind review file).
4. Judge-vs-human agreement statistics remain **not computable** until real human labels exist; nothing in Stage D computes them.

*All facts above were extracted read-only; both files remain byte-identical (hashes recorded in §1.1/§2.1 and re-verified at Stage D close).*
