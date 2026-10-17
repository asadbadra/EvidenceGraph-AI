"""Record the reviewer's corrected ruling for ann-d1-0012 ONLY (Stage D3 correction,
2026-10-17).

Reviewer supplied in the project conversation (explicit correction authorization):
  ann-d1-0012: needs_adjudication -> accept (the existing machine-proposed label
  insufficient_evidence stands as the reviewer-approved label).

Provenance requirement: the note records that this CORRECTS the earlier held decision
(the §11 needs_adjudication ruling), which is preserved in the snapshot chain rather
than erased.

Conventions honored (§3/§7-§11 of d3_reviewer_decision_note.md): no reviewer_label
column exists; the accepted label is named inside reviewer_note. Machine columns -
including suggested_revised_label - are never written (validator B7).

Safety rules enforced by construction:
  - Byte-copies the pre-correction CSV to d3_review_decisions_pre0012correction_snapshot.csv
    before the first write; all six older snapshots preserved untouched.
  - Changes ONLY reviewer_decision + reviewer_note of ann-d1-0012 (2 cells asserted
    exactly); every other cell of all 46 rows asserted byte-identical.
  - Prior state asserted = the full guarded composite through final4 (blank + 16 + 0017
    + 0033 + 0014 + batch30 + final4) with ann-d1-0012 still needs_adjudication; refuses
    on any mismatch (no silent overwrite of any other decision).
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
UPDATE_SNAPSHOT = HERE / "d3_review_decisions_pre0012correction_snapshot.csv"

from record_d3_decisions import DECISIONS as D16
from record_d3_0017_update import NEW_DECISION as D17, NEW_NOTE as N17
from record_d3_0033_update import NEW_DECISION as D33, NEW_NOTE as N33
from record_d3_0014_update import NEW_DECISION as D14, NEW_NOTE as N14
from record_d3_batch30_update import (ACCEPT_IDS as B_ACC, REVISE_TARGET as B_TGT,
                                      REVISE_NOTE as B_NOTE, accept_note)
from record_d3_final4_update import DECISIONS4

TARGET = "ann-d1-0012"
NEW_DECISION = "accept"
NEW_NOTE = ("Reviewer decision: accept (corrects the earlier needs_adjudication hold for "
            "this item). The reviewer accepts the existing proposed label, "
            "insufficient_evidence: the evaluative 'significant' clause is the unsupported "
            "weakest part of the compound claim, and no passage assigns severity or "
            "ranking to any product. Machine-proposed fields preserved unchanged.")


def load(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        return rd.fieldnames, list(rd)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fieldnames, current = load(CSV_PATH)
    _, blank = load(BLANK_SNAPSHOT)
    assert len(current) == 46

    # Expected prior state = the full guarded composite through final4
    prior = [dict(r) for r in blank]
    for r in prior:
        if r["annotation_id"] in D16:
            r["reviewer_decision"], r["reviewer_note"] = D16[r["annotation_id"]]
    for tgt, d, n in (("ann-d1-0017", D17, N17), ("ann-d1-0033", D33, N33),
                      ("ann-d1-0014", D14, N14)):
        for r in prior:
            if r["annotation_id"] == tgt:
                r["reviewer_decision"], r["reviewer_note"] = d, n
    for r in prior:
        if r["annotation_id"] in B_ACC:
            r["reviewer_decision"], r["reviewer_note"] = "accept", accept_note(r)
        elif r["annotation_id"] == B_TGT:
            r["reviewer_decision"], r["reviewer_note"] = "revise", B_NOTE
    for r in prior:
        if r["annotation_id"] in DECISIONS4:
            r["reviewer_decision"], r["reviewer_note"] = DECISIONS4[r["annotation_id"]]

    # Expected updated state = prior with only ann-d1-0012 corrected
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
        print("already recorded: the ann-d1-0012 correction is already in the CSV; no write.")
        return 0

    if current != prior:
        print("ERROR: CSV matches neither the expected prior state (guarded composite "
              "through final4, 0012=needs_adjudication) nor the expected corrected "
              "state. Refusing to write.")
        print("  divergences vs prior:", cell_diff(current, prior)[:12])
        return 1

    # Guards: the correction target is the held row; machine label is the one being accepted
    by = {r["annotation_id"]: r for r in current}
    assert by[TARGET]["reviewer_decision"] == "needs_adjudication", "unexpected prior decision"
    assert by[TARGET]["proposed_label"] == "insufficient_evidence"
    assert not by[TARGET]["suggested_revised_label"].strip()

    shutil.copyfile(CSV_PATH, UPDATE_SNAPSHOT)
    print(f"pre-correction snapshot created: {UPDATE_SNAPSHOT.name}")
    print(f"  snapshot sha256: {hashlib.sha256(UPDATE_SNAPSHOT.read_bytes()).hexdigest()}")

    for r in current:
        if r["annotation_id"] == TARGET:
            old = (r["reviewer_decision"], r["reviewer_note"])
            r["reviewer_decision"], r["reviewer_note"] = NEW_DECISION, NEW_NOTE
            print(f"  previous: decision={old[0]!r} note={old[1][:70]!r}...")

    diffs = cell_diff(current, prior)
    assert diffs == [(TARGET, "reviewer_decision"), (TARGET, "reviewer_note")], diffs

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
    print(f"recorded: {TARGET} needs_adjudication -> accept (accepted label: "
          f"insufficient_evidence, named in the note); cells changed: {len(diffs)}")
    print(f"decision distribution now: {counts}; blank rows: {blank_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
