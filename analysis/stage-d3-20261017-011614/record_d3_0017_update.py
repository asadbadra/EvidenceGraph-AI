"""Record the reviewer's explicit ruling for ann-d1-0017 ONLY (Stage D3 update, 2026-10-17).

Reviewer supplied in the project conversation:
  reviewer_decision = revise ; reviewer_label = contradicted ; reviewer_note = <verbatim text below>

Schema note: d3_review_decisions.csv has NO reviewer_label column (only reviewer_decision
and reviewer_note carry human authority). Consistent with the ann-d1-0030 handling already
documented in d3_reviewer_decision_note.md, the reviewer's label is carried in reviewer_note
as a structured prefix, and the machine column suggested_revised_label is left untouched
(it is a machine column per the cards' integrity statement, and validator check B7 couples
it to the machine recommended_action, which is needs_adjudication for this row).

Safety rules enforced by construction:
  - Byte-copies the pre-update CSV to d3_review_decisions_pre0017update_snapshot.csv first.
  - Changes ONLY the reviewer_decision and reviewer_note cells of ann-d1-0017 (2 cells).
    All other cells of all 46 rows asserted byte-identical; machine columns never written.
  - The prior state is asserted to equal exactly what record_d3_decisions.py recorded
    (the 16 decisions from the previous turn) before anything is written; refuses otherwise.
  - Idempotent: re-running prints "already recorded" and exits 0 without writing.
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "d3_review_decisions.csv"
BLANK_SNAPSHOT = HERE / "d3_review_decisions_predecision_snapshot.csv"
UPDATE_SNAPSHOT = HERE / "d3_review_decisions_pre0017update_snapshot.csv"

from record_d3_decisions import DECISIONS  # historical record of the previous turn's 16 decisions

REVIEWER_NOTE_VERBATIM = (
    "Under the adopted R1 ruling, evaluate the claim as written against the retrieved "
    "passages. The wording says the passages only mention the FortiOS vulnerability, but "
    "the displayed retrieved set also includes Log4j, OpenSSL, and MOVEit. Therefore, the "
    "literal first clause conflicts with the shown evidence. This is a corpus-grounded "
    "judgment about the wording and retrieved set only; it does not establish anything "
    "about the complete corpus or the real world.")
NEW_DECISION = "revise"
NEW_NOTE = "Reviewer label: contradicted | " + REVIEWER_NOTE_VERBATIM
TARGET = "ann-d1-0017"


def load(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        return rd.fieldnames, list(rd)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fieldnames, current = load(CSV_PATH)
    _, blank = load(BLANK_SNAPSHOT)

    # Expected prior state = blank snapshot + the 16 previously recorded decisions
    prior = [dict(r) for r in blank]
    for r in prior:
        if r["annotation_id"] in DECISIONS:
            r["reviewer_decision"], r["reviewer_note"] = DECISIONS[r["annotation_id"]]

    # Expected updated state = prior with only ann-d1-0017 changed
    updated = [dict(r) for r in prior]
    for r in updated:
        if r["annotation_id"] == TARGET:
            r["reviewer_decision"], r["reviewer_note"] = NEW_DECISION, NEW_NOTE

    def cell_diff(a_rows, b_rows):
        diffs = []
        for a, b in zip(a_rows, b_rows):
            assert a["annotation_id"] == b["annotation_id"], "row order mismatch"
            for col in fieldnames:
                if a[col] != b[col]:
                    diffs.append((a["annotation_id"], col))
        return diffs

    if current == updated:
        print("already recorded: ann-d1-0017 already holds the explicit ruling; no write.")
        return 0

    if current != prior:
        print("ERROR: CSV matches neither the expected prior state (16 decisions, "
              "0017=needs_adjudication) nor the expected updated state. Refusing to write.")
        print("  divergences vs prior:", cell_diff(current, prior)[:10])
        return 1

    # Prior state confirmed -> snapshot bytes, apply the two-cell change, assert scope, write
    shutil.copyfile(CSV_PATH, UPDATE_SNAPSHOT)
    print(f"pre-update snapshot created: {UPDATE_SNAPSHOT.name}")

    for r in current:
        if r["annotation_id"] == TARGET:
            old = (r["reviewer_decision"], r["reviewer_note"])
            r["reviewer_decision"], r["reviewer_note"] = NEW_DECISION, NEW_NOTE
            print(f"  previous: decision={old[0]!r} note={old[1][:60]!r}...")

    diffs = cell_diff(current, prior)
    assert diffs == [(TARGET, "reviewer_decision"), (TARGET, "reviewer_note")], diffs

    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(current)

    print(f"recorded: {TARGET} reviewer_decision={NEW_DECISION!r}, "
          f"reviewer_note=prefix 'Reviewer label: contradicted | ' + reviewer's verbatim text")
    print(f"cells changed: {len(diffs)} (reviewer_decision + reviewer_note of {TARGET} only)")
    counts: dict[str, int] = {}
    for r in current:
        if r["reviewer_decision"].strip():
            counts[r["reviewer_decision"]] = counts.get(r["reviewer_decision"], 0) + 1
    blank_n = sum(1 for r in current if not r["reviewer_decision"].strip())
    print(f"decision distribution now: {counts}; blank/pending rows: {blank_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
