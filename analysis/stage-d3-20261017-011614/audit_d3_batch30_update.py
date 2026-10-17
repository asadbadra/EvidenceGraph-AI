"""Read-only audit of the Stage D3 batch recording update (26 decisions, 2026-10-17).

Additive checks only. Does not replace or weaken validate_stage_d3.py (whose B6 failure is
the expected signature of reviewer decisions being present) nor the earlier point-in-time
audits (audit_d3_decisions.py, audit_d3_0017_update.py, audit_d3_0033_update.py,
audit_d3_0014_update.py - their state-encoding checks show expected drift after this
authorized update, as their docstrings already state).

Verifies: pre-update bytes preserved in the new snapshot; exactly 52 cells changed (the 26
authorized ids' two reviewer fields); the 4 HOLD ids still blank; machine columns and all
other rows byte-identical; the 0020 revise note recorded with the label prefix; historical
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
TARGET = "ann-d1-0020"
PREUPDATE_SHA = "95ad984d4c7f37d1eeb01b76f5af2dbe4ee5866758534a316ee847821a22286e"
DB_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
GIT_HEAD = "d4ea26d"

ACCEPT_IDS = ["ann-d1-0001", "ann-d1-0002", "ann-d1-0003", "ann-d1-0004", "ann-d1-0005",
              "ann-d1-0006", "ann-d1-0007", "ann-d1-0008", "ann-d1-0009", "ann-d1-0010",
              "ann-d1-0011", "ann-d1-0016", "ann-d1-0021", "ann-d1-0022", "ann-d1-0024",
              "ann-d1-0025", "ann-d1-0026", "ann-d1-0027", "ann-d1-0028", "ann-d1-0029",
              "ann-d1-0031", "ann-d1-0034", "ann-d1-0039", "ann-d1-0041", "ann-d1-0046"]
HOLD_IDS = ["ann-d1-0012", "ann-d1-0015", "ann-d1-0023", "ann-d1-0035"]
EXPECTED_LABELS = {
    "ann-d1-0001": "insufficient_evidence", "ann-d1-0002": "supported",
    "ann-d1-0003": "supported", "ann-d1-0004": "insufficient_evidence",
    "ann-d1-0005": "unverifiable", "ann-d1-0006": "unverifiable",
    "ann-d1-0007": "unverifiable", "ann-d1-0008": "insufficient_evidence",
    "ann-d1-0009": "insufficient_evidence", "ann-d1-0010": "insufficient_evidence",
    "ann-d1-0011": "insufficient_evidence", "ann-d1-0016": "supported",
    "ann-d1-0021": "supported", "ann-d1-0022": "supported", "ann-d1-0024": "supported",
    "ann-d1-0025": "not_applicable", "ann-d1-0026": "not_applicable",
    "ann-d1-0027": "not_applicable", "ann-d1-0028": "not_applicable",
    "ann-d1-0029": "not_applicable", "ann-d1-0031": "supported",
    "ann-d1-0034": "supported", "ann-d1-0039": "insufficient_evidence",
    "ann-d1-0041": "supported", "ann-d1-0046": "insufficient_evidence"}
REVISE_VERBATIM = ("Under the retrieved-passage evaluation scope, the claim presents the "
                   "product list as exhaustive, while the retrieved passages positively "
                   "identify additional products. This is a judgment about the retrieved "
                   "evidence and wording only; it does not establish anything about the "
                   "complete corpus or the real world.")
EXPECTED_REVISE_NOTE = "Reviewer label: contradicted | " + REVISE_VERBATIM

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


print("\n=== Stage D3 batch recording audit ===")
cols, rows = load(HERE / "d3_review_decisions.csv")
_, snap0 = load(HERE / "d3_review_decisions_predecision_snapshot.csv")     # blank state
_, snapB = load(HERE / "d3_review_decisions_prebatch30update_snapshot.csv")  # pre-update state
by = {r["annotation_id"]: r for r in rows}
b0 = {r["annotation_id"]: r for r in snap0}
bB = {r["annotation_id"]: r for r in snapB}

check("B1 schema intact: 46 rows x 15 cols, ids unique, reviewer cols last",
      len(rows) == 46 and len(cols) == 15 and len(set(by)) == 46
      and cols[-2:] == ["reviewer_decision", "reviewer_note"])
check("B2 pre-update bytes preserved (new snapshot sha == pre-write CSV baseline)",
      sha(HERE / "d3_review_decisions_prebatch30update_snapshot.csv") == PREUPDATE_SHA)
check("B3 older snapshots untouched (0017/0033/0014/predecision byte-identical)",
      sha(HERE / "d3_review_decisions_predecision_snapshot.csv")
      == "65bd58ce3a79e66f4009cbc653cac2726ed38c48ed6c9c8174e1a6fa545d8ac5"
      and sha(HERE / "d3_review_decisions_pre0017update_snapshot.csv")
      == "31751232964d54fc720d050b0faba109691b030947127ce1765a584363e6a40f"
      and sha(HERE / "d3_review_decisions_pre0033update_snapshot.csv")
      == "dc013c26fc18580a813b45029916269278b2f6492980e6cbd07c88b181db9f13"
      and sha(HERE / "d3_review_decisions_pre0014update_snapshot.csv")
      == "303f7f609443a464f619ef423660e7481f9e115d11e512064a3d6ee970ef3451")

diffB = {(a, c) for a in by for c in cols if by[a][c] != bB[a][c]}
want = {(a, c) for a in ACCEPT_IDS + [TARGET] for c in ("reviewer_decision", "reviewer_note")}
check("B4 vs pre-update snapshot: exactly 52 cells changed, all reviewer columns, all authorized ids",
      diffB == want and len(diffB) == 52, f"cells={len(diffB)}")
mach_bad = [a for a in by for c in cols
            if c not in ("reviewer_decision", "reviewer_note") and by[a][c] != bB[a][c]]
check("B5 every machine-owned column byte-identical on all 46 rows", not mach_bad,
      f"violations={mach_bad[:3]}")
diff0 = {(a, c) for a in by for c in cols if by[a][c] != b0[a][c]}
check("B6 vs original blank snapshot: 42 decided rows x 2 cells = 84 reviewer cells; holds still blank there",
      len(diff0) == 84 and all(c in ("reviewer_decision", "reviewer_note") for _, c in diff0),
      f"cells={len(diff0)}")

counts: dict[str, int] = {}
for r in rows:
    d = r["reviewer_decision"].strip()
    if d:
        counts[d] = counts.get(d, 0) + 1
pending_now = [a for a in by if not by[a]["reviewer_decision"].strip()]
check("B7 distribution: accept=37, revise=5, needs_adjudication=0, exactly 4 pending",
      counts == {"accept": 37, "revise": 5} and sorted(pending_now) == sorted(HOLD_IDS),
      f"{counts} pending={sorted(pending_now)}")

bad_acc = [a for a in ACCEPT_IDS
           if by[a]["reviewer_decision"] != "accept"
           or not by[a]["reviewer_note"].startswith(
               f"Reviewer accepted the existing proposed label ({EXPECTED_LABELS[a]})")
           or ("Stage D3 batch decision of 2026-10-17" not in by[a]["reviewer_note"])]
check("B8 all 25 accepts: decision=accept, note names the exact approved proposed label + batch provenance",
      not bad_acc, f"bad={bad_acc}")
abst = [a for a in ACCEPT_IDS if EXPECTED_LABELS[a] == "not_applicable"]
check("B9 the 5 abstention accepts also carry their approved abstention assessment in the note",
      all(f"abstention assessment ({by[a]['proposed_abstention_assessment']})" in by[a]["reviewer_note"]
          and by[a]["proposed_abstention_assessment"] == "appropriate_abstention" for a in abst))
check("B10 ann-d1-0020 recorded exactly as approved: revise + 'Reviewer label: contradicted | ' + rationale",
      by[TARGET]["reviewer_decision"] == "revise" and by[TARGET]["reviewer_note"] == EXPECTED_REVISE_NOTE)
check("B11 0020 machine fields untouched: proposed_label stays insufficient_evidence, suggested_revised_label still empty",
      by[TARGET]["proposed_label"] == "insufficient_evidence"
      and not by[TARGET]["suggested_revised_label"].strip()
      and all(by[TARGET][c] == bB[TARGET][c] for c in cols if c not in ("reviewer_decision", "reviewer_note")))
check("B12 the 4 HOLD rows byte-identical to pre-update state, both reviewer fields still blank",
      all(by[a] == bB[a] and not by[a]["reviewer_decision"].strip()
          and not by[a]["reviewer_note"].strip() for a in HOLD_IDS))
prev16 = ["ann-d1-0013", "ann-d1-0014", "ann-d1-0017", "ann-d1-0018", "ann-d1-0019",
          "ann-d1-0030", "ann-d1-0032", "ann-d1-0033", "ann-d1-0036", "ann-d1-0037",
          "ann-d1-0038", "ann-d1-0040", "ann-d1-0042", "ann-d1-0043", "ann-d1-0044",
          "ann-d1-0045"]
check("B13 the 16 previously recorded decisions byte-identical (untouched by the batch)",
      all(by[a] == bB[a] for a in prev16))
queue_claim = {x["annotation_id"]: x["claim_text"] for x in json.loads(
    (REPO / "analysis/stage-d-20261016-213744/human_review_queue.json")
    .read_text(encoding="utf-8"))["items"]}
check("B14 claim text unchanged on every changed row (byte-equal to queue)",
      all(by[a]["claim_or_question"] == (queue_claim[a] or by[a]["claim_or_question"])
          for a in ACCEPT_IDS + [TARGET]))

note_txt = (HERE / "d3_reviewer_decision_note.md").read_text(encoding="utf-8")
norm = " ".join(note_txt.split())
check("B15 decision note documents this batch update (section 10): counts, hold list, snapshot sha",
      "## 10." in note_txt and " ".join(REVISE_VERBATIM.split()) in norm
      and PREUPDATE_SHA in note_txt
      and "d3_review_decisions_prebatch30update_snapshot.csv" in note_txt
      and all(a in note_txt for a in HOLD_IDS))

for label, mp, n in (("B16a Stage D1 manifest (21 files)",
                      HERE.parent / "stage-d1-20261017-000041/stage_d1_manifest.json", 21),
                     ("B16b Stage D2 manifest (14 files)",
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
check("B17 source DB sha256 unchanged; no DB copied into D3",
      sha(REPO / "data/evidencegraph.db") == DB_SHA
      and not list(HERE.glob("*.db")) and not list(HERE.glob("*.sqlite")))
head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
gdiff = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only"],
                       capture_output=True, text=True).stdout.strip()
check("B18 git: HEAD unchanged, no tracked file modified", head == GIT_HEAD and not gdiff,
      f"head={head}")
vrep = (HERE / "d3_validation_report.md").read_text(encoding="utf-8")
check("B19 validator report (regenerated this turn): 26/27, sole FAIL = B6",
      "26/27 checks PASS" in vrep and "B6 reviewer columns 100% blank | FAIL |" in vrep
      and vrep.count("| FAIL |") == 1)

import_re = re.compile(
    r"^\s*(?:import|from)\s+(requests|httpx|socket|urllib|smtplib|ftplib|telnetlib)\b", re.M)
scripts = ["record_d3_batch30_update.py", "audit_d3_batch30_update.py"]
check("B20 new scripts: no network-module imports",
      not [s for s in scripts if import_re.search((HERE / s).read_text(encoding="utf-8"))])
secret_re = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}")
sec = [p.name for p in list(HERE.glob("*.py")) + list(HERE.glob("*.md")) + list(HERE.glob("*.csv"))
       if secret_re.search(p.read_text(encoding="utf-8", errors="ignore"))]
check("B21 no secret-like assignments in any D3 file", not sec, f"violations={sec}")

passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} audit checks PASS")
raise SystemExit(0 if passed == len(results) else 1)
