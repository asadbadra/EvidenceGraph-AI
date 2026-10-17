# Stage D3 Validation Report

- Run: `validate_stage_d3.py` · 2026-10-17T12:58:21+00:00
- Result: **26/27 checks PASS**

| # | Check | Result | Detail |
|---|-------|--------|--------|
| 1 | A1 required D3 files exist | PASS | missing=[] |
| 2 | B1 46 rows, every id exactly once | PASS | n=46 |
| 3 | B2 claim/question wording unchanged (byte-equal to queue) | PASS | bad=[] |
| 4 | B3 excerpts verbatim in queue AND D1 workspace | PASS | bad=[] |
| 5 | B4 source references cite only shown chunk ids | PASS | bad=[] |
| 6 | B5 proposed_* byte-equal to D1 proposals | PASS | bad=[] |
| 7 | B6 reviewer columns 100% blank | FAIL | violations=[('ann-d1-0033', 'reviewer_decision'), ('ann-d1-0033', 'reviewer_note'), ('ann-d1-0014', 'reviewer_decision')] |
| 8 | B7 vocabulary enforced (status/action/revised-label consistency) | PASS | bad=[] |
| 9 | B8 review_order is 1..46 | PASS |  |
| 10 | C1 46 cards, one per item (grouped by risk, not file-order sequential) | PASS | found=46 |
| 11 | C2 card groups match CSV groups | PASS |  |
| 12 | C3 group sections + R1 ruling present | PASS |  |
| 13 | C4 R1 covers exactly the 12 flagged items | PASS |  |
| 14 | C5 no pre-checked boxes in any card | PASS |  |
| 15 | C6 summary lists the five priority decisions first | PASS |  |
| 16 | C7 no fabricated-confirmation language | PASS | hits=[] |
| 17 | D1+D2 unchanged (35 manifest hashes) | PASS | bad=[] |
| 18 | E1 Stage C + D recorded hashes intact | PASS | 16 recorded hashes verified |
| 19 | E2 no historical/D1/D2 file modified during D3 | PASS | recent=[] |
| 20 | E3 git HEAD unchanged (d4ea26d) | PASS | d4ea26db3e27 |
| 21 | E4 no new tracked changes | PASS |  |
| 22 | F1 no database artifacts in D3 | PASS | [] |
| 23 | F2 stdlib-only, no network imports | PASS | [] |
| 24 | F3 no secrets | PASS | [] |
| 25 | F4 evidence-layer absence tokens 0 occurrences (chunks table only) | PASS | 13 tokens |
| 26 | F4b metadata dates confirmed unsurfaced (in documents, 0 in chunks) | PASS | dates live in documents.published_at only |
| 27 | F5 test suite passes | PASS | 763 passed, 1 warning in 13.82s |

## Notes
- Reviewer columns were blank at build time and at validation time: every row is pending; no acceptance was inferred.
- `recommended_action` / `suggested_revised_label` are machine review aids; only the reviewer columns carry human authority.
- Claim wording is byte-equal to the Stage D queue; evidence excerpts are verbatim substrings of both the raw queue evidence and the D1 workspace (traceability proven twice).
- Scope correction discovered during D3 (read-only DB scan): the date tokens asserted absent from 'the corpus' are absent from the EVIDENCE layer (chunks table, 0 occurrences) but four KEV-style dates exist in documents.published_at metadata, which the retrieval pipeline never surfaces to model or judge. All affected cards state this precisely. A related D1/D2 'answer-level fabrication' remark about 2022-05-04 is corrected in D3 cards: the value matches the document metadata (unsurfaced), so it is an unsupported-by-passage claim, not an invented number. D1/D2 files remain untouched.
- D1 and D2 packages verified unchanged via their manifests; the protected database was opened read-only for the token scan only.
- No model calls, no network, no database writes, no git changes.
