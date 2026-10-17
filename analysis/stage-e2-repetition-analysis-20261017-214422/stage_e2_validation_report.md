# Stage E2 Validation Report

- Run: `validate_repetition_analysis.py` · 2026-10-17T19:10:27+00:00
- Result: **14/14 checks PASS**

| # | Check | Result | Detail |
|---|-------|--------|--------|
| 1 | V1 required E2 files exist | PASS | missing=[] |
| 2 | V2 manifest input/output hashes match live files | PASS | in=[] out=[] |
| 3 | V2b manifest declares no label/db writes and no model calls | PASS |  |
| 4 | V3 exactly one run dir per expected label | PASS | stage-e-repeat1-20261017-155403, stage-e-repeat2-20261017-163026, stage-e-repeat3-20261017-170438 |
| 5 | V4a every repetition has readable manifest+report | PASS | fail=[] |
| 6 | V4 repetitions comparable (fresh check) | PASS |  |
| 7 | V5 source DB unchanged in every run; gold_label NULL everywhere | PASS | bad=[] |
| 8 | V6 eval_questions.json hash unchanged | PASS |  |
| 9 | V7a stability recomputed == results.json | PASS | answers_identical=47/48 |
| 10 | V7b aggregate recomputed == results.json | PASS | all_completed=True calls=336 |
| 11 | V8 report quotes recomputed numbers verbatim | PASS | missing=[] |
| 12 | V9 git HEAD d4ea26d; no staged or tracked changes | PASS | head=d4ea26d |
| 13 | V10 mandated caveats present; banned victory phrases absent | PASS | missing=[] banned=[] |
| 14 | V11 scripts: no network imports, no secrets | PASS | bad=[] |
