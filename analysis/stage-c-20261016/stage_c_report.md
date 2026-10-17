# Stage C — Comparative Analysis Report
## Historical pre-gate pilot vs Stage B post-gate run

**Date:** 2026-10-16
**Status:** Complete (analysis only; no model calls, no source artifacts modified)
**Script:** `analysis/stage-c-20261016/analyze_stage_c.py` (read-only against both run databases; all counts in this report are re-derived by that script from stored records)

---

## 1. Executive summary

This report compares two evaluation runs of EvidenceGraph-AI over the **same 22 cybersecurity questions**, the **same corpus** (5 documents / 6 chunks), and the **same model configuration** (local Ollama `llama3.2:latest`, temperature 0.0):

| | Historical pre-gate pilot | Stage B post-gate run |
|---|---|---|
| Run ID | `eval-pilot22-20261014-181354` | `eval-postgate22-20261016-141416` |
| Code provenance | one-off script; **no git commit recorded** in its report | commit `d4ea26d` (clean tree), manifest recorded |
| Grounding gate | **absent** (pre-dates commit `b370fa4`) | **present** (retract-only, bar 0.50) |

**Key findings (all recomputed from stored database records):**

1. **Verdict delta:** `supported` claims fell from **24 → 11**; `insufficient_evidence` rose from **16 → 29**. Exactly **13 claims transitioned `supported → insufficient_evidence`**; the other **43 claim verdicts are unchanged**; `contradicted` is 0 in both runs.
2. **The delta is attributable to the grounding gate, not to model or prompt drift:** all 44 answer texts and all 56 claim texts are **byte-identical** across the two runs; `build_judge_prompt` is **byte-identical** between the pre-gate commit (`84f3a25`) and the Stage B commit (`d4ea26d`); the judge (temperature 0) reproduced all 56 historical verdicts before the gate applied (observed once; not a determinism guarantee).
3. **All 13 retractions fired by the documented gate rule** (`grounding_ratio < 0.50`, ratios 0.00–0.47), recorded as anomalies; the 14th anomaly is a **pre-existing** "supported requires evidence" rule that also fired in the historical run.
4. **Whether the 13 retractions are *correct* cannot be established from stored data.** The gate refuses endorsements the cited text does not ground; it can also refuse genuine support expressed as low-overlap paraphrase (documented known cost). No human labels exist for any of the 56 claims. **No accuracy or superiority claim is made.**
5. **Citation precision is not computable:** per-citation support labels are null in both reports and absent from the schema. Only marker counts are reported (17 baseline / 18 verified, 0 invalid, identical across runs).
6. **Token usage for the post-gate run is unavailable** (the tracked runner discards the provider usage block); it is reported as null and **not inferred** from the historical run.

**Answer-level behavior is unchanged by the gate:** baseline and verified arms diverge on 7/22 questions in *both* runs (the gate affects claim verdicts, not generation). The six zero-claim abstentions are identical across runs.

---

## 2. Data provenance and integrity checks

### 2.1 Artifacts analyzed (all read-only)

| Artifact | Path | SHA-256 (first 16) |
|---|---|---|
| Historical run DB | `runs/eval-pilot22-20261014-181354/evidencegraph-eval.db` | `71e4a78703c2ae38…` |
| Historical report | `runs/eval-pilot22-20261014-181354/report.json` | `5247890849614a95…` |
| Post-gate run DB | `runs/eval-postgate22-20261016-141416/evidencegraph-eval.db` | `ed3c4f0d2ee713dd…` |
| Post-gate manifest | `runs/eval-postgate22-20261016-141416/manifest.json` | `c080638f72953297…` |
| Post-gate report | `runs/eval-postgate22-20261016-141416/report.json` | `e8380401f2c15231…` |
| Question set | `data/sample/eval_questions.json` | `500ed32d55466833…` |
| Protected source DB | `data/evidencegraph.db` | `0b9cacbac61f99d7…` |

Full before/after hashes: `integrity_hashes_before.json`, `integrity_hashes_after.json`.

### 2.2 Integrity result

**All 10 checked source artifacts are byte-identical before and after the analysis** (10/10 unchanged). `git status --porcelain` shows only the new untracked `analysis/` directory; **no tracked file was modified or added**. Both run databases were opened with SQLite `mode=ro` URI connections. No model evaluations were run.

### 2.3 Paired question IDs (verified three ways)

- Manifest `configuration.question_ids` (22 IDs) == question IDs derived from stored `eval_results` (22 verified-arm rows) == historical run's 22 IDs. **All three sets identical.**
- The 2 excluded IDs from the 24-question set are exactly `direct-02` and `wrong-04` (covered by the earlier mini pilot), matching the pre-registered Stage B scope.

### 2.4 Report totals vs stored records (both runs)

Independently recomputed from `verif_claims` joined to `eval_results`:

| Tally (verified arm) | supported | contradicted | insufficient | unverifiable | total |
|---|---|---|---|---|---|
| Historical — from DB | 24 | 0 | 16 | 16 | 56 |
| Historical — from report.json | 24 | 0 | 16 | 16 | 56 | ✅ match |
| Post-gate — from DB | 11 | 0 | 29 | 16 | 56 |
| Post-gate — from report.json | 11 | 0 | 29 | 16 | 56 | ✅ match |

### 2.5 Code-version and gate-behavior differences (verified from git)

- Commit `b370fa4` ("Improve EvidenceGraph grounding gate and research UI") **introduced `_SUPPORTED_GROUNDING_BAR = 0.5` and `_apply_grounding_gate`** into `app/verification/judge.py` (+130/−5 lines); `app/llm/prompts.py` is unchanged in that commit.
- `app/llm/prompts.py` is **byte-identical** between `84f3a25` (pre-gate parent) and `d4ea26d` (Stage B commit).
- The `build_judge_prompt` function is **byte-identical** between `84f3a25` and `d4ea26d` (AST source-segment comparison); `JUDGE_PROMPT_VERSION = "judge-v1"` in both.
- **Gate semantics (from `app/verification/judge.py`):** applies only to `supported` verdicts; computes the fraction of the claim's distinct content tokens covered by the cited passages; if below 0.50, **retracts** the endorsement to `insufficient_evidence` and records an anomaly. It cannot add, swap, or invent a verdict. Claims with no content tokens skip the gate.
- **Gate side-effect on stored evidence IDs (important):** on retraction the gate rebuilds the verdict as an abstention, which by design carries **no evidence IDs** — so post-gate `evidence_ids_json` is empty for all 13 retracted claims. The originally-cited IDs are recoverable from the anomaly-note text and the historical DB; both sources **agree 13/13** (see §5).

### 2.6 Missing / null / unreliable fields (documented, not imputed)

| Field | Historical run | Post-gate run |
|---|---|---|
| Git commit in report/manifest | **absent** (one-off script, provenance unknown) | `d4ea26d`, clean tree ✅ |
| Token usage | recorded (provider-reported) | **null** — runner's client discards usage; recorded as unavailable, never zero |
| Cost | null (local Ollama; no pricing) | null (same) |
| Per-call / per-question latency | not stored | not stored |
| Per-citation support labels (`verified_citations`) | **null** | **null** |
| Gold labels on claims (`verif_claims.gold_label`) | 0 non-null | 0 non-null |
| Prompt/gate/dataset versions in historical report | prompt version only; no gate version (gate absent) | full (manifest) |

The historical run's missing git provenance is the single largest comparability caveat: we verify prompt/behavioral equivalence *post hoc* (§2.5), but cannot prove the exact historical working-tree state.

---

## 3. Methods and definitions

**Design.** Paired, question-level comparison of two runs over the same 22 questions (paired units), with claims as clustered observations *within* questions (56 claims over 16 claim-bearing questions; max 10 claims in one question, `opinion-01`). This is **not an identical replication**: the post-gate run differs from the historical pilot by the tracked runner and the grounding gate. It is analyzed as a **pre-gate vs post-gate comparison**.

**No model calls.** All figures derive from stored records, deterministic offline replay of the project's own extraction/BM25 code, and git history inspection.

**Metric definitions used in this report**

| Metric | Definition | Source |
|---|---|---|
| Verdict tally | Count of `verif_claims.label` per system arm | run DBs |
| Verdict transition | Per (question, claim_index) pair: historical label vs post-gate label; requires claim-key sets equal across runs (asserted) | `claim_transition_matrix.csv` |
| Grounding ratio | Fraction of the claim's distinct content tokens present in ≥1 cited passage (project definition, `judge.py::_grounding_ratio`); bar = 0.50 | judge code + anomaly notes |
| Abstention | Stored answer equals the verbatim string "Insufficient evidence in the retrieved passages." | run DBs |
| Zero-claim question | Verified-arm `claims_total = 0` | run DBs |
| Citation marker | `[n]`-style markers counted by the harness at generation time | `eval_results.citation_count` |
| Invalid marker | Marker referencing a non-retrieved chunk id | `eval_results.invalid_marker_count` |
| Claim carrying citation markers | Claim text containing a citation-pattern match (descriptive only; *not* support) | deterministic regex over stored claim text |
| Retrieval reconstruction | Deterministic BM25 replay: identical `BM25Index`, identical chunk order (`chunk.id`), identical selection rule (`-score, index`, top-4, drop ≤0), query = raw question text (as `pipeline.py` does) | offline replay, validated 22/22 against stored `retrieved_count` |
| Answer content in corpus | Presence of the gold claim's answer-bearing value tokens (numbers, KB ids, versions) in the corpus text | lexical probe over the 6 chunks |

**Explicitly not computed:** citation precision / support rate (no labels exist); accuracy (no human gold labels exist); significance tests (single run, n=22, clustered claims, no human labels — see §8).

---

## 4. Question-level and claim-level comparisons

### 4.1 Claim-level transition matrix (56 claims; claim-key sets asserted equal across runs)

| Historical label → Post-gate label | Count | Changed? |
|---|---|---|
| supported → insufficient_evidence | **13** | ✅ changed |
| supported → supported | 11 | — |
| insufficient_evidence → insufficient_evidence | 16 | — |
| unverifiable → unverifiable | 16 | — |
| **Total** | **56** | 13 changed / 43 unchanged |

All 56 claim texts are **byte-identical** across runs (`claim_text_identical = True` for every row).

### 4.2 The 13 retracted claims (`retracted_claims_13.csv`)

All 13 fired the documented gate rule; grounding ratios 0.00–0.47, all < 0.50. Originally-cited evidence IDs recovered from anomaly notes and cross-validated against the historical DB (**13/13 agreement**); chunk texts are included in the CSV (`evidence_text_by_id`).

| Question | idx | Grounding | Cited evidence (hist) | Claim (truncated) |
|---|---|---|---|---|
| direct-03 | 0 | 0.11 | [1, 2, 5] | "The date CVE-2021-44228 was added to the catalog is December 10, 2021…" |
| direct-04 | 0 | 0.25 | [2] | "…the weakness class associated with CVE-2014-0160 is CWE-125." |
| direct-04 | 1 | 0.45 | [1, 2] | "…OpenSSL Information Disclosure Vulnerability has a CWE number of…" |
| hop-03 | 0 | 0.42 | [1, 6] | "…cataloged vulnerabilities flagged as known ransomware campaign us…" |
| opinion-01 | 1 | 0.00 | [1, 2, 3] | "However, we can compare the severity of Log4Shell with the other…" |
| opinion-01 | 2 | 0.47 | [1, 2, 3, 4, 5] | "Log4Shell is not explicitly mentioned in the passages, but CVE-2021-44228…" |
| opinion-01 | 3 | 0.44 | [6, 1, 4, 3, 2] | "According to the passage, this vulnerability allows for remote code execution…" |
| opinion-01 | 9 | 0.40 | [1, 3, 4] | "However, based on the available information, Log4Shell … appears to be a highly severe…" |
| opinion-03 | 1 | 0.18 | [4, 3] | "This vulnerability is not explicitly stated as being 'overhyped,' but…" |
| opinion-03 | 3 | 0.41 | [3, 4, 2, 1, 6, 5] | "However, it is clear that other vulnerabilities, such as … MOVEit Transfer SQL…" |
| opinion-04 | 3 | 0.38 | [2, 4] | "In contrast, the OpenSSL Information Disclosure Vulnerability … is mentioned only once…" |
| wrong-01 | 2 | 0.00 | [4, 3] | "Therefore, the answer to the research question is: False." |
| wrong-02 | 4 | 0.00 | [3, 4] | "Therefore, the answer to the research question is: False." |

**Observation:** retractions concentrate in **opinion-*** questions (7 of 13 across opinion-01/03/04) and in abstract/meta-answer claims ("Therefore, the answer… is: False", 2× at ratio 0.00) — consistent with the gate catching claims whose wording shares little vocabulary with the passages. *Hypothesis (unverified):* opinion/comparative questions induce comparative claims that cite passages topically without being textually grounded. Human review (Stage D) is required to judge correctness.

### 4.3 The 11 surviving `supported` claims (`supported_claims_11.csv`, for later human review)

| Question | idx | Evidence IDs | Claim (truncated) |
|---|---|---|---|
| absent-03 | 1 | [5, 1] | "The passages only mention the Fortinet FortiOS … but it d…" |
| hop-01 | 0 | [6, 1, 3, 4, 2] | "…the cataloged vulnerability added on 2021-11-03 is the Microsoft Exchange Serv…" |
| hop-02 | 0 | [1, 6] | "…cataloged products affected by remote code execution vulnerabilities are: 1." |
| hop-02 | 1 | [1, 4, 3] | "Apache Log4j2 (Apache) - CVE-2021-44228 2." |
| opinion-01 | 4 | [1, 2, 3, 4, 5] | "In comparison, CVE-2014-0160 refers to the OpenSSL Information Disclosure…" |
| opinion-01 | 7 | [3, 4, 5, 1, 6] | "However, it is noted that this vulnerability could allow an unauthenticated…" |
| opinion-04 | 2 | [3, 4] | "The first passage mentions that the vulnerability could allow an unauthenticated…" |
| plausible-01 | 1 | [1, 2, 3, 4, 5] | "The passage for CVE-2018-13379 does not mention the Conti ransomware group…" |
| plausible-01 | 2 | [1, 3, 4, 6, 5] | "The passage for … MOVEit Transfer SQL Injection Vulnerability also mentions…" |
| plausible-03 | 1 | [3, 2, 4, 5, 1, 6] | "The products mentioned are: Progress MOVEit Transfer, OpenSSL, FortiOS…" |
| wrong-02 | 3 | [1, 2, 3, 4, 5] | "In contrast, the passage for CVE-2021-44228 describes a vulnerability in Apache…" |

These 11 pass the gate (ratio ≥ 0.50); that is a **lexical-grounding statement, not a correctness statement**. They are Stage D review targets.

### 4.4 Question-level table (`question_level_comparison.csv`, 22 rows)

Per-question columns: category, baseline/verified answer status (abstention vs answered), cross-run answer identity, retrieved counts (hist/new), claim and verdict counts (hist/new), verdict changes, citation and invalid-marker counts, anomaly counts, latency marker. Highlights:

- **Cross-run answer identity: 22/22 baseline and 22/22 verified** (44/44 byte-identical) — generation did not change between runs.
- **Retrieval parity: 22/22** identical `retrieved_count` between runs (reconstruction also matches stored counts 22/22).
- **Baseline arm abstains on 7 questions; verified arm on 6** — the verified arm gave a substantive answer to `plausible-01` (with 2 surviving supported claims) where the baseline abstained. This is a *generation-flow* difference (verified pipeline's prompt/constraints), present identically in the historical run; the gate does not affect it.
- **Baseline vs verified answers diverge on 7/22 questions** in both runs (direct-01, plausible-01, wrong-01, wrong-03, opinion-01, opinion-03, opinion-04) — unchanged by the gate.
- **Per-question latency: not stored** by either run (only run-level elapsed time exists).

### 4.5 Anomaly analysis (14 post-gate; `anomaly_analysis.csv`)

| Class | Count | Questions |
|---|---|---|
| Grounding-gate retraction | **13** | opinion-01 (4), direct-04 (2), opinion-03 (2), direct-03, hop-03, opinion-04, wrong-01, wrong-02 (1 each) |
| Pre-existing "supported requires evidence, none remained; downgraded to unverifiable" | **1** | wrong-02 idx0 |

- **The 13 gate retractions have no anomalies in the historical run** (0/13) — they are new by construction (the gate did not exist).
- **The 14th anomaly is not new:** the identical note string appears in the historical run for the same claim (`wrong-02` idx0), and the historical report records `with_anomalies: 1`. The gate is retract-only and did not interact with this rule (the claim is `unverifiable` in both runs).

### 4.6 The six zero-claim abstentions (`abstention_analysis.json`)

All six questions are identical across runs (answer text byte-identical; 0 claims in both runs). Deterministic replay of `extract_claims` on the **stored** answer text (offline, no model calls) reproduces **0 claims for each**, with every fragment skipped as "abstention statement" — extraction behavior is fully explained by the stored text. Retrieval was reconstructed with the project's own BM25 code (validated 22/22 against stored counts; per-question retrieved-chunk lists are *not* persisted by the schema — a documented limitation, addressed by the validated reconstruction).

| Question | Category | Gold claim (label) | Answer-bearing value in corpus? | Provisional review category |
|---|---|---|---|---|
| absent-01 | not_in_corpus | "The CVSS base score of CVE-2021-44228 is 10.0." (insufficient_evidence) | No ("10.0" absent) | appropriate abstention, likely |
| absent-02 | not_in_corpus | "The MOVEit Transfer exploit compromised 2500 endpoints." (insufficient_evidence) | No ("2500" absent) | appropriate abstention, likely |
| absent-04 | not_in_corpus | "Microsoft published KB5004236 for CVE-2021-34473." (insufficient_evidence) | No ("KB5004236" absent) | appropriate abstention, likely |
| opinion-02 | non_factual | "Organizations should prioritize MOVEit remediation over Log4j remediation." (unverifiable) | Normative "should"; no prioritization guidance in corpus | appropriate abstention, likely (opinion question) |
| plausible-02 | plausible_but_absent | "OpenSSL released a 1.0.2g hotfix for CVE-2014-0160." (insufficient_evidence) | No (version "1.0.2g" absent; corpus covers Heartbleed generally) | appropriate abstention, likely |
| plausible-04 | plausible_but_absent | "CVE-2021-45046 is present in the catalog." (**contradicted** — by absence) | CVE absent from the 6-chunk catalog | **Review priority:** model abstained ("insufficient evidence") rather than asserting absence; a closed-world catalog assumption could support a `contradicted` verdict instead |

**Important:** these provisional categories are analyst hypotheses from a deterministic lexical probe plus the question set's declared categories — **not gold labels**. Note also that topical overlap (e.g. the CVE id itself appearing in the corpus) was explicitly separated from answer-content presence; a naive overlap signal would have mislabeled five of the six. Human answerability review remains required (Stage D). The gold labels above are the committed fixture's claim labels (designer intent), not independent human annotation of model output.

**Notable design observation:** abstentions receive zero claim-level coverage by design — the verdict tally of 56 excludes them entirely. Any claim-level "support rate" metric is conditional on claims existing; abstention quality must be evaluated separately (§8, Stage D plan).

---

## 5. Interpretation of the evidence

**Observations (facts from stored data):**
- 13 of 24 previously-`supported` endorsements (54%) were retracted by the deterministic gate; 11 survived; nothing else changed (claims, answers, retrieval, citations byte- or count-identical).
- All retractions followed the single documented rule (ratio < 0.50) and are individually auditable (ratio, cited IDs, evidence text, anomaly note).
- The judge reproduced 56/56 historical verdicts at temperature 0 before gating (single observation).

**Calculations (derived, reproducible):**
- Retraction rate among pre-gate supported claims: 13/24 = 54%.
- Verdict-delta decomposition: supported −13, insufficient +13, contradicted 0, unverifiable 0 — a pure endorsement→abstention shift.
- Question-level concentration: 8/16 claim-bearing questions had ≥1 retraction; opinion-* questions account for 7/13 retractions while contributing 19/56 claims.

**Hypotheses (require human labels to test):**
- H1: A meaningful share of the 13 retractions are *correct* refusals (the passages genuinely did not ground those endorsements — e.g. ratio-0.00 meta-claims like "the answer… is: False").
- H2: Some retractions may be *false refusals* of genuine support expressed as low-overlap paraphrase (the gate's documented accepted cost).
- H3: Comparative/opinion questions structurally induce low-grounding claims; the gate's benefit may concentrate there.

**Conclusions (bounded by available evidence):**
- The grounding gate **changes system behavior as designed**: it retracts ungrounded endorsements, is retract-only, and is fully auditable per claim. Every retraction is recoverable with evidence (§4.2).
- **We do not yet know whether the post-gate system is more *accurate*.** Verdict changes are not accuracy improvements without human-verified labels; `supported` after the gate means "passes a lexical-grounding bar", not "true". No superiority claim is made — this remains the research *hypothesis* for Stage E.
- The comparison is pre-gate vs post-gate (not identical replication); prompt and generation equivalence were verified post hoc but the historical run lacks recorded git provenance.
- The RQ ("does verification improve factual grounding vs standard RAG?") is only partially addressable here: the **baseline arm performs no claim verification by design** (0 claims by construction), so claim-level grounding of baseline answers cannot be measured from these runs. The current evidence supports only the narrower claim that the *gated verified arm* refuses more endorsements than the *ungated verified arm*. A baseline-claim comparison would require running the (offline, deterministic) extraction over baseline answers — proposed for Stage E, not done here.

**Statistical restraint:** no significance test is reported. This is a single run over 22 paired questions with 56 claims clustered within 16 questions (max 10 in one question); claims within a question are not independent, verdicts come from the same judge model that (per §4.2) has systematic low-overlap sensitivity, and no human labels exist to define "correct". A paired sign test or bootstrap on these data would imply a population and an error definition we do not have. Effect sizes and raw counts are reported instead, with the paired structure preserved in the CSVs for later analysis once labels exist.

---

## 6. Citation and cost-measurement limitations

**Citation comparison (`citation_comparison.json`) — only stored-data-supported metrics:**

| Metric | Historical | Post-gate |
|---|---|---|
| Baseline citation markers (total) | 17 | 17 |
| Verified citation markers (total) | 18 | 18 |
| Invalid markers (both arms) | 0 | 0 |
| Invalid marker rate | 0.0 | 0.0 |
| Claims with judge-cited evidence IDs | 24 | 11 |
| Per-citation support labels (`verified_citations`) | **null** | **null** |

- **Citation precision / support rate: NOT COMPUTABLE.** No stored field records whether a citation marker supports its claim (null in both reports; absent from schema). Marker counts describe *quantity and syntactic validity only*; they must not be read as support rates. This limitation is recorded rather than an invented proxy metric.
- The `claims with judge-cited evidence IDs` drop (24 → 11) exactly mirrors the supported-count drop and is a *storage consequence of the gate's retraction semantics* (§2.5), not an independent citation-quality signal.

**Resource comparison (`resource_comparison.json`):**

| Metric | Historical | Post-gate |
|---|---|---|
| Calls (total / failed) | 100 / 0 | 100 / 0 |
| Call purposes | 22 baseline + 78 verified (gen+judge combined) | 22 baseline gen + 22 verified gen + 56 judge |
| Elapsed | 1,660.0 s | 2,097.8 s (+26%; cause unexplained — machine load, no per-call latency stored) |
| Tokens (in/out/total) | 122,924 / 8,683 / 131,607 (provider-reported) | **unavailable** (runner client discards usage; root-caused in Stage B) |
| Cost | null (local Ollama; no pricing) | null (same) |

Post-gate token counts are recorded as **unavailable, never zero, never inferred** from the historical run. The token-usage fix (switching the runner to the usage-aware client) is a separately-authorized future change; this run's artifacts are not altered.

---

## 7. Threats to validity

1. **No human gold labels** (internal validity): all 56 claim verdicts and all abstention judgments are model-produced; the gate's correctness is unmeasured. This is the dominant threat — addressed by Stage D.
2. **Non-identical comparison**: the post-gate run uses the tracked runner (commit `d4ea26d`); the historical run's code state is unrecorded. Prompt equivalence was verified post hoc (byte-identical `build_judge_prompt`, identical `prompts.py`), but full equivalence cannot be proven.
3. **Judge = same model family as generator** (llama3.2 self-judging): potential shared blind spots; the gate mitigates *ungrounded* endorsements but cannot fix shared comprehension errors.
4. **Temperature-0 non-determinism**: one reproduction observed (56/56); not a guarantee across runs, drivers, or hardware.
5. **Gate construct validity**: the grounding ratio measures *content-vocabulary overlap*, not entailment; it is paraphrase-blind by design (documented accepted cost). "Passes the gate" ≠ "supported".
6. **Small, clustered sample**: 22 questions, 56 claims in 16 questions, single corpus (5 docs/6 chunks), single model, single domain (KEV-style advisories). No significance claims (§5).
7. **Selection**: 22 of 24 questions (2 excluded by prior mini-pilot coverage); the corpus is small and synthetic-ish, so absolute numbers will not generalize.
8. **Unmeasured resources**: token usage unavailable post-gate; latency unrecorded per call; the +26% runtime difference is unexplained.
9. **AI-draft annotations are not ground truth**: the existing `human_claim_review56.md` is self-declared AI-assisted; it is excluded from all correctness reasoning here (and must not be promoted to gold; provenance of the 8 labels in the mini-pilot review file is an open Stage D question).

---

## 8. Prioritized plan for Stage D human verification

1. **Resolve annotation provenance first (blocker).** Determine who filled the 8 labels in `runs/eval-mini-20261014-165641/human_claim_review.md` (no provenance marker). Nothing existing may be treated as human truth until this is settled.
2. **Design the annotation schema** separating `proposed_ai_label` (pre-filled, clearly marked AI-draft, never overwritten by annotators) from `human_label`, plus annotator id, timestamp, per-claim rationale field, and an "insufficient context / cannot judge" option. Double-label at least a substantial subset; report agreement only on independent annotations.
3. **Review queues, in priority order** (all items exported with full context in the Stage C CSVs):
   a. **The 13 retracted claims** (`retracted_claims_13.csv`) — was the refusal correct? (Directly tests H1/H2; the gate's core benefit/cost.)
   b. **The 11 surviving supported claims** (`supported_claims_11.csv`) — are they truly supported? (Measures residual false-endorsement rate.)
   c. **The six abstentions** (`abstention_analysis.json`) — especially `plausible-04` (closed-world catalog question with fixture label `contradicted`).
   d. **A stratified sample of unchanged `insufficient_evidence`/`unverifiable` claims** — guard against the gate masking prior under-verification.
4. **Sample sizing**: the 30 exported claims (13+11) plus ~10 abstention/answerability judgments cover the decision-critical surface; expand toward the roadmap's ~100–150 double-labeled claims with the schema above if agreement permits.
5. **Only after labels**: compute supported-precision / false-refusal rates per arm, then (Stage E) run the controlled experiments (generate-once, ≥3 repeats, gate ablation, baseline-claim extraction) to test the RQ properly.

---

## 9. Created files (all under `analysis/stage-c-20261016/`, all new; nothing overwritten)

| File | Purpose |
|---|---|
| `stage_c_report.md` | This report |
| `analyze_stage_c.py` | Reproducible read-only analysis script (recomputes every count; asserts report-vs-DB equality) |
| `input_verification.json` | Provenance checks: ID sets, report-vs-DB tallies, manifest/git/config, missing fields |
| `question_level_comparison.csv` | 22-row paired question-level table |
| `claim_transition_matrix.csv` | 56-row claim-level pre/post label matrix (with claim-text identity flags) |
| `retracted_claims_13.csv` | The 13 gate retractions with ratios, recovered+cross-validated evidence IDs, evidence text, rationales |
| `supported_claims_11.csv` | The 11 surviving supported claims for human review |
| `anomaly_analysis.csv` | 14 post-gate anomalies classified (13 gate + 1 pre-existing, with historical counterpart) |
| `abstention_analysis.json` | Six zero-claim abstentions: stored answers, extraction replay, validated retrieval reconstruction, corpus probes, provisional categories |
| `citation_comparison.json` | Citation metrics limited to stored data + explicit non-computability statements |
| `resource_comparison.json` | Calls, runtime, token availability (null, not inferred), cost |
| `integrity_hashes_before.json` / `integrity_hashes_after.json` | SHA-256 of all source artifacts before/after (10/10 unchanged) |

**Stop condition honored:** no Stage D work started, no application code edited, no model evaluations run, no commits/pushes; only the new analysis directory was written.

---

*Every number in this report is recomputed by `analyze_stage_c.py` from the stored run databases or derived by the explicitly described calculations above; artifact paths are given inline. Where a metric is unavailable, it is marked unavailable rather than estimated.*
