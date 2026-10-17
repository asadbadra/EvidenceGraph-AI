"""Stage D1: build the review workspace from the Stage D queue + authored proposals.

Deterministic (no timestamps at runtime, no randomness, stdlib only):
  analysis/stage-d-20261017-000041/d1_proposed_judgments.json  (authored proposals)
  analysis/stage-d-20261016-213744/human_review_queue.json    (read-only source)
  data/sample/eval_questions.json                             (read-only source)

Outputs (written ONLY inside this script's directory):
  proposed_judgments.csv        machine-drafted proposals, clearly marked unconfirmed
  review_workspace.csv          Excel-friendly confirmation workspace (human fields empty)
  review_confirmation_sheet.md  compact accept/revise/reject view

Integrity rules enforced here:
  - No system verdict column is emitted into any output (blind confirmation surface).
  - Every human-judgment field is emitted EMPTY (no promotion of proposals to human labels).
  - Original identifiers, claim texts, evidence references are copied verbatim.
  - The script reads sources only; it never writes outside its own directory.
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
PROPOSALS_PATH = HERE / "d1_proposed_judgments.json"

CLAIM_LABELS = {"supported", "contradicted", "insufficient_evidence", "unverifiable"}
CITATION_LABELS = CLAIM_LABELS | {"not_applicable"}
ABSTENTION_LABELS = {"appropriate_abstention", "inappropriate_abstention", "uncertain"}
PROPOSAL_STATUS = {"proposed_unconfirmed", "needs_adjudication"}
D1_REVIEW_STATUS = {"unreviewed", "proposed", "confirmed", "uncertain", "needs_adjudication"}

WORKSPACE_COLUMNS = [
    "annotation_id", "review_category", "review_status", "priority_tier",
    "question_id", "question_category", "question_text",
    "claim_id", "claim_text",
    "source_run_id", "source_claim_row_ref",
    "paired_baseline_answer", "paired_verified_answer",
    "evidence_chunk_ids", "evidence_document_ids", "evidence_selection_sources",
    "evidence_text", "stored_citation_ids",
    "proposed_label", "proposed_abstention_assessment", "proposed_rationale",
    "proposed_uncertainty_notes", "policy_alternative_label", "proposal_status",
    "human_label", "human_rationale", "evidence_sufficiency_rationale",
    "citation_support_label", "citation_support_rationale", "abstention_assessment",
    "reviewer_decision", "reviewer_id", "review_timestamp", "uncertainty_notes",
    "adjudicated_label", "adjudication_rationale",
]

PROPOSAL_COLUMNS = [
    "annotation_id", "item_type", "priority_tier", "question_id", "claim_id",
    "proposed_label", "proposed_abstention_assessment",
    "proposed_rationale", "proposed_evidence_sufficiency_rationale",
    "proposed_citation_support_label", "proposed_citation_support_rationale",
    "evidence_reference", "uncertainty_notes", "policy_alternative_label",
    "proposal_status", "proposed_by", "authored_at_utc",
]

# Columns that must be emitted EMPTY in the workspace (human/adjudication layer only).
HUMAN_EMPTY_COLUMNS = [
    "human_label", "human_rationale", "evidence_sufficiency_rationale",
    "citation_support_label", "citation_support_rationale", "abstention_assessment",
    "reviewer_decision", "reviewer_id", "review_timestamp", "uncertainty_notes",
    "adjudicated_label", "adjudication_rationale",
]


def load() -> tuple[list[dict], dict, dict, dict]:
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]}
    proposals = json.loads(PROPOSALS_PATH.read_text(encoding="utf-8"))
    items = queue["items"]
    entries = proposals["entries"]

    # Coverage: exactly the 46 queue items, same order, no duplicates, no extras.
    q_ids = [i["annotation_id"] for i in items]
    p_ids = [e["annotation_id"] for e in entries]
    assert len(items) == 46, f"queue has {len(items)} items"
    assert len(entries) == 46, f"proposals have {len(entries)} entries"
    assert q_ids == p_ids, "proposal ids/order must match queue ids/order exactly"
    assert len(set(q_ids)) == 46, "duplicate annotation ids"
    return items, questions, proposals, {e["annotation_id"]: e for e in entries}


def evidence_fields(item: dict) -> tuple[str, str, str, str]:
    ev = item["evidence_text_or_reference"]
    ids = ",".join(str(e["chunk_id"]) for e in ev)
    docs = ",".join(e["document_external_id"] for e in ev)
    srcs = ",".join(e["selection_source"] for e in ev)
    blocks = [
        f"=== chunk {e['chunk_id']} | {e['document_external_id']} | {e['selection_source']} ===\n{e['text']}"
        for e in ev
    ]
    return ids, docs, srcs, "\n\n".join(blocks)


def validate_proposal(e: dict, item: dict) -> None:
    assert e["proposal_status"] in PROPOSAL_STATUS, e
    assert e["proposed_citation_support_label"] in CITATION_LABELS, e
    assert e["proposed_rationale"].strip(), f"{e['annotation_id']}: empty rationale"
    assert e["proposed_evidence_sufficiency_rationale"].strip(), e
    assert e["proposed_citation_support_rationale"].strip(), e
    assert e["evidence_reference"].strip(), e
    assert e["short_rationale"].strip(), e
    if e["proposed_abstention_assessment"] in ABSTENTION_LABELS:
        assert item["item_type"] == "abstention_question", e["annotation_id"]
        assert e["proposed_label"] == "not_applicable", e["annotation_id"]
        assert e["proposed_abstention_assessment"] != "not_applicable", e["annotation_id"]
    else:
        assert e["proposed_abstention_assessment"] == "not_applicable", e["annotation_id"]
        assert item["item_type"] == "claim", e["annotation_id"]
        assert e["proposed_label"] in CLAIM_LABELS, e["annotation_id"]
    if e["proposal_status"] == "needs_adjudication":
        assert e["uncertainty_notes"].strip(), f"{e['annotation_id']}: adjudication needs notes"


def build_workspace_row(item: dict, q: dict, e: dict) -> dict:
    ids, docs, srcs, text = evidence_fields(item)
    cites = item["retrieved_evidence_ids"]
    row = {
        "annotation_id": item["annotation_id"],
        "review_category": "claim_level" if item["item_type"] == "claim" else "question_level_abstention",
        "review_status": ("needs_adjudication" if e["proposal_status"] == "needs_adjudication"
                          else "proposed"),
        "priority_tier": item["item_priority"],
        "question_id": item["question_id"],
        "question_category": q["category"],
        "question_text": q["question"],
        "claim_id": "" if item["claim_id"] is None else item["claim_id"],
        "claim_text": item["claim_text"] or "",
        "source_run_id": item["run_id"],
        "source_claim_row_ref": item["source_artifact_refs"]["claim_row_source"],
        "paired_baseline_answer": item["paired_answer_texts"]["baseline"] or "",
        "paired_verified_answer": item["paired_answer_texts"]["verified"] or "",
        "evidence_chunk_ids": ids,
        "evidence_document_ids": docs,
        "evidence_selection_sources": srcs,
        "evidence_text": text,
        "stored_citation_ids": "" if cites is None else json.dumps(cites),
        "proposed_label": e["proposed_label"],
        "proposed_abstention_assessment": e["proposed_abstention_assessment"],
        "proposed_rationale": e["proposed_rationale"],
        "proposed_uncertainty_notes": e["uncertainty_notes"],
        "policy_alternative_label": e["policy_alternative_label"],
        "proposal_status": e["proposal_status"],
    }
    for col in HUMAN_EMPTY_COLUMNS:
        row[col] = ""
    return row


def build_proposal_row(item: dict, e: dict, proposals: dict) -> dict:
    return {
        "annotation_id": item["annotation_id"],
        "item_type": item["item_type"],
        "priority_tier": item["item_priority"],
        "question_id": item["question_id"],
        "claim_id": "" if item["claim_id"] is None else item["claim_id"],
        "proposed_label": e["proposed_label"],
        "proposed_abstention_assessment": e["proposed_abstention_assessment"],
        "proposed_rationale": e["proposed_rationale"],
        "proposed_evidence_sufficiency_rationale": e["proposed_evidence_sufficiency_rationale"],
        "proposed_citation_support_label": e["proposed_citation_support_label"],
        "proposed_citation_support_rationale": e["proposed_citation_support_rationale"],
        "evidence_reference": e["evidence_reference"],
        "uncertainty_notes": e["uncertainty_notes"],
        "policy_alternative_label": e["policy_alternative_label"],
        "proposal_status": e["proposal_status"],
        "proposed_by": proposals["proposed_by"],
        "authored_at_utc": proposals["authored_at_utc"],
    }


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    assert all(list(r.keys()) == columns for r in rows), "column order mismatch"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)


def write_confirmation_sheet(items: list[dict], qmap: dict, amap: dict) -> None:
    lines = [
        "# Stage D1 - Confirmation Sheet (compact view)",
        "",
        "**Status: every row below is a MACHINE-DRAFTED proposal (`proposed_unconfirmed`). "
        "No human has confirmed anything yet. Nothing here is a human label.**",
        "",
        "How to use (~10 minutes for the full 46): read the evidence and rationale, then mark one "
        "decision per item and record it in `review_workspace.csv` "
        "(`reviewer_decision` = accept / revise / reject, then fill the `human_*` fields you confirm or change).",
        "",
        "- **accept** = you checked the evidence and agree with the proposed label.",
        "- **revise** = you disagree; write your label and reason in the workspace human fields.",
        "- **reject** = the proposal is wrong and you cannot supply a better label; leave `human_label` "
        "blank and explain in `uncertainty_notes` (a blank is data; a guess is not).",
        "",
        "Full evidence text: `review_workspace.csv` (evidence_text column). "
        "Proposals in full: `proposed_judgments.csv`. "
        "Guidelines: `../stage-d-20261016-213744/human_annotation_guidelines.md`.",
        "",
        "| Annotation | Tier | Question / Claim | Proposed label | Why (one line) | Decision |",
        "|---|---|---|---|---|---|",
    ]
    for item in items:
        e = amap[item["annotation_id"]]
        q = qmap[item["question_id"]]
        subject = item["claim_text"] or f"(abstention) {q['question']}"
        subject = subject.replace("|", "/").replace("\n", " ")
        if len(subject) > 110:
            subject = subject[:107] + "..."
        proposed = e["proposed_label"]
        if item["item_type"] == "abstention_question":
            proposed = e["proposed_abstention_assessment"]
        short = e["short_rationale"].replace("|", "/").replace("\n", " ")
        status = "" if e["proposal_status"] == "proposed_unconfirmed" else " **[adjudicate]**"
        lines.append(
            f"| {item['annotation_id']} | {item['item_priority']} | {subject} | "
            f"{proposed}{status} | {short} | [ ] accept  [ ] revise  [ ] reject |"
        )
    lines += [
        "",
        "Record decisions in `review_workspace.csv`; this sheet is a reading aid, not the record.",
    ]
    (HERE / "review_confirmation_sheet.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    items, qmap, proposals, amap = load()
    for item in items:
        validate_proposal(amap[item["annotation_id"]], item)

    ws_rows = [build_workspace_row(it, qmap[it["question_id"]], amap[it["annotation_id"]]) for it in items]
    pj_rows = [build_proposal_row(it, amap[it["annotation_id"]], proposals) for it in items]

    # Workspace integrity: identifiers verbatim, human layer empty, no verdict leakage.
    for item, row in zip(items, ws_rows):
        assert row["question_id"] == item["question_id"]
        assert row["claim_text"] == (item["claim_text"] or "")
        assert row["evidence_chunk_ids"], row["annotation_id"]
        assert row["evidence_text"], row["annotation_id"]
        for col in HUMAN_EMPTY_COLUMNS:
            assert row[col] == "", f"{row['annotation_id']}: {col} must be empty"
    banned = ("system_verdict", "verdict", "grounding_ratio", "proposed_ai_label", "diagnostics")
    for col in WORKSPACE_COLUMNS + PROPOSAL_COLUMNS:
        assert not any(b in col.lower() for b in banned), f"leaky column name: {col}"

    write_csv(HERE / "review_workspace.csv", WORKSPACE_COLUMNS, ws_rows)
    write_csv(HERE / "proposed_judgments.csv", PROPOSAL_COLUMNS, pj_rows)
    write_confirmation_sheet(items, qmap, amap)

    n_adj = sum(1 for e in amap.values() if e["proposal_status"] == "needs_adjudication")
    from collections import Counter
    labels = Counter(
        (amap[i["annotation_id"]]["proposed_abstention_assessment"]
         if i["item_type"] == "abstention_question"
         else amap[i["annotation_id"]]["proposed_label"])
        for i in items
    )
    print(f"built: review_workspace.csv ({len(ws_rows)} rows x {len(WORKSPACE_COLUMNS)} cols)")
    print(f"built: proposed_judgments.csv ({len(pj_rows)} rows x {len(PROPOSAL_COLUMNS)} cols)")
    print("built: review_confirmation_sheet.md (46 rows)")
    print("assessment/label distribution:", dict(labels))
    print(f"needs_adjudication: {n_adj} | proposed_unconfirmed: {46 - n_adj} | human-confirmed: 0")


if __name__ == "__main__":
    main()
