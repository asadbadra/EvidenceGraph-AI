# Stage E1 Validation Report

- Run: `validate_stage_e1.py` · 2026-10-17T19:10:27+00:00
- Result: **14/14 checks PASS**

| # | Check | Result | Detail |
|---|-------|--------|--------|
| 1 | V1 required E1 files exist | PASS | missing=[] |
| 2 | V2 derived table: 46 rows, unique ids == source ids | PASS |  |
| 3 | V3 status counts: 40 accepted_proposal / 5 parsed_prefix / 1 derived_scope_mapping / 0 failed | PASS | {'parsed_prefix': 5, 'derived_scope_mapping': 1, 'accepted_proposal': 40} |
| 4 | V4 every derived row links to live CSV hash + verbatim note hash | PASS | bad=[] |
| 5 | V5 exactly ann-d1-0033 excluded, with documented reason; all others included | PASS | excluded=['ann-d1-0033'] |
| 6 | V6 labels independently re-derived from live CSV match the derived table | PASS | mismatches=[] |
| 7 | V7a ledger block present with 9 lines | PASS | found=9 |
| 8 | V7b all 9 ledger lines match independent recomputation | PASS | bad=[]; hits=16/39, retr=10c/3f/7x, surv=8t/3f |
| 9 | V8 all pre-existing inputs + 7 snapshots byte-identical to baselines | PASS | bad=[] |
| 10 | V9 D3 decision note: sections 1-12 + fork decisions structurally intact | PASS | sha256(observed)=476cb6871cc413d6 sections=True markers=True |
| 11 | V10 git HEAD d4ea26d; no staged or tracked changes | PASS | head=d4ea26d |
| 12 | V11 mandated honesty phrases present; banned victory phrases absent | PASS | missing=[] banned=[] |
| 13 | V12 E1 scripts: stdlib-only, no network imports, no secrets | PASS | bad=[] |
| 14 | V13 manifest: output hashes match; input hashes match baselines | PASS |  |
