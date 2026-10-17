"""Read-only audit of the ann-d1-0017 reviewer-ruling update (Stage D3, 2026-10-17).

Additive checks only. Does not replace or weaken validate_stage_d3.py (whose B6 failure
is the expected signature of reviewer decisions being present) nor the first-turn audit
audit_d3_decisions.py (a point-in-time artifact for the original 16 decisions; its four
state-encoding checks now show expected drift because ann-d1-0017 changed by design).

Verifies: pre-update bytes preserved in snapshot; exactly 2 cells changed (0017's two
reviewer fields); machine columns and all other rows byte-identical; unrelated decisions
(0033, 0014, 0030, 0032, R1 batch of 11) untouched; claim text unchanged; historical
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
TARGET = "ann-d1-0017"
PREUPDATE_SHA = "31751232964d54fc720d050b0faba109691b030947127ce1765a584363e6a40f"
DB_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
GIT_HEAD = "d4ea26d"
VERBATIM = ("Under the adopted R1 ruling, evaluate the claim as written against the retrieved "
            "passages. The wording says the passages only mention the FortiOS vulnerability, "
            "but the displayed retrieved set also includes Log4j, OpenSSL, and MOVEit. "
            "Therefore, the literal first clause conflicts with the shown evidence. This is a "
            "corpus-grounded judgment about the wording and retrieved set only; it does not "
            "establish anything about the complete corpus or the real world.")
EXPECTED_NOTE = "Reviewer label: contradicted | " + VERBATIM

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


print("\n=== ann-d1-0017 update audit ===")
cols, rows = load(HERE / "d3_review_decisions.csv")
_, snap0 = load(HERE / "d3_review_decisions_predecision_snapshot.csv")   # blank state
_, snap1 = load(HERE / "d3_review_decisions_pre0017update_snapshot.csv")  # pre-update state
by = {r["annotation_id"]: r for r in rows}
by0 = {r["annotation_id"]: r for r in snap0}
by1 = {r["annotation_id"]: r for r in snap1}
d3_pairs = dict(manifest_pairs(HERE / "stage_d3_manifest.json"))
CSV_REL = "analysis/stage-d3-20261017-011614/d3_review_decisions.csv"

check("U1 schema intact: 46 rows x 15 columns, ids match queue exactly once",
      len(rows) == 46 and len(cols) == 15 and len(set(by)) == 46
      and sorted(by) == sorted(a["annotation_id"] for a in json.loads(
          (REPO / "analysis/stage-d-20261016-213744/human_review_queue.json")
          .read_text(encoding="utf-8"))["items"]))
check("U2 pre-update bytes preserved (snapshot sha == pre-update baseline)",
      sha(HERE / "d3_review_decisions_pre0017update_snapshot.csv") == PREUPDATE_SHA)
check("U3 first-turn blank-state snapshot still untouched (sha == stage manifest record)",
      sha(HERE / "d3_review_decisions_predecision_snapshot.csv") == d3_pairs[CSV_REL])

diff1 = {(a, c) for a in by for c in cols if by[a][c] != by1[a][c]}
check("U4 vs pre-update snapshot: exactly 2 cells changed (0017's two reviewer fields)",
      diff1 == {(TARGET, "reviewer_decision"), (TARGET, "reviewer_note")}, f"cells={len(diff1)}")
diff0 = {(a, c) for a in by for c in cols if by[a][c] != by0[a][c]}
check("U5 vs original blank snapshot: still exactly the 16 rows' 32 reviewer cells",
      len(diff0) == 32 and all(c in ("reviewer_decision", "reviewer_note") for _, c in diff0))

t = by[TARGET]
check("U6 ann-d1-0017 recorded exactly as supplied: revise + 'Reviewer label: contradicted | ' + verbatim note",
      t["reviewer_decision"] == "revise" and t["reviewer_note"] == EXPECTED_NOTE)
check("U7 0017 machine columns untouched (proposal supported / abstention not_applicable / no suggested label)",
      t["proposed_label"] == "supported" and t["proposed_abstention_assessment"] == "not_applicable"
      and not t["suggested_revised_label"].strip()
      and all(t[c] == by1[TARGET][c] for c in ("explanation", "evidence_status",
                                               "recommended_action", "confidence")))

counts: dict[str, int] = {}
for r in rows:
    if r["reviewer_decision"].strip():
        counts[r["reviewer_decision"]] = counts.get(r["reviewer_decision"], 0) + 1
check("U8 distribution: accept=12, needs_adjudication=2 (0033,0014), revise=2 (0030,0017), 30 blank",
      counts == {"accept": 12, "needs_adjudication": 2, "revise": 2}
      and sum(1 for r in rows if not r["reviewer_decision"].strip()) == 30, str(counts))
check("U9 unrelated decisions unchanged: 0033/0014 still needs_adjudication; 0030/0032 unchanged",
      all(by[a] == by1[a] for a in ("ann-d1-0033", "ann-d1-0014", "ann-d1-0030", "ann-d1-0032")))
r1_batch = ["ann-d1-0013", "ann-d1-0018", "ann-d1-0019", "ann-d1-0036", "ann-d1-0037",
            "ann-d1-0038", "ann-d1-0040", "ann-d1-0042", "ann-d1-0043", "ann-d1-0044",
            "ann-d1-0045"]
check("U10 R1 batch of 11 accepts byte-identical to pre-update state",
      all(by[a] == by1[a] for a in r1_batch))
queue_claim = [x for x in json.loads((REPO / "analysis/stage-d-20261016-213744/human_review_queue.json")
                                     .read_text(encoding="utf-8"))["items"]
               if x["annotation_id"] == TARGET][0]["claim_text"]
check("U11 claim text unchanged (byte-equal to queue; not reinterpreted in any column)",
      t["claim_or_question"] == queue_claim)

note_txt = (HERE / "d3_reviewer_decision_note.md").read_text(encoding="utf-8")
norm = " ".join(note_txt.split())  # markdown line-wraps the quote; compare whitespace-normalized
check("U12 decision note documents this update (section 7): label handling, change record, snapshot",
      "## 7. Update 2026-10-17" in note_txt and " ".join(VERBATIM.split()) in norm
      and "no `reviewer_label` column" in note_txt
      and "d3_review_decisions_pre0017update_snapshot.csv" in note_txt)

for label, mp in (("U13a Stage D1 manifest (21 files)",
                   HERE.parent / "stage-d1-20261017-000041/stage_d1_manifest.json"),
                  ("U13b Stage D2 manifest (14 files)",
                   HERE.parent / "stage-d2-20261017-002537/stage_d2_manifest.json")):
    pairs = manifest_pairs(mp)
    ok = all((REPO / rel).exists() and sha(REPO / rel) == d for rel, d in pairs)
    check(f"{label} hash-verified unchanged", ok and
          len(pairs) == (21 if "D1" in label else 14), f"{len(pairs)} files")
check("U14 source DB sha256 unchanged; no DB copied into D3",
      sha(REPO / "data/evidencegraph.db") == DB_SHA
      and not list(HERE.glob("*.db")) and not list(HERE.glob("*.sqlite")))
head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
diff = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only"],
                      capture_output=True, text=True).stdout.strip()
check("U15 git: HEAD unchanged, no tracked file modified", head == GIT_HEAD and not diff,
      f"head={head}")
vrep = (HERE / "d3_validation_report.md").read_text(encoding="utf-8")
check("U16 validator report (regenerated this turn): 26/27, sole FAIL = B6",
      "26/27 checks PASS" in vrep and "B6 reviewer columns 100% blank | FAIL |" in vrep
      and vrep.count("| FAIL |") == 1)
check("U17 validator script NOT weakened (sha == stage manifest record)",
      sha(HERE / "validate_stage_d3.py")
      == d3_pairs["analysis/stage-d3-20261017-011614/validate_stage_d3.py"])

import_re = re.compile(
    r"^\s*(?:import|from)\s+(requests|httpx|socket|urllib|smtplib|ftplib|telnetlib)\b", re.M)
scripts = ["record_d3_decisions.py", "record_d3_0017_update.py",
           "audit_d3_decisions.py", "audit_d3_0017_update.py"]
check("U18 new/updated scripts: no network-module imports",
      not [s for s in scripts if import_re.search((HERE / s).read_text(encoding="utf-8"))])
secret_re = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}")
sec = [p.name for p in list(HERE.glob("*.py")) + list(HERE.glob("*.md")) + list(HERE.glob("*.csv"))
       if secret_re.search(p.read_text(encoding="utf-8", errors="ignore"))]
check("U19 no secret-like assignments in any D3 file", not sec, f"violations={sec}")

passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} audit checks PASS")
raise SystemExit(0 if passed == len(results) else 1)
