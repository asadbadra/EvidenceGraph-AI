# Stage D3 - Highest-Risk Decisions (start here)

Full cards: `d3_review_cards.md` - main file: `d3_review_decisions.csv`.
Record choices ONLY in the CSV: `reviewer_decision` = `accept` / `revise` / `needs_adjudication` (+ optional short `reviewer_note`).

**Integrity:** Everything in the machine columns (proposed_label, explanation, evidence_status, recommended_action, suggested_revised_label, confidence) is an AI-assistant review aid, not a human judgment. Only the reviewer_decision / reviewer_note columns carry human authority, and they start blank.

## Do these five first

### Card 1 - ann-d1-0033 (Group C)

- **Claim:** "Microsoft Exchange Server Remote Code Execution Vulnerability | CVE-2021-34473 Both of these vulnerabilities are marked as "Known" in the passages, indicating that they have been independently verified as being used in ransomware campaigns."
- **Evidence:** "Known ransomware campaign use: Known (per source record; not independently verified here)"
- **Source:** shown chunks: 1, 2, 3, 6 | cited: [none] | 1=Apache Log4j2 Remote Code Execution Vulnerability; 2=OpenSSL Information Disclosure Vulnerability; 3=Progress MOVEit Transfer SQL Injection Vulnerability; 6=Microsoft Exchange Server Remote Code Execution Vulnerability
- **What it means:** The claim upgrades a 'Known ransomware use' flag into 'independently verified'. Both records shown carry the words 'not independently verified here'.
- **Proposed label:** `contradicted` / abstention_assessment: not_applicable
- **Recommendation:** accept proposal
- **Why:** The evidence states the opposite of the claim's inference - a direct conflict (guideline 1.D).
- **Confidence:** high - The disclaimer appears twice inside the shown evidence itself; nothing is ambiguous.
- **Your action:** [ ] accept  [ ] revise  [ ] needs adjudication

### Card 2 - ann-d1-0014 (Group C)

- **Claim:** "Based on the provided passages, the cataloged vulnerability added on 2021-11-03 is the Microsoft Exchange Server Remote Code Execution Vulnerability, which is CVE-2021-34473."
- **Evidence:** "Microsoft Exchange Server Remote Code Execution Vulnerability"
- **Source:** shown chunks: 1, 2, 3, 4, 6 | cited: [6, 1, 3, 4, 2] | 1=Apache Log4j2 Remote Code Execution Vulnerability; 2=OpenSSL Information Disclosure Vulnerability; 3=Progress MOVEit Transfer SQL Injection Vulnerability; 4=CVE-2023-34362; 6=Microsoft Exchange Server Remote Code Execution Vulnerability
- **What it means:** The identity half is real (chunk 6 names the Exchange CVE-2021-34473 issue), but the date 2021-11-03 - the whole point of the question - appears in no chunk; no chunk contains any date. (D3 finding: the database's document-level published_at holds 2021-11-03 for BOTH the Exchange and FortiOS documents, so even the metadata layer makes this date non-unique.)
- **Proposed label:** `insufficient_evidence` / abstention_assessment: not_applicable
- **Recommendation:** accept proposal
- **Why:** System verdict said 'supported'; this is the candidate false endorsement. Insufficient_evidence is the honest corpus-grounded label either way.
- **Confidence:** high - Zero date tokens in any chunk text (evidence layer), verified by database scan; metadata is not evidence the system saw.
- **Your action:** [ ] accept  [ ] revise  [ ] needs adjudication

### Card 3 - ann-d1-0030 (Group C)

- **Claim:** "Is CVE-2021-45046 present in this catalog?"
- **Evidence:** "Apache Log4j2 Remote Code Execution Vulnerability"
- **Source:** shown chunks: 1, 3, 4, 6 | cited: [none] | 1=Apache Log4j2 Remote Code Execution Vulnerability; 3=Progress MOVEit Transfer SQL Injection Vulnerability; 4=CVE-2023-34362; 6=Microsoft Exchange Server Remote Code Execution Vulnerability
- **What it means:** None of the four chunks the system saw mention CVE-2021-45046, and the full corpus does not either. Whether the model's 'not in this catalog' answer was right depends on whether 'this catalog' means the retrieved passages or the whole catalog.
- **Proposed label:** `not_applicable` / abstention_assessment: uncertain
- **Recommendation:** needs adjudication
- **Why:** Evidence is solid (absence verified); the scope rule is missing. Guideline 1.F's 'uncertain' is written for exactly this debatable closed-world case.
- **Confidence:** low - Both readings are defensible; a one-line scope ruling by you resolves it.
- **Your action:** [ ] accept  [ ] revise  [ ] needs adjudication

### Card 7 - ann-d1-0032 (Group B)

- **Claim:** "Microsoft Exchange Server (Microsoft) - CVE-2021-34473 Insufficient evidence in the retrieved passages to determine if other products are affected by remote code execution vulnerabilities."
- **Evidence:** "JNDI features do not protect against attacker-controlled JNDI-related endpoints, allowing for remote code execution"
- **Source:** shown chunks: 1, 2, 6 | cited: [none] | 1=Apache Log4j2 Remote Code Execution Vulnerability; 2=OpenSSL Information Disclosure Vulnerability; 6=Microsoft Exchange Server Remote Code Execution Vulnerability
- **What it means:** Clause 1 (Exchange = CVE-2021-34473) is verified. Clause 2 says the passages give 'insufficient evidence... if other products are affected by remote code execution' - but chunk 1 in the same shown set fully determines that Apache Log4j2 IS affected by RCE.
- **Proposed label:** `supported` / abstention_assessment: not_applicable
- **Recommendation:** revise proposal -> candidate: insufficient_evidence
- **Why:** Fresh D3 inspection: the second clause does not hold as written against the shown evidence. Weakest-part rule (2.1) points to insufficient_evidence; a strict closed-world reading even allows contradicted.
- **Confidence:** medium - Changed from D2's borderline-accept after re-examining the shown set; the garbled text makes any choice imperfect.
- **Your action:** [ ] accept  [ ] revise  [ ] needs adjudication

### Card 20 - ann-d1-0002 (Group A)

- **Claim:** "Based on the provided passages, the weakness class associated with CVE-2014-0160 is CWE-125."
- **Evidence:** "CWEs: CWE-125"
- **Source:** shown chunks: 2, 3, 4, 6 | cited: [2] | 2=OpenSSL Information Disclosure Vulnerability; 3=Progress MOVEit Transfer SQL Injection Vulnerability; 4=CVE-2023-34362; 6=Microsoft Exchange Server Remote Code Execution Vulnerability
- **What it means:** Chunk 2 states the OpenSSL record's weakness class verbatim as CWE-125 - the exact value the claim asserts.
- **Proposed label:** `supported` / abstention_assessment: not_applicable
- **Recommendation:** accept proposal
- **Why:** Gate retracted this as insufficient_evidence despite the value being present; accepting records a false retraction.
- **Confidence:** high - Verbatim value in the cited chunk; no competing reading.
- **Your action:** [ ] accept  [ ] revise  [ ] needs adjudication

## Then: Ruling R1 (one decision, twelve items)

See the R1 section at the top of `d3_review_cards.md`. Mark the 12 listed items `accept` (committed reading) or `revise` + `unverifiable` (strict 1.A).

## Workload estimate

- 5 priority cards above: ~5 minutes.
- Ruling R1 + 12 items: ~3 minutes.
- Group C remainder (4 interpretation items): ~4 minutes.
- Group A (28 items): ~10 minutes if you skim-accept; less if you batch `accept` after spot-checking the excerpts.

Nothing is decided until you fill the CSV. Blanks stay pending; a blank is data.
