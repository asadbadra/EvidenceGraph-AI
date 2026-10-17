# Ruling R1 — Plain-English Explanation (single decision, 12 items)

**Purpose:** this file corrects and supersedes only the R1 consequence *table* inside
`d3_review_cards.md` (lines 16–21). That table's card-number lists contain an
enumeration error, documented in §6 below. No other file is affected; no existing
file was modified. No decision has been recorded anywhere — every reviewer field in
`d3_review_decisions.csv` remains blank.

**Author:** AI assistant (machine-written). This is an aid, not a judgment.

---

## 1. What the rule (R1) actually is

R1 is not a rule in the guidelines. It is a **gap** between two guideline passages
that both exist in `human_annotation_guidelines.md` (the only authoritative protocol):

- **§1.A** defines `unverifiable` as: *"not a checkable factual assertion (hedging,
  meta-commentary like "the passages do not mention…", fragments about the retrieval
  itself)."* — this sentence names passage-content statements as unverifiable.
- **§1.D** gives, as a worked example of `contradicted`: *"a claim that a CVE is
  absent from the catalog when a chunk lists it."* — this treats an absence claim as
  a checkable factual claim that evidence can conflict with.

Both sentences are real and in the same document. They cannot both be applied
literally to the same sentence shape. That is R1. Nothing else in the guidelines
(§§1.B–1.F, 2.1–2.6) resolves it; §2.4 ("external truth is irrelevant… corpus-grounded
verification") and §2.6 ("a blank is better than a forced label") do not disambiguate
this particular collision.

## 2. The two interpretations, in one sentence each

- **Committed reading (A):** a statement like *"the passage does not mention Conti"*
  is a **closed-world factual claim about the evidence** — checkable. True → `supported`.
  Contradicted by a chunk → `contradicted`.
- **Strict §1.A reading (B):** the same sentence shape is **meta-commentary about the
  system's retrieval** — not a world-fact — so it is `unverifiable` regardless of
  whether it is accurate.

## 3. Which reading the documented protocol better supports

**Recommendation: Committed reading (A)** — with an honest caveat that this is a
genuine gap, not a solved problem. Reasons, from the protocol only:

1. **§1.D's example would be dead letter under (B).** The guidelines say "Do not use
   `contradicted` for mere absence of confirmation — absence is `insufficient_evidence`"
   and then give an absence-claim contradiction example. Under (B), that example could
   never be reached: every absence claim would be `unverifiable` before §1.D applied.
   A protocol that supplies a worked example intends it to be usable.
2. **§1.A's "key distinction" paragraph points toward (A) for these items.** It says:
   "if the *corpus could in principle contain the answer* but this evidence does not →
   `insufficient_evidence`. If the claim is… about the system/retrieval rather than the
   world → `unverifiable`." The eight flipping claims are about *what the corpus
   contains* (Conti, Cisco, JNDI-in-FortiOS, path-traversal-in-Exchange) — i.e. what
   the world-record says — not about the model's retrieval process. Their subject is
   the catalog, not the system.
3. **§0.1 fixes the judging stance as closed-world.** "The question is always: *would
   the evidence this system saw support this claim as written?*" The evidence the
   system saw *is* the corpus for that item; a statement about that corpus is therefore
   in scope for a factual label.
4. **§2.6 counsels exactly this kind of ruling.** "Solo pass: blank label + `uncertainty_notes`
   explaining what blocked you is always better than a forced label." The gap blocked
   the drafter, which is why R1 was surfaced rather than silently resolved — the
   protocol's own escalation path.

**Caveat stated plainly:** reading (B) is *not* unreasonable. §1.A's parenthetical
does literally say "the passages do not mention…" is unverifiable. A reviewer choosing
(B) would be following a literal phrase in the guidelines, and this assistant cannot
declare them wrong — hence a ruling, not a default.

## 4. The 12 affected annotation IDs (verified against the CSV)

| ID | Proposed label | Card # in d3_review_cards.md | Question stem |
|---|---|---|---|
| ann-d1-0013 | `supported` | 8 | opinion-04 (mention-count) |
| ann-d1-0017 | `supported` | 4 | absent-03 (CISA AA id) |
| ann-d1-0018 | `supported` | 9 | plausible-01 (Conti) |
| ann-d1-0019 | `supported` | 10 | plausible-01 (Conti) |
| ann-d1-0036 | `unverifiable` | 11 | plausible-01 (Conti) |
| ann-d1-0037 | `supported` | 12 | plausible-01 (Conti) |
| ann-d1-0038 | `supported` | 13 | plausible-03 (Cisco) |
| ann-d1-0040 | `supported` | 14 | wrong-02 (FortiOS/JNDI) |
| ann-d1-0042 | `supported` | 15 | wrong-03 (Exchange) |
| ann-d1-0043 | `unverifiable` | 16 | opinion-01 (Log4Shell) |
| ann-d1-0044 | `unverifiable` | 17 | opinion-01 (Log4Shell) |
| ann-d1-0045 | `unverifiable` | 18 | opinion-03 (Heartbleed) |

## 5. What actually changes under each interpretation

Only **8 of the 12 rows change their answer**. Four rows are `unverifiable` under
*both* readings, because their claim text is a hedge or an evidence-sufficiency verdict
("there is insufficient evidence to determine…", "it is difficult to determine…",
"not entirely clear whether…"), which §1.A/§1.E already classify as unverifiable
independently of R1.

| Interpretation | Rows that change | Action on those 8 | Action on the other 4 |
|---|---|---|---|
| **A — committed** (passage-content = checkable fact) | none | `accept` (proposals stand) | `accept` (proposals stand) |
| **B — strict §1.A** (passage-content = retrieval-meta) | 0013, 0017, 0018, 0019, 0037, 0038, 0040, 0042 → `unverifiable` | `revise`, revised label `unverifiable` | `accept` still correct (label unchanged; rationale basis shifts) |

Note for (B) on ann-d1-0017: under (B) the label becomes `unverifiable` regardless of
the literal-vs-scoped wording question, so that item's separate sub-choice (Card 4)
becomes moot. Under (A) it is still required — see Card 4.

## 6. Discrepancy found in `d3_review_cards.md` (correction)

The R1 consequence table inside `d3_review_cards.md` line 19 lists, for interpretation
(B), the card numbers "items 8, 9, 13, 14, 15, 17 change label; items 4, 10, 11, 12,
16, 18 keep `unverifiable`". Checking those card numbers against the card headings and
each card's own `- **Proposed label:**` line:

- The "change" list wrongly includes **card 17 (ann-d1-0044)**, whose proposed label is
  already `unverifiable` — it does not change under either reading.
- The "change" list omits **card 4 (ann-d1-0017)**, **card 10 (ann-d1-0019)** and
  **card 12 (ann-d1-0037)**, all three of which are proposed `supported` and therefore
  do change under (B).
- The "keep `unverifiable`" list correspondingly misassigns cards 4, 10 and 12.

The per-card guidance inside each individual card (e.g. Card 12 "True passage-content
statement; R1-dependent under the strict reading") is correct; only the summary table's
card-number arithmetic was wrong. This file's §4–§5 are the corrected view. The
underlying 12-ID set was always correct in both files (it is machine-derived from the
same source list and was verified by validation check C4).

## 7. What to record once you decide

- **Choose A:** on all 12 rows, `reviewer_decision = accept`. Then handle Card 4
  (ann-d1-0017) separately with its literal-vs-scoped choice.
- **Choose B:** on the 8 rows in §5, `reviewer_decision = revise` with revised label
  `unverifiable`; on the 4 wrapper rows (0036, 0043, 0044, 0045), `reviewer_decision = accept`.
- Nothing is applied until you fill `d3_review_decisions.csv` yourself. This file
  records no decision, creates no label, and touches no database or historical file.

*Machine-generated aid · Stage D3 · No human decision exists yet · Stage E not started.*
