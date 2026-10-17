# Stage E2 — Controlled-Repetition Report

- Built by `build_repetition_analysis.py` · 2026-10-17T17:38:30+00:00
- Experiment: 3 repetitions × 24 questions,
  model `llama3.2:latest`, judge `llm`,
  temperature 0.0, max_tokens 700,
  commit `d4ea26db3e27b9bd002c27d157ac5c773be3b800`, prompts
  `baseline-v1`/`judge-v1`
- Scaffolding under test: `app/verification.experiments` (offline unit tests in
  `tests/test_experiments.py`, part of the full pytest suite)

## 1. Comparability (precondition, checked before any aggregation)

**PASS** — all comparability fields identical across repetitions

## 2. Per-repetition record

| label | run dir | status | elapsed_s | load error |
|-------|---------|--------|-----------|------------|
| stage-e-repeat1 | stage-e-repeat1-20261017-155403 | completed | 1999.0 | — |
| stage-e-repeat2 | stage-e-repeat2-20261017-163026 | completed | 2011.7 | — |
| stage-e-repeat3 | stage-e-repeat3-20261017-170438 | completed | 1970.1 | — |

Between-run aggregate: all_completed=True; elapsed n=3, mean
1993.6s, stdev 21.319, min 1970.1, max 2011.7;
calls=336 (ok=336, failed=0), by purpose {'baseline_generation': 72, 'judge': 192, 'verified_generation': 72}.
Verified-claims per run: [64, 64, 64] (mean
64, stdev 0.0, range
[64, 64]).
Token usage: totals_available=False
(3 repetition(s) without usage) — local Ollama
reports no token counts; totals stay null rather than estimated.

## 2b. Within-run observations (per-system counts per repetition)

| run | v claims | v supported | v contradicted | v insufficient | v unverifiable | b claims | b citations |
|-----|----------|-------------|----------------|----------------|-----------------|----------|-------------|
| stage-e-repeat1 | 64 | 14 | 0 | 31 | 19 | 0 | 22 |
| stage-e-repeat2 | 64 | 14 | 0 | 31 | 19 | 0 | 22 |
| stage-e-repeat3 | 64 | 14 | 0 | 31 | 19 | 0 | 22 |

Within-run counts describe what each run's verifier SAID (mechanism metrics),
not whether it was right; between-run variability above describes only these
repetitions of one model on one fixture.

## 3. Reproducibility (descriptive)

- Units (question × system): 48
- Answers byte-identical across ALL 3 repetitions:
  47/48
  (answer_stability=0.9792)
- Claim-label sequences identical across all repetitions:
  48/48
- Differing units:

| question | system | reason | distinct answers | distinct label sequences |
|----------|--------|--------|------------------|--------------------------|
| direct-01 | baseline |  | 2 | 1 |

Interpretation: temperature 0 does not make the local model bit-deterministic;
these counts describe THIS fixture and model only and are a reproducibility
smoke signal, not an accuracy or quality figure.

## 4. Safety invariants (verified per run)

- Source corpus `data/evidencegraph.db` unchanged in every run
  (sha `0b9cacbac61f99d7…` before == after, `source_db_unchanged=True`).
- `verif_claims.gold_label IS NULL` for every row in every run database
  (a machine run never writes labels).
- Runs live under `runs/` (git-ignored): no run output is published by the
  planned repository update; run provenance stays local.

## 5. Exclusions (recorded, not silently pooled)

- **eval-postgate22-20261016-141416** — pre-Stage-E reference run: git.dirty=false vs true (untracked analysis/ present during Stage E); excluded from strict comparability, not silently pooled
- **eval-20261017-155111** — mock-provider wiring smoke (1 question), not a repetition
- **eval-20261017-155226** — real-path smoke (1 question), not a repetition

## 5b. Known discrepancies (recorded, not silently corrected)

- Repeat 1's free-text --notes says '22-question run matching eval-postgate22', but its machine-readable configuration (authoritative) ran all 24 fixture questions; repeats 2-3 carry corrected notes. Comparability is decided on machine fields only.
- The historical eval-postgate22 ran a 22-question subset (excluded direct-02 and wrong-04) with git.dirty=false; it is excluded from strict comparability for that reason (and recorded here), not silently pooled.

## 6. Limitations

- One model, one fixture corpus (6 chunks), 24 questions,
  clustered claims: no significance testing, no superiority claim.
- `gold_label` remains NULL: these repetitions say nothing about correctness;
  judge-vs-single-reviewer comparisons live only in the Stage E1 annotation
  report (single-reviewer human labels, not independently validated).
- Completing repetitions does not prove the research hypothesis.
