"""Record the reviewer's four approved final Stage D3 decisions (the former HOLD set)
for these four annotation IDs ONLY (Stage D3 final-4 update, 2026-10-17).

Reviewer supplied in the project conversation (explicit authorization, this turn):
  - ann-d1-0012: needs_adjudication + note (held for adjudication; NO final claim label)
  - ann-d1-0015: revise, reviewer label supported (carried in the note's structured prefix,
    exactly as the reviewer wrote it)
  - ann-d1-0023: accept (proposed label supported preserved)
  - ann-d1-0035: accept (proposed label supported preserved)
No other annotation's decision may change.

Recording conventions honored (established in §3/§7-§10 of d3_reviewer_decision_note.md):
  - The schema has no reviewer_label column; a human label travels in reviewer_note as the
    structured prefix "Reviewer label: <label> | ". ann-d1-0015's reviewer-supplied note
    already begins with that prefix and is stored verbatim.
  - Machine columns - including suggested_revised_label - are never written (validator B7).

Safety rules enforced by construction:
  - Byte-copies the pre-update CSV to d3_review_decisions_prefixhold4_snapshot.csv before
    the first write; all five older snapshots preserved untouched.
  - Changes ONLY reviewer_decision + reviewer_note, ONLY on the 4 authorized ids
    (8 cells asserted exactly); every other cell of all 46 rows asserted byte-identical.
  - Prior state asserted = blank snapshot + first-turn 16 + 0017 + 0033 + 0014 + batch30
    composite, before anything is written; refuses on any mismatch (no silent overwrite).
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
UPDATE_SNAPSHOT = HERE / "d3_review_decisions_prefixhold4_snapshot.csv"

from record_d3_decisions import DECISIONS as D16
from record_d3_0017_update import (NEW_DECISION as D17, NEW_NOTE as N17)
from record_d3_0033_update import (NEW_DECISION as D33, NEW_NOTE as N33)
from record_d3_0014_update import (NEW_DECISION as D14, NEW_NOTE as N14)
from record_d3_batch30_update import (ACCEPT_IDS as B_ACC, REVISE_TARGET as B_TGT,
                                      REVISE_NOTE as B_NOTE, accept_note)

DECISIONS4: dict[str, tuple[str, str]] = {
    # 0012 - held for adjudication; no final claim label assigned
    "ann-d1-0012": ("needs_adjudication",
                    "Held for adjudication. The unsupported evaluative significance is the "
                    "weakest part of the compound claim. No final claim label is approved "
                    "at this time."),
    # 0015 - revise to supported (reviewer's note already carries the label prefix; verbatim)
    "ann-d1-0015": ("revise",
                    'Reviewer label: supported | The retrieved passages support the intended '
                    'two-product list (Log4j2 and Exchange Server), but the stored claim is '
                    'truncated after "are: 1.". This decision evaluates the intended substance '
                    'rather than the incomplete stored fragment; the truncation remains a '
                    'claim-storage/extraction defect.'),
    # 0023 - accept
    "ann-d1-0023": ("accept",
                    'Reviewer decision: accept. The claim\'s core statement is supported by '
                    'the retrieved passage, and "significant security concern" is read in its '
                    'natural context as describing the documented impact, not as an '
                    'independent severity rating.'),
    # 0035 - accept
    "ann-d1-0035": ("accept",
                    "Reviewer decision: accept. Under the natural contextual reading, the "
                    "retrieved Exchange advisory pairs CWE-918 with the RCE advisory and "
                    "states that the vulnerability allows remote code execution. No external "
                    "CWE taxonomy knowledge is used."),
}
assert set(DECISIONS4) == {"ann-d1-0012", "ann-d1-0015", "ann-d1-0023", "ann-d1-0035"}


def load(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        return rd.fieldnames, list(rd)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fieldnames, current = load(CSV_PATH)
    _, blank = load(BLANK_SNAPSHOT)
    assert len(current) == 46

    # Expected prior state = the established guarded composite through batch30
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

    # Expected updated state = prior with only the 4 authorized changes
    updated = [dict(r) for r in prior]
    for r in updated:
        if r["annotation_id"] in DECISIONS4:
            r["reviewer_decision"], r["reviewer_note"] = DECISIONS4[r["annotation_id"]]

    def cell_diff(a_rows, b_rows):
        diffs = []
        for a, b in zip(a_rows, b_rows):
            assert a["annotation_id"] == b["annotation_id"], "row order mismatch"
            for col in fieldnames:
                if a[col] != b[col]:
                    diffs.append((a["annotation_id"], col))
        return diffs

    if current == updated:
        print("already recorded: the four final decisions are already in the CSV; no write.")
        return 0

    if current != prior:
        print("ERROR: CSV matches neither the expected prior state (guarded composite "
              "through batch30; the four target rows blank) nor the expected updated "
              "state. Refusing to write.")
        print("  divergences vs prior:", cell_diff(current, prior)[:12])
        return 1

    # Guards: targets blank pre-write; machine labels match the approvals' references
    by = {r["annotation_id"]: r for r in current}
    assert all(not by[a]["reviewer_decision"].strip() and not by[a]["reviewer_note"].strip()
               for a in DECISIONS4), "target not blank"
    assert by["ann-d1-0012"]["proposed_label"] == "insufficient_evidence"
    assert by["ann-d1-0015"]["proposed_label"] == "unverifiable"
    assert by["ann-d1-0023"]["proposed_label"] == "supported"
    assert by["ann-d1-0035"]["proposed_label"] == "supported"
    assert all(not by[a]["suggested_revised_label"].strip() for a in DECISIONS4)

    shutil.copyfile(CSV_PATH, UPDATE_SNAPSHOT)
    print(f"pre-update snapshot created: {UPDATE_SNAPSHOT.name}")
    print(f"  snapshot sha256: {hashlib.sha256(UPDATE_SNAPSHOT.read_bytes()).hexdigest()}")

    for r in current:
        if r["annotation_id"] in DECISIONS4:
            r["reviewer_decision"], r["reviewer_note"] = DECISIONS4[r["annotation_id"]]

    diffs = cell_diff(current, prior)
    want = {(a, c) for a in DECISIONS4 for c in ("reviewer_decision", "reviewer_note")}
    assert set(diffs) == want and len(diffs) == 8, (len(diffs), set(diffs) ^ want)

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
    print("recorded: 4 decisions (0012 needs_adjudication/held, 0015 revise->supported, "
          "0023 accept, 0035 accept); cells changed: 8 (reviewer columns only, "
          "authorized ids only)")
    print(f"decision distribution now: {counts}; blank rows: {blank_n} "
          "(0012 carries needs_adjudication and remains held for adjudication)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
