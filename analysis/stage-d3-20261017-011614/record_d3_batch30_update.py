"""Record the reviewer-approved Stage D3 batch decisions (25 accept + 1 revise) for the
26 authorized items ONLY (Stage D3 batch update, 2026-10-17).

Reviewer supplied in the project conversation (batch approval, this turn):
  - 25 ids: reviewer_decision = accept (the existing machine-proposed label stands)
  - ann-d1-0020: reviewer_decision = revise, reviewer label = contradicted (note below)
  - 4 ids on HOLD (ann-d1-0012, 0015, 0023, 0035): NO decision, NO note - left pending

Recording convention (established for ann-d1-0030, 0017, 0033, 0014): the CSV has no
reviewer_label column, so the human label for a revise is carried in reviewer_note as the
structured prefix "Reviewer label: <label> | " followed by the reviewer's note. Machine
columns - including suggested_revised_label - are never written (validator check B7 couples
that column to the machine recommendation).

Safety rules enforced by construction:
  - Byte-copies the pre-update CSV to d3_review_decisions_prebatch30update_snapshot.csv
    before the first write (all four older snapshots preserved untouched).
  - Changes ONLY reviewer_decision + reviewer_note, ONLY on the 26 authorized ids
    (52 cells asserted exactly); every other cell of all 46 rows asserted byte-identical.
  - The four HOLD ids are asserted to remain blank and byte-identical to the prior state.
  - Prior state asserted = blank snapshot + first-turn 16 decisions + the ann-d1-0017,
    ann-d1-0033 and ann-d1-0014 updates, before anything is written; refuses on any mismatch.
  - Idempotent: re-running prints "already recorded" and exits 0 without writing.
"""
from __future__ import annotations

import csv
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "d3_review_decisions.csv"
BLANK_SNAPSHOT = HERE / "d3_review_decisions_predecision_snapshot.csv"
UPDATE_SNAPSHOT = HERE / "d3_review_decisions_prebatch30update_snapshot.csv"

from record_d3_decisions import DECISIONS          # historical: first-turn 16 decisions
from record_d3_0017_update import (                # historical: 0017 update
    NEW_DECISION as P17_DECISION, NEW_NOTE as P17_NOTE, TARGET as P17_TARGET)
from record_d3_0033_update import (                # historical: 0033 update
    NEW_DECISION as P33_DECISION, NEW_NOTE as P33_NOTE, TARGET as P33_TARGET)
from record_d3_0014_update import (                # historical: 0014 update
    NEW_DECISION as P14_DECISION, NEW_NOTE as P14_NOTE, TARGET as P14_TARGET)

ACCEPT_IDS = ["ann-d1-0001", "ann-d1-0002", "ann-d1-0003", "ann-d1-0004", "ann-d1-0005",
              "ann-d1-0006", "ann-d1-0007", "ann-d1-0008", "ann-d1-0009", "ann-d1-0010",
              "ann-d1-0011", "ann-d1-0016", "ann-d1-0021", "ann-d1-0022", "ann-d1-0024",
              "ann-d1-0025", "ann-d1-0026", "ann-d1-0027", "ann-d1-0028", "ann-d1-0029",
              "ann-d1-0031", "ann-d1-0034", "ann-d1-0039", "ann-d1-0041", "ann-d1-0046"]
HOLD_IDS = ["ann-d1-0012", "ann-d1-0015", "ann-d1-0023", "ann-d1-0035"]
REVISE_TARGET = "ann-d1-0020"

REVISE_NOTE = (
    "Reviewer label: contradicted | Under the retrieved-passage evaluation scope, the claim "
    "presents the product list as exhaustive, while the retrieved passages positively identify "
    "additional products. This is a judgment about the retrieved evidence and wording only; it "
    "does not establish anything about the complete corpus or the real world.")

BATCH_TAG = ("under the approved Stage D3 batch decision of 2026-10-17 "
             "(batch review package analysis/stage-d3-batch-review-20261017-150516)")


def accept_note(row: dict[str, str]) -> str:
    label = row["proposed_label"]
    if label == "not_applicable":
        return (f"Reviewer accepted the existing proposed label ({label}) and abstention "
                f"assessment ({row['proposed_abstention_assessment']}) {BATCH_TAG}. "
                "Machine-proposed fields preserved unchanged.")
    return (f"Reviewer accepted the existing proposed label ({label}) {BATCH_TAG}. "
            "Machine-proposed label, evidence, confidence, and all other machine-owned "
            "fields preserved unchanged.")


def load(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        return rd.fieldnames, list(rd)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fieldnames, current = load(CSV_PATH)
    _, blank = load(BLANK_SNAPSHOT)
    assert len(current) == 46 and len(ACCEPT_IDS) == 25 and len(HOLD_IDS) == 4
    assert not (set(ACCEPT_IDS) & set(HOLD_IDS)) and REVISE_TARGET not in set(ACCEPT_IDS) | set(HOLD_IDS)

    # Expected prior state = blank + first-turn 16 + 0017 + 0033 + 0014 updates
    prior = [dict(r) for r in blank]
    for r in prior:
        if r["annotation_id"] in DECISIONS:
            r["reviewer_decision"], r["reviewer_note"] = DECISIONS[r["annotation_id"]]
    for tgt, d, n in ((P17_TARGET, P17_DECISION, P17_NOTE),
                      (P33_TARGET, P33_DECISION, P33_NOTE),
                      (P14_TARGET, P14_DECISION, P14_NOTE)):
        for r in prior:
            if r["annotation_id"] == tgt:
                r["reviewer_decision"], r["reviewer_note"] = d, n

    # Expected updated state = prior with only the 26 authorized changes
    updated = [dict(r) for r in prior]
    for r in updated:
        if r["annotation_id"] in ACCEPT_IDS:
            r["reviewer_decision"], r["reviewer_note"] = "accept", accept_note(r)
        elif r["annotation_id"] == REVISE_TARGET:
            r["reviewer_decision"], r["reviewer_note"] = "revise", REVISE_NOTE

    def cell_diff(a_rows, b_rows):
        diffs = []
        for a, b in zip(a_rows, b_rows):
            assert a["annotation_id"] == b["annotation_id"], "row order mismatch"
            for col in fieldnames:
                if a[col] != b[col]:
                    diffs.append((a["annotation_id"], col))
        return diffs

    if current == updated:
        print("already recorded: the batch decisions are already in the CSV; no write.")
        return 0

    if current != prior:
        print("ERROR: CSV matches neither the expected prior state (16 first-turn decisions "
              "+ 0017 + 0033 + 0014 updates; batch rows blank) nor the expected updated "
              "state. Refusing to write.")
        print("  divergences vs prior:", cell_diff(current, prior)[:12])
        return 1

    # Guard: every accept target's machine proposed_label must be the one the reviewer approved
    expected_labels = {
        "ann-d1-0001": "insufficient_evidence", "ann-d1-0002": "supported",
        "ann-d1-0003": "supported", "ann-d1-0004": "insufficient_evidence",
        "ann-d1-0005": "unverifiable", "ann-d1-0006": "unverifiable",
        "ann-d1-0007": "unverifiable", "ann-d1-0008": "insufficient_evidence",
        "ann-d1-0009": "insufficient_evidence", "ann-d1-0010": "insufficient_evidence",
        "ann-d1-0011": "insufficient_evidence", "ann-d1-0016": "supported",
        "ann-d1-0021": "supported", "ann-d1-0022": "supported", "ann-d1-0024": "supported",
        "ann-d1-0025": "not_applicable", "ann-d1-0026": "not_applicable",
        "ann-d1-0027": "not_applicable", "ann-d1-0028": "not_applicable",
        "ann-d1-0029": "not_applicable", "ann-d1-0031": "supported",
        "ann-d1-0034": "supported", "ann-d1-0039": "insufficient_evidence",
        "ann-d1-0041": "supported", "ann-d1-0046": "insufficient_evidence"}
    by = {r["annotation_id"]: r for r in current}
    mismatched = {a: by[a]["proposed_label"] for a in ACCEPT_IDS
                  if by[a]["proposed_label"] != expected_labels[a]}
    assert not mismatched, f"approved labels no longer match the CSV: {mismatched}"
    assert by[REVISE_TARGET]["proposed_label"] == "insufficient_evidence"
    assert all(not by[a]["reviewer_decision"].strip() for a in HOLD_IDS)

    shutil.copyfile(CSV_PATH, UPDATE_SNAPSHOT)
    print(f"pre-update snapshot created: {UPDATE_SNAPSHOT.name}")
    print(f"  snapshot sha256: {hashlib.sha256(UPDATE_SNAPSHOT.read_bytes()).hexdigest()}")

    for r in current:
        if r["annotation_id"] in ACCEPT_IDS:
            r["reviewer_decision"], r["reviewer_note"] = "accept", accept_note(r)
        elif r["annotation_id"] == REVISE_TARGET:
            r["reviewer_decision"], r["reviewer_note"] = "revise", REVISE_NOTE

    diffs = cell_diff(current, prior)
    expected_cells = {(a, c) for a in ACCEPT_IDS + [REVISE_TARGET]
                      for c in ("reviewer_decision", "reviewer_note")}
    assert set(diffs) == expected_cells and len(diffs) == 52, (len(diffs), set(diffs) ^ expected_cells)
    for a in HOLD_IDS:
        assert by[a] == {k: v for k, v in prior[[p["annotation_id"] for p in prior].index(a)].items()}, a

    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(current)

    counts: dict[str, int] = {}
    for r in current:
        d = r["reviewer_decision"].strip()
        if d:
            counts[d] = counts.get(d, 0) + 1
    blank_n = sum(1 for r in current if not r["reviewer_decision"].strip())
    print(f"recorded: 26 decisions (25 accept + 1 revise/contradicted); "
          f"cells changed: {len(diffs)} (reviewer columns only, authorized ids only)")
    print(f"decision distribution now: {counts}; blank/pending rows: {blank_n} "
          f"(the 4 HOLD ids remain pending)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
