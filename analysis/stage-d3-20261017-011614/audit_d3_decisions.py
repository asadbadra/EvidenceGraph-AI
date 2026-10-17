"""Read-only supplementary audit of the recorded Stage D3 reviewer decisions.

Additive confirmations only - this does NOT replace or weaken validate_stage_d3.py
(which still reports its expected B6 failure, as designed for the pre-decision
invariant). It confirms the review-brief items the existing script does not cover:
  - only the explicitly authorized fields/rows changed (vs. the preserved snapshot)
  - ann-d1-0033 and ann-d1-0014 remain unresolved
  - the R1 ruling and retrieved-passage scope are documented without inventing
    labels for unresolved items
  - Stage D1/D2 files, historical artifacts, source DB, git state unchanged
  - the validator script itself was not weakened (hash still matches manifest)

Modifies nothing. Prints one line per check.
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

from record_d3_decisions import DECISIONS, REVIEWER_COLS  # noqa: E402

R1_ACCEPT_IDS = {aid for aid, (d, _) in DECISIONS.items() if aid not in (
    "ann-d1-0033", "ann-d1-0014", "ann-d1-0030", "ann-d1-0032", "ann-d1-0017")}
R1_ALL_IDS = R1_ACCEPT_IDS | {"ann-d1-0017"}
DB_EXPECTED_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
GIT_HEAD_EXPECTED = "d4ea26d"
MACHINE_COLS = ["annotation_id", "review_order", "review_group", "claim_or_question",
                "evidence_excerpt", "source_reference", "proposed_label",
                "proposed_abstention_assessment", "explanation", "evidence_status",
                "recommended_action", "suggested_revised_label", "confidence"]

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


def manifest_pairs(manifest_path: Path) -> list[tuple[str, str]]:
    """Collect every {'path':..., 'sha256':...} pair from any stage-manifest shape."""
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    pairs: list[tuple[str, str]] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if "path" in node and "sha256" in node:
                pairs.append((node["path"], node["sha256"]))
            else:
                for v in node.values():
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return pairs


def manifest_ok(manifest_path: Path) -> tuple[bool, int, int]:
    ok = n = 0
    for rel, digest in manifest_pairs(manifest_path):
        n += 1
        if (REPO / rel).exists() and sha(REPO / rel) == digest:
            ok += 1
    return ok == n, ok, n


print("\n=== Stage D3 supplementary decision audit ===")

fieldnames, rows = load(HERE / "d3_review_decisions.csv")
_, snap = load(HERE / "d3_review_decisions_predecision_snapshot.csv")
by_id = {r["annotation_id"]: r for r in rows}
snap_by_id = {r["annotation_id"]: r for r in snap}

# --- A. schema + rows -------------------------------------------------------
check("A1 CSV is 46 rows x 15 columns, no reviewer_id/timestamp columns",
      len(rows) == 46 and len(fieldnames) == 15 and fieldnames == MACHINE_COLS + REVIEWER_COLS)
queue_ids = [a["annotation_id"] for a in json.loads(
    (REPO / "analysis/stage-d-20261016-213744/human_review_queue.json").read_text(encoding="utf-8"))["items"]]
check("A2 ids match the queue: every id once, none missing/duplicated",
      sorted(by_id) == sorted(queue_ids) and len(set(by_id)) == 46)

# --- B. cell-level change scope vs pre-decision snapshot --------------------
diffs = [(aid, col) for aid in by_id for col in fieldnames
         if by_id[aid][col] != snap_by_id[aid][col]]
allowed = {(aid, col) for aid in DECISIONS for col in REVIEWER_COLS}
check("B1 only reviewer_decision/reviewer_note changed, only on the 16 authorized rows",
      set(diffs) <= allowed and len(diffs) == 32, f"changed cells={len(diffs)}")
mach_bad = [aid for aid in by_id for col in MACHINE_COLS
            if by_id[aid][col] != snap_by_id[aid][col]]
check("B2 machine/proposal columns byte-identical to snapshot on all 46 rows",
      not mach_bad, f"violations={mach_bad[:3]}")
d3_pairs = dict(manifest_pairs(HERE / "stage_d3_manifest.json"))
recorded_csv_sha = d3_pairs["analysis/stage-d3-20261017-011614/d3_review_decisions.csv"]
check("B3 snapshot is the untouched pre-decision file (sha == stage manifest record)",
      sha(HERE / "d3_review_decisions_predecision_snapshot.csv") == recorded_csv_sha)

# --- C. decision map exactly as authorized ----------------------------------
observed = {r["annotation_id"]: r["reviewer_decision"] for r in rows if r["reviewer_decision"].strip()}
expected = {aid: d for aid, (d, _) in DECISIONS.items()}
check("C1 exactly the 16 authorized rows carry a decision (30 remain blank/pending)",
      observed == expected and len(rows) - len(observed) == 30)
counts: dict[str, int] = {}
for d in observed.values():
    counts[d] = counts.get(d, 0) + 1
check("C2 decision distribution: accept=12, needs_adjudication=3, revise=1",
      counts == {"accept": 12, "needs_adjudication": 3, "revise": 1}, str(counts))

# --- D. the individually named decisions ------------------------------------
d33, d14, d30, d32, d17 = (by_id[a] for a in
                           ("ann-d1-0033", "ann-d1-0014", "ann-d1-0030", "ann-d1-0032", "ann-d1-0017"))
check("D1 ann-d1-0033 unresolved: needs_adjudication, proposal preserved, no revised label",
      d33["reviewer_decision"] == "needs_adjudication" and bool(d33["reviewer_note"].strip())
      and d33["proposed_label"] == "contradicted" and not d33["suggested_revised_label"].strip()
      and snap_by_id["ann-d1-0033"]["proposed_label"] == "contradicted")
check("D2 ann-d1-0014 unresolved: needs_adjudication, proposal preserved, no revised label",
      d14["reviewer_decision"] == "needs_adjudication" and bool(d14["reviewer_note"].strip())
      and d14["proposed_label"] == "insufficient_evidence"
      and not d14["suggested_revised_label"].strip())
check("D3 ann-d1-0030 scope ruling recorded in note; no claim label invented; abstention proposal untouched",
      d30["reviewer_decision"] == "revise"
      and "retrieved passages" in d30["reviewer_note"]
      and "appropriate_abstention" in d30["reviewer_note"]
      and "NOT a claim that CVE-2021-45046 is absent" in d30["reviewer_note"]
      and d30["proposed_label"] == "not_applicable"
      and d30["proposed_abstention_assessment"] == "uncertain"
      and not d30["suggested_revised_label"].strip())
check("D4 ann-d1-0032 accept; proposed label stands; machine revise-suggestion retained",
      d32["reviewer_decision"] == "accept" and d32["proposed_label"] == "supported"
      and d32["suggested_revised_label"] == "insufficient_evidence")
check("D5 ann-d1-0017 left unresolved (needs_adjudication) with reason, no label chosen",
      d17["reviewer_decision"] == "needs_adjudication" and "unresolved" in d17["reviewer_note"]
      and d17["proposed_label"] == "supported" and not d17["suggested_revised_label"].strip())

# --- E. R1 documentation + application --------------------------------------
build_txt = (HERE / "build_d3_review.py").read_text(encoding="utf-8")
s1 = set(re.findall(r"ann-d1-\d+", re.search(r"R1_FAMILY = \[(.*?)\]", build_txt, re.S).group(0)))
cards_txt = (HERE / "d3_review_cards.md").read_text(encoding="utf-8")
s2 = set(re.findall(r"ann-d1-\d+", [l for l in cards_txt.splitlines()
                                    if l.startswith("Items covered:")][0]))
expl_txt = (HERE / "r1_explainer.md").read_text(encoding="utf-8")
s3 = set(re.findall(r"\| (ann-d1-\d+) \|", expl_txt))
check("E1 R1 membership recalculated from files: builder == cards == explainer (12 ids)",
      s1 == s2 == s3 == R1_ALL_IDS)
check("E2 R1 application: 11 items accept with ruling-based note; ann-d1-0017 unresolved",
      all(by_id[a]["reviewer_decision"] == "accept" and "R1=A" in by_id[a]["reviewer_note"]
          for a in R1_ACCEPT_IDS)
      and by_id["ann-d1-0017"]["reviewer_decision"] == "needs_adjudication")
note_txt = (HERE / "d3_reviewer_decision_note.md").read_text(encoding="utf-8")
check("E3 decision note documents ruling + scope statements + provenance + mapping table",
      "A (committed reading)" in note_txt
      and "does not establish absence from the complete" in note_txt
      and "proof that the system's answer is factually correct" in note_txt
      and "project conversation" in note_txt
      and note_txt.count("ann-d1-0") >= 12)
banned = ["human-confirmed", "reviewer confirmed", "you accepted",
          "review is complete", "decisions have been recorded"]
check("E4 no fabricated-confirmation language in decision note (C7 vocabulary)",
      not any(b in note_txt.lower() for b in banned))

# --- F. existing validator outcome + not weakened ---------------------------
vrep = (HERE / "d3_validation_report.md").read_text(encoding="utf-8")
check("F1 existing validator report shows 26/27 with sole FAIL = B6",
      "26/27 checks PASS" in vrep
      and "B6 reviewer columns 100% blank | FAIL |" in vrep
      and vrep.count("| FAIL |") == 1)
check("F2 validator script NOT weakened (sha still == stage manifest record)",
      sha(HERE / "validate_stage_d3.py")
      == d3_pairs["analysis/stage-d3-20261017-011614/validate_stage_d3.py"])
unchanged = [rel for rel in ("analysis/stage-d3-20261017-011614/d3_review_cards.md",
                             "analysis/stage-d3-20261017-011614/d3_highest_risk_summary.md",
                             "analysis/stage-d3-20261017-011614/build_d3_review.py")
             if sha(REPO / rel) == d3_pairs[rel]]
check("F3 other manifest-covered D3 outputs unchanged (cards, summary, builder)",
      len(unchanged) == 3)

# --- G. historical artifacts + environment ----------------------------------
for label, path in (("G1 Stage D1 manifest (21 files)", HERE.parents[0] / "stage-d1-20261017-000041/stage_d1_manifest.json"),
                    ("G2 Stage D2 manifest (14 files)", HERE.parents[0] / "stage-d2-20261017-002537/stage_d2_manifest.json")):
    ok, good, n = manifest_ok(path)
    check(f"{label} hash-verified unchanged", ok, f"{good}/{n}")
check("G3 source DB sha256 unchanged", sha(REPO / "data/evidencegraph.db") == DB_EXPECTED_SHA)
check("G4 no .db / .sqlite copied into D3", not list(HERE.glob("*.db")) and not list(HERE.glob("*.sqlite")))
head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
tracked = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only"],
                         capture_output=True, text=True).stdout.strip()
check("G5 git: HEAD unchanged, no tracked file modified",
      head == GIT_HEAD_EXPECTED and not tracked, f"head={head}")

# --- H. hygiene on the new files I added ------------------------------------
import_re = re.compile(
    r"^\s*(?:import|from)\s+(requests|httpx|socket|urllib|smtplib|ftplib|telnetlib)\b", re.M)
new_py = [p for p in HERE.glob("*.py") if p.name in ("record_d3_decisions.py", "audit_d3_decisions.py")]
py_bad = [p.name for p in new_py if import_re.search(p.read_text(encoding="utf-8"))]
check("H1 new scripts: no network-module imports (F2 standard)", not py_bad)
secret_re = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}")
sec_bad = [p.name for p in list(HERE.glob("*.py")) + list(HERE.glob("*.md")) + list(HERE.glob("*.csv"))
           if secret_re.search(p.read_text(encoding="utf-8", errors="ignore"))]
check("H2 no secret-like assignments in any D3 file", not sec_bad, f"violations={sec_bad}")

passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} audit checks PASS")
raise SystemExit(0 if passed == len(results) else 1)
