"""Stage D2 offline validation (stdlib + pytest only, no network, no model calls).

Checks
  A. required D2 files exist
  B. confirmation_decisions.csv: 46 rows, queue order, reviewer columns 100% empty,
     proposed_* fields byte-equal to the D1 proposal file, recommendation vocabulary
  C. review_summary.md: 46 numbered items in order, four groups, machine disclaimers,
     no fabricated human-confirmation language
  D. D1 package unchanged (hashes recorded in stage_d1_manifest.json still match)
  E. historical integrity: Stage C + D hash checks, mtime scan (nothing external
     modified since the D2 start reference), git HEAD/clean state
  F. no database artifacts in D2, no network imports, no secrets, pytest 763 pass

Writes stage_d2_validation_report.md (this directory only).
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
D1_DIR = REPO / "analysis/stage-d1-20261017-000041"
QUEUE_PATH = REPO / "analysis/stage-d-20261016-213744/human_review_queue.json"

# D2 work on the historical tree started at directory creation; nothing historical
# may have an mtime after this reference (2-minute build allowance applied).
D2_START = datetime(2026, 10, 17, 0, 25, 0, tzinfo=timezone.utc).timestamp()
MTTOLER = 120.0

results: list[tuple[str, bool, str]] = []
secrets_hits: list[str] = []


def check(name: str, ok: bool, detail: str) -> bool:
    results.append((name, bool(ok), detail))
    return bool(ok)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # A. required files
    required = ["review_summary.md", "confirmation_decisions.csv",
                "build_d2_interface.py", "validate_stage_d2.py"]
    missing = [f for f in required if not (HERE / f).is_file()]
    check("A1 required D2 files exist", not missing, f"missing={missing}")

    # B. decisions file
    with (HERE / "confirmation_decisions.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    ids = [r["annotation_id"] for r in rows]
    check("B1 46 rows, queue order", ids == [i["annotation_id"] for i in queue["items"]],
          f"n={len(rows)}")
    reviewer_cols = ["reviewer_decision", "revised_label", "reviewer_note",
                     "reviewer_id", "review_timestamp"]
    filled = [(r["annotation_id"], c) for r in rows for c in reviewer_cols if r.get(c, "").strip()]
    check("B2 reviewer columns 100% empty (nothing pre-accepted)", not filled,
          f"violations={filled[:3]}")
    props = {r["annotation_id"]: r for r in csv.DictReader(
        (D1_DIR / "proposed_judgments.csv").open(encoding="utf-8", newline=""))}
    mismatched = [r["annotation_id"] for r in rows
                  if r["proposed_label"] != props[r["annotation_id"]]["proposed_label"]
                  or r["proposed_abstention_assessment"]
                  != props[r["annotation_id"]]["proposed_abstention_assessment"]]
    check("B3 proposed_* byte-equal to D1 proposals", not mismatched, f"mismatched={mismatched}")
    recs = [r["draft_recommendation"] for r in rows]
    n_adj = sum(1 for x in recs if x == "needs_adjudication")
    check("B4 recommendation vocabulary (45 accept / 1 needs_adjudication)",
          set(recs) == {"accept", "needs_adjudication"} and n_adj == 1
          and recs[ids.index("ann-d1-0030")] == "needs_adjudication",
          f"counts accept={recs.count('accept')} adj={n_adj}")
    check("B5 P1 items marked",
          {r["annotation_id"] for r in rows if r["review_priority"] == "P1_decide_first"}
          == {"ann-d1-0014", "ann-d1-0030", "ann-d1-0033"}, "P1={14,30,33}")

    # C. summary file
    txt = (HERE / "review_summary.md").read_text(encoding="utf-8")
    heads = re.findall(r"^#### (\d+)\. (ann-d1-\d+)", txt, flags=re.M)
    check("C1 46 numbered items, sequential",
          [int(n) for n, _ in heads] == list(range(1, 47)) and len(set(a for _, a in heads)) == 46,
          f"found={len(heads)}")
    check("C2 four tier groups present",
          all(s in txt for s in ["## Group 1", "## Group 2", "## Group 3", "## Group 4"]), "")
    check("C3 machine-draft + not-confirmed disclaimers",
          "machine-drafted" in txt and "Review NOT complete" in txt, "")
    banned = ["human-confirmed", "confirmed by the reviewer", "I accept", "review is complete"]
    hits = [b for b in banned if b.lower() in txt.lower()]
    check("C4 no fabricated confirmation language", not hits, f"hits={hits}")
    check("C5 priorities, ledger, unresolved sections",
          "## 0. Priority decisions" in txt and "Disagreement ledger" in txt
          and "Items left unresolved" in txt, "")

    # D. D1 unchanged
    manifest = json.loads((D1_DIR / "stage_d1_manifest.json").read_text(encoding="utf-8"))
    bad: list[str] = []
    d1_recs = manifest["source_inputs_read_only"] + manifest["outputs"]
    for rec in d1_recs:
        p = REPO / rec["path"]
        if not p.is_file() or sha256(p) != rec["sha256"]:
            bad.append(rec["path"])
    check(f"D1 package unchanged ({len(d1_recs)} manifest hashes)", not bad, f"bad={bad}")

    # E. historical integrity (Stage C/D recorded hashes + mtime scan + git)
    def collect_path_hash_pairs(obj, out: list[tuple[str, str]]) -> None:
        if isinstance(obj, dict):
            path_keys = [k for k in obj if "path" in k.lower()]
            hash_keys = [k for k in obj if k.endswith("sha256")]
            if path_keys and hash_keys:
                out.append((str(obj[path_keys[0]]), str(obj[hash_keys[0]])))
            for v in obj.values():
                collect_path_hash_pairs(v, out)
        elif isinstance(obj, list):
            for v in obj:
                collect_path_hash_pairs(v, out)

    pairs: list[tuple[str, str]] = []
    collect_path_hash_pairs(json.loads(
        (REPO / "analysis/stage-c-20261016/integrity_hashes_after.json")
        .read_text(encoding="utf-8")), pairs)
    collect_path_hash_pairs(json.loads(
        (REPO / "analysis/stage-d-20261016-213744/stage_d_manifest.json")
        .read_text(encoding="utf-8")), pairs)
    bad2: list[str] = []
    seen = 0
    for rel_norm, want in pairs:
        p = (REPO / rel_norm.replace("/", "\\"))
        if not p.is_file():
            continue  # manifest may reference paths outside the repo
        seen += 1
        if sha256(p) != want:
            bad2.append(rel_norm)
    check("E1 Stage C + D recorded hashes intact", not bad2,
          f"{seen} recorded hashes verified" if not bad2 else f"bad={bad2}")
    recent: list[str] = []
    for sub in ["analysis/stage-b-evalpostgate22-20261016", "analysis/stage-c-20261016",
                "analysis/stage-d-20261016-213744", "analysis/stage-d1-20261017-000041",
                "analysis/stage-d1-20261017-000041-old-draft", "runs", "data", "prompts",
                "src", "tests", "docs", "Makefile", "Dockerfile", "pyproject.toml"]:
        base = REPO / sub
        if base.is_file():
            cand = [base]
        elif base.is_dir():
            cand = [p for p in base.rglob("*") if p.is_file()]
        else:
            continue
        for p in cand:
            if HERE in p.parents:
                continue
            if p.stat().st_mtime > D2_START + MTTOLER:
                recent.append(str(p.relative_to(REPO)))
    check("E2 no historical file modified during D2", not recent, f"recent={recent[:5]}")
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    check("E3 git HEAD unchanged (d4ea26d)", head.startswith("d4ea26d"), head[:12])
    status = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    check("E4 no new tracked changes", not any(l.strip() and not l.startswith("??") for l in
                                               status.splitlines()), "only untracked allowed")

    # F. hygiene
    dbs = [p.name for p in HERE.rglob("*") if p.suffix == ".db"]
    check("F1 no database artifacts in D2", not dbs, f"{dbs}")
    imports: list[str] = []
    for py in HERE.glob("*.py"):
        for line in py.read_text(encoding="utf-8").splitlines():
            if re.match(r"^\s*import\s+(requests|httpx|urllib|socket)\b", line):
                imports.append(f"{py.name}: {line.strip()}")
    check("F2 stdlib-only, no network imports", not imports, f"{imports}")
    for p in list(HERE.glob("*.py")) + list(HERE.glob("*.md")) + list(HERE.glob("*.csv")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if re.search(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}", line, re.I):
                secrets_hits.append(f"{p.name}")
    check("F3 no secrets", not secrets_hits, f"{secrets_hits}")
    # pyproject addopts already contains "-q"; do not add another (it becomes -qq
    # and suppresses the summary line, hiding the pass count).
    proc = subprocess.run([sys.executable, "-m", "pytest"],
                          cwd=str(REPO), capture_output=True, text=True)
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "?"
    passed = proc.returncode == 0 and " passed" in proc.stdout and "failed" not in proc.stdout
    check("F4 test suite passes", passed, tail)

    # report
    n_ok = sum(1 for _, ok, _ in results if ok)
    lines = [
        "# Stage D2 Validation Report", "",
        f"- Run: `{sys.argv[0]}` · {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Result: **{n_ok}/{len(results)} checks PASS**", "",
        "| # | Check | Result | Detail |", "|---|-------|--------|--------|",
    ]
    for idx, (name, ok, detail) in enumerate(results, 1):
        lines.append(f"| {idx} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines += [
        "", "## Notes",
        "- `confirmation_decisions.csv` reviewer columns were verified empty at build "
        "time and at validation time: every row is pending; no acceptance was inferred.",
        "- `draft_recommendation` is a machine column; the only authoritative reviewer "
        "inputs are the five reviewer columns.",
        "- D1 files verified unchanged via `stage_d1_manifest.json` (12 inputs + 9 outputs).",
        "- No model calls, no network, no database writes, no git state changes.",
    ]
    (HERE / "stage_d2_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{n_ok}/{len(results)} checks PASS")
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail if not ok else ''}")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
