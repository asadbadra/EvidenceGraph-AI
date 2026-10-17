# Stage E Final Report & GitHub Publication Package

- Package: `analysis/stage-e-final-20261017/` · built 2026-10-18 (UTC dates in run artifacts)
- Repository: `master` @ `d4ea26d`, one commit ahead of `origin/master` (`b370fa4`)
- Status: **local Stage E work complete; publication prepared, NOT staged/committed/pushed**
- Companion artifacts in this directory: `publication_manifest.json` (exact file
  manifest, built by `build_publication_manifest.py`), `publication_validation_report.md`
  (produced by `validate_publication.py`).

## 1. Stage E summary

Approved scope executed in full: (B) derived-label annotation analysis (Stage E1),
(C) test-backed controlled-repetition scaffolding (`app/verification/experiments.py`
+ `tests/test_experiments.py`), (D) smoke tests (mock-provider wiring run + real
single-question run), (E) three controlled repetitions with analysis and validation.
**Ablation, generate-once, and baseline-claim-extraction experiments remain
UNEXECUTED: no predeclared experimental design has been approved for them.**
No second reviewer was contacted; no D3 record was changed; no Git action was taken.

## 2. Repetitions (all terminal, all comparable)

| # | Run directory (`runs/`, local-only) | Status | Elapsed | Calls ok/total | Verified claims (sup/contr/insuff/unver) | Baseline claims | Token usage |
|---|---|---|---|---|---|---|---|
| 1 | `stage-e-repeat1-20261017-155403` | completed (exit 0) | 1999.0 s | 112/112 | 64 (14/0/31/19) | 0 | **unavailable** (null) |
| 2 | `stage-e-repeat2-20261017-163026` | completed (exit 0) | 2011.7 s | 112/112 | 64 (14/0/31/19) | 0 | **unavailable** (null) |
| 3 | `stage-e-repeat3-20261017-170438` | completed (exit 0) | 1970.1 s | 112/112 | 64 (14/0/31/19) | 0 | **unavailable** (null) |

Configuration identity (identical machine fields across all three, verified):
commit `d4ea26d`; dataset `data/sample/eval_questions.json` sha `500ed32d…` (24
questions); corpus `data/evidencegraph.db` sha `0b9cacba…` (6 chunks);
model `llama3.2:latest` via local Ollama `http://localhost:11434/v1` (no remote
endpoint); temperature 0.0; max_tokens 700; retrieval top_k 4; judge `LLMJudge`
(`judge-v1`); prompt `baseline-v1`; git dirty flag = true (untracked `analysis/`
only; tracked tree clean). No failures, no retries; every run directory contains
exactly `manifest.json`, `report.json`, `evidencegraph-eval.db`.

Between-run variability (n=3): elapsed mean **1993.6 s**, stdev **21.319 s**, range
[1970.1, 2011.7]; verified-claims totals `[64, 64, 64]`, stdev **0.0**; calls
336/336 ok, 0 failed. Reproducibility: of 48 units (24 questions × 2 systems),
answers byte-identical across all three runs in **47/48 (0.9792)**; claim-label
sequences identical in **48/48**. The single drifting unit is the `direct-01`
**baseline** answer (2 distinct texts; no label impact — baseline emits no claims).

Disclosed deviation: repetition 1's free-text `--notes` says "22-question run
matching eval-postgate22", but its authoritative machine configuration ran all
24 fixture questions; repetitions 2–3 carry corrected notes. The historical
`eval-postgate22` run (22-question subset excluding `direct-02`/`wrong-04`,
`git.dirty=false`) is **excluded** from the repetition pool with the reason
recorded in `repetition_results.json`, not silently pooled.

## 3. What these results do and do not show

The repetitions demonstrate **repeatability of the pipeline under the tested
configuration only** (one model, one 6-chunk fixture, 24 questions, temperature 0).
They are **not** evidence of accuracy, statistical significance, or superiority
over baseline RAG. Local Ollama reports no token usage: cost/token fields are
recorded as **null/unavailable and were never estimated**. The baseline arm
produced **zero extracted claims by construction** in this pipeline, so the
verified-vs-baseline comparison here covers mechanism behavior (citations,
invalid markers, abstention strings), not claim-level correctness differences.

## 4. Stage E1 — annotation-quality analysis (single reviewer)

Source of truth: `d3_review_decisions.csv` (sha `488ecb14…`, asserted, never
written). Parsing (fail-closed rules R1–R5): 40 accepted proposals + 5
reviewer-label prefixes + 1 scope-qualified derivation, **0 failures**.

- Reviewer decisions: accept=40, revise=6. Label authority: **single-reviewer
  human labels (n=46, coverage=1.0)** — one reviewer, **not independently
  validated**; AI-proposed labels remain quarantined machine values, never
  ground truth.
- **`ann-d1-0030` (approved treatment):** included in the **primary** abstention
  analysis (n=6 → `appropriate_abstention=6`) with explicit flag
  `derived_scope_mapping` (passages-scope ruling via the mapping pre-documented
  in Stage D2 `review_summary.md`; not proof of catalog absence; the fixture's
  catalog-presence gold divergence is preserved, not reconciled). The
  **sensitivity** analysis excluding it (n=5) yields `appropriate_abstention=5`.
- **`ann-d1-0033` (approved exclusion):** excluded from label-based metrics
  (**excluded=1**) due to the unresolved label/rationale inconsistency; original
  record untouched. Claim-label denominator **40 → 39**; gate denominators
  unchanged (retracted 13 / survivors 11 / abstentions 6 — 0033 is tier 4,
  text-verified absent from those sets).
- Gate analyses (single-reviewer labels): retraction correctness **10/13** (3/13
  false refusals; 7/13 exact `new_label` match); surviving-supported endorsement
  **8/11 true / 3/11 false**; system abstained on **6/6**.
- System-vs-single-reviewer claim agreement: **16/39**, coverage 39/40 — a
  descriptive comparison, **not** inter-rater agreement (no second reviewer
  labels exist: human-vs-human agreement is not computable).
- Completing annotation does not prove the research hypothesis.

## 5. Validation & tests (exact executed results)

| Check | Command | Result |
|---|---|---|
| E1 validator | `python validate_stage_e1.py` (in E1 dir) | **14/14 PASS**, exit 0 |
| E2 validator | `python validate_repetition_analysis.py` (in E2 dir) | **14/14 PASS**, exit 0 |
| Publication validator | `python validate_publication.py` (this dir) | see `publication_validation_report.md` |
| Full suite | `python -m pytest` (repo root) | **804 passed**, exit 0 |
| Repetition audit | `final_repeat_audit.py` (temp, read-only) | 3× ALL OK (14 identity checks each) |
| DB↔report cross-checks | read-only SQLite vs `report.json` | 7/7 PASS × 3 runs |

Notes: the D3 validator was **not** re-run because it rewrites the historical
`d3_validation_report.md` (protected evidence); its prior result (26/27, sole
FAIL = expected pre-decision invariant B6) stands as recorded. Three defects in
the E2 validator were found and fixed during Stage E (JSON tuple-vs-list
comparison; bold-markdown needle; case-sensitive phrase) — documented inline in
that validator; none were bypassed.

## 6. Integrity status

- Source database `data/evidencegraph.db` sha `0b9cacbac61f99d7…` unchanged
  (live hash + each run's before/after `source_db_unchanged=True`).
- Stage E1 validator V8 (executed): D3 decisions CSV `488ecb14…`, all seven D3
  snapshots, Stage D queue, Stage C gate files, eval questions — byte-identical
  to recorded baselines. All run artifacts preserved; nothing overwritten
  (unique timestamped directories).
- Git: nothing staged; no modified tracked files; HEAD `d4ea26d`.

## 7. Publication manifest (summary; exact paths in `publication_manifest.json`)

**A — already-committed local commit that a push would publish** (unpushed
`d4ea26d`, "Add reproducible evaluation runner and dependency constraints"):
`README.md`, `app/verification/runner.py`, `constraints.txt`,
`pyproject.toml`, `tests/test_runner.py`.

**B — new code/tests** (proposed new commit):
`app/verification/experiments.py`, `tests/test_experiments.py`.

**C — research analysis & validation artifacts** (90 files, proposed new
commit): all `analysis/**` packages — Stage C (13), Stage D (12), D1 (10),
D2 (5), D3 (30), D3 batch-review (3), Stage E1 (6), Stage E2 (6) — plus this
final package (5 files: `stage_e_final_report.md`,
`build_publication_manifest.py`, `validate_publication.py`,
`publication_manifest.json`, `publication_validation_report.md`).
2.48 MB total; no file >500 KB.

**D — sanitized publication copy**: `analysis/stage-d2-20261017-002537/
stage_d2_validation_report_sanitized.md` — replaces the original (below) for
publication; header records original sha256 `06ffaaf1…` and the single change
(local absolute path on the run line → repository-relative path).

**E — excluded / local-only (retained locally; exclusion ≠ deletion)**:
`runs/**` (gitignored run outputs incl. the three repetitions and their eval
databases — local provenance); all `*.db` (corpus + run copies); `.env`
(absent; `.env.example` already tracked); `__pycache__/`, `.pytest_cache/`,
coverage artifacts (gitignored); temp scripts (outside the repo);
`analysis/stage-d2-20261017-002537/stage_d2_validation_report.md` (original —
contains a local absolute path/username; superseded for publication by the
sanitized copy, retained unchanged as historical evidence).

**Totals:** **93 newly proposed publication paths** (2 group B + 90 group C +
1 group D) **plus the 5 files already committed in `d4ea26d`** (group A) — a
push makes **98 paths public in total**: the 5 from the pre-existing commit
plus the 93 new ones.

Scans over the exact publication set: no secrets/credentials/private URLs; no
absolute local paths or usernames (post-sanitization); no databases, caches, or
oversized files. **A future push would also publish the pre-existing local
commit `d4ea26d`** — it is ahead of `origin/master` and cannot be skipped by
pushing only the new work.

## 8. Suggested commit grouping & messages

1. *(exists — nothing to stage)* `d4ea26d` — "Add reproducible evaluation runner
   and dependency constraints".
2. `git add app/verification/experiments.py tests/test_experiments.py`
   → "Add test-backed controlled-repetition experiment scaffolding (Stage E)".
3. `git add analysis/` (all paths except the excluded original D2 report, which
   is never added)
   → "Add Stage C–E research packages, review artifacts, and validators".
4. *(optional separate)* `git add analysis/stage-e-final-20261017/ analysis/stage-d2-20261017-002537/stage_d2_validation_report_sanitized.md`
   → "Add Stage E final report, publication manifest, and sanitized D2 validation report".

Exact commands for a later, separately authorized publication:

```
git add app/verification/experiments.py tests/test_experiments.py
git commit -m "Add test-backed controlled-repetition experiment scaffolding (Stage E)"
git add analysis/
git rm --cached analysis/stage-d2-20261017-002537/stage_d2_validation_report.md 2>nul
git commit -m "Add Stage C-E research packages, review artifacts, and validators"
git log --stat -2                 # review before pushing
git push origin master            # publishes new commits AND pre-existing d4ea26d
```

## 9. Remaining research work (requires separate predeclared design + authorization)

- Gate-ablation experiment matrix (authored and approved by the researcher).
- Generate-once paired-comparison design.
- Baseline-claim-extraction experiment over stored baseline answers.
- Second-reviewer annotation round (blind packet designed; no contact authorized).
- `ann-d1-0033` resolution (revise label / revise note / confirm both intentional).
- D3 closure-report file write (draft exists; file creation not yet authorized).
