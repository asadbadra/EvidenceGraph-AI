"""Record the reviewer's explicit ruling for ann-d1-0014 ONLY (Stage D3 update, 2026-10-17).

Reviewer supplied in the project conversation:
  reviewer_decision = revise ; human-selected label = insufficient_evidence ;
  reviewer_note = <verbatim text below>

Recording convention (established for ann-d1-0030, ann-d1-0017 and ann-d1-0033): the CSV
has no reviewer_label column, so the human label is carried in reviewer_note as the
structured prefix "Reviewer label: <label> | " followed by the reviewer's verbatim note.
Machine columns - including suggested_revised_label - are never written (validator check
B7 couples that column to the machine recommendation).

Note (documented, not acted upon): the recorded label `insufficient_evidence` equals the
machine-proposed label for this row; the reviewer nevertheless chose reviewer_decision
`revise` while the machine recommended `accept_proposal`. Both values are recorded exactly
as the reviewer supplied them; no field is aligned either way.

Safety rules enforced by construction:
  - Byte-copies the pre-update CSV to d3_review_decisions_pre0014update_snapshot.csv.
  - Changes ONLY the reviewer_decision and reviewer_note cells of ann-d1-0014 (2 cells);
    every other cell of all 46 rows asserted byte-identical.
  - Prior state asserted = blank snapshot + the 16 first-turn decisions + the ann-d1-0017
    update + the ann-d1-0033 update, before anything is written; refuses on any mismatch.
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
UPDATE_SNAPSHOT = HERE / "d3_review_decisions_pre0014update_snapshot.csv"

from record_d3_decisions import DECISIONS          # historical: first-turn 16 decisions
from record_d3_0017_update import (                # historical: 0017 update
    NEW_DECISION as P0017_DECISION, NEW_NOTE as P0017_NOTE, TARGET as P0017_TARGET)
from record_d3_0033_update import (                # historical: 0033 update
    NEW_DECISION as P0033_DECISION, NEW_NOTE as P0033_NOTE, TARGET as P0033_TARGET)

REVIEWER_NOTE_VERBATIM = (
    "The retrieved passages identify Microsoft Exchange Server Remote Code Execution "
    "Vulnerability (CVE-2021-34473), but none contains the claimed addition date "
    "2021-11-03. The date appears only in separately inspected document metadata that "
    "was not shown to the system. No retrieved passage gives a conflicting date, so the "
    "claim is not contradicted; however, its date component is not established by the "
    "retrieved evidence. This decision is limited to the retrieved passages and does not "
    "establish real-world truth.")
NEW_DECISION = "revise"
NEW_NOTE = "Reviewer label: insufficient_evidence | " + REVIEWER_NOTE_VERBATIM
TARGET = "ann-d1-0014"


def load(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        return rd.fieldnames, list(rd)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fieldnames, current = load(CSV_PATH)
    _, blank = load(BLANK_SNAPSHOT)

    # Expected prior state = blank + first-turn decisions + 0017 update + 0033 update
    prior = [dict(r) for r in blank]
    for r in prior:
        if r["annotation_id"] in DECISIONS:
            r["reviewer_decision"], r["reviewer_note"] = DECISIONS[r["annotation_id"]]
    for r in prior:
        if r["annotation_id"] == P0017_TARGET:
            r["reviewer_decision"], r["reviewer_note"] = P0017_DECISION, P0017_NOTE
    for r in prior:
        if r["annotation_id"] == P0033_TARGET:
            r["reviewer_decision"], r["reviewer_note"] = P0033_DECISION, P0033_NOTE

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
        print("already recorded: ann-d1-0014 already holds the explicit ruling; no write.")
        return 0

    if current != prior:
        print("ERROR: CSV matches neither the expected prior state "
              "(16 first-turn decisions + 0017 update + 0033 update, 0014=needs_adjudication) "
              "nor the expected updated state. Refusing to write.")
        print("  divergences vs prior:", cell_diff(current, prior)[:10])
        return 1

    shutil.copyfile(CSV_PATH, UPDATE_SNAPSHOT)
    print(f"pre-update snapshot created: {UPDATE_SNAPSHOT.name}")
    import hashlib
    print(f"  snapshot sha256: {hashlib.sha256(UPDATE_SNAPSHOT.read_bytes()).hexdigest()}")

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
          f"reviewer_note = prefix 'Reviewer label: insufficient_evidence | ' + reviewer's verbatim text")
    counts: dict[str, int] = {}
    for r in current:
        if r["reviewer_decision"].strip():
            counts[r["reviewer_decision"]] = counts.get(r["reviewer_decision"], 0) + 1
    blank_n = sum(1 for r in current if not r["reviewer_decision"].strip())
    print(f"decision distribution now: {counts}; blank/pending rows: {blank_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
