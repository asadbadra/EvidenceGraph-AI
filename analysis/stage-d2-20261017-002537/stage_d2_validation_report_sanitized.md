# SANITIZED PUBLICATION COPY — Stage D2 Validation Report

> **Provenance.** This file is a sanitized copy of the original historical
> artifact `stage_d2_validation_report.md`, which remains byte-for-byte
> unchanged in this directory (original sha256
> `06ffaaf13b1cfecc165807473a8561d70837328175870d5da31ea06e2d8a2cfa`).
> **Exactly one change was made, on the line marked `[SANITIZED]` below**: the
> validator's local absolute invocation path on the original's "Run" line — an
> absolute Windows path embedding the local username and OneDrive folder — was
> replaced by the repository-relative path. **No check name, result, count,
> detail, or timestamp was altered.** Reason: personal local paths and
> usernames must not be published; the original file is excluded from the
> proposed GitHub publication set and retained locally as evidence. This copy
> — not the original — is the artifact proposed for publication.

# Stage D2 Validation Report

- Run: `[SANITIZED] analysis/stage-d2-20261017-002537/validate_stage_d2.py` · 2026-10-16T19:30:50+00:00
- Result: **20/20 checks PASS**

| # | Check | Result | Detail |
|---|-------|--------|--------|
| 1 | A1 required D2 files exist | PASS | missing=[] |
| 2 | B1 46 rows, queue order | PASS | n=46 |
| 3 | B2 reviewer columns 100% empty (nothing pre-accepted) | PASS | violations=[] |
| 4 | B3 proposed_* byte-equal to D1 proposals | PASS | mismatched=[] |
| 5 | B4 recommendation vocabulary (45 accept / 1 needs_adjudication) | PASS | counts accept=45 adj=1 |
| 6 | B5 P1 items marked | PASS | P1={14,30,33} |
| 7 | C1 46 numbered items, sequential | PASS | found=46 |
| 8 | C2 four tier groups present | PASS |  |
| 9 | C3 machine-draft + not-confirmed disclaimers | PASS |  |
| 10 | C4 no fabricated confirmation language | PASS | hits=[] |
| 11 | C5 priorities, ledger, unresolved sections | PASS |  |
| 12 | D1 package unchanged (21 manifest hashes) | PASS | bad=[] |
| 13 | E1 Stage C + D recorded hashes intact | PASS | 16 recorded hashes verified |
| 14 | E2 no historical file modified during D2 | PASS | recent=[] |
| 15 | E3 git HEAD unchanged (d4ea26d) | PASS | d4ea26db3e27 |
| 16 | E4 no new tracked changes | PASS | only untracked allowed |
| 17 | F1 no database artifacts in D2 | PASS | [] |
| 18 | F2 stdlib-only, no network imports | PASS | [] |
| 19 | F3 no secrets | PASS | [] |
| 20 | F4 test suite passes | PASS | 763 passed, 1 warning in 14.71s |

## Notes
- `confirmation_decisions.csv` reviewer columns were verified empty at build time and at validation time: every row is pending; no acceptance was inferred.
- `draft_recommendation` is a machine column; the only authoritative reviewer inputs are the five reviewer columns.
- D1 files verified unchanged via `stage_d1_manifest.json` (12 inputs + 9 outputs).
- No model calls, no network, no database writes, no git state changes.
