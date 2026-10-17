"""Stage D2: build the reviewer confirmation interface.

Reads (read-only): the Stage D queue + the D1 proposal file.
Writes (only inside this directory): confirmation_decisions.csv

Rules enforced by construction:
  - Reviewer columns are emitted EMPTY. Nothing is pre-accepted, pre-decided,
    or inferred. Empty reviewer_decision == pending.
  - proposed_label / proposed_abstention_assessment / short_rationale are copied
    BYTE-FOR-BYTE from the D1 proposal file (proposals are preserved, not edited).
  - draft_recommendation is a MACHINE recommendation column, clearly named; it is
    not a decision and carries no human authority.
  - Deterministic: no runtime timestamps, stdlib only.
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
PROPOSALS_CSV = D1_DIR / "proposed_judgments.csv"
JUDGMENTS_JSON = D1_DIR / "d1_proposed_judgments.json"

COLUMNS = [
    "annotation_id", "review_priority", "decision_type", "item_type", "question_id",
    "claim_or_question",
    "proposed_label", "proposed_abstention_assessment",          # copied from D1 (byte-equal)
    "draft_recommendation", "recommendation_confidence", "open_issue", "short_rationale",
    "reviewer_decision", "revised_label", "reviewer_note", "reviewer_id", "review_timestamp",
]
REVIEWER_COLUMNS = ["reviewer_decision", "revised_label", "reviewer_note",
                    "reviewer_id", "review_timestamp"]

# P1 = decide first (contradiction, false-endorsement candidate, unresolved abstention)
P1 = {"ann-d1-0033", "ann-d1-0014", "ann-d1-0030"}
# Items whose label turns on a single guideline-1A ruling (unresolved_evidence.md D)
FAMILY_1A = {"ann-d1-0013", "ann-d1-0017", "ann-d1-0018", "ann-d1-0019", "ann-d1-0036",
             "ann-d1-0037", "ann-d1-0038", "ann-d1-0040", "ann-d1-0042", "ann-d1-0043",
             "ann-d1-0044", "ann-d1-0045"}
# Committed under the weakest-part/reading rules with a recorded alternative
BORDERLINE = {
    "ann-d1-0012": "weakest-part: 'significant' has no severity basis; recorded alternative supported",
    "ann-d1-0015": "claim truncated mid-enumeration; recorded alternative supported (substance over form)",
    "ann-d1-0017": "clause 1 literal-vs-scoped reading; strict-1A alternative unverifiable",
    "ann-d1-0020": "three-way reading: supported / insufficient_evidence (committed) / contradicted",
    "ann-d1-0023": "evaluative tail tied to documented impact; recorded alternative insufficient_evidence",
    "ann-d1-0032": "malformed compound (splitter); both clauses verify; recorded alternative unverifiable",
    "ann-d1-0035": "'which'-referent (CVE vs CWE); recorded alternative insufficient_evidence",
}
OPEN_ISSUE_1A = "guideline 1A ruling decides label (unresolved_evidence.md section D)"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    items = queue["items"]
    qtext = {q["id"]: q["question"] for q in
             json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]}

    with PROPOSALS_CSV.open(encoding="utf-8", newline="") as fh:
        props = {r["annotation_id"]: r for r in csv.DictReader(fh)}
    short = {e["annotation_id"]: e["short_rationale"]
             for e in json.loads(JUDGMENTS_JSON.read_text(encoding="utf-8"))["entries"]}

    rows = []
    for it in items:
        aid = it["annotation_id"]
        p = props[aid]
        tier = it["item_priority"]
        abstention = it["item_type"] == "abstention_question"

        if aid == "ann-d1-0030":
            rec, conf = "needs_adjudication", "needs_scope_rule"
            issue = ("scope rule needed: retrieved passages vs catalog; or fixture-author "
                     "attestation for plausible-04 (unresolved_evidence.md section E)")
        else:
            rec = "accept"
            if aid in FAMILY_1A:
                conf = "conditional_on_1A_ruling"
                issue = OPEN_ISSUE_1A
            elif aid in BORDERLINE:
                conf = "borderline_read_note"
                issue = BORDERLINE[aid]
            else:
                conf, issue = "high", ""

        if abstention:
            dtype = "abstention_adjudication" if aid == "ann-d1-0030" else "abstention"
        elif tier == 1:
            dtype = "gate_retraction"
        else:
            dtype = "stratified_claim"

        priority = "P1_decide_first" if aid in P1 else ("P2_gate_and_abstentions" if tier in (1, 3)
                                                       else "P3_standard")

        subject = it["claim_text"] or qtext[it["question_id"]]
        subject = " ".join(subject.split())
        if len(subject) > 160:
            subject = subject[:157] + "..."

        row = {
            "annotation_id": aid,
            "review_priority": priority,
            "decision_type": dtype,
            "item_type": it["item_type"],
            "question_id": it["question_id"],
            "claim_or_question": subject,
            "proposed_label": p["proposed_label"],
            "proposed_abstention_assessment": p["proposed_abstention_assessment"],
            "draft_recommendation": rec,
            "recommendation_confidence": conf,
            "open_issue": issue,
            "short_rationale": short[aid],
        }
        for col in REVIEWER_COLUMNS:
            row[col] = ""          # always empty - the reviewer writes here, never tooling
        rows.append(row)

    # ---- assertions --------------------------------------------------------
    q_ids = [i["annotation_id"] for i in items]
    assert [r["annotation_id"] for r in rows] == q_ids, "id/order mismatch"
    assert len(rows) == 46
    for r in rows:
        p = props[r["annotation_id"]]
        assert r["proposed_label"] == p["proposed_label"], r["annotation_id"]
        assert r["proposed_abstention_assessment"] == p["proposed_abstention_assessment"], r["annotation_id"]
        assert r["short_rationale"].strip(), r["annotation_id"]
        for col in REVIEWER_COLUMNS:
            assert r[col] == "", f"{r['annotation_id']}: {col} must be empty"
        assert r["draft_recommendation"] in {"accept", "needs_adjudication"}
    n_adj = sum(1 for r in rows if r["draft_recommendation"] == "needs_adjudication")

    out = HERE / "confirmation_decisions.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)

    print(f"built: confirmation_decisions.csv ({len(rows)} rows x {len(COLUMNS)} cols)")
    print(f"draft recommendations: accept={len(rows) - n_adj}, needs_adjudication={n_adj}")
    print(f"reviewer columns empty: {REVIEWER_COLUMNS} -> all empty (pending)")
    print("P1 items:", ", ".join(sorted(P1)))


if __name__ == "__main__":
    main()
