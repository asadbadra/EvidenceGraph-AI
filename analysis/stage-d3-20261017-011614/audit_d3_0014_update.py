"""Read-only audit of the ann-d1-0014 reviewer-ruling update (Stage D3, 2026-10-17).

Additive checks only. Does not replace or weaken validate_stage_d3.py (B6 failure is the
expected signature of reviewer decisions being present) nor the earlier audits
(audit_d3_decisions.py, audit_d3_0017_update.py and audit_d3_0033_update.py are
point-in-time artifacts; their state-encoding checks show expected drift after this
authorized update).

Verifies: pre-update bytes preserved; exactly 2 cells changed (0014's two reviewer
fields); machine columns and all other rows byte-identical; the reviewer's note recorded
verbatim with the established label prefix; snapshot chain intact; historical artifacts,
databases, evaluation run and git unchanged; validator not weakened. Modifies nothing.
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
TARGET = "ann-d1-0014"
PREUPDATE_SHA = "303f7f609443a464f619ef423660e7481f9e115d11e512064a3d6ee970ef3451"
P0017_SNAPSHOT_SHA = "31751232964d54fc720d050b0faba109691b030947127ce1765a584363e6a40f"
P0033_SNAPSHOT_SHA = "dc013c26fc18580a813b45029916269278b2f6492980e6cbd07c88b181db9f13"
DB_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
RUN_DB_SHA = "ed3c4f0d2ee713dd784fefac6378daa015091ce3890d9317265d41c763863d59"
GIT_HEAD = "d4ea26d"
VERBATIM = (
    "The retrieved passages identify Microsoft Exchange Server Remote Code Execution "
    "Vulnerability (CVE-2021-34473), but none contains the claimed addition date "
    "2021-11-03. The date appears only in separately inspected document metadata that "
    "was not shown to the system. No retrieved passage gives a conflicting date, so the "
    "claim is not contradicted; however, its date component is not established by the "
    "retrieved evidence. This decision is limited to the retrieved passages and does not "
    "establish real-world truth.")
EXPECTED_NOTE = "Reviewer label: insufficient_evidence | " + VERBATIM

from record_d3_0033_update import NEW_DECISION as P33_DECISION, NEW_NOTE as P33_NOTE

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


print("\n=== ann-d1-0014 update audit ===")
cols, rows = load(HERE / "d3_review_decisions.csv")
_, snap0 = load(HERE / "d3_review_decisions_predecision_snapshot.csv")      # blank state
_, snap3 = load(HERE / "d3_review_decisions_pre0033update_snapshot.csv")    # pre-0033-update state
_, snap4 = load(HERE / "d3_review_decisions_pre0014update_snapshot.csv")    # pre-0014-update state
by = {r["annotation_id"]: r for r in rows}
by0 = {r["annotation_id"]: r for r in snap0}
by3 = {r["annotation_id"]: r for r in snap3}
by4 = {r["annotation_id"]: r for r in snap4}
d3_pairs = dict(manifest_pairs(HERE / "stage_d3_manifest.json"))
CSV_REL = "analysis/stage-d3-20261017-011614/d3_review_decisions.csv"

check("W1 schema intact: 46 rows x 15 columns, no reviewer_label column, ids match queue once",
      len(rows) == 46 and len(cols) == 15 and "reviewer_label" not in cols and len(set(by)) == 46
      and sorted(by) == sorted(a["annotation_id"] for a in json.loads(
          (REPO / "analysis/stage-d-20261016-213744/human_review_queue.json")
          .read_text(encoding="utf-8"))["items"]))
check("W2 pre-0014-update bytes preserved (snapshot sha == this turn's baseline)",
      sha(HERE / "d3_review_decisions_pre0014update_snapshot.csv") == PREUPDATE_SHA)
check("W3 snapshot chain intact: blank == stage manifest record; 0017 + 0033 snapshots untouched",
      sha(HERE / "d3_review_decisions_predecision_snapshot.csv") == d3_pairs[CSV_REL]
      and sha(HERE / "d3_review_decisions_pre0017update_snapshot.csv") == P0017_SNAPSHOT_SHA
      and sha(HERE / "d3_review_decisions_pre0033update_snapshot.csv") == P0033_SNAPSHOT_SHA)

diff4 = {(a, c) for a in by for c in cols if by[a][c] != by4[a][c]}
check("W4 vs pre-0014-update snapshot: exactly 2 cells changed (0014's two reviewer fields)",
      diff4 == {(TARGET, "reviewer_decision"), (TARGET, "reviewer_note")}, f"cells={len(diff4)}")
diff0 = {(a, c) for a in by for c in cols if by[a][c] != by0[a][c]}
check("W5 vs original blank snapshot: still exactly 16 rows' 32 reviewer cells (no new rows filled)",
      len(diff0) == 32 and all(c in ("reviewer_decision", "reviewer_note") for _, c in diff0),
      f"cells={len(diff0)}")

t = by[TARGET]
check("W6 ann-d1-0014 recorded exactly as supplied: revise + 'Reviewer label: insufficient_evidence | ' + verbatim note",
      t["reviewer_decision"] == "revise" and t["reviewer_note"] == EXPECTED_NOTE)
check("W7 0014 machine columns untouched (proposal insufficient_evidence / no human label in machine fields)",
      t["proposed_label"] == "insufficient_evidence"
      and t["proposed_abstention_assessment"] == "not_applicable"
      and not t["suggested_revised_label"].strip() and t["recommended_action"] == "accept_proposal"
      and all(t[c] == by4[TARGET][c] for c in cols if c not in ("reviewer_decision", "reviewer_note")))

counts: dict[str, int] = {}
for r in rows:
    if r["reviewer_decision"].strip():
        counts[r["reviewer_decision"]] = counts.get(r["reviewer_decision"], 0) + 1
check("W8 distribution: accept=12, revise=4 (0030,0017,0033,0014), needs_adjudication=0, 30 blank",
      counts == {"accept": 12, "revise": 4}
      and sum(1 for r in rows if not r["reviewer_decision"].strip()) == 30, str(counts))
check("W9 unrelated rows unchanged vs pre-update snapshot (every row except 0014)",
      all(by[a] == by4[a] for a in by if a != TARGET))
check("W10 0033 keeps its own recorded ruling byte-for-byte (revise + its note), unchanged this turn",
      by["ann-d1-0033"] == by4["ann-d1-0033"]
      and by["ann-d1-0033"]["reviewer_decision"] == P33_DECISION
      and by["ann-d1-0033"]["reviewer_note"] == P33_NOTE)
queue_item = [x for x in json.loads((REPO / "analysis/stage-d-20261016-213744/human_review_queue.json")
                                    .read_text(encoding="utf-8"))["items"]
              if x["annotation_id"] == TARGET][0]
check("W11 claim text unchanged (byte-equal to queue claim_text)",
      t["claim_or_question"] == queue_item["claim_text"])
check("W12 documented observation: reviewer label equals machine proposal while decision=revise "
      "vs machine accept_proposal (both recorded, neither aligned)",
      t["reviewer_note"].startswith("Reviewer label: insufficient_evidence | ")
      and t["proposed_label"] == "insufficient_evidence"
      and t["recommended_action"] == "accept_proposal")

note_txt = (HERE / "d3_reviewer_decision_note.md").read_text(encoding="utf-8")
norm = " ".join(note_txt.split())
check("W13 decision note documents update (section 9) incl. verbatim note + snapshot sha",
      "## 9. Update 2026-10-17" in note_txt and " ".join(VERBATIM.split()) in norm
      and PREUPDATE_SHA in note_txt
      and "d3_review_decisions_pre0014update_snapshot.csv" in note_txt
      and "documented, not acted upon" in note_txt)

for label, mp, n in (("W14a Stage D1 manifest (21 files)",
                      HERE.parent / "stage-d1-20261017-000041/stage_d1_manifest.json", 21),
                     ("W14b Stage D2 manifest (14 files)",
                      HERE.parent / "stage-d2-20261017-002537/stage_d2_manifest.json", 14)):
    pairs = manifest_pairs(mp)
    ok = all((REPO / rel).exists() and sha(REPO / rel) == d for rel, d in pairs)
    check(f"{label} hash-verified unchanged", ok and len(pairs) == n, f"{len(pairs)} files")
check("W15 source DB sha256 unchanged; no DB copied into D3",
      sha(REPO / "data/evidencegraph.db") == DB_SHA
      and not list(HERE.glob("*.db")) and not list(HERE.glob("*.sqlite")))
check("W16 evaluation run DB sha256 unchanged (runs/eval-postgate22-20261016-141416)",
      sha(REPO / "runs/eval-postgate22-20261016-141416/evidencegraph-eval.db") == RUN_DB_SHA)
head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
diff = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only"],
                      capture_output=True, text=True).stdout.strip()
check("W17 git: HEAD unchanged, no tracked file modified", head == GIT_HEAD and not diff,
      f"head={head}")
vrep = (HERE / "d3_validation_report.md").read_text(encoding="utf-8")
check("W18 validator report (regenerated this turn): 26/27, sole FAIL = B6",
      "26/27 checks PASS" in vrep and "B6 reviewer columns 100% blank | FAIL |" in vrep
      and vrep.count("| FAIL |") == 1)
check("W19 validator script NOT weakened (sha == stage manifest record)",
      sha(HERE / "validate_stage_d3.py")
      == d3_pairs["analysis/stage-d3-20261017-011614/validate_stage_d3.py"])

import_re = re.compile(
    r"^\s*(?:import|from)\s+(requests|httpx|socket|urllib|smtplib|ftplib|telnetlib)\b", re.M)
scripts = ["record_d3_decisions.py", "record_d3_0017_update.py", "record_d3_0033_update.py",
           "record_d3_0014_update.py", "audit_d3_decisions.py", "audit_d3_0017_update.py",
           "audit_d3_0033_update.py", "audit_d3_0014_update.py"]
check("W20 all workflow scripts: no network-module imports",
      not [s for s in scripts if import_re.search((HERE / s).read_text(encoding="utf-8"))])
secret_re = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}")
sec = [p.name for p in list(HERE.glob("*.py")) + list(HERE.glob("*.md")) + list(HERE.glob("*.csv"))
       if secret_re.search(p.read_text(encoding="utf-8", errors="ignore"))]
check("W21 no secret-like assignments in any D3 file", not sec, f"violations={sec}")

passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} audit checks PASS")
raise SystemExit(0 if passed == len(results) else 1)
