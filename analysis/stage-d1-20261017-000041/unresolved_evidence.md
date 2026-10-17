# Stage D1 — Unresolved Evidence, Ambiguities, and Open Decisions

**Directory:** `analysis/stage-d1-20261017-000041/` · **Dataset:** `d1` (46 items)
**Status:** every item carries a **machine-drafted proposal only** (`proposed_unconfirmed` ×45, `needs_adjudication` ×1). **Zero human confirmations exist.** Nothing in this file is a human judgment.
**Drafter:** OpenCode AI assistant (MiMo-V2.6-Flash), evidence-first, system verdicts visible (acknowledged), no model calls.

This file exists so uncertainty is preserved rather than smoothed over. Each section lists what the evidence does and does not establish, and what a human reviewer must decide.

---

## A. Missing evidence — claims asserting values the corpus does not contain

The run corpus is 6 chunks / 5 CISA KEV advisory records. Direct DB scan: **0 occurrences** of any date-added field, `CVSS`, `KB`, version strings, `2500`, `CVE-2021-45046`, `Heartbleed`, `Conti`, `Cisco`, `Log4Shell`, `overhyped`. Claims below fail on missing values, not on false values — absence in this corpus does not make a real-world claim false (guideline §2.4).

| Annotation | Asserted value | What the evidence has | Proposal |
|---|---|---|---|
| ann-d1-0001 | add-date "December 10, 2021" (+ false "as stated in the passage" attribution) | no date field anywhere | `insufficient_evidence` |
| ann-d1-0004 | "added in 2021" | ransomware-Known flags only (chunks 1,6) | `insufficient_evidence` (compound + truncated) |
| ann-d1-0014 | add-date "2021-11-03" | identity confirmed (chunk 6), no date | `insufficient_evidence` — **tier-2 disagreement, see §C** |
| ann-d1-0039 | "published on 2022-05-04" | OpenSSL identity confirmed (chunk 2), no date | `insufficient_evidence` (compound) |
| ann-d1-0009, 0010 | "high-severity" / "highly severe" | impact facts only (chunk 1), no severity field | `insufficient_evidence` |
| ann-d1-0011 | "not as widely publicized as Heartbleed" | no publicity data; name "Heartbleed" absent | `insufficient_evidence` (compound) |
| ann-d1-0012 | MOVEit etc. were "significant" | "Required action: Apply updates" (chunk 3) grounds the remediation half | `insufficient_evidence` (borderline, §C) |
| ann-d1-0046 | mention-count "suggests significant" | count premise true (chunks 3,4); no severity rating | `insufficient_evidence` (compound) |
| ann-d1-0008 | CVE-2021-44228 "often referred to as Log4Shell" | name absent corpus-wide; identity confirmed | `insufficient_evidence` (compound) |
| ann-d1-0025–0027, 0029 | CVSS `10.0`, endpoint count `2500`, `KB5004236`, `1.0.2g` | none present in any chunk | `appropriate_abstention` ×4 |

Fixture note (absent-01): `data/sample/nvd_sample.json` — a trimmed NVD record for CVE-2021-44228 — is **not indexed in the eval run corpus** and itself contains **no CVSS metrics** (removed during fixture trimming). The fixture-gold value `10.0` exists nowhere in the system's evidence.

## B. Conflicting, contradictory, and fabricated content

1. **Direct contradiction (priority): `ann-d1-0033` → `contradicted`.** The claim says the ransomware flags mean the vulnerabilities "have been independently verified"; chunks 1 and 6 state verbatim `"Known ransomware campaign use: Known (per source record; not independently verified here)"`. The corpus disclaims exactly what the claim asserts. (System verdict was `insufficient_evidence`; the old AI draft also said `contradicted` — the proposal is evidence-derived regardless.)
2. **Answer-level fabrication context (does not change claim labels):** the paired answers for `wrong-01` state CVE-2014-0160 "was published on 2022-05-04" (no passage has dates), and `hop-03`'s answer glosses "independently verified" against the corpus disclaimer. Relevant for Stage E answer-level analysis; recorded here so it is not lost.
3. **Miscitation:** `ann-d1-0006` — the judge cited chunks [3,4] (MOVEit records) for a FortiOS/Log4j question; the answer itself cites the correct chunks. Recorded in the proposal's citation rationale.
4. **No conflicting source documents:** chunks 3 and 4 are two chunks of the same MOVEit record and agree with each other; no shown pair of chunks disagrees (full corpus read).
5. **No prompt-injection text** found in any chunk (guideline §2.5 checked; none of the instruction-like patterns occur).

## C. Borderline / compound judgments — committed, flagged, reviewer may revise

| Annotation | Why borderline | Committed | Alternative recorded |
|---|---|---|---|
| ann-d1-0014 | tier-2 **surviving "supported"** but its date clause has no evidence → candidate **false endorsement** | `insufficient_evidence` | — (flag: verify before any gate-precision claim) |
| ann-d1-0020 | Cisco-absence true, but the exhaustive product list omits chunks 1,6 products → three readings | `insufficient_evidence` (§2.1 weakest part) | `supported` (notes also hold `contradicted`) |
| ann-d1-0012 | remediation half grounded, "significant" half not | `insufficient_evidence` | `supported` |
| ann-d1-0023 | evaluative tail "significant security concern" tied to documented impact | `supported` | `insufficient_evidence` |
| ann-d1-0035 | "which is a RCE vulnerability" referent (CVE vs CWE-918) | `supported` | `insufficient_evidence` |
| ann-d1-0032 | malformed concatenation (list entry + hedge sentence); both clauses verify against shown chunks 1,2,6 | `supported` | `unverifiable` |
| ann-d1-0015 vs 0016 | truncation handling: 0015 has **no** checkable content → `unverifiable`; 0016 has a complete pairing → `supported` (label what is stored) | as stated | `supported` for 0015 |

The 13 gate retractions are tier 1; proposals **agree with 7 of 13** retractions and **disagree with 6** (0002, 0003, 0013 supported; 0005, 0006, 0007 unverifiable). These are proposals, not gate-precision results — precision can only be computed after human confirmation (protocol §5).

## D. Guideline-interpretation ruling needed (one decision covers 12 items)

`human_annotation_guidelines.md` §1.A's `unverifiable` definition contains the parenthetical *"meta-commentary like 'the passages do not mention…'"*, while §1.D treats catalog-absence claims as checkable (they can be *contradicted* when a chunk lists the CVE) and §1.F lets closed-world absence ground an abstention judgment. The two readings:

- **Committed reading (used for all 46 proposals):** statements about what the passages/catalog contain or omit are **checkable against the shown evidence** and get factual labels; `unverifiable` is reserved for verdict wrappers, intent announcements, normative statements, and hedges (§1.E's operational examples).
- **Strict §1.A reading:** every passage-content statement is retrieval meta-commentary → `unverifiable`.

Items whose label would flip under the strict reading (also carried per-row in `policy_alternative_label`):

| Committed | Strict-§1.A would be | Items |
|---|---|---|
| `supported` | `unverifiable` | 0013, 0017, 0018, 0019, 0037, 0038, 0040, 0042 |
| `unverifiable` | `insufficient_evidence` / `supported` (accurate evidence-state reading) | 0036, 0043, 0044, 0045 |

**Reviewer action:** confirm the ruling once (write it down), then confirm/reject the 12 items as a group. The choice is methodologically material — under the strict reading, system-vs-proposal agreement rises substantially — so it must be settled by a human before any agreement statistic is computed, and whichever way it lands, it must be reported with the labels.

## E. Abstention adjudication priority — `ann-d1-0030` (plausible-04)

The only item with `proposal_status = needs_adjudication`. Question: *"Is CVE-2021-45046 present in this catalog?"* System abstained.

- **For `appropriate_abstention`:** the model's context held only the 4 retrieved passages (chunks 4,3,6,1); BM25 retrieval is not exhaustive; the system prompt (`baseline-v1`) scopes answers to *"the provided retrieved passages"* and mandates the abstention string when they lack the answer. Absence from 4 retrieved chunks cannot establish catalog-wide absence.
- **For `inappropriate_abstention`:** direct DB scan shows **all 6 indexed chunks** lack CVE-2021-45046, so a closed-world "not present" answer was supportable from the corpus — which is what the fixture expects (gold claim "is present" → `contradicted`); §1.F names closed-world absence as an abstention failure mode.
- **Proposal:** `uncertain` (§1.F's literal "closed-world assumption is itself debatable" case) + routed to adjudication.
- **Rule needed:** does this harness treat the retrieved passages as "the catalog" for closed-world presence questions? That ruling also determines fixture-vs-system scoring for this question class.

Related: `ann-d1-0028` (normative "should prioritize") → `appropriate_abstention` committed; both advisories prescribe equal-force remediation and no passage ranks them.

## F. Extraction artifacts (claim splitter) — labeled as stored, never corrected

| Artifact | Items |
|---|---|
| Truncated enumeration ("are: 1.") | 0004, 0015 |
| Trailing list marker ("… 2.") | 0016 |
| Leading stripped-citation fragment ("states that…") | 0003, 0039 |
| Garbled field concatenation ("FortiOS Fortinet FortiOS SSL VPN") | 0031 |
| List entry concatenated with answer hedge sentence | 0032 |
| False source attribution ("as stated in the passage") | 0001 |

No claim text was repaired. Where the stored text still contains checkable content, it was labeled on that content; where it does not, the label is `unverifiable` (guideline §1.A: label what is stored).

## G. Provenance exclusions and missing-citation handling (unchanged from Stage D)

- **Tier-4 empty citations** (items 0031–0046): insufficient/unverifiable verdicts store no citations **by design**; `proposed_citation_support_label = not_applicable`, never reconstructed (guideline §2.2).
- **13 retracted claims:** citations restored from gate anomaly notes, cross-validated 13/13 vs the historical run (Stage C/D); recovery provenance shown per chunk.
- **`human_claim_review56.md`** (56 labels): `ai_generated_draft` — quarantined as `proposed_ai_label`; **not consulted for any proposal rationale** (proposals were derived from claim + evidence text).
- **`human_claim_review.md`** (8 mini labels): `provenance_unknown` — still excluded; the pending attestation question is unchanged.
- No file in any `runs/` directory, no Stage C/D artifact, no database was modified by Stage D1.

---

*Prepared by tooling as part of Stage D1. Human review of the 46 items — starting from `review_confirmation_sheet.md` or `review_workspace.csv` — is the only path by which any label here becomes a human label.*
