"""Read-only audit of the Stage D3 final-4 recording update (2026-10-17).

Additive checks only. Does not replace or weaken validate_stage_d3.py (B6 failure is the
expected signature of reviewer decisions being present) nor the earlier point-in-time
audits (their state-encoding checks show expected drift after this authorized update, as
their own docstrings state).

Verifies: pre-update bytes preserved in the new snapshot; exactly 8 cells changed (the 4
authorized ids' two reviewer fields); the specific approved decisions/notes recorded
exactly; ann-d1-0012 held with no final claim label; machine columns and all other rows
byte-identical; the batch30 decisions byte-identical; snapshots/DB/git/manifests
unchanged; validator not weakened. Modifies nothing.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PREUPDATE_SHA = "2ba3f58409db5714d67c8ac67a5b61cfab6ef80656b10608df8ce9c0f3d290da"
DB_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
GIT_HEAD = "d4ea26d"

from record_d3_final4_update import DECISIONS4  # the recorded rulings under audit
TARGETS = sorted(DECISIONS4)

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


print("\n=== Stage D3 final-4 recording audit ===")
cols, rows = load(HERE / "d3_review_decisions.csv")
_, snap0 = load(HERE / "d3_review_decisions_predecision_snapshot.csv")
_, snapF = load(HERE / "d3_review_decisions_prefixhold4_snapshot.csv")
by = {r["annotation_id"]: r for r in rows}
b0 = {r["annotation_id"]: r for r in snap0}
bF = {r["annotation_id"]: r for r in snapF}

check("C1 schema intact: 46 rows x 15 cols, ids unique, reviewer cols last",
      len(rows) == 46 and len(cols) == 15 and len(set(by)) == 46
      and cols[-2:] == ["reviewer_decision", "reviewer_note"])
check("C2 pre-update bytes preserved (new snapshot sha == pre-write CSV baseline)",
      sha(HERE / "d3_review_decisions_prefixhold4_snapshot.csv") == PREUPDATE_SHA)
check("C3 all five older snapshots untouched (predecision/0017/0033/0014/batch30)",
      sha(HERE / "d3_review_decisions_predecision_snapshot.csv")
      == "65bd58ce3a79e66f4009cbc653cac2726ed38c48ed6c9c8174e1a6fa545d8ac5"
      and sha(HERE / "d3_review_decisions_pre0017update_snapshot.csv")
      == "31751232964d54fc720d050b0faba109691b030947127ce1765a584363e6a40f"
      and sha(HERE / "d3_review_decisions_pre0033update_snapshot.csv")
      == "dc013c26fc18580a813b45029916269278b2f6492980e6cbd07c88b181db9f13"
      and sha(HERE / "d3_review_decisions_pre0014update_snapshot.csv")
      == "303f7f609443a464f619ef423660e7481f9e115d11e512064a3d6ee970ef3451"
      and sha(HERE / "d3_review_decisions_prebatch30update_snapshot.csv")
      == "95ad984d4c7f37d1eeb01b76f5af2dbe4ee5866758534a316ee847821a22286e")

diffF = {(a, c) for a in by for c in cols if by[a][c] != bF[a][c]}
want = {(a, c) for a in TARGETS for c in ("reviewer_decision", "reviewer_note")}
check("C4 vs pre-update snapshot: exactly 8 cells changed, all reviewer columns, all 4 authorized ids",
      diffF == want and len(diffF) == 8, f"cells={len(diffF)}")
mach_bad = [a for a in by for c in cols
            if c not in ("reviewer_decision", "reviewer_note") and by[a][c] != bF[a][c]]
check("C5 every machine-owned column byte-identical on all 46 rows", not mach_bad,
      f"violations={mach_bad[:3]}")
diff0 = {(a, c) for a in by for c in cols if by[a][c] != b0[a][c]}
check("C6 vs original blank snapshot: 46 rows x 2 cells = 92 reviewer cells (all rows now carry a reviewer field)",
      len(diff0) == 92 and all(c in ("reviewer_decision", "reviewer_note") for _, c in diff0),
      f"cells={len(diff0)}")

for aid, (d, n) in DECISIONS4.items():
    check(f"C7 {aid} recorded exactly as approved: decision={d!r} + approved note verbatim",
          by[aid]["reviewer_decision"] == d and by[aid]["reviewer_note"] == n)
check("C8 ann-d1-0012 held: needs_adjudication, note says no final label approved, "
      "machine proposed_label still insufficient_evidence, suggested_revised_label still empty",
      by["ann-d1-0012"]["reviewer_decision"] == "needs_adjudication"
      and "No final claim label is approved" in by["ann-d1-0012"]["reviewer_note"]
      and by["ann-d1-0012"]["proposed_label"] == "insufficient_evidence"
      and not by["ann-d1-0012"]["suggested_revised_label"].strip())
check("C9 ann-d1-0015: revise + reviewer label supported recorded in the note prefix; "
      "machine proposed_label untouched (stays unverifiable, machine/human separation intact)",
      by["ann-d1-0015"]["reviewer_decision"] == "revise"
      and by["ann-d1-0015"]["reviewer_note"].startswith("Reviewer label: supported | ")
      and by["ann-d1-0015"]["proposed_label"] == "unverifiable"
      and not by["ann-d1-0015"]["suggested_revised_label"].strip())
check("C10 ann-d1-0023 and ann-d1-0035 accepted; proposed labels preserved as supported",
      all(by[a]["reviewer_decision"] == "accept" and by[a]["proposed_label"] == "supported"
          and by[a]["reviewer_note"].startswith("Reviewer decision: accept.")
          for a in ("ann-d1-0023", "ann-d1-0035")))
counts: dict[str, int] = {}
for r in rows:
    d = r["reviewer_decision"].strip()
    if d:
        counts[d] = counts.get(d, 0) + 1
check("C11 final distribution: accept=39, revise=6, needs_adjudication=1, blank=0",
      counts == {"accept": 39, "revise": 6, "needs_adjudication": 1}
      and sum(1 for r in rows if not r["reviewer_decision"].strip()) == 0, str(counts))
check("C12 the 42 previously decided rows byte-identical to the pre-update snapshot",
      all(by[a] == bF[a] for a in by if a not in TARGETS))

note_txt = (HERE / "d3_reviewer_decision_note.md").read_text(encoding="utf-8")
norm = " ".join(note_txt.split())
check("C13 decision note documents this update (section 11): four rulings, held-item note, snapshot sha",
      "## 11." in note_txt and PREUPDATE_SHA in note_txt
      and "d3_review_decisions_prefixhold4_snapshot.csv" in note_txt
      and all(a in note_txt for a in TARGETS))

for label, mp, n in (("C14a Stage D1 manifest (21 files)",
                      HERE.parent / "stage-d1-20261017-000041/stage_d1_manifest.json", 21),
                     ("C14b Stage D2 manifest (14 files)",
                      HERE.parent / "stage-d2-20261017-002537/stage_d2_manifest.json", 14)):
    man = json.loads(mp.read_text(encoding="utf-8"))
    pairs = []
    def walk(node):
        if isinstance(node, dict):
            if "path" in node and "sha256" in node:
                pairs.append((node["path"], node["sha256"]))
            else:
                for v in node.values():
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(man)
    ok = all((REPO / rel).exists() and sha(REPO / rel) == d for rel, d in pairs)
    check(f"{label} hash-verified unchanged", ok and len(pairs) == n, f"{len(pairs)} files")
check("C15 source DB sha256 unchanged; eval-run DB untouched; no DB copied into D3",
      sha(REPO / "data/evidencegraph.db") == DB_SHA
      and sha(REPO / "runs/eval-postgate22-20261016-141416/evidencegraph-eval.db")
      == "ed3c4f0d2ee713dd784fefac6378daa015091ce3890d9317265d41c763863d59"
      and not list(HERE.glob("*.db")) and not list(HERE.glob("*.sqlite")))
head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
gdiff = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only"],
                       capture_output=True, text=True).stdout.strip()
check("C16 git: HEAD unchanged, no tracked file modified", head == GIT_HEAD and not gdiff,
      f"head={head}")
vrep = (HERE / "d3_validation_report.md").read_text(encoding="utf-8")
check("C17 validator report (regenerated this turn): 26/27, sole FAIL = B6 (pre-existing expected warning)",
      "26/27 checks PASS" in vrep and "B6 reviewer columns 100% blank | FAIL |" in vrep
      and vrep.count("| FAIL |") == 1)

import_re = re.compile(
    r"^\s*(?:import|from)\s+(requests|httpx|socket|urllib|smtplib|ftplib|telnetlib)\b", re.M)
scripts = ["record_d3_final4_update.py", "audit_d3_final4_update.py"]
check("C18 new scripts: no network-module imports",
      not [s for s in scripts if import_re.search((HERE / s).read_text(encoding="utf-8"))])
secret_re = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}")
sec = [p.name for p in list(HERE.glob("*.py")) + list(HERE.glob("*.md")) + list(HERE.glob("*.csv"))
       if secret_re.search(p.read_text(encoding="utf-8", errors="ignore"))]
check("C19 no secret-like assignments in any D3 file", not sec, f"violations={sec}")

passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} audit checks PASS")
raise SystemExit(0 if passed == len(results) else 1)
