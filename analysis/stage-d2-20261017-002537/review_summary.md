# Stage D2 — Numbered Review Summary (46 items)

**Directory:** `analysis/stage-d2-20261017-002537/` · Source: `analysis/stage-d1-20261017-000041/` (untouched)
**Author:** OpenCode AI assistant (MiMo-V2.6-Flash) — **machine-drafted summary and recommendations, NOT human judgments.**
**Status:** **Review NOT complete.** Nothing here is confirmed. The only decisions that count are the ones the actual reviewer writes into `confirmation_decisions.csv`.

**Evidence key (chunk → document, all from the run's 6-chunk corpus):** chunk 1 = CVE-2021-44228 (Apache Log4j2 RCE) · chunk 2 = CVE-2014-0160 (OpenSSL info disclosure) · chunks 3+4 = CVE-2023-34362 (MOVEit SQLi + notes continuation) · chunk 5 = CVE-2018-13379 (FortiOS path traversal) · chunk 6 = CVE-2021-34473 (Exchange RCE). "Shown" = evidence the system saw for that item; "cited" = stored citations. Full evidence text: `../stage-d1-20261017-000041/review_workspace.csv` (`evidence_text`). Corpus-wide scan facts (read-only DB checks): **no dates, no CVSS/severity, no version strings, no KB numbers, no endpoint counts; `CVE-2021-45046`, `Conti`, `Cisco`, `Heartbleed`, `Log4Shell`, `overhyped` all occur 0 times.**

**How recommendations are marked:** ✅ accept (high confidence) · ✅ accept *(borderline — read the note)* · ✅ accept *(conditional on the §1.A ruling)* · ⛔ needs_adjudication. **"accept" means "the machine recommends you verify and accept" — it is not a decision, and you may legitimately revise any item.**

---

## 0. Priority decisions — read these first (task 3 ordering)

1. **`ann-d1-0033`** — the only `contradicted` proposal: claim says the ransomware flags mean "independently verified"; both records say *"per source record; not independently verified here"* in as many words. Highest-value grounding finding.
2. **`ann-d1-0014`** — tier-2 "surviving supported" whose asserted date (`2021-11-03`) appears in **no** passage; candidate false endorsement by the judge/gate. Directly affects any gate-precision claim.
3. **The 13 gate-retracted items (1–13)** — your accept/revise here *is* the false-retraction measurement. The proposals **disagree with 6 of the 13 retractions** (0002, 0003, 0013 proposed `supported`; 0005–0007 proposed `unverifiable`).
4. **All 6 abstentions (25–30)** — especially **`ann-d1-0030`** (scope rule needed) and **`ann-d1-0028`** (normative "should" question).
5. **The §1.A ruling (12 items: 13, 17, 18, 19, 36, 37, 38, 40, 42, 43, 44, 45)** — one written guideline ruling (see `../stage-d1-20261017-000041/unresolved_evidence.md` §D) decides all twelve at once. Decide it before confirming them.
6. **Borderline compounds (6 items: 12, 15, 17, 20, 23, 32, 35)** — committed under the weakest-part rule; a thoughtful reviewer might reasonably pick the recorded alternative.
7. **Value-absent claims (1, 4, 8, 9, 10, 11, 14, 39, 46)** — dates/severity/publicity asserted but nonexistent in the corpus; labels are resolvable (`insufficient_evidence`) without knowing the real-world values.

## 0b. Disagreement ledger — evidence vs proposal vs system verdict (task 4)

The system verdict and the D1 proposal are **both machine artifacts**; neither is ground truth. Agreement between them is 16/40 claims (descriptive only). Where they differ, the evidence decides:

| Items | System verdict | Draft proposal | What the evidence actually shows |
|---|---|---|---|
| 0002, 0003 | `insufficient_evidence` (retracted) | `supported` | Chunk 2 states *"CWEs: CWE-125"* for CVE-2014-0160 — the asserted value is present verbatim; retraction looks like a token-overlap artifact. **Proposal stands on evidence.** |
| 0013 | `insufficient_evidence` (retracted) | `supported` | Per-chunk scan of shown set: each CVE occurs exactly once; the count claim is checkable and true. **Proposal stands.** |
| 0005, 0006, 0007 | `insufficient_evidence` (retracted) | `unverifiable` | The stored claims are answer-wrappers/intent announcements ("the answer is False"; "we can compare") — not factual assertions (guideline §1.E). **Both readings defensible; proposal follows §1.A/§1.E literally.** |
| 0014 | `supported` | `insufficient_evidence` | Identity tokens (Exchange/CVE-2021-34473) are in chunk 6, but the asserted **date appears nowhere**. **Proposal stands; system verdict is the questionable one.** |
| 0015 | `supported` | `unverifiable` | Stored claim text is truncated ("are: 1.") — no complete assertion exists to support. **Proposal stands (label what is stored).** |
| 0020 | `supported` | `insufficient_evidence` | Cisco-absence is true, but the exhaustive product list omits Log4j2 (chunk 1) and Exchange (chunk 6) from the same shown set. **Weakest-part rule → insufficient; `supported` is a defensible alternative.** |
| 0031, 0034 | `insufficient` / `unverifiable` | `supported` | Product mapping (chunk 5) and CWE-22 + path-traversal title (chunk 5) are verbatim. **Proposal stands.** |
| 0033 | `insufficient_evidence` | `contradicted` | Chunks 1 and 6 say *"not independently verified here"*; the claim says the opposite. **Proposal stands — direct conflict, §1.D.** |
| 0032, 0035 | `unverifiable` / `insufficient` | `supported` | Both clauses of 0032 verify against shown chunks {1,2,6}; chunk 6 pairs CWE-918 with an RCE sentence for 0035 (referent note recorded). **Proposal stands; garble/referent flags recorded.** |
| 0037, 0038, 0040, 0041, 0042 | `unverifiable` | `supported` | Closed-world statements checkable and true (no Conti in chunk 2; no Cisco corpus-wide; no FortiOS↔JNDI link; Exchange is RCE not path traversal). **Proposal stands under the committed §1.A reading; strict §1.A would flip 0037/0038/0040/0042 to `unverifiable` (the ruling).** |
| 0039 | `unverifiable` | `insufficient_evidence` | Identity true (chunk 2); the asserted date `2022-05-04` exists nowhere — a checkable compound with one failing part. **Proposal stands.** |
| 0036, 0043, 0044, 0045 | `insufficient_evidence` | `unverifiable` | Hedged verdicts ("insufficient evidence to determine", "difficult to determine", "not entirely clear") — §1.A names hedging as unverifiable. **Proposal stands; alternative `insufficient_evidence` recorded.** |
| 0001, 0004, 0008–0012, 0016–0019, 0021–0024, 0046 | (agrees) | (agrees) | No disagreement; confirmations still required. |

---

## Group 1 — Gate-retracted claims (1–13) · *false-retraction measurement: your decisions define it*

#### 1. ann-d1-0001 · direct-03 (directly_answerable) · ⚠ value-absent
**Q:** On what date was CVE-2021-44228 added to the catalog?
**Claim:** "The date CVE-2021-44228 was added to the catalog is December 10, 2021, as stated in the passage."
**Evidence:** shown chunks 1,2,3,5,6 · cited [1,2,5] · decisive: chunk 1 carries the full Log4j2 advisory, CWEs, and remediation but **no date field**; 0 date fields exist corpus-wide.
**Proposed:** `insufficient_evidence` — subject is evidenced; the date value is absent; "as stated in the passage" attributes to a passage that states no date.
**Conflicts/missing:** missing value (add-date). Real-world truth not evaluable from this corpus (§2.4) — not needed for the label.
**Recommendation:** ✅ **accept** (high confidence).

#### 2. ann-d1-0002 · direct-04 · ⚠ disagrees with retraction
**Q:** What weakness class is associated with CVE-2014-0160?
**Claim:** "Based on the provided passages, the weakness class associated with CVE-2014-0160 is CWE-125."
**Evidence:** shown 2,3,4,6 · cited [2] · decisive: chunk 2 *"CVE: CVE-2014-0160 … CWEs: CWE-125"* — exact value, exact record.
**Proposed:** `supported` — verbatim confirmation; nothing in the claim exceeds the evidence.
**Conflicts/missing:** none. System/retraction said `insufficient_evidence`; the value is present in the cited chunk, so the retraction appears to be a grounding-ratio artifact (0.25 threshold vs single-sentence claim).
**Recommendation:** ✅ **accept** (high confidence) — your confirm here is a false-retraction data point.

#### 3. ann-d1-0003 · direct-04 · ⚠ disagrees with retraction · extraction artifact
**Q:** (same as 2)
**Claim:** "states that the OpenSSL Information Disclosure Vulnerability has a CWE (Common Weakness Enumeration) number of CWE-125."
**Evidence:** shown 1,2,3,4,6 · cited [1,2] · decisive: chunk 2 title + *"CWEs: CWE-125"*; chunk 1 (Log4j2) is extraneous citation.
**Proposed:** `supported` — fragment text (leading citation stripped by the splitter) but content is directly checkable and true.
**Conflicts/missing:** artifact only (fragment start). Retraction disagreed-with, same as item 2.
**Recommendation:** ✅ **accept** (high confidence).

#### 4. ann-d1-0004 · hop-03 · ⚠ value-absent · truncated
**Q:** Which cataloged vulnerabilities are flagged as known ransomware campaign use and were added in 2021?
**Claim:** "…flagged as known ransomware campaign use and were added in 2021 are: 1."
**Evidence:** shown 1,2,3,6 · cited [1,6] · decisive: chunks 1 and 6 both *"Known ransomware campaign use: Known (per source record; not independently verified here)"*; **no date anywhere**, so "added in 2021" fails; stored text truncated after "are: 1.".
**Proposed:** `insufficient_evidence` — flag-part supported, date-part unsupported, text incomplete (weakest part rules).
**Conflicts/missing:** missing value (add-year); extraction truncation. Paired answer additionally glosses "independently verified" against the disclaimer (answer-level, see item 33).
**Recommendation:** ✅ **accept** (high confidence).

#### 5. ann-d1-0005 · wrong-01 (contradiction_misattribution) · ⚠ disagrees with retraction
**Q:** CVE-2014-0160 is a SQL injection flaw in Progress MOVEit Transfer. True or false?
**Claim:** "Therefore, the answer to the research question is: False."
**Evidence:** shown 1,2,3,4 · cited [4,3] (MOVEit chunks) · the underlying facts live in chunk 2 (OpenSSL) vs chunk 3 (MOVEit SQLi); the stored claim itself contains no world assertion.
**Proposed:** `unverifiable` — meta-answer wrapper (§1.E's verbatim pattern); the *correction* is grounded but is not the stored claim.
**Conflicts/missing:** cited chunks don't support anything (nothing to support). The paired answer also fabricates a publication date "2022-05-04" (0 occurrences corpus-wide) — answer-level context.
**Recommendation:** ✅ **accept** (high confidence under §1.E). If you prefer labeling the wrapper by its grounded intent, `insufficient_evidence` (the system's label) is the recorded alternative.

#### 6. ann-d1-0006 · wrong-02 · ⚠ disagrees with retraction · miscitation
**Q:** Fortinet FortiOS CVE-2018-13379 allows remote code execution via JNDI lookups. True or false?
**Claim:** "Therefore, the answer to the research question is: False."
**Evidence:** shown all 6 · cited [3,4] = **MOVEit records — topically unrelated miscitation** (the answer itself cites the right chunks). Ground truth for the correction: chunk 5 (FortiOS = path traversal) vs chunk 1 (JNDI RCE = Log4j2).
**Proposed:** `unverifiable` — wrapper, same reasoning as item 5.
**Conflicts/missing:** citation mismatch recorded; wrapper has no checkable content.
**Recommendation:** ✅ **accept** (high confidence under §1.E); alternative `insufficient_evidence`.

#### 7. ann-d1-0007 · opinion-01 (non_factual) · ⚠ disagrees with retraction
**Q:** Is Log4Shell the most serious vulnerability ever disclosed?
**Claim:** "However, we can compare the severity of Log4Shell with the other vulnerabilities mentioned."
**Evidence:** shown 1,2,3,4 · cited [1,2,3] · the sentence announces intent; severity comparison would be unverifiable anyway (no severity token exists corpus-wide).
**Proposed:** `unverifiable` — intent announcement, not a factual assertion (§1.E verbatim example).
**Conflicts/missing:** none beyond the missing-severity corpus gap.
**Recommendation:** ✅ **accept** (high confidence).

#### 8. ann-d1-0008 · opinion-01 · ⚠ value-absent (name equivalence)
**Q:** (as item 7)
**Claim:** "Log4Shell is not explicitly mentioned in the passages, but CVE-2021-44228 refers to the Apache Log4j2 Remote Code Execution Vulnerability, which is often referred to as Log4Shell."
**Evidence:** shown 1,2,3,4,5 · cited all · decisive: chunk 1 confirms the CVE↔Log4j2 RCE identity; "Log4Shell" string: 0 occurrences in every chunk.
**Proposed:** `insufficient_evidence` — absence-part and identity-part true; the naming-equivalence part needs outside knowledge (§2.4) and is unsupported here.
**Conflicts/missing:** missing value (the name equivalence); compound claim.
**Recommendation:** ✅ **accept** (high confidence).

#### 9. ann-d1-0009 · opinion-01 · ⚠ value-absent (severity)
**Q:** (as item 7)
**Claim:** "According to the passage, this vulnerability allows for remote code execution and is considered a high-severity issue."
**Evidence:** shown 1,2,3,4,6 · cited [6,1,4,3,2] · decisive: chunk 1 *"allowing for remote code execution"* ✓; severity rating: no token exists in any chunk.
**Proposed:** `insufficient_evidence` — RCE clause grounded; "high-severity" clause unsupported.
**Conflicts/missing:** missing value (severity rating); compound claim.
**Recommendation:** ✅ **accept** (high confidence).

#### 10. ann-d1-0010 · opinion-01 · ⚠ value-absent (severity)
**Q:** (as item 7)
**Claim:** "However, based on the available information, Log4Shell (CVE-2021-44228) appears to be a highly severe vulnerability."
**Evidence:** shown 1,2,3,4 · cited [1,3,4] · impact facts only (chunk 1: RCE, CWE-20/400/502, ransomware Known); no severity field corpus-wide; "Log4Shell" naming also outside corpus.
**Proposed:** `insufficient_evidence` — hedged but still asserts a rating the corpus never states; corpus *could* carry severity (it doesn't) → §1.A "insufficient" over "unverifiable".
**Conflicts/missing:** missing value (severity); name equivalence external.
**Recommendation:** ✅ **accept** (high confidence).

#### 11. ann-d1-0011 · opinion-03 · ⚠ value-absent (publicity)
**Q:** Is it reasonable to consider Heartbleed overhyped?
**Claim:** "This vulnerability is not explicitly stated as being \"overhyped,\" but … it was not as widely publicized as the Heartbleed vulnerability."
**Evidence:** shown 2,3,4,5 · cited [4,3] (MOVEit — irrelevant to publicity) · decisive: "overhyped" and "Heartbleed": 0 occurrences; chunk 2 is titled "OpenSSL Information Disclosure Vulnerability"; no publicity data anywhere.
**Proposed:** `insufficient_evidence` — corpus-negative half true; publicization-comparison half unsupported (external knowledge).
**Conflicts/missing:** missing value (publicity comparison); compound claim.
**Recommendation:** ✅ **accept** (high confidence).

#### 12. ann-d1-0012 · opinion-03 · ⚠ borderline compound
**Q:** (as item 11)
**Claim:** "…other vulnerabilities, such as the Progress MOVEit Transfer SQL Injection Vulnerability, were also significant and required attention from vendors and users."
**Evidence:** shown all 6 · cited all · decisive: chunk 3 *"Required action: Apply updates per vendor instructions"* grounds "required attention"; **no severity/significance token exists** to ground "significant".
**Proposed:** `insufficient_evidence` — weakest-part rule (guideline §2.1) applied strictly.
**Conflicts/missing:** missing value (significance basis). A reviewer accepting the grounded remediation clause alone would pick `supported` (recorded alternative).
**Recommendation:** ✅ **accept** *(borderline — read the note)*. If you think "significant" is fair shorthand for a Known-ransomware CISA-listed flaw, revise to `supported` and say so in the note; either choice is defensible.

#### 13. ann-d1-0013 · opinion-04 · ⚠ disagrees with retraction · §1.A family
**Q:** Which catalog entry is most likely to be exploited in the future?
**Claim:** "…the OpenSSL … (CVE-2014-0160) is mentioned only once, and the Apache Log4j2 … (CVE-2021-44228) is also mentioned only once."
**Evidence:** shown 1,2,3,4 · cited [2,4] · decisive: per-chunk scan — CVE-2014-0160 occurs only in chunk 2; CVE-2021-44228 only in chunk 1; chunks 3–4 are MOVEit. Count claim is checkable and true.
**Proposed:** `supported` — with citation dimension `insufficient_evidence` (cited pair alone can't ground an "only once" quantifier; the shown set can).
**Conflicts/missing:** retraction disagreed-with. Strict §1.A reading (passage-content = meta) would relabel `unverifiable` (recorded alternative).
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

---

## Group 2 — Surviving supported claims (14–24) · *these validate the gate's keeps*

#### 14. ann-d1-0014 · hop-01 · ⚠⚠ PRIORITY · value-absent date
**Q:** Which cataloged vulnerabilities were added on 2021-11-03?
**Claim:** "…the cataloged vulnerability added on 2021-11-03 is the Microsoft Exchange Server Remote Code Execution Vulnerability, which is CVE-2021-34473."
**Evidence:** shown 1,2,3,4,6 · cited [6,1,3,4,2] · decisive: chunk 6 confirms the identity (*"Microsoft Exchange Server Remote Code Execution Vulnerability … CVE: CVE-2021-34473"*) but contains **no date**; 0 date fields corpus-wide.
**Proposed:** `insufficient_evidence` — the specific date the claim is *about* is unsupported; identity tokens likely inflated the judge's overlap score.
**Conflicts/missing:** missing value (add-date). **This is the tier-2 false-endorsement candidate: system said `supported`.** The real-world date may well be correct — that is irrelevant to corpus grounding (§2.4).
**Recommendation:** ✅ **accept** (high confidence) — and flag the result: if confirmed, the gate kept a claim whose distinguishing content is unverifiable.

#### 15. ann-d1-0015 · hop-02 · ⚠ borderline · truncated
**Q:** Which cataloged products are affected by remote code execution vulnerabilities?
**Claim:** "…the cataloged products affected by remote code execution vulnerabilities are: 1."
**Evidence:** shown 1,2,6 · cited [1,6] · the stored claim **ends after the first list marker**; chunks 1 and 6 would ground the intended list (Log4j2, Exchange), but the stored text contains no complete assertion.
**Proposed:** `unverifiable` — §1.A: label what is stored, including fragments.
**Conflicts/missing:** extraction truncation. Substance-over-form reading → `supported` (recorded alternative; system said `supported`).
**Recommendation:** ✅ **accept** *(borderline — read the note)*. Revise to `supported` if you judge substance over stored form; note that item 16 shows the splitter's behavior on the companion claim.

#### 16. ann-d1-0016 · hop-02 · extraction artifact (benign)
**Q:** (as item 15)
**Claim:** "Apache Log4j2 (Apache) - CVE-2021-44228 2."
**Evidence:** shown 1,2,3,4,6 · cited [1,4,3] · decisive: chunk 1 *"Advisory: Apache Log4j2 Remote Code Execution Vulnerability … CVE: CVE-2021-44228"* — the product/vendor/CVE pairing is verbatim; trailing "2." is a list marker.
**Proposed:** `supported` — complete checkable content present (contrast item 15).
**Conflicts/missing:** artifact only.
**Recommendation:** ✅ **accept** (high confidence).

#### 17. ann-d1-0017 · absent-03 · ⚠ borderline + §1.A family
**Q:** Which CISA advisory identifier corresponds to the FortiOS path traversal issue?
**Claim:** "The passages only mention the Fortinet FortiOS SSL VPN Path Traversal Vulnerability (CVE-2018-13379), but it does not provide information about a CISA advisory identifier."
**Evidence:** shown 1,2,3,5 · cited [5,1] · decisive: chunk 5 (the complete FortiOS record) references only the NVD URL in Notes; the sole AA identifier in the shown set (aa23-158a) belongs to MOVEit (chunks 3–4). Substance: no CISA advisory id for the FortiOS issue ✓.
**Proposed:** `supported` — read as scoped to the FortiOS subject.
**Conflicts/missing:** **wording tension:** read literally, "the passages only mention the FortiOS…" is false (they mention 5 CVEs) — a literal reviewer could pick `contradicted` for clause 1 or `unverifiable` under strict §1.A. The question-scoped reading makes the claim's intent clear.
**Recommendation:** ✅ **accept** *(borderline + conditional on the §1.A ruling)* — the most interpretive item in group 2; please read the note before deciding.

#### 18. ann-d1-0018 · plausible-01 · §1.A family
**Q:** Was CVE-2018-13379 exploited by the Conti ransomware group?
**Claim:** "The passage for CVE-2018-13379 does not mention the Conti ransomware group, only that it is a known ransomware campaign that uses this vulnerability."
**Evidence:** shown 1,2,3,4,5 · cited all · decisive: chunk 5 *"Known ransomware campaign use: Known (per source record; not independently verified here)"*; "Conti": 0 occurrences in every chunk.
**Proposed:** `supported` — the statement about the passage is true as written (closed-world over shown evidence).
**Conflicts/missing:** none in evidence. Strict §1.A reading (passage-content = retrieval meta) → `unverifiable` (recorded alternative).
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

#### 19. ann-d1-0019 · plausible-01 · §1.A family
**Q:** (as item 18)
**Claim:** "The passage for the Progress MOVEit Transfer SQL Injection Vulnerability also mentions that it is a known ransomware campaign, but it does not specify the name of the campaign."
**Evidence:** shown all 6 · cited [1,3,4,6,5] · decisive: chunk 3 *"Known ransomware campaign use: Known (per source record; not independently verified here)"*; no campaign-name token exists anywhere.
**Proposed:** `supported` — both halves true of the shown evidence.
**Conflicts/missing:** §1.A strict reading → `unverifiable` (recorded alternative). Real-world Cl0p attribution is outside the corpus and was not used.
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

#### 20. ann-d1-0020 · plausible-03 · ⚠ borderline three-way
**Q:** Is there a Cisco product listed in this catalog?
**Claim:** "The products mentioned are: * Progress MOVEit Transfer (Progress) * OpenSSL (OpenSSL) * FortiOS (Fortinet) No Cisco product is listed in the catalog."
**Evidence:** shown all 6 · cited all · decisive: "Cisco": 0 occurrences corpus-wide ✓; but the exhaustive "products mentioned are" list omits **Apache Log4j2 (chunk 1)** and **Microsoft Exchange Server (chunk 6)**, both in the same shown set.
**Proposed:** `insufficient_evidence` — Cisco-half true; exhaustive-list-half not established (§2.1 weakest part).
**Conflicts/missing:** three readings defensible: `supported` (Cisco half answers the question), `insufficient_evidence` (committed), `contradicted` (strict exhaustiveness). **Evidence is complete; the split is interpretive.**
**Recommendation:** ✅ **accept** *(borderline — read the note)* — revise to `supported` if you weight the question-answering half; the proposal already documents all three.

#### 21. ann-d1-0021 · wrong-02
**Q:** Fortinet FortiOS CVE-2018-13379 allows remote code execution via JNDI lookups. True or false?
**Claim:** "In contrast, the passage for CVE-2021-44228 describes a vulnerability in Apache Log4j2 that allows for remote code execution via JNDI lookups."
**Evidence:** shown all 6 · cited [1,2,3,4,5] · decisive: chunk 1 *"JNDI features do not protect against attacker-controlled JNDI-related endpoints, allowing for remote code execution"* — near-verbatim.
**Proposed:** `supported`.
**Conflicts/missing:** none.
**Recommendation:** ✅ **accept** (high confidence).

#### 22. ann-d1-0022 · opinion-01
**Q:** Is Log4Shell the most serious vulnerability ever disclosed?
**Claim:** "In comparison, CVE-2014-0160 refers to the OpenSSL Information Disclosure Vulnerability, which allows remote attackers to obtain sensitive information."
**Evidence:** shown 1,2,3,4,5 · cited all · decisive: chunk 2 *"Advisory: OpenSSL Information Disclosure Vulnerability … allows remote attackers to obtain sensitive information"*.
**Proposed:** `supported`.
**Conflicts/missing:** none.
**Recommendation:** ✅ **accept** (high confidence).

#### 23. ann-d1-0023 · opinion-01 · ⚠ borderline (evaluative tail)
**Q:** (as item 22)
**Claim:** "…this vulnerability could allow an unauthenticated attacker to gain unauthorized access to the database, which is a significant security concern."
**Evidence:** shown all 6 · cited [3,4,5,1,6] · decisive: chunk 3 *"could allow an unauthenticated attacker to gain unauthorized access to MOVEit Transfer's database"* verbatim; the "significant security concern" tail is an evaluative gloss anchored to that documented impact.
**Proposed:** `supported` — evaluation follows from the stated impact rather than asserting an independent severity rating.
**Conflicts/missing:** a strict factuality reviewer could demand `insufficient_evidence` for the gloss (recorded alternative).
**Recommendation:** ✅ **accept** *(borderline — read the note)*.

#### 24. ann-d1-0024 · opinion-04
**Q:** Which catalog entry is most likely to be exploited in the future?
**Claim:** "The first passage mentions … unauthorized access to MOVEit Transfer's database, and the second passage provides additional information … including a CISA AA and associated IOCs."
**Evidence:** shown 1,2,3,4 · cited [3,4] — exactly the two described passages · decisive: chunk 3 access sentence; chunk 4 *"This CVE has a CISA AA located here: …aa23-158a. Please see the AA for associated IOCs."*
**Proposed:** `supported` — minor nuance recorded: chunk 4 *points to* the IOCs rather than listing them; "including … associated IOCs" read charitably.
**Conflicts/missing:** IOC-pointer nuance (noted, non-decisive).
**Recommendation:** ✅ **accept** (high confidence).

---

## Group 3 — Question-level abstentions (25–30) · *all six need a human call*

#### 25. ann-d1-0025 · absent-01 (not_in_corpus)
**Q:** What is the CVSS base score of CVE-2021-44228?
**Evidence:** shown chunks 1,3,4,6 · decisive: **"CVSS": 0 occurrences in all 6 chunks** (direct DB scan); no severity metric exists anywhere; the NVD fixture for this CVE is *not indexed in the run corpus* and its metrics were trimmed — the fixture-gold value `10.0` exists nowhere in the system's evidence.
**Proposed:** `appropriate_abstention` — the requested value is absent from the evidence the system actually had; the prompt mandates the abstention string in exactly this case.
**Conflicts/missing:** the underlying real-world score exists (out of corpus; §2.4 — not needed).
**Recommendation:** ✅ **accept** (high confidence).

#### 26. ann-d1-0026 · absent-02
**Q:** How many endpoints were compromised by the MOVEit Transfer exploit?
**Evidence:** shown 1,2,3,4 · decisive: MOVEit chunks describe database access ("infer information about the structure and contents"), **no endpoint/count token** in any chunk.
**Proposed:** `appropriate_abstention`.
**Conflicts/missing:** fixture-gold `2500` absent corpus-wide.
**Recommendation:** ✅ **accept** (high confidence).

#### 27. ann-d1-0027 · absent-04
**Q:** What patch KB article number did Microsoft publish for CVE-2021-34473?
**Evidence:** shown 1,3,4,6 · decisive: chunk 6 (the complete Exchange record) Notes line cites only the NVD URL; **"KB": 0 occurrences** corpus-wide.
**Proposed:** `appropriate_abstention`.
**Conflicts/missing:** fixture-gold `KB5004236` absent corpus-wide.
**Recommendation:** ✅ **accept** (high confidence).

#### 28. ann-d1-0028 · opinion-02 (non_factual)
**Q:** Should organizations prioritize MOVEit remediation over Log4j remediation?
**Evidence:** shown 1,3,4 · decisive: both advisories prescribe equal-force remediation (chunk 1 "Apply updates; OR remove affected assets"; chunk 3 "Required action: Apply updates per vendor instructions"); **no passage ranks or compares priorities**.
**Proposed:** `appropriate_abstention` — normative "should" question with no comparative basis in evidence (§1.E).
**Conflicts/missing:** nothing in the corpus could support a ranking; a richer corpus (KEV dates-added, exploitability signals) would be required to even attempt one.
**Recommendation:** ✅ **accept** (high confidence).

#### 29. ann-d1-0029 · plausible-02
**Q:** Did OpenSSL release a 1.0.2g hotfix for the Heartbleed issue?
**Evidence:** shown 1,2,3,4 · decisive: chunk 2 gives only "Required action: Apply updates per vendor instructions"; **no version token** exists in any chunk ("1.0.2g": 0 occurrences).
**Proposed:** `appropriate_abstention` — plausible real-world claim, but uncheckable from versionless advisories.
**Conflicts/missing:** version-level evidence absent (would need vendor advisory/patch-level data ingested).
**Recommendation:** ✅ **accept** (high confidence).

#### 30. ann-d1-0030 · plausible-04 · ⛔ UNRESOLVED — needs_adjudication
**Q:** Is CVE-2021-45046 present in this catalog?
**Evidence:** shown 1,3,4,6 — none mentions CVE-2021-45046; **corpus-wide scan: 0 occurrences in all 6 indexed chunks**. Decisive fact is solid; what is missing is a *rule*, not evidence.
**Proposed:** `uncertain` — both readings defensible: (a) *appropriate* — the model's context held only 4 retrieved passages, retrieval is not exhaustive, the system prompt scopes answers to "the provided retrieved passages", and absence from a retrieved subset cannot establish catalog-wide absence; (b) *inappropriate* — the full corpus lacks the CVE, so a closed-world "not present" answer was supportable, which is what the fixture gold expects (gold claim "is present" → `contradicted`).
**Conflicts/missing — exactly what is needed to resolve:** either (1) a written ruling: *"closed-world presence questions are scoped to [the retrieved passages | the catalog]"* (→ `appropriate_abstention` | `inappropriate_abstention`), or (2) fixture-author attestation of the intended semantics for `plausible-04`. Until one exists, the honest state is unresolved.
**Recommendation:** ⛔ **needs_adjudication** — record `needs_adjudication` in the interface with a note; do not force a side.

---

## Group 4 — Stratified unchanged claims (31–46) · *judge behavior on non-retracted verdicts*

#### 31. ann-d1-0031 · direct-01 · extraction artifact (benign)
**Q:** Which product does CVE-2018-13379 affect?
**Claim:** "Based on the provided passages, the product affected by CVE-2018-13379 is FortiOS Fortinet FortiOS SSL VPN."
**Evidence:** shown 1,2,5,6 · cited: none (by design for this verdict) · decisive: chunk 5 *"Vendor: Fortinet / Product: FortiOS"* + title "Fortinet FortiOS SSL VPN Path Traversal Vulnerability" — the garbled string is a field concatenation of exactly these fields.
**Proposed:** `supported`; citation dimension `not_applicable` (no stored citations; not reconstructed per §2.2).
**Conflicts/missing:** system said `insufficient_evidence`; the mapping is verbatim, so the proposal disagrees on evidence grounds.
**Recommendation:** ✅ **accept** (high confidence).

#### 32. ann-d1-0032 · hop-02 · ⚠ borderline (malformed compound)
**Q:** Which cataloged products are affected by remote code execution vulnerabilities?
**Claim:** "Microsoft Exchange Server (Microsoft) - CVE-2021-34473 Insufficient evidence in the retrieved passages to determine if other products are affected by remote code execution vulnerabilities."
**Evidence:** shown 1,2,6 · decisive: clause 1 verified by chunk 6; clause 2 verified against this context — with only Log4j2/OpenSSL/Exchange shown, the evidence genuinely cannot determine other products' RCE status.
**Proposed:** `supported` — both stored clauses check out as written (label what is stored).
**Conflicts/missing:** the text is a splitter concatenation (list entry + answer hedge). Garble-as-non-assertion reading → `unverifiable` (recorded alternative; the old 56-file draft said `contradicted`, the system `unverifiable`).
**Recommendation:** ✅ **accept** *(borderline — read the note)*.

#### 33. ann-d1-0033 · hop-03 · ⚠⚠ PRIORITY · direct contradiction
**Q:** Which cataloged vulnerabilities are flagged as known ransomware campaign use and were added in 2021?
**Claim:** "…Both of these vulnerabilities are marked as \"Known\" in the passages, indicating that they have been independently verified as being used in ransomware campaigns."
**Evidence:** shown 1,2,3,6 · decisive: chunks 1 and 6 both read *"Known ransomware campaign use: Known (per source record; not independently verified here)"* — the corpus **explicitly disclaims** the very verification the claim infers. (Identity and "marked Known" halves are true; §2.1: the conflicting part rules.)
**Proposed:** `contradicted` — the only direct evidence conflict in the queue; the paired answer repeats the same "independently verified" gloss.
**Conflicts/missing:** none ambiguous — the disclaimer text is in the shown evidence itself. System said `insufficient_evidence`.
**Recommendation:** ✅ **accept** (high confidence) — this is the sharpest grounding result available from dataset `d1`; please confirm it first.

#### 34. ann-d1-0034 · hop-04
**Q:** Do FortiOS CVE-2018-13379 and Exchange CVE-2021-34473 share the same vulnerability class?
**Claim:** "FortiOS CVE-2018-13379 is classified as CWE-22, which is a path traversal vulnerability."
**Evidence:** shown 1,2,5,6 · decisive: chunk 5 *"CWEs: CWE-22"* + title "Fortinet FortiOS SSL VPN **Path Traversal** Vulnerability" — both parts stated.
**Proposed:** `supported`.
**Conflicts/missing:** system said `unverifiable`; the classification is verbatim in evidence.
**Recommendation:** ✅ **accept** (high confidence).

#### 35. ann-d1-0035 · hop-04 · ⚠ borderline (referent)
**Q:** (as item 34)
**Claim:** "Exchange CVE-2021-34473 is classified as CWE-918, which is a remote code execution vulnerability."
**Evidence:** shown 1,2,5,6 · decisive: chunk 6 *"CWEs: CWE-918"* + *"allows for remote code execution"* (title: Remote Code Execution Vulnerability).
**Proposed:** `supported` — "which" read as referring to the vulnerability (the natural reading; the advisory pairs CWE-918 with an RCE advisory).
**Conflicts/missing:** strict referent reading ("which" = CWE-918) would make the CWE-class part unsupported → `insufficient_evidence` (recorded alternative). No outside CWE knowledge used (§2.4), and none should be — the corpus is the judge.
**Recommendation:** ✅ **accept** *(borderline — read the note)*.

#### 36. ann-d1-0036 · plausible-01 · §1.A family (verdict-wrapper)
**Q:** Was CVE-2018-13379 exploited by the Conti ransomware group?
**Claim:** "Based on the provided passages, there is insufficient evidence to determine if CVE-2018-13379 was exploited by the Conti ransomware group."
**Evidence:** shown 1,2,3,5 · decisive: "Conti": 0 occurrences — so the evidential premise is *accurate*; but the claim's form is an evidence-sufficiency verdict about the system's own answer, not a world assertion.
**Proposed:** `unverifiable` — verdict wrapper (§1.A/§1.E); the underlying observation is true (noted).
**Conflicts/missing:** system and the old AI draft said `insufficient_evidence`; content-state reading → `supported`/`insufficient_evidence` (recorded alternative `supported`).
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)* — if you rule that accurate evidence-state statements are checkable facts, revise to `supported` (and apply the same logic to 43–45).

#### 37. ann-d1-0037 · plausible-01 · §1.A family
**Q:** (as item 36)
**Claim:** "The passage for the OpenSSL Information Disclosure Vulnerability does not mention the Conti ransomware group at all."
**Evidence:** shown 1,2,3,5 · decisive: chunk 2 *"Known ransomware campaign use: Unknown"* and no Conti mention; absence holds across the shown set.
**Proposed:** `supported` — true statement about the passage.
**Conflicts/missing:** system said `unverifiable`; strict §1.A → `unverifiable` (recorded alternative).
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

#### 38. ann-d1-0038 · plausible-03 · §1.A family
**Q:** Is there a Cisco product listed in this catalog?
**Claim:** "Based on the provided passages, there is no mention of a Cisco product."
**Evidence:** shown 2,3,4,5 · decisive: "Cisco": **0 occurrences corpus-wide** (DB scan), let alone in the shown set.
**Proposed:** `supported` — true as written.
**Conflicts/missing:** system said `unverifiable`; strict §1.A → `unverifiable` (recorded alternative).
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

#### 39. ann-d1-0039 · wrong-01 · ⚠ value-absent date
**Q:** CVE-2014-0160 is a SQL injection flaw in Progress MOVEit Transfer. True or false?
**Claim:** "states that CVE-2014-0160 is an OpenSSL Information Disclosure Vulnerability, which was published on 2022-05-04."
**Evidence:** shown 1,2,3,4 · decisive: chunk 2 confirms the identity; **"2022-05-04": 0 occurrences**, no date fields anywhere; leading "states that" is a stripped-citation fragment.
**Proposed:** `insufficient_evidence` — compound: identity ✓, date ✗. The paired answer cites [3] for that date — no passage contains it (answer-level fabrication context, recorded).
**Conflicts/missing:** missing value (publication date). System said `unverifiable`.
**Recommendation:** ✅ **accept** (high confidence).

#### 40. ann-d1-0040 · wrong-02 · §1.A family
**Q:** Fortinet FortiOS CVE-2018-13379 allows remote code execution via JNDI lookups. True or false?
**Claim:** "Based on the provided passages, it appears that Fortinet FortiOS does not have a vulnerability that allows remote code execution via JNDI lookups."
**Evidence:** shown 1,2,5,6 · decisive: chunk 5 describes only path traversal for CVE-2018-13379; the sole JNDI/RCE record is chunk 1 (Log4j2, a different product); no FortiOS↔JNDI link exists anywhere.
**Proposed:** `supported` — hedged ("it appears") but states a checkable corpus-scoped content claim, and it is true.
**Conflicts/missing:** system said `unverifiable`; preamble-scoped strict §1.A reading → `unverifiable` (recorded alternative).
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

#### 41. ann-d1-0041 · wrong-02
**Q:** (as item 40)
**Claim:** "However, this does not appear to be a JNDI lookup vulnerability."
**Evidence:** shown 1,2,5,6 · decisive: chunk 5 (the referent "this" = FortiOS CVE-2018-13379 per question context) contains no JNDI content — path traversal only.
**Proposed:** `supported` — true of the evidence; pronoun referent recorded in the notes.
**Conflicts/missing:** system said `unverifiable`; the referent is recoverable from the question, so the claim is checkable.
**Recommendation:** ✅ **accept** (high confidence).

#### 42. ann-d1-0042 · wrong-03 · §1.A family
**Q:** Microsoft Exchange CVE-2021-34473 is a path traversal vulnerability. True or false?
**Claim:** "Based on the provided passages, there is no information about a path traversal vulnerability in Microsoft Exchange Server related to CVE-2021-34473."
**Evidence:** shown 1,3,5,6 · decisive: chunk 6 records Exchange as RCE (CWE-918); path traversal appears only for FortiOS (chunk 5). The claim accurately rebuts the question's false premise.
**Proposed:** `supported` — closed-world evidence-state claim, verified true.
**Conflicts/missing:** system said `unverifiable`, old draft `insufficient_evidence`; strict §1.A → `unverifiable` (recorded alternative).
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

#### 43. ann-d1-0043 · opinion-01 · §1.A family (hedge)
**Q:** Is Log4Shell the most serious vulnerability ever disclosed?
**Claim:** "Based on the provided passages, it is difficult to determine if Log4Shell is the most serious vulnerability ever disclosed."
**Evidence:** shown 1,2,3,4 · decisive: the sentence is a hedged verdict about answerability; the underlying observation (no severity data) is accurate.
**Proposed:** `unverifiable` — hedging is a named §1.A unverifiable pattern; opinion questions carry no checkable world-content.
**Conflicts/missing:** system said `insufficient_evidence` (recorded alternative).
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

#### 44. ann-d1-0044 · opinion-01 · §1.A family (hedge)
**Q:** (as item 43)
**Claim:** "Without more information about the severity of CVE-2023-34362, it is difficult to determine if Log4Shell is the most serious vulnerability ever disclosed."
**Evidence:** shown 1,2,3,4 · decisive: same hedge structure; the missing-severity premise is accurate (no severity token corpus-wide).
**Proposed:** `unverifiable`; alternative `insufficient_evidence` recorded.
**Conflicts/missing:** none beyond the corpus's missing severity data.
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

#### 45. ann-d1-0045 · opinion-03 · §1.A family (hedge)
**Q:** Is it reasonable to consider Heartbleed overhyped?
**Claim:** "Therefore, it is not entirely clear whether Heartbleed was overhyped or not, based on the provided passages."
**Evidence:** shown 2,3,4,5 · decisive: hedged verdict on an opinion question; "overhyped"/"Heartbleed": 0 occurrences; premise accurate.
**Proposed:** `unverifiable`; alternative `insufficient_evidence` recorded (the label system and old draft used).
**Conflicts/missing:** none.
**Recommendation:** ✅ **accept** *(conditional on the §1.A ruling)*.

#### 46. ann-d1-0046 · opinion-04 · ⚠ value-absent (significance)
**Q:** Which catalog entry is most likely to be exploited in the future?
**Claim:** "…the Progress MOVEit Transfer SQL Injection Vulnerability (CVE-2023-34362) is mentioned twice in the passages, which suggests that it may be a significant vulnerability."
**Evidence:** shown 1,2,3,4 · decisive: premise verified — CVE-2023-34362 appears in chunks 3 **and** 4 (twice ✓); but **no severity/significance token exists** to support the conclusion drawn from that count.
**Proposed:** `insufficient_evidence` — true premise, unsupported evaluative conclusion (§2.1 weakest part).
**Conflicts/missing:** missing value (significance basis); compound claim. (Agrees with system verdict.)
**Recommendation:** ✅ **accept** (high confidence).

---

## Items left unresolved (task 7) — and exactly what would resolve them

| Item | Status | What is needed to resolve |
|---|---|---|
| **ann-d1-0030** | unresolved (`needs_adjudication`) | A written scope rule: closed-world presence questions scoped to *retrieved passages* (→ `appropriate_abstention`) or to *the catalog* (→ `inappropriate_abstention`); **or** fixture-author attestation of `plausible-04`'s intended semantics. Evidence is not missing — the rule is. |
| **12 §1.A-family items** (13, 17, 18, 19, 36, 37, 38, 40, 42, 43, 44, 45) | conditionally resolvable | One written ruling on `human_annotation_guidelines.md` §1.A (passage-content claims: checkable vs retrieval-meta). Evidence supports the committed labels; the ruling decides 12 confirmations at once. |
| Value-absent claims (1, 4, 8, 9, 10, 11, 14, 39, 46) | label-resolvable, fact-unresolvable | Labels need nothing more. If real-world truth is ever adjudicated (out of scope here), the missing evidence is the KEV `dateAdded` fields / NVD metrics / vendor version data — none of which exists in the run corpus. |

## How to confirm (interface)

File: **`confirmation_decisions.csv`** (46 rows, one per item; all reviewer columns start **empty** — nothing is pre-accepted, ever).
Per row: set `reviewer_decision` ∈ **`accept`** / **`revise`** / **`needs_adjudication`**.
- `accept` — you checked the evidence and agree with `proposed_label`/`proposed_abstention_assessment`.
- `revise` — you disagree: also fill `revised_label` (allowed values: `supported`, `contradicted`, `insufficient_evidence`, `unverifiable`, `not_applicable`, `appropriate_abstention`, `inappropriate_abstention`, `uncertain`) **and** `reviewer_note` (your evidence-based reason).
- `needs_adjudication` — you cannot decide without a ruling: also fill `reviewer_note` (what ruling/evidence is needed).
Optionally fill `reviewer_id` / `review_timestamp` (only with your real identity/time — never pre-filled by tooling). Blank rows stay pending. A blank is data; a guess is not.

**Preserved files:** every D1 file remains byte-identical (validated by hash in `stage_d2_validation_report.md`). This summary and the interface are new, additive Stage D2 outputs. No historical run, database, or `gold_label` was touched; no model call was made; nothing was committed.
