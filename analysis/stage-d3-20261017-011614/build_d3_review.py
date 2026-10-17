"""Stage D3: build the low-effort human review interface.

Reads (read-only): Stage D queue, questions, D1 proposal workspace, D2 decisions.
Writes (only inside this directory):
  d3_review_decisions.csv     - main spreadsheet interface (reviewer columns blank)
  d3_highest_risk_summary.md  - short summary of the decisions that matter most
  d3_review_cards.md          - all 46 compact review cards, grouped C -> B -> A

Rules enforced by construction:
  - claim_or_question is copied byte-for-byte from the queue (original wording).
  - evidence_excerpt must match VERBATIM inside the item's stored evidence_text
    (asserted at build time; the build fails if any excerpt is not traceable).
  - proposed_label / proposed_abstention_assessment copied byte-for-byte from D1.
  - reviewer_decision / reviewer_note are emitted EMPTY. Nothing is pre-accepted.
  - Deterministic: no runtime timestamps, stdlib only, no model calls, no network.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
QUEUE_PATH = REPO / "analysis/stage-d-20261016-213744/human_review_queue.json"
QUESTIONS_PATH = REPO / "data/sample/eval_questions.json"
D1_DIR = REPO / "analysis/stage-d1-20261017-000041"

COLUMNS = [
    "annotation_id", "review_order", "review_group", "claim_or_question",
    "evidence_excerpt", "source_reference", "proposed_label",
    "proposed_abstention_assessment", "explanation", "evidence_status",
    "recommended_action", "suggested_revised_label", "confidence",
    "reviewer_decision", "reviewer_note",
]
REVIEWER_COLUMNS = ["reviewer_decision", "reviewer_note"]

DISCLAIMER = (
    "Everything in the machine columns (proposed_label, explanation, evidence_status, "
    "recommended_action, suggested_revised_label, confidence) is an AI-assistant review "
    "aid, not a human judgment. Only the reviewer_decision / reviewer_note columns carry "
    "human authority, and they start blank."
)

# ---------------------------------------------------------------------------
# Curated per-item review content. Group C = needs attention, B = likely
# revision, A = straightforward. review_order puts the highest-risk items first.
# ---------------------------------------------------------------------------
E: list[dict] = []


def entry(id, order, group, excerpt, meaning, why, status, rec, conf, conf_why, suggested=""):
    E.append(dict(id=id, order=order, group=group, excerpt=excerpt, meaning=meaning,
                  why=why, status=status, rec=rec, conf=conf, conf_why=conf_why,
                  suggested=suggested))


R1 = "accept_proposal"

# --- Group C: highest-risk first -------------------------------------------
entry("ann-d1-0033", 1, "C",
      "Known ransomware campaign use: Known (per source record; not independently verified here)",
      "The claim upgrades a 'Known ransomware use' flag into 'independently verified'. Both records shown carry the words 'not independently verified here'.",
      "The evidence states the opposite of the claim's inference - a direct conflict (guideline 1.D).",
      "contradicts", "accept_proposal", "high",
      "The disclaimer appears twice inside the shown evidence itself; nothing is ambiguous.")
entry("ann-d1-0014", 2, "C",
      "Microsoft Exchange Server Remote Code Execution Vulnerability",
      "The identity half is real (chunk 6 names the Exchange CVE-2021-34473 issue), but the date 2021-11-03 - the whole point of the question - appears in no chunk; no chunk contains any date. (D3 finding: the database's document-level published_at holds 2021-11-03 for BOTH the Exchange and FortiOS documents, so even the metadata layer makes this date non-unique.)",
      "System verdict said 'supported'; this is the candidate false endorsement. Insufficient_evidence is the honest corpus-grounded label either way.",
      "insufficient", "accept_proposal", "high",
      "Zero date tokens in any chunk text (evidence layer), verified by database scan; metadata is not evidence the system saw.")
entry("ann-d1-0030", 3, "C",
      "Apache Log4j2 Remote Code Execution Vulnerability",
      "None of the four chunks the system saw mention CVE-2021-45046, and the full corpus does not either. Whether the model's 'not in this catalog' answer was right depends on whether 'this catalog' means the retrieved passages or the whole catalog.",
      "Evidence is solid (absence verified); the scope rule is missing. Guideline 1.F's 'uncertain' is written for exactly this debatable closed-world case.",
      "unclear", "needs_adjudication", "low",
      "Both readings are defensible; a one-line scope ruling by you resolves it.", suggested="")
entry("ann-d1-0017", 4, "C",
      "Notes: https://nvd.nist.gov/vuln/detail/CVE-2018-13379",
      "Substance is clear: the FortiOS record (chunk 5) links only to NVD - no CISA advisory id exists for it. But the sentence's first half, 'the passages only mention the FortiOS...', is literally false (five CVEs are shown) unless read as scoped to FortiOS.",
      "Choose the reading: scoped -> supported; literal -> contradicted; strict guideline-1.A -> unverifiable (Ruling R1 decides that part).",
      "unclear", "needs_adjudication", "low",
      "The most interpretive claim in the queue; three labels are defensible depending on one reading choice.")
entry("ann-d1-0020", 5, "C",
      "Advisory: Microsoft Exchange Server Remote Code Execution Vulnerability",
      "The Cisco half is verified ('Cisco' appears in zero chunks). But the claim's product list (MOVEit, OpenSSL, FortiOS) is incomplete: the same shown evidence also contains Apache Log4j2 (chunk 1) and this Exchange record (chunk 6).",
      "Weakest-part rule (2.1) -> insufficient_evidence; question-weighted reading -> supported; strict exhaustiveness -> contradicted.",
      "unclear", "needs_adjudication", "low",
      "Three-way interpretation; the evidence is complete, the reading is your call.")
entry("ann-d1-0015", 6, "C",
      "Apache Log4j2 Remote Code Execution Vulnerability",
      "The stored claim is cut off mid-list ('...are: 1.') and states no complete assertion. The chunks would ground the intended list (Log4j2, Exchange), so a substance-based reading could accept it.",
      "Proposal labels the stored text (unverifiable); revise to supported if you prefer judging intent over stored form.",
      "unclear", "needs_adjudication", "low",
      "Form-versus-substance choice; the guideline says label what is stored.")
entry("ann-d1-0032", 7, "B",
      "JNDI features do not protect against attacker-controlled JNDI-related endpoints, allowing for remote code execution",
      "Clause 1 (Exchange = CVE-2021-34473) is verified. Clause 2 says the passages give 'insufficient evidence... if other products are affected by remote code execution' - but chunk 1 in the same shown set fully determines that Apache Log4j2 IS affected by RCE.",
      "Fresh D3 inspection: the second clause does not hold as written against the shown evidence. Weakest-part rule (2.1) points to insufficient_evidence; a strict closed-world reading even allows contradicted.",
      "insufficient", "revise_proposal", "medium",
      "Changed from D2's borderline-accept after re-examining the shown set; the garbled text makes any choice imperfect.",
      suggested="insufficient_evidence")
# --- Group C: the 12 items resolved by Ruling R1 ---------------------------
entry("ann-d1-0013", 8, "C",
      "CVE: CVE-2014-0160",
      "Each CVE appears in exactly one shown chunk (Log4j2 in chunk 1, OpenSSL in chunk 2), so the 'mentioned only once' count is checkable and true.",
      "Accept unless Ruling R1 goes strict - then passage-content statements like this one become unverifiable.",
      "supports", R1, "medium",
      "Count verified per-chunk; label depends on the single 1.A ruling.")
entry("ann-d1-0018", 9, "C",
      "Known ransomware campaign use: Known (per source record; not independently verified here)",
      "Chunk 5 flags the FortiOS issue as Known ransomware use (per source) and 'Conti' appears in zero chunks - the claim describes the passage accurately.",
      "True statement about passage content; R1-dependent under the strict reading.",
      "supports", R1, "medium",
      "Evidence unambiguous; label turns on the 1.A ruling.")
entry("ann-d1-0019", 10, "C",
      "Known ransomware campaign use: Known (per source record; not independently verified here)",
      "Chunk 3 flags MOVEit as Known ransomware use (per source) and names no campaign anywhere - exactly what the claim says.",
      "True passage-content statement; R1-dependent under the strict reading.",
      "supports", R1, "medium",
      "Evidence unambiguous; label turns on the 1.A ruling.")
entry("ann-d1-0036", 11, "C",
      "Known ransomware campaign use: Known (per source record; not independently verified here)",
      "The sentence is a verdict about the answer's own evidence, not a world fact. Its premise is accurate ('Conti' appears in zero chunks), but guideline 1.A/1.E label such meta-verdicts unverifiable.",
      "Accept as unverifiable; the recorded alternative (insufficient_evidence) applies if you prefer checking the premise instead.",
      "unclear", R1, "medium",
      "Wrapper family: under either 1.A reading the honest label stays unverifiable.")
entry("ann-d1-0037", 12, "C",
      "Known ransomware campaign use: Unknown",
      "Chunk 2 (OpenSSL) flags ransomware use as 'Unknown' and never mentions Conti; the word appears in zero chunks.",
      "True passage-content statement; R1-dependent under the strict reading.",
      "supports", R1, "medium",
      "Evidence unambiguous; label turns on the 1.A ruling.")
entry("ann-d1-0038", 13, "C",
      "Vendor: Fortinet",
      "The catalog records list vendors Apache, OpenSSL, Progress, Fortinet and Microsoft - 'Cisco' appears in zero chunks, so the passage statement is true as written.",
      "True passage-content statement; R1-dependent under the strict reading.",
      "supports", R1, "medium",
      "Absence verified corpus-wide by database scan; label turns on the 1.A ruling.")
entry("ann-d1-0040", 14, "C",
      "JNDI features do not protect against attacker-controlled JNDI-related endpoints, allowing for remote code execution",
      "The only JNDI/RCE record in the evidence is chunk 1 (Apache Log4j2); the FortiOS record (chunk 5) is path traversal only - the hedged 'appears not to' statement holds.",
      "True hedged passage-content statement; R1-dependent under the strict reading.",
      "supports", R1, "medium",
      "Evidence unambiguous; label turns on the 1.A ruling.")
entry("ann-d1-0042", 15, "C",
      "Microsoft Exchange Server Remote Code Execution Vulnerability",
      "Chunk 6 records the Exchange issue as remote code execution (CWE-918); path traversal appears only for FortiOS (chunk 5) - the rebuttal of the question's false premise is accurate.",
      "True passage-content statement; R1-dependent under the strict reading.",
      "supports", R1, "medium",
      "Evidence unambiguous; label turns on the 1.A ruling.")
entry("ann-d1-0043", 16, "C",
      "allowing for remote code execution",
      "A hedged verdict on an opinion question ('difficult to determine'). Its premise is right - the corpus has no severity rating at all - but guideline 1.A names hedging as unverifiable.",
      "Accept as unverifiable; recorded alternative insufficient_evidence if you prefer premise-checking.",
      "unclear", R1, "medium",
      "Wrapper family: honest label stays unverifiable under either 1.A reading.")
entry("ann-d1-0044", 17, "C",
      "could allow an unauthenticated attacker to gain unauthorized access to MOVEit Transfer's database",
      "Same hedge structure as the previous item, anchored to the MOVEit record; the missing-severity premise is accurate (no severity value exists anywhere).",
      "Accept as unverifiable; recorded alternative insufficient_evidence.",
      "unclear", R1, "medium",
      "Wrapper family: honest label stays unverifiable under either 1.A reading.")
entry("ann-d1-0045", 18, "C",
      "Advisory: OpenSSL Information Disclosure Vulnerability",
      "Hedged verdict on an opinion question; 'Heartbleed' and 'overhyped' appear in zero chunks, so nothing checkable is asserted.",
      "Accept as unverifiable; recorded alternative insufficient_evidence.",
      "unclear", R1, "medium",
      "Wrapper family: honest label stays unverifiable under either 1.A reading.")
# --- Group A: the 13 gate-retracted claims ---------------------------------
entry("ann-d1-0001", 19, "A",
      "Apache Log4j2 Remote Code Execution Vulnerability",
      "The Log4j2 record (chunk 1) carries no date, and no chunk contains any date token - so the claimed add-date 'December 10, 2021' and the phrase 'as stated in the passage' are unsupported by the evidence. (D3 finding: the value 2021-12-10 does exist in the database's document-level published_at metadata, which the retrieval pipeline never surfaces to the model or the judge.)",
      "Annotations judge from the shown evidence only (guideline 0.1): the label is insufficient_evidence regardless of the metadata value.",
      "insufficient", "accept_proposal", "high",
      "Zero date tokens in any chunk text (evidence layer), verified by database scan; the value lives only in unsurfaced metadata.")
entry("ann-d1-0002", 20, "A",
      "CWEs: CWE-125",
      "Chunk 2 states the OpenSSL record's weakness class verbatim as CWE-125 - the exact value the claim asserts.",
      "Gate retracted this as insufficient_evidence despite the value being present; accepting records a false retraction.",
      "supports", "accept_proposal", "high",
      "Verbatim value in the cited chunk; no competing reading.")
entry("ann-d1-0003", 21, "A",
      "CWEs: CWE-125",
      "Same fact in narrative form: the advisory title plus 'CWEs: CWE-125' confirm the claim; the leading 'states that' is a citation-extraction artifact.",
      "Like item 2: the asserted value is present, so the retraction looks like a token-overlap artifact.",
      "supports", "accept_proposal", "high",
      "Verbatim value present; artifact affects wording, not factuality.")
entry("ann-d1-0004", 22, "A",
      "Known ransomware campaign use: Known (per source record; not independently verified here)",
      "The ransomware flag exists (chunks 1, 6) but no date exists anywhere, so the 'added in 2021' half fails; the stored text is also cut off after 'are: 1.'.",
      "Weakest-part rule (2.1) on a compound with an unsupported date part -> insufficient_evidence.",
      "insufficient", "accept_proposal", "high",
      "Both defects (absent date, truncation) are objective.")
entry("ann-d1-0005", 23, "A",
      "Advisory: OpenSSL Information Disclosure Vulnerability",
      "The stored claim is just 'the answer is False' - a meta-answer with nothing checkable. The underlying facts (OpenSSL is not MOVEit: chunk 2 vs chunk 3) are true but are not the stored claim.",
      "Guideline 1.E uses this exact sentence pattern as its unverifiable example.",
      "unclear", "accept_proposal", "high",
      "Guideline text matches the case verbatim.")
entry("ann-d1-0006", 24, "A",
      "Advisory: Fortinet FortiOS SSL VPN Path Traversal Vulnerability",
      "Same wrapper pattern; the correction behind it is grounded (chunk 5 = path traversal, not JNDI/RCE - that is chunk 1), though the stored citations point at unrelated MOVEit chunks.",
      "1.E wrapper -> unverifiable; the citation mismatch is recorded separately and does not change the label.",
      "unclear", "accept_proposal", "high",
      "Wrapper is unambiguous; miscitation noted for the citation dimension only.")
entry("ann-d1-0007", 25, "A",
      "allowing for remote code execution",
      "'We can compare the severity...' announces an intent and asserts nothing; a severity comparison would be uncheckable anyway (no severity values exist in the corpus).",
      "1.E intent-announcement pattern -> unverifiable.",
      "unclear", "accept_proposal", "high",
      "Sentence asserts no world-content; guideline pattern match.")
entry("ann-d1-0008", 26, "A",
      "Apache Log4j2 Remote Code Execution Vulnerability",
      "The CVE-to-Log4j2 identity is in chunk 1 and 'Log4Shell' appears in zero chunks - but the naming equivalence ('often referred to as Log4Shell') needs outside knowledge the corpus does not carry.",
      "Two of three clauses verified; the weakest part is external -> insufficient_evidence.",
      "insufficient", "accept_proposal", "high",
      "Compound with one clearly external part; objective.")
entry("ann-d1-0009", 27, "A",
      "allowing for remote code execution",
      "Remote code execution is stated in chunk 1; 'high-severity' is not - no severity rating exists in any chunk.",
      "Compound: impact clause verified, severity clause unsupported -> insufficient_evidence.",
      "insufficient", "accept_proposal", "high",
      "Severity absence verified corpus-wide; objective.")
entry("ann-d1-0010", 28, "A",
      "allowing for remote code execution",
      "The corpus has impact facts (chunk 1) but no severity field, so the hedge 'appears to be highly severe' still asserts an unevidenced rating.",
      "The corpus could in principle carry severity; it does not - guideline 1.A's key distinction makes this insufficient_evidence.",
      "insufficient", "accept_proposal", "high",
      "Severity absence verified corpus-wide; objective.")
entry("ann-d1-0011", 29, "A",
      "Advisory: OpenSSL Information Disclosure Vulnerability",
      "The claim's absence half is true ('overhyped' has zero occurrences), but its comparison - Heartbleed was 'not as widely publicized' - needs real-world knowledge the corpus does not contain.",
      "Weakest part is external to the corpus -> insufficient_evidence.",
      "insufficient", "accept_proposal", "high",
      "Token absences objective; the comparison is clearly outside-knowledge.")
entry("ann-d1-0012", 30, "A",
      "Required action: Apply updates per vendor instructions.",
      "The MOVEit record does ground 'required attention' (chunk 3), but nothing in the corpus grounds 'significant' - there is no severity or ranking data anywhere.",
      "Weakest-part rule -> insufficient_evidence; revise to supported if you read 'significant' as fair shorthand for a Known-ransomware, CISA-listed flaw.",
      "insufficient", "accept_proposal", "medium",
      "Rule-driven answer, but the evaluative word is genuinely arguable.")
# --- Group A: remaining items ----------------------------------------------
entry("ann-d1-0016", 31, "A",
      "Apache Log4j2 Remote Code Execution Vulnerability",
      "Chunk 1 pairs the product/vendor/CVE exactly as claimed; the trailing '2.' is just a list marker.",
      "Complete, verbatim-checkable content -> supported (contrast the truncated item 6).",
      "supports", "accept_proposal", "high",
      "Direct confirmation; artifact is cosmetic.")
entry("ann-d1-0021", 32, "A",
      "JNDI features do not protect against attacker-controlled JNDI-related endpoints, allowing for remote code execution",
      "The claim's Log4j2 half is near-verbatim from chunk 1: JNDI endpoints plus remote code execution.",
      "Direct confirmation of both components -> supported.",
      "supports", "accept_proposal", "high",
      "Near-verbatim match; no competing reading.")
entry("ann-d1-0022", 33, "A",
      "allows remote attackers to obtain sensitive information",
      "Chunk 2 states the OpenSSL advisory's impact almost word-for-word as the claim's comparison sentence.",
      "Direct confirmation -> supported.",
      "supports", "accept_proposal", "high",
      "Near-verbatim match; no competing reading.")
entry("ann-d1-0023", 34, "A",
      "could allow an unauthenticated attacker to gain unauthorized access to MOVEit Transfer's database",
      "The core sentence is verbatim from chunk 3; the tail 'a significant security concern' is an evaluation that follows from the documented impact rather than an independent rating.",
      "Supported; revise to insufficient_evidence only if you want the evaluative tail treated as an unevidenced claim.",
      "supports", "accept_proposal", "medium",
      "Verbatim core; only the evaluative tail invites disagreement.")
entry("ann-d1-0024", 35, "A",
      "Please see the AA for associated IOCs.",
      "Chunk 3 gives the access description; chunk 4 points to the CISA advisory and its IOCs - matching the claim's 'first passage... second passage' exactly.",
      "Both clauses verified; minor nuance: chunk 4 points to the IOCs rather than listing them.",
      "supports", "accept_proposal", "high",
      "Both clauses directly evidenced; nuance is non-decisive.")
entry("ann-d1-0025", 36, "A",
      "Apache Log4j2 Remote Code Execution Vulnerability",
      "The question asks for a CVSS base score; 'CVSS' appears in zero chunks, so the system could only answer from outside knowledge - abstaining was correct.",
      "Answer-bearing value absent from the evidence -> appropriate_abstention.",
      "insufficient", "accept_proposal", "high",
      "Zero 'CVSS' occurrences verified corpus-wide; objective.")
entry("ann-d1-0026", 37, "A",
      "could allow an unauthenticated attacker to gain unauthorized access to MOVEit Transfer's database",
      "The MOVEit chunks describe database access but give no endpoint count ('2500' appears nowhere), so abstaining was the right call.",
      "Requested count absent from evidence -> appropriate_abstention.",
      "insufficient", "accept_proposal", "high",
      "Token absence objective; the chunks show only qualitative impact.")
entry("ann-d1-0027", 38, "A",
      "Microsoft Exchange Server Remote Code Execution Vulnerability",
      "The Exchange record's only reference is an NVD URL; 'KB' appears in zero chunks, so the patch-KB number could not be answered from evidence.",
      "Requested value absent from evidence -> appropriate_abstention.",
      "insufficient", "accept_proposal", "high",
      "Token absence objective; record fully shown.")
entry("ann-d1-0028", 39, "A",
      "Required action: Apply updates per vendor instructions.",
      "Both advisories prescribe remediation (chunks 1, 3) but nothing ranks priorities; a normative 'should prioritize' question has no basis in this evidence.",
      "Non-factual normative question (1.E) with no comparative basis -> appropriate_abstention.",
      "insufficient", "accept_proposal", "high",
      "No ranking content exists corpus-wide; objective.")
entry("ann-d1-0029", 40, "A",
      "Required action: Apply updates per vendor instructions.",
      "The OpenSSL record says only 'apply updates' - no version strings exist in any chunk, so the specific hotfix version could not be checked.",
      "Requested version absent from evidence -> appropriate_abstention.",
      "insufficient", "accept_proposal", "high",
      "Version absence objective; record fully shown.")
entry("ann-d1-0031", 41, "A",
      "Fortinet FortiOS SSL VPN Path Traversal Vulnerability",
      "Chunk 5 maps CVE-2018-13379 to Fortinet FortiOS; the claim's garbled name is just those fields concatenated.",
      "The mapping is verbatim in evidence -> supported; no stored citations exist for this verdict, so citation support is not applicable.",
      "supports", "accept_proposal", "high",
      "Mapping direct; garble is cosmetic.")
entry("ann-d1-0034", 42, "A",
      "CWEs: CWE-22",
      "Chunk 5 gives CWE-22 and a title containing 'Path Traversal Vulnerability' - both halves of the claim are stated.",
      "Direct confirmation -> supported.",
      "supports", "accept_proposal", "high",
      "Both components verbatim in one chunk.")
entry("ann-d1-0035", 43, "A",
      "CWEs: CWE-918",
      "Chunk 6 pairs CWE-918 with a 'remote code execution' advisory; 'which is a remote code execution vulnerability' reads naturally as describing the CVE.",
      "Supported under the natural referent; if you read 'which' as describing CWE-918 itself, revise to insufficient_evidence (the corpus does not define CWE classes).",
      "supports", "accept_proposal", "medium",
      "Corpus-internal only by design; real-world CWE taxonomy deliberately not consulted.")
entry("ann-d1-0039", 44, "A",
      "Advisory: OpenSSL Information Disclosure Vulnerability",
      "Chunk 2 confirms the identity half, but the date '2022-05-04' appears in no chunk. (D3 correction: that value is not invented - it matches the database's document-level published_at for CVE-2014-0160 - yet the claim says the passage 'states' it, and the passage states no date at all.)",
      "Compound with an unsupported-by-passage date -> insufficient_evidence; the paired answer cites a chunk that cannot carry the date (citation-accuracy issue, recorded separately).",
      "insufficient", "accept_proposal", "high",
      "Zero date tokens in any chunk text; the value exists only in unsurfaced document metadata.")
entry("ann-d1-0041", 45, "A",
      "Advisory: Fortinet FortiOS SSL VPN Path Traversal Vulnerability",
      "The FortiOS record (chunk 5) describes path traversal only; 'this does not appear to be a JNDI lookup vulnerability' is accurate of that record.",
      "True of the referent record -> supported; the pronoun's referent comes from the question.",
      "supports", "accept_proposal", "high",
      "Referent recoverable from question context; claim accurate.")
entry("ann-d1-0046", 46, "A",
      "CVE-2023-34362",
      "The premise checks out - CVE-2023-34362 appears in two chunks (3 and 4) - but no severity or ranking data exists to support the leap from 'mentioned twice' to 'significant'.",
      "True premise, unsupported conclusion -> insufficient_evidence (weakest-part rule).",
      "insufficient", "accept_proposal", "high",
      "Count objective; the inference is clearly unevidenced.")

R1_FAMILY = ["ann-d1-0013", "ann-d1-0017", "ann-d1-0018", "ann-d1-0019", "ann-d1-0036",
             "ann-d1-0037", "ann-d1-0038", "ann-d1-0040", "ann-d1-0042", "ann-d1-0043",
             "ann-d1-0044", "ann-d1-0045"]
ALLOWED_LABELS = {"supported", "contradicted", "insufficient_evidence", "unverifiable",
                  "not_applicable", "appropriate_abstention", "inappropriate_abstention",
                  "uncertain"}
STATUS_VOCAB = {"supports", "contradicts", "insufficient", "unclear"}
ACTION_VOCAB = {"accept_proposal", "revise_proposal", "needs_adjudication"}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    qitems = {it["annotation_id"]: it for it in queue["items"]}
    qtext = {q["id"]: q["question"] for q in
             json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]}
    with (D1_DIR / "review_workspace.csv").open(encoding="utf-8", newline="") as fh:
        ws = {r["annotation_id"]: r for r in csv.DictReader(fh)}

    # ---- ID / category verification against the actual files (task 6) ------
    assert len(qitems) == 46 and len(E) == 46
    assert {e["id"] for e in E} == set(qitems), "entry ids != queue ids"
    assert "independently verified" in qitems["ann-d1-0033"]["claim_text"]
    assert "2021-11-03" in qitems["ann-d1-0014"]["claim_text"]
    a30 = qitems["ann-d1-0030"]
    assert a30["item_type"] == "abstention_question" and "CVE-2021-45046" in qtext[a30["question_id"]]
    tiers = {t: sum(1 for it in qitems.values() if it["item_priority"] == t) for t in (1, 2, 3, 4)}
    assert tiers == {1: 13, 2: 11, 3: 6, 4: 16}, tiers
    assert all(qitems[i]["claim_text"] for i in R1_FAMILY), "family must be claim items"
    assert sum(1 for it in qitems.values() if it["item_type"] == "abstention_question") == 6

    rows, cards = [], []
    for e in sorted(E, key=lambda x: x["order"]):
        it = qitems[e["id"]]
        w = ws[e["id"]]
        claim = " ".join((it["claim_text"] or qtext[it["question_id"]]).split())
        evidence = w["evidence_text"]
        assert e["excerpt"] and e["excerpt"] in evidence, \
            f"{e['id']}: excerpt not found verbatim in stored evidence_text"

        shown = ", ".join(str(c["chunk_id"]) for c in it["evidence_text_or_reference"])
        cited = ", ".join(str(c) for c in it.get("retrieved_evidence_ids") or []) or "none"
        doc_parts = []
        for c in it["evidence_text_or_reference"]:
            adv = next((ln.split("Advisory: ", 1)[1] for ln in c["text"].splitlines()
                        if ln.startswith("Advisory: ")), c.get("document_external_id", "?"))
            doc_parts.append(f"{c['chunk_id']}={adv}")
        src = f"shown chunks: {shown} | cited: [{cited}] | " + "; ".join(doc_parts)

        prop_label = w["proposed_label"]
        prop_abst = w["proposed_abstention_assessment"]
        assert prop_label in ALLOWED_LABELS and e["status"] in STATUS_VOCAB
        assert e["rec"] in ACTION_VOCAB
        assert (e["suggested"] in ALLOWED_LABELS) if e["suggested"] else True

        rows.append({
            "annotation_id": e["id"], "review_order": e["order"], "review_group": e["group"],
            "claim_or_question": claim, "evidence_excerpt": e["excerpt"],
            "source_reference": src, "proposed_label": prop_label,
            "proposed_abstention_assessment": prop_abst, "explanation": e["meaning"],
            "evidence_status": e["status"], "recommended_action": e["rec"],
            "suggested_revised_label": e["suggested"],
            "confidence": f"{e['conf']} - {e['conf_why']}",
            "reviewer_decision": "", "reviewer_note": "",
        })
        cards.append((e, claim, prop_label, prop_abst, src))

    out_csv = HERE / "d3_review_decisions.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)

    # ---- cards markdown -----------------------------------------------------
    def card(e, claim, pl, pa, src, n):
        abst = f" / abstention_assessment: {pa}" if pa else ""
        sug = f" -> candidate: {e['suggested']}" if e["suggested"] else ""
        return (
            f"### Card {n} - {e['id']} (Group {e['group']})\n\n"
            f"- **Claim:** \"{claim}\"\n"
            f"- **Evidence:** \"{e['excerpt']}\"\n"
            f"- **Source:** {src}\n"
            f"- **What it means:** {e['meaning']}\n"
            f"- **Proposed label:** `{pl}`{abst}\n"
            f"- **Recommendation:** {e['rec'].replace('_', ' ')}{sug}\n"
            f"- **Why:** {e['why']}\n"
            f"- **Confidence:** {e['conf']} - {e['conf_why']}\n"
            f"- **Your action:** [ ] accept  [ ] revise  [ ] needs adjudication\n")

    by_group = {"C": [], "B": [], "A": []}
    for e, cl, pl, pa, src in cards:
        by_group[e["group"]].append((e, cl, pl, pa, src))

    md = [
        "# Stage D3 - Human Review Cards (46 items)",
        "",
        f"**Main interface:** `d3_review_decisions.csv` (one row per item; "
        f"`reviewer_decision` and `reviewer_note` are blank and are the ONLY columns you fill).",
        "",
        "**How to record a choice (any one of three, per row):**",
        "1. Agree with the proposal -> write `accept` in `reviewer_decision`.",
        "2. Disagree -> write `revise` and put one permitted label in the CSV's "
        "`suggested_revised_label` guidance column *and your own* decision record "
        "(permitted labels: `supported`, `contradicted`, `insufficient_evidence`, "
        "`unverifiable`, `not_applicable`, `appropriate_abstention`, "
        "`inappropriate_abstention`, `uncertain`) plus an optional short note.",
        "3. Cannot decide without a ruling -> write `needs_adjudication` + one short "
        "note saying what ruling/evidence is needed.",
        "",
        f"**Integrity:** {DISCLAIMER} No decision has been pre-filled, no label has "
        "been written to any database, and Stage B/C/D/D1/D2 artifacts are unchanged.",
        "",
        "## Ruling R1 - one decision, twelve items (do this before Card 4+)",
        "",
        "**The question:** guideline 1.A calls `unverifiable` any text that is "
        "\"meta-commentary like 'the passages do not mention...'\" (strict reading), "
        "but guideline 1.D's contradiction example treats absence claims as checkable "
        "facts (\"a claim that a CVE is absent from the catalog when a chunk lists "
        "it\"). Twelve items sit on this line.",
        "",
        "| Your ruling | What to do on those 12 items |",
        "|---|---|",
        "| **R1 = committed reading**: passage-content statements are checkable facts | "
        "mark `accept` (the proposals stand) |",
        "| **R1 = strict 1.A reading**: such statements are retrieval-meta | mark "
        "`revise` with `unverifiable` (items 8, 9, 13, 14, 15, 17 change label; items "
        "4, 10, 11, 12, 16, 18 keep `unverifiable` but were proposed for the same reason) |",
        "",
        "Items covered: " + ", ".join(R1_FAMILY) + ". Card 4 (ann-d1-0017) additionally "
        "needs its own literal-vs-scoped reading choice after R1.",
        "",
        "---",
        "",
        "## Group C - needs your attention (17 items, highest-risk first)",
        "",
    ]
    for e, cl, pl, pa, src in by_group["C"]:
        md.append(card(e, cl, pl, pa, src, e["order"]))
    md += ["---", "", "## Group B - likely revision (1 item)", "",
           "*Fresh D3 inspection found a probable problem with this proposal; a "
           "candidate label is given. Everything else stayed in A/C.*", ""]
    for e, cl, pl, pa, src in by_group["B"]:
        md.append(card(e, cl, pl, pa, src, e["order"]))
    md += ["---", "", "## Group A - straightforward (28 items)", "",
           "*Evidence cleanly supports the proposal under the explicit guideline "
           "rules. Recommended action: accept - but your decision stays blank until "
           "you actually mark it.*", ""]
    for e, cl, pl, pa, src in by_group["A"]:
        md.append(card(e, cl, pl, pa, src, e["order"]))
    (HERE / "d3_review_cards.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # ---- highest-risk summary ------------------------------------------------
    pick = {e["id"]: (e, cl, pl, pa, src) for e, cl, pl, pa, src in cards}
    top = [
        "# Stage D3 - Highest-Risk Decisions (start here)",
        "",
        "Full cards: `d3_review_cards.md` - main file: `d3_review_decisions.csv`.",
        "Record choices ONLY in the CSV: `reviewer_decision` = "
        "`accept` / `revise` / `needs_adjudication` (+ optional short `reviewer_note`).",
        "",
        f"**Integrity:** {DISCLAIMER}",
        "",
        "## Do these five first",
        "",
    ]
    for aid in ["ann-d1-0033", "ann-d1-0014", "ann-d1-0030", "ann-d1-0032", "ann-d1-0002"]:
        e, cl, pl, pa, src = pick[aid]
        top.append(card(e, cl, pl, pa, src, e["order"]))
    top += [
        "## Then: Ruling R1 (one decision, twelve items)",
        "",
        "See the R1 section at the top of `d3_review_cards.md`. Mark the 12 listed "
        "items `accept` (committed reading) or `revise` + `unverifiable` (strict 1.A).",
        "",
        "## Workload estimate",
        "",
        "- 5 priority cards above: ~5 minutes.",
        "- Ruling R1 + 12 items: ~3 minutes.",
        "- Group C remainder (4 interpretation items): ~4 minutes.",
        "- Group A (28 items): ~10 minutes if you skim-accept; less if you batch "
        "`accept` after spot-checking the excerpts.",
        "",
        "Nothing is decided until you fill the CSV. Blanks stay pending; a blank is data.",
    ]
    (HERE / "d3_highest_risk_summary.md").write_text("\n".join(top) + "\n", encoding="utf-8")

    # ---- final build assertions --------------------------------------------
    assert [r["review_order"] for r in rows] == list(range(1, 47))
    for r in rows:
        for c in REVIEWER_COLUMNS:
            assert r[c] == "", r["annotation_id"]
        p = ws[r["annotation_id"]]
        assert r["proposed_label"] == p["proposed_label"], r["annotation_id"]
        assert r["proposed_abstention_assessment"] == p["proposed_abstention_assessment"]
        assert r["claim_or_question"] == " ".join(
            (qitems[r["annotation_id"]]["claim_text"]
             or qtext[qitems[r["annotation_id"]]["question_id"]]).split())
    n_rev = sum(1 for r in rows if r["recommended_action"] == "revise_proposal")
    n_adj = sum(1 for r in rows if r["recommended_action"] == "needs_adjudication")
    n_acc = sum(1 for r in rows if r["recommended_action"] == "accept_proposal")
    print(f"built: d3_review_decisions.csv ({len(rows)} rows x {len(COLUMNS)} cols)")
    print("groups: A=%d B=%d C=%d" % (len(by_group["A"]), len(by_group["B"]), len(by_group["C"])))
    print(f"machine recommendations: accept={n_acc} revise={n_rev} needs_adjudication={n_adj}")
    print("all 46 excerpts verified verbatim against stored evidence_text; "
          "reviewer columns blank")


if __name__ == "__main__":
    main()
