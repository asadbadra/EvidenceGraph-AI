# Publication Validation Report

- Run: `validate_publication.py` · 2026-10-17T19:10:36+00:00
- Result: **8/8 checks PASS**

| # | Check | Result | Detail |
|---|-------|--------|--------|
| 1 | P1 every included path exists; hashes/blobs match manifest | PASS | bad=[] |
| 2 | P2 every excluded entry has a documented reason | PASS | entries=6 |
| 3 | P3 publication set: no local paths/usernames, secrets, caches, DBs, oversized files | PASS | leaks=[] secrets=[] oversized=[] badnames=[] scanned=93 |
| 4 | P4 original D2 report byte-identical (protected); sanitized copy has provenance header, no path/username, same 20/20 result | PASS |  |
| 5 | P5 final report quotes E1 ledger + E2 results verbatim | PASS | missing=[] |
| 6 | P6 git: HEAD d4ea26d, nothing staged, no modified tracked files | PASS | head=d4ea26d |
| 7 | P7 source database sha256 unchanged | PASS | 0b9cacbac61f99d7 |
| 8 | P8 E1 14/14, E2 14/14 recorded; all three repetition reports completed | PASS |  |
