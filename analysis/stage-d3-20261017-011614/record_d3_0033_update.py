"""Record the reviewer's explicit ruling for ann-d1-0033 ONLY (Stage D3 update, 2026-10-17).

Reviewer supplied in the project conversation:
  reviewer_decision = revise ; human-selected label = supported ;
  reviewer_note = <verbatim text below>

Recording convention (established for ann-d1-0030 and ann-d1-0017): the CSV has no
reviewer_label column, so the human label is carried in reviewer_note as the structured
prefix "Reviewer label: <label> | " followed by the reviewer's verbatim note. Machine
columns - including suggested_revised_label - are never written (validator check B7
couples that column to the machine recommendation, which is accept_proposal here).

REVIEWER-FLAGGED INCONSISTENCY (preserved, NOT resolved here): the selected label
`supported` differs from the conflict described in the reviewer's own note text. Per the
reviewer's instruction the label is recorded exactly as selected and the note exactly as
supplied; the inconsistency is documented in the audit artifacts and the decision note,
not silently reconciled. The machine proposal (contradicted) is untouched.

Safety rules enforced by construction:
  - Byte-copies the pre-update CSV to d3_review_decisions_pre0033update_snapshot.csv.
  - Changes ONLY the reviewer_decision and reviewer_note cells of ann-d1-0033 (2 cells);
    every other cell of all 46 rows asserted byte-identical.
  - Prior state asserted = blank snapshot + the 16 first-turn decisions + the ann-d1-0017
    update, before anything is written; refuses on any mismatch.
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
UPDATE_SNAPSHOT = HERE / "d3_review_decisions_pre0033update_snapshot.csv"

from record_d3_decisions import DECISIONS          # first-turn 16 decisions (historical)
from record_d3_0017_update import (                # 0017 update (historical)
    NEW_DECISION as P0017_DECISION, NEW_NOTE as P0017_NOTE, TARGET as P0017_TARGET)

REVIEWER_NOTE_VERBATIM = (
    "The retrieved passages mark both Log4j2 and Microsoft Exchange as Known, but each "
    "explicitly states that this is per the source record and was not independently "
    "verified here. The claim's inference of independent verification conflicts with "
    "those explicit disclaimers. This decision is limited to the retrieved passages and "
    "does not establish real-world truth.")
NEW_DECISION = "revise"
NEW_NOTE = "Reviewer label: supported | " + REVIEWER_NOTE_VERBATIM
TARGET = "ann-d1-0033"


def load(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        return rd.fieldnames, list(rd)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fieldnames, current = load(CSV_PATH)
    _, blank = load(BLANK_SNAPSHOT)

    # Expected prior state = blank snapshot + first-turn decisions + 0017 update
    prior = [dict(r) for r in blank]
    for r in prior:
        if r["annotation_id"] in DECISIONS:
            r["reviewer_decision"], r["reviewer_note"] = DECISIONS[r["annotation_id"]]
    for r in prior:
        if r["annotation_id"] == P0017_TARGET:
            r["reviewer_decision"], r["reviewer_note"] = P0017_DECISION, P0017_NOTE

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
        print("already recorded: ann-d1-0033 already holds the explicit ruling; no write.")
        return 0

    if current != prior:
        print("ERROR: CSV matches neither the expected prior state "
              "(16 first-turn decisions + 0017 update, 0033=needs_adjudication) "
              "nor the expected updated state. Refusing to write.")
        print("  divergences vs prior:", cell_diff(current, prior)[:10])
        return 1

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

    print(f"recorded: {TARGET} reviewer_decision={NEW_DECISION!r}; "
          f"reviewer_note = prefix 'Reviewer label: supported | ' + reviewer's verbatim text")
    print("REVIEWER-FLAGGED INCONSISTENCY preserved as supplied: label `supported` vs "
          "note text describing a conflict; documented in audit + decision note, not resolved.")
    counts: dict[str, int] = {}
    for r in current:
        if r["reviewer_decision"].strip():
            counts[r["reviewer_decision"]] = counts.get(r["reviewer_decision"], 0) + 1
    blank_n = sum(1 for r in current if not r["reviewer_decision"].strip())
    print(f"decision distribution now: {counts}; blank/pending rows: {blank_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
