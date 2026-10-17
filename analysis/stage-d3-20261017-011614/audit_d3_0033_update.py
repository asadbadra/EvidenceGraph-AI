"""Read-only audit of the ann-d1-0033 reviewer-ruling update (Stage D3, 2026-10-17).

Additive checks only. Does not replace or weaken validate_stage_d3.py (B6 failure is the
expected signature of reviewer decisions being present) nor the earlier audits
(audit_d3_decisions.py and audit_d3_0017_update.py are point-in-time artifacts; their
state-encoding checks show expected drift after this authorized update).

Verifies: pre-update bytes preserved; exactly 2 cells changed (0033's two reviewer
fields); machine columns and all other rows byte-identical; the reviewer's label/note
INCONSISTENCY preserved as supplied and documented (not silently resolved); historical
artifacts, DB, git unchanged; validator not weakened. Modifies nothing.
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
TARGET = "ann-d1-0033"
PREUPDATE_SHA = "dc013c26fc18580a813b45029916269278b2f6492980e6cbd07c88b181db9f13"
P0017_SNAPSHOT_SHA = "31751232964d54fc720d050b0faba109691b030947127ce1765a584363e6a40f"
DB_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
GIT_HEAD = "d4ea26d"
VERBATIM = ("The retrieved passages mark both Log4j2 and Microsoft Exchange as Known, but "
            "each explicitly states that this is per the source record and was not "
            "independently verified here. The claim's inference of independent "
            "verification conflicts with those explicit disclaimers. This decision is "
            "limited to the retrieved passages and does not establish real-world truth.")
EXPECTED_NOTE = "Reviewer label: supported | " + VERBATIM

from record_d3_0017_update import NEW_DECISION as P17_DECISION, NEW_NOTE as P17_NOTE

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


def manifest_pairs(mp: Path) -> list[tuple[str, str]]:
    doc = json.loads(mp.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []

    def walk(n) -> None:
        if isinstance(n, dict):
            if "path" in n and "sha256" in n:
                out.append((n["path"], n["sha256"]))
            else:
                for v in n.values():
                    walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(doc)
    return out


print("\n=== ann-d1-0033 update audit ===")
cols, rows = load(HERE / "d3_review_decisions.csv")
_, snap0 = load(HERE / "d3_review_decisions_predecision_snapshot.csv")        # blank state
_, snap1 = load(HERE / "d3_review_decisions_pre0017update_snapshot.csv")      # 0017-update state
_, snap2 = load(HERE / "d3_review_decisions_pre0033update_snapshot.csv")      # pre-0033-update state
by = {r["annotation_id"]: r for r in rows}
by0 = {r["annotation_id"]: r for r in snap0}
by1 = {r["annotation_id"]: r for r in snap1}
by2 = {r["annotation_id"]: r for r in snap2}
d3_pairs = dict(manifest_pairs(HERE / "stage_d3_manifest.json"))
CSV_REL = "analysis/stage-d3-20261017-011614/d3_review_decisions.csv"

check("V1 schema intact: 46 rows x 15 columns, no reviewer_label column, ids match queue once",
      len(rows) == 46 and len(cols) == 15 and "reviewer_label" not in cols and len(set(by)) == 46
      and sorted(by) == sorted(a["annotation_id"] for a in json.loads(
          (REPO / "analysis/stage-d-20261016-213744/human_review_queue.json")
          .read_text(encoding="utf-8"))["items"]))
check("V2 pre-0033-update bytes preserved (snapshot sha == this turn's baseline)",
      sha(HERE / "d3_review_decisions_pre0033update_snapshot.csv") == PREUPDATE_SHA)
check("V3 snapshot chain intact: blank snapshot == stage manifest record; 0017 snapshot untouched",
      sha(HERE / "d3_review_decisions_predecision_snapshot.csv") == d3_pairs[CSV_REL]
      and sha(HERE / "d3_review_decisions_pre0017update_snapshot.csv") == P0017_SNAPSHOT_SHA)

diff2 = {(a, c) for a in by for c in cols if by[a][c] != by2[a][c]}
check("V4 vs pre-0033-update snapshot: exactly 2 cells changed (0033's two reviewer fields)",
      diff2 == {(TARGET, "reviewer_decision"), (TARGET, "reviewer_note")}, f"cells={len(diff2)}")
diff0 = {(a, c) for a in by for c in cols if by[a][c] != by0[a][c]}
check("V5 vs original blank snapshot: still exactly 16 rows' 32 reviewer cells (no new rows filled)",
      len(diff0) == 32 and all(c in ("reviewer_decision", "reviewer_note") for _, c in diff0),
      f"cells={len(diff0)}")

t = by[TARGET]
check("V6 ann-d1-0033 recorded exactly as supplied: revise + 'Reviewer label: supported | ' + verbatim note",
      t["reviewer_decision"] == "revise" and t["reviewer_note"] == EXPECTED_NOTE)
check("V7 0033 machine columns untouched (proposal contradicted / no human label in machine fields)",
      t["proposed_label"] == "contradicted" and t["proposed_abstention_assessment"] == "not_applicable"
      and not t["suggested_revised_label"].strip() and t["recommended_action"] == "accept_proposal"
      and all(t[c] == by2[TARGET][c] for c in ("explanation", "evidence_status", "confidence",
                                               "claim_or_question", "evidence_excerpt",
                                               "source_reference")))

counts: dict[str, int] = {}
for r in rows:
    if r["reviewer_decision"].strip():
        counts[r["reviewer_decision"]] = counts.get(r["reviewer_decision"], 0) + 1
check("V8 distribution: accept=12, revise=3 (0030,0017,0033), needs_adjudication=1 (0014), 30 blank",
      counts == {"accept": 12, "revise": 3, "needs_adjudication": 1}
      and sum(1 for r in rows if not r["reviewer_decision"].strip()) == 30, str(counts))
check("V9 unrelated rows unchanged vs pre-update snapshot (0014, 0017, 0030, 0032, R1 batch of 11)",
      all(by[a] == by2[a] for a in ("ann-d1-0014", "ann-d1-0017", "ann-d1-0030", "ann-d1-0032"))
      and all(by[a] == by2[a] for a in by if a not in (TARGET, "ann-d1-0014", "ann-d1-0017",
                                                        "ann-d1-0030", "ann-d1-0032")))
check("V10 0017 keeps its own recorded ruling byte-for-byte (revise + its note), unchanged this turn",
      by["ann-d1-0017"] == by2["ann-d1-0017"]
      and by["ann-d1-0017"]["reviewer_decision"] == P17_DECISION
      and by["ann-d1-0017"]["reviewer_note"] == P17_NOTE)
queue_item = [x for x in json.loads((REPO / "analysis/stage-d-20261016-213744/human_review_queue.json")
                                    .read_text(encoding="utf-8"))["items"]
              if x["annotation_id"] == TARGET][0]
check("V11 claim text unchanged (byte-equal to queue claim_text)",
      t["claim_or_question"] == queue_item["claim_text"])

check("V12 INCONSISTENCY preserved, not resolved: label=supported (in note) + note keeps its "
      "conflict language + machine proposal still contradicted",
      t["reviewer_note"].startswith("Reviewer label: supported | ")
      and "conflicts with those explicit disclaimers" in t["reviewer_note"]
      and t["proposed_label"] == "contradicted"
      and t["reviewer_note"] == EXPECTED_NOTE)

note_txt = (HERE / "d3_reviewer_decision_note.md").read_text(encoding="utf-8")
norm = " ".join(note_txt.split())
check("V13 decision note documents update (section 8) incl. the flagged inconsistency",
      "## 8. Update 2026-10-17" in note_txt and " ".join(VERBATIM.split()) in norm
      and "REVIEWER-FLAGGED INCONSISTENCY" in note_txt
      and "deliberately NOT resolved" in note_txt
      and "d3_review_decisions_pre0033update_snapshot.csv" in note_txt)

for label, mp, n in (("V14a Stage D1 manifest (21 files)",
                      HERE.parent / "stage-d1-20261017-000041/stage_d1_manifest.json", 21),
                     ("V14b Stage D2 manifest (14 files)",
                      HERE.parent / "stage-d2-20261017-002537/stage_d2_manifest.json", 14)):
    pairs = manifest_pairs(mp)
    ok = all((REPO / rel).exists() and sha(REPO / rel) == d for rel, d in pairs)
    check(f"{label} hash-verified unchanged", ok and len(pairs) == n, f"{len(pairs)} files")
check("V15 source DB sha256 unchanged; no DB copied into D3",
      sha(REPO / "data/evidencegraph.db") == DB_SHA
      and not list(HERE.glob("*.db")) and not list(HERE.glob("*.sqlite")))
head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
diff = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only"],
                      capture_output=True, text=True).stdout.strip()
check("V16 git: HEAD unchanged, no tracked file modified", head == GIT_HEAD and not diff,
      f"head={head}")
vrep = (HERE / "d3_validation_report.md").read_text(encoding="utf-8")
check("V17 validator report (regenerated this turn): 26/27, sole FAIL = B6",
      "26/27 checks PASS" in vrep and "B6 reviewer columns 100% blank | FAIL |" in vrep
      and vrep.count("| FAIL |") == 1)
check("V18 validator script NOT weakened (sha == stage manifest record)",
      sha(HERE / "validate_stage_d3.py")
      == d3_pairs["analysis/stage-d3-20261017-011614/validate_stage_d3.py"])

import_re = re.compile(
    r"^\s*(?:import|from)\s+(requests|httpx|socket|urllib|smtplib|ftplib|telnetlib)\b", re.M)
scripts = ["record_d3_decisions.py", "record_d3_0017_update.py", "record_d3_0033_update.py",
           "audit_d3_decisions.py", "audit_d3_0017_update.py", "audit_d3_0033_update.py"]
check("V19 all workflow scripts: no network-module imports",
      not [s for s in scripts if import_re.search((HERE / s).read_text(encoding="utf-8"))])
secret_re = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}")
sec = [p.name for p in list(HERE.glob("*.py")) + list(HERE.glob("*.md")) + list(HERE.glob("*.csv"))
       if secret_re.search(p.read_text(encoding="utf-8", errors="ignore"))]
check("V20 no secret-like assignments in any D3 file", not sec, f"violations={sec}")

passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} audit checks PASS")
raise SystemExit(0 if passed == len(results) else 1)
