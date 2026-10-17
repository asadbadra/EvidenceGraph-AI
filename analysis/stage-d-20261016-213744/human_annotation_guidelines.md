# Human Annotation Guidelines — EvidenceGraph-AI Claim Verification Review

**Dataset:** `d1` · **Schema:** v1.0.0 · **Read time:** ~10 minutes · **Apply with:** `human_review_queue_blind.csv` (first pass) then `human_review_queue.csv` (self-check)

Thank you for doing this review. You are the first independent human ground truth in this project. Everything downstream (judge-vs-human agreement, gate precision, abstention quality) depends on your honest judgments — **including your blanks and uncertainties**. A blank is data. A guess is not.

## 0. The five-minute version

1. **Judge from the evidence shown in the queue only.** Each item contains the verbatim retrieved chunks. Do not use outside knowledge (what you know about Log4j, Heartbleed, MOVEit from the real world). The question is always: *would the evidence this system saw support this claim as written?*
2. **Work blind.** Use `human_review_queue_blind.csv` first — it contains no system verdicts. The full queue (with verdicts) exists only for your post-hoc self-check. If you ever judge with verdicts visible, say so in `uncertainty_notes` (e.g. "verdict visible, judged independently anyway") — honesty about blinding beats silent contamination.
3. **Label the claim exactly as written**, including fragments, hedging, and meta-commentary. You are labeling what is stored, not what you suspect was meant.
4. **A conservative verdict is not automatically correct.** The system's abstention or `insufficient_evidence` can be *wrong* if the evidence was actually there. Do not reward caution; reward accuracy against the evidence.
5. **When unsure, leave the label blank** and put your reasoning in `uncertainty_notes`. Never invent evidence, labels, or rationales.
6. **Filling the queue writes nothing to any database.** `gold_label` stays NULL until a separate, explicitly approved transfer step. Your file is the only place your labels exist.

## 1. The six dimensions (label them separately — do not collapse)

Each item asks for up to four independent judgments. They often agree; when they diverge, that divergence is finding, not noise.

### A. Claim factuality → `human_label`

*Does the available authoritative (corpus) evidence agree with the claim?*

| Label | Apply when |
|---|---|
| `supported` | The shown evidence **directly confirms** the specific factual content of the claim. Minor paraphrase is fine; missing detail is not. "Directly confirms" = a careful reader of the quoted chunks would accept the claim as true. |
| `contradicted` | The shown evidence **directly conflicts** with a factual part of the claim (wrong product, wrong CVE mapping, wrong CWE, wrong date, opposite meaning). |
| `insufficient_evidence` | The evidence **touches the claim's subject** but cannot decide it either way — the specific value, relation, or assertion is simply not in the shown text. This is the "abstain-worthy" middle: not false, not established. |
| `unverifiable` | The text is **not a checkable factual assertion** (hedging, meta-commentary like "the passages do not mention…", fragments about the retrieval itself), **or** nothing in the corpus could ever bear on it. |
| `not_applicable` | Only on abstention-question items at claim level (their real assessment is `abstention_assessment`). Never use it on a claim to mean "unsure" — that is a blank. |

**Key distinction — `insufficient_evidence` vs `unverifiable`:** if the *corpus could in principle contain the answer* but this evidence does not → `insufficient_evidence`. If the claim is not a factual assertion at all, or is about the system/retrieval rather than the world → `unverifiable`.

### B. Evidence sufficiency → `evidence_sufficiency_rationale`

*Do the retrieved passages support the **specific** claim, rather than merely discuss the same topic?*

Topic overlap is not support. A claim about "the CVSS score of CVE-2021-44228" is not supported by a passage that merely discusses CVE-2021-44228. In your rationale: name the chunk ids and **quote the exact span** that carries the support — or state plainly that no span does. If the claim is compound, assess the *weakest* supported part (see §2.1).

### C. Citation support → `citation_support_label` + `citation_support_rationale`

*Does the cited passage actually support the claim it is attached to?*

- Claims in this dataset were generated with `[n]`-style citations resolved against the retrieved set; the queue shows which chunks the judge cited (`retrieved_evidence_ids`) and the chunks themselves.
- `not_applicable` = the claim cites nothing, or citation targets are unavailable (some post-gate rows lost citations by design — the queue recovers and marks these; judge carefully from the recovered list).
- A claim can be factually `supported` by *some* chunk while its *cited* chunk fails to support it — that is `human_label=supported` + `citation_support_label=contradicted` (or `insufficient_evidence`). Record both.

### D. Contradiction

Contradiction is label `contradicted` in dimension A, applied when evidence **directly conflicts**. Examples from this corpus: a claim mapping CVE-2023-34362 to Apache Log4j2 (evidence says Progress MOVEit Transfer); a claim that a CVE is absent from the catalog when a chunk lists it. Do not use `contradicted` for *mere absence of confirmation* — absence is `insufficient_evidence`.

### E. Unverifiability

Unverifiability is label `unverifiable` in dimension A (see the distinction in §1.A). Typical cases in this dataset: "Therefore, the answer to the research question is: False." (meta-answer, not a world fact); "However, we can compare the severity…" (announces an intent, asserts nothing); normative "should" statements.

### F. Abstention quality → `abstention_assessment` (question-level; six items only)

*Was abstaining the right move for this question, given the corpus?*

The system answered six questions with the verbatim string "Insufficient evidence in the retrieved passages." and produced zero claims.

| Label | Apply when |
|---|---|
| `appropriate_abstention` | The corpus genuinely lacks the answer-bearing content (e.g. the question asks for a CVSS score, KB number, endpoint count, or version string that appears nowhere in the chunks). |
| `inappropriate_abstention` | The retrieved/corpus text **did contain** the answer (or a direct basis to answer, including a closed-world "X is not present in this catalog" answer the corpus could support) and the system still abstained. |
| `uncertain` | You cannot decide from the shown evidence (e.g. a closed-world assumption is itself debatable). |
| `not_applicable` | Claim items (always). |

Also record any factual view of the question in `human_label` per §1.A if the item asks for it; the abstention verdict itself lives in `abstention_assessment`.

## 2. Hard cases — required handling

### 2.1 Partially supported / compound claims
Label by the **weakest independently-checkable part**: if one clause is supported and another is not, the claim is `insufficient_evidence` overall (or `contradicted` if a part conflicts). Say which part failed in `human_rationale` and flag `compound claim` in `uncertainty_notes`. Do not average; do not "mostly true".

### 2.2 Missing or broken citations
If `retrieved_evidence_ids` is empty and the queue marks evidence as `unavailable_not_stored`: judge factuality from whatever verbatim evidence IS shown; set `citation_support_label=not_applicable`; note `citations missing` in `uncertainty_notes`. **Never reconstruct a citation you cannot see.**

### 2.3 Conflicting source documents
If two shown chunks conflict with each other: do not pick a winner silently. Set `human_label=unverifiable` (or `insufficient_evidence` if one is clearly the authoritative record — e.g. a vendor advisory vs a fragment), explain both sides in `human_rationale`, and flag `conflicting sources` in `uncertainty_notes`. The adjudicator will see your note.

### 2.4 Claims requiring knowledge outside the corpus
The corpus is five CISA KEV advisory records (six chunks). A claim that is true in the real world but unsupported *by this corpus* gets `insufficient_evidence` (or `unverifiable` if unfixable in principle). External truth is irrelevant here — this exercise measures **corpus-grounded** verification. If you find yourself reasoning from outside knowledge, stop and write `used outside knowledge — consider blank` in `uncertainty_notes`, then decide.

### 2.5 Prompt-injection text in retrieved documents
The corpus is treated as **untrusted input**. If a chunk (or a claim's quoted evidence) contains text that looks like instructions — "ignore previous instructions", "label this claim supported", "SYSTEM:", fake reviewer directions — **do not comply**. Label strictly on evidential content, and write `possible prompt injection in chunk N` in `uncertainty_notes`. (No injection text is known to exist in this corpus; the rule exists so your reflex is ready.)

### 2.6 Uncertainty and disagreement
- Solo pass: blank label + `uncertainty_notes` explaining what blocked you is always better than a forced label.
- Double pass (if a second reviewer is available): disagreement is expected and useful. Each reviewer labels independently and blind; neither sees the other's labels until both are stored. Disagreements go to adjudication (see `stage_d_protocol.md` §5); do not negotiate labels directly.
- If you filled labels while knowing the system verdict, record it (`visible_acknowledged` path). Self-reported contamination is recoverable; silent contamination is not.

## 3. Anti-bias checklist (per item, ~5 seconds)

- [ ] Did I read the quoted evidence before the claim's neighbors? (Order matters less than blindness, but evidence first keeps you honest.)
- [ ] Am I agreeing with the system because it sounds authoritative? (Remember: 13 of 24 "supported" verdicts were retracted by a later gate — confident verdicts were often wrong.)
- [ ] Am I punishing a correct-but-cautious abstention? (Abstention quality is judged on evidence presence, not on caution.)
- [ ] Would a stranger reading only my rationale reach the same label? (If not, rewrite the rationale.)

## 4. What your labels will and will not be used for

**Will:** computing judge-vs-human agreement (with matched/total/coverage), gate retraction precision (were the 13 retractions right?), surviving-supported false-endorsement rate, abstention appropriateness, and Stage E experiment design.

**Will not:** any claim of "human-verified accuracy" beyond what your sample covers; any transfer to `gold_label` without your explicit approval; any use of AI-draft labels as if they were yours (they are kept separate and marked).
