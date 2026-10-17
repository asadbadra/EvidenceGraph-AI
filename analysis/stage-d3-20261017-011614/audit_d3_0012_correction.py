"""Read-only audit of the ann-d1-0012 correction (Stage D3, 2026-10-17).

Additive check set for this single-row correction. Verifies: pre-correction bytes
preserved in the new snapshot; exactly 2 cells changed (ann-d1-0012's two reviewer
fields); the correction note recorded verbatim with the accepted label named; machine
columns and all other 45 rows byte-identical; all seven snapshots intact; DB/git
unchanged. Modifies nothing.
"""
from __future__ import annotations

import csv
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TARGET = "ann-d1-0012"
PREUPDATE_SHA = "3ef6fae315634c970d259888c67c15f7d01f9184d23113e0d671884eb84ec5ad"
DB_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
GIT_HEAD = "d4ea26d"

from record_d3_0012_correction import NEW_DECISION, NEW_NOTE

results: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def load(p: Path):
    with p.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        return rd.fieldnames, list(rd)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


print("\n=== ann-d1-0012 correction audit ===")
cols, rows = load(HERE / "d3_review_decisions.csv")
_, snap0 = load(HERE / "d3_review_decisions_predecision_snapshot.csv")
_, snapC = load(HERE / "d3_review_decisions_pre0012correction_snapshot.csv")
by = {r["annotation_id"]: r for r in rows}
b0 = {r["annotation_id"]: r for r in snap0}
bC = {r["annotation_id"]: r for r in snapC}

check("K1 schema intact: 46 rows x 15 cols, ids unique", len(rows) == 46 and len(cols) == 15
      and len(set(by)) == 46)
check("K2 pre-correction bytes preserved (new snapshot sha == pre-write baseline)",
      sha(HERE / "d3_review_decisions_pre0012correction_snapshot.csv") == PREUPDATE_SHA)
check("K3 all six older snapshots untouched (predecision/0017/0033/0014/batch30/hold4)",
      sha(HERE / "d3_review_decisions_predecision_snapshot.csv")
      == "65bd58ce3a79e66f4009cbc653cac2726ed38c48ed6c9c8174e1a6fa545d8ac5"
      and sha(HERE / "d3_review_decisions_pre0017update_snapshot.csv")
      == "31751232964d54fc720d050b0faba109691b030947127ce1765a584363e6a40f"
      and sha(HERE / "d3_review_decisions_pre0033update_snapshot.csv")
      == "dc013c26fc18580a813b45029916269278b2f6492980e6cbd07c88b181db9f13"
      and sha(HERE / "d3_review_decisions_pre0014update_snapshot.csv")
      == "303f7f609443a464f619ef423660e7481f9e115d11e512064a3d6ee970ef3451"
      and sha(HERE / "d3_review_decisions_prebatch30update_snapshot.csv")
      == "95ad984d4c7f37d1eeb01b76f5af2dbe4ee5866758534a316ee847821a22286e"
      and sha(HERE / "d3_review_decisions_prefixhold4_snapshot.csv")
      == "2ba3f58409db5714d67c8ac67a5b61cfab6ef80656b10608df8ce9c0f3d290da")

diffC = {(a, c) for a in by for c in cols if by[a][c] != bC[a][c]}
check("K4 vs pre-correction snapshot: exactly 2 cells changed, both ann-d1-0012 reviewer fields",
      diffC == {(TARGET, "reviewer_decision"), (TARGET, "reviewer_note")}, f"cells={len(diffC)}")
mach_bad = [a for a in by for c in cols
            if c not in ("reviewer_decision", "reviewer_note") and by[a][c] != bC[a][c]]
check("K5 every machine-owned column byte-identical on all 46 rows", not mach_bad,
      f"violations={mach_bad[:3]}")
diff0 = {(a, c) for a in by for c in cols if by[a][c] != b0[a][c]}
check("K6 vs original blank snapshot: 46 rows x 2 cells = 92 reviewer cells",
      len(diff0) == 92 and all(c in ("reviewer_decision", "reviewer_note") for _, c in diff0))

t = by[TARGET]
check("K7 correction recorded exactly: decision=accept + note verbatim, records that it "
      "corrects the earlier hold, and names the accepted label insufficient_evidence",
      t["reviewer_decision"] == NEW_DECISION and t["reviewer_note"] == NEW_NOTE
      and "corrects the earlier needs_adjudication hold" in t["reviewer_note"]
      and "insufficient_evidence" in t["reviewer_note"])
check("K8 0012 machine fields untouched: proposed_label stays insufficient_evidence, "
      "suggested_revised_label still empty, evidence/confidence byte-identical to snapshot",
      t["proposed_label"] == "insufficient_evidence"
      and not t["suggested_revised_label"].strip()
      and all(t[c] == bC[TARGET][c] for c in cols if c not in ("reviewer_decision", "reviewer_note")))
counts: dict[str, int] = {}
for r in rows:
    d = r["reviewer_decision"].strip()
    if d:
        counts[d] = counts.get(d, 0) + 1
check("K9 final distribution: accept=40, revise=6, needs_adjudication=0, blank=0",
      counts == {"accept": 40, "revise": 6}
      and sum(1 for r in rows if not r["reviewer_decision"].strip()) == 0, str(counts))
check("K10 the other 45 rows byte-identical to the pre-correction snapshot",
      all(by[a] == bC[a] for a in by if a != TARGET))
held_history = bC[TARGET]["reviewer_decision"] == "needs_adjudication" \
    and bC[TARGET]["reviewer_note"].startswith("Held for adjudication.")
check("K11 the superseded hold ruling is preserved in the snapshot (audit history, not erased)",
      held_history)

note_txt = (HERE / "d3_reviewer_decision_note.md").read_text(encoding="utf-8")
check("K12 decision note documents the correction (section 12): correction statement, snapshot sha",
      "## 12." in note_txt and PREUPDATE_SHA in note_txt
      and "d3_review_decisions_pre0012correction_snapshot.csv" in note_txt
      and "corrects" in note_txt.lower())
check("K13 source DB sha256 unchanged; eval-run DB untouched",
      sha(REPO / "data/evidencegraph.db") == DB_SHA
      and sha(REPO / "runs/eval-postgate22-20261016-141416/evidencegraph-eval.db")
      == "ed3c4f0d2ee713dd784fefac6378daa015091ce3890d9317265d41c763863d59")
head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
gdiff = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only"],
                       capture_output=True, text=True).stdout.strip()
check("K14 git: HEAD unchanged, no tracked file modified", head == GIT_HEAD and not gdiff,
      f"head={head}")
vrep = (HERE / "d3_validation_report.md").read_text(encoding="utf-8")
check("K15 validator report (regenerated this turn): 26/27, sole FAIL = B6 (pre-existing expected warning)",
      "26/27 checks PASS" in vrep and "B6 reviewer columns 100% blank | FAIL |" in vrep
      and vrep.count("| FAIL |") == 1)
import_re = re.compile(
    r"^\s*(?:import|from)\s+(requests|httpx|socket|urllib|smtplib|ftplib|telnetlib)\b", re.M)
check("K16 new scripts: no network-module imports",
      not [s for s in ("record_d3_0012_correction.py", "audit_d3_0012_correction.py")
           if import_re.search((HERE / s).read_text(encoding="utf-8"))])

passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} audit checks PASS")
raise SystemExit(0 if passed == len(results) else 1)
