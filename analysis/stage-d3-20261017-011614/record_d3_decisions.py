"""Record reviewer decisions (supplied by the reviewer in the project conversation)
into d3_review_decisions.csv. Stage D3.

Safety rules enforced by construction:
  - Byte-copies the untouched pre-decision CSV to
    d3_review_decisions_predecision_snapshot.csv before the first write (audit baseline).
  - Writes ONLY the reviewer_decision and reviewer_note cells, and ONLY on the 16
    authorized rows (R1 ruling application + the four individually named decisions).
  - Machine columns (proposed_*, explanation, evidence_status, recommended_action,
    suggested_revised_label, confidence, ...) are never written. In particular
    suggested_revised_label stays machine-owned: validator check B7 couples it to the
    machine recommendation, and keeping the reviewer's label text in reviewer_note
    preserves the machine/human separation required by the review protocol.
  - Refuses to run if the CSV is neither the expected pre-decision state nor the
    expected post-decision state (no silent overwrites).
  - The schema has no reviewer_id / review_timestamp columns; none are invented.

Re-run: prints "already recorded" and exits 0 without writing when post-state holds.
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "d3_review_decisions.csv"
SNAPSHOT = HERE / "d3_review_decisions_predecision_snapshot.csv"
REVIEWER_COLS = ["reviewer_decision", "reviewer_note"]

R1_NOTE = (
    "Shared ruling R1=A (reviewer, via conversation): passage-content claims are judged "
    "against the retrieved evidence actually available; the proposal stands as drafted. "
    "Basis is the guideline ruling only - per-item reviewer evidence inspection not "
    "claimed. Absence from retrieved passages does not establish absence from the "
    "complete catalog or the real world; this is not proof that the system's answer is "
    "factually correct.")

R1_ACCEPT_IDS = ["ann-d1-0013", "ann-d1-0018", "ann-d1-0019", "ann-d1-0036",
                 "ann-d1-0037", "ann-d1-0038", "ann-d1-0040", "ann-d1-0042",
                 "ann-d1-0043", "ann-d1-0044", "ann-d1-0045"]

DECISIONS: dict[str, tuple[str, str]] = {
    # Decision B - individually named by the reviewer
    "ann-d1-0033": ("needs_adjudication",
                    "Reviewer decision supplied via conversation: needs_adjudication - "
                    "neither accepted nor rejected; further review required. Evidence and "
                    "proposed label preserved as recorded. Machine recommendation "
                    "(accept_proposal) kept unchanged as machine guidance."),
    # Decision C - individually named by the reviewer
    "ann-d1-0014": ("needs_adjudication",
                    "Reviewer decision supplied via conversation: needs_adjudication - "
                    "neither accepted nor rejected; further review required. Evidence and "
                    "proposed label preserved as recorded. Machine recommendation "
                    "(accept_proposal) kept unchanged as machine guidance."),
    # Decision D - scope choice recorded; derived label documented in the note only
    "ann-d1-0030": ("revise",
                    "Reviewer scope ruling supplied via conversation: retrieved passages = "
                    "evaluation scope (consistent with R1); an evaluation-scope decision "
                    "only, NOT a claim that CVE-2021-45046 is absent from the complete "
                    "catalog. Documented mapping: passages scope => abstention appropriate; "
                    "the reviewer's revised label 'appropriate_abstention' is recorded here "
                    "in the note because the schema has no reviewer-label column (machine "
                    "suggested_revised_label left untouched). No claim label supplied by "
                    "the reviewer; proposed_label remains not_applicable."),
    # Decision E - reviewer accepts the existing proposal
    "ann-d1-0032": ("accept",
                    "Reviewer decision supplied via conversation: accept - the existing "
                    "proposed label (supported) stands, per the schema's documented meaning "
                    "of accept. Evidence and rationale preserved as recorded. Machine "
                    "recommendation (revise_proposal -> insufficient_evidence) kept "
                    "unchanged as machine guidance and not adopted. No personal evidence "
                    "re-inspection claimed."),
    # Decision A - shared ruling R1 applied to the 12 affected items...
    **{aid: ("accept", R1_NOTE) for aid in R1_ACCEPT_IDS},
    # ...except ann-d1-0017, whose separate wording question R1 does not settle
    "ann-d1-0017": ("needs_adjudication",
                    "R1=A applied but this row is left unresolved: the separate "
                    "literal-vs-scoped wording question (Card 4) was not ruled by the "
                    "reviewer; that ruling is required before any label decision. "
                    "No label chosen here."),
}
assert len(DECISIONS) == 16, len(DECISIONS)
assert set(R1_ACCEPT_IDS) | {"ann-d1-0017"} == {
    "ann-d1-0013", "ann-d1-0017", "ann-d1-0018", "ann-d1-0019", "ann-d1-0036",
    "ann-d1-0037", "ann-d1-0038", "ann-d1-0040", "ann-d1-0042", "ann-d1-0043",
    "ann-d1-0044", "ann-d1-0045"}


def load(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, list(reader)


def post_state(fieldnames, snap_rows):
    rows = [dict(r) for r in snap_rows]
    for r in rows:
        if r["annotation_id"] in DECISIONS:
            r["reviewer_decision"], r["reviewer_note"] = DECISIONS[r["annotation_id"]]
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fieldnames, current = load(CSV_PATH)
    assert fieldnames is not None
    if len(current) != 46:
        print(f"ERROR: expected 46 rows, found {len(current)}"); return 1

    if not SNAPSHOT.exists():
        shutil.copyfile(CSV_PATH, SNAPSHOT)
        print(f"pre-decision snapshot created: {SNAPSHOT.name}")
    _, snap = load(SNAPSHOT)

    # Cell-level comparison helpers (all 15 columns compared)
    def cell_diff(a_rows, b_rows):
        diffs = []
        for a, b in zip(a_rows, b_rows):
            assert a["annotation_id"] == b["annotation_id"], "row order mismatch"
            for col in fieldnames:
                if a[col] != b[col]:
                    diffs.append((a["annotation_id"], col, a[col], b[col]))
        return diffs

    expected_post = post_state(fieldnames, snap)

    if current == expected_post:
        print("already recorded: CSV already in the expected post-decision state; "
              "no changes written.")
        return 0
    if current != snap:
        diffs = cell_diff(current, snap)
        print("ERROR: CSV matches neither the pre-decision snapshot nor the expected "
              "post-decision state. Refusing to write. Divergences vs snapshot:")
        for aid, col, _, _ in diffs[:20]:
            print(f"  {aid} :: {col}")
        print(f"  total divergent cells: {len(diffs)}")
        return 1

    # Pre-state confirmed identical to snapshot -> apply to memory, assert scope, write.
    for r in current:
        if r["annotation_id"] in DECISIONS:
            r["reviewer_decision"], r["reviewer_note"] = DECISIONS[r["annotation_id"]]

    diffs = cell_diff(current, snap)
    allowed_cols = set(REVIEWER_COLS)
    allowed_ids = set(DECISIONS)
    bad = [d for d in diffs if d[1] not in allowed_cols or d[0] not in allowed_ids]
    assert not bad, f"out-of-scope cell writes: {bad}"
    assert len(diffs) == 2 * len(DECISIONS), f"unexpected diff count {len(diffs)}"

    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(current)

    counts: dict[str, int] = {}
    for r in current:
        if r["reviewer_decision"].strip():
            counts[r["reviewer_decision"]] = counts.get(r["reviewer_decision"], 0) + 1
    blank = sum(1 for r in current if not r["reviewer_decision"].strip())
    print(f"recorded {len(DECISIONS)} reviewer decisions "
          f"({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))}); "
          f"{blank} rows left blank/pending")
    print(f"cells changed: {len(diffs)} (only reviewer_decision + reviewer_note, "
          f"only on authorized rows)")
    print(f"pre-state snapshot preserved: {SNAPSHOT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
