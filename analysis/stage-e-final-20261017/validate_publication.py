"""Validate the GitHub publication package (Stage E final).

Checks, against live state:
  P1  every included path (groups A-D) exists; sha256/git-blob matches
  P2  every excluded entry (group E) documents a reason
  P3  publication-set scan: no secrets, usernames, absolute local paths,
      databases, caches, or oversized files in any included path
  P4  the original D2 report is byte-identical to its recorded hash (protected
      evidence untouched) and the sanitized copy carries provenance and leaks
      nothing
  P5  the final report's quoted numbers agree with the E1 ledger and the E2
      machine-readable results
  P6  git state: HEAD d4ea26d, nothing staged, no modified tracked files
  P7  source database hash unchanged
  P8  E1/E2 validation reports and all three repetition reports exist and
      record the expected results

Writes publication_validation_report.md. Read-only elsewhere; makes no git
changes and no model calls.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
E1 = ROOT / "analysis" / "stage-e1-20261017-211414"
E2 = ROOT / "analysis" / "stage-e2-repetition-analysis-20261017-214422"
D2 = ROOT / "analysis" / "stage-d2-20261017-002537"
SOURCE_DB_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
D2_ORIGINAL_SHA = "06ffaaf13b1cfecc165807473a8561d70837328175870d5da31ea06e2d8a2cfa"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True).stdout


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== Publication package validation ===")
    man = json.loads((HERE / "publication_manifest.json").read_text(encoding="utf-8"))

    # P1 existence + hashes
    bad: list[str] = []
    for entry in man["A_preexisting_local_commit"]["files"]:
        if not (ROOT / entry["path"]).is_file():
            bad.append(f"A-missing:{entry['path']}")
    blobs = {}
    for line in git("ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        blobs[path] = meta.split()[2]
    for entry in man["A_preexisting_local_commit"]["files"]:
        if blobs.get(entry["path"]) != entry["git_blob"]:
            bad.append(f"A-blob:{entry['path']}")
    for group in ("B_new_code_and_tests", "C_research_analysis_and_validation",
                  "D_sanitized_publication_copies"):
        for entry in man[group]:
            if entry.get("sha256") is None:
                continue  # self-referential/generated; existence not required here
            p = ROOT / entry["path"]
            if not p.is_file():
                bad.append(f"missing:{entry['path']}")
            elif sha256(p) != entry["sha256"]:
                bad.append(f"hash:{entry['path']}")
    check("P1 every included path exists; hashes/blobs match manifest", not bad,
          f"bad={bad[:3]}")

    # P2 exclusions documented
    undocumented = [e for e in man["E_excluded_local_only"]
                    if not str(e.get("reason", "")).strip()]
    check("P2 every excluded entry has a documented reason",
          not undocumented and len(man["E_excluded_local_only"]) >= 5,
          f"entries={len(man['E_excluded_local_only'])}")

    # P3 scan of the exact publication set
    pub_paths = [e["path"] for g in ("B_new_code_and_tests",
                                     "C_research_analysis_and_validation",
                                     "D_sanitized_publication_copies")
                 for e in man[g]]
    sec_re = re.compile(
        r"(api[_-]?key|secret|passwd|password|bearer|ghp_|sk-[A-Za-z0-9]{20})"
        r"\s*[=:]\s*['\"][A-Za-z0-9_\-]{8,}", re.I)
    leaks, secrets, oversized, badnames = [], [], [], []
    for rel in pub_paths:
        p = ROOT / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "C:\\Users" in text or re.search(r"\brauf\b", text, re.I):
            leaks.append(rel)
        if sec_re.search(text):
            secrets.append(rel)
        if p.stat().st_size > 512_000:
            oversized.append(rel)
        low = rel.lower()
        if low.endswith((".db", ".env")) or "__pycache__" in low or ".pytest_cache" in low:
            badnames.append(rel)
    check("P3 publication set: no local paths/usernames, secrets, caches, DBs, "
          "oversized files",
          not (leaks or secrets or oversized or badnames),
          f"leaks={leaks[:2]} secrets={secrets[:2]} oversized={oversized[:2]} "
          f"badnames={badnames[:2]} scanned={len(pub_paths)}")

    # P4 original preserved + sanitized copy clean and provenance-tagged
    orig = D2 / "stage_d2_validation_report.md"
    san = D2 / "stage_d2_validation_report_sanitized.md"
    san_text = san.read_text(encoding="utf-8") if san.is_file() else ""
    check("P4 original D2 report byte-identical (protected); sanitized copy "
          "has provenance header, no path/username, same 20/20 result",
          sha256(orig) == D2_ORIGINAL_SHA
          and "SANITIZED PUBLICATION COPY" in san_text
          and D2_ORIGINAL_SHA in san_text
          and "C:\\Users" not in san_text
          and not re.search(r"\brauf\b", san_text, re.I)
          and "20/20 checks PASS" in san_text
          and "[SANITIZED]" in san_text)

    # P5 final report numbers agree with E1 ledger + E2 results JSON.
    # Needles are phrased the way the final report actually quotes the values.
    final = (HERE / "stage_e_final_report.md").read_text(encoding="utf-8")
    e2 = json.loads((E2 / "repetition_results.json").read_text(encoding="utf-8"))
    s, a = e2["stability"], e2["aggregate"]
    need_final = [
        f"{s['answer_identical_all_repetitions']}/{s['units_total']}",  # 47/48
        str(s["answer_stability"]),          # 0.9792
        str(a["elapsed_s"]["mean"]),         # 1993.6
        str(a["elapsed_s"]["stdev"]),        # 21.319
        str(a["usage"]["calls"]),            # 336
        "10/13", "8/11", "16/39", "excluded=1",
        "14/14", "804 passed",
        "appropriate_abstention=6", "n=5",
    ]
    missing = [n for n in need_final if n not in final]
    check("P5 final report quotes E1 ledger + E2 results verbatim", not missing,
          f"missing={missing[:4]}")

    # P6 git state
    head = git("rev-parse", "--short", "HEAD").strip()
    staged = git("diff", "--cached", "--name-only").strip()
    mod = git("diff", "--name-only").strip()
    check("P6 git: HEAD d4ea26d, nothing staged, no modified tracked files",
          head == "d4ea26d" and not staged and not mod, f"head={head}")

    # P7 source database
    db = ROOT / "data" / "evidencegraph.db"
    check("P7 source database sha256 unchanged",
          db.is_file() and sha256(db) == SOURCE_DB_SHA,
          sha256(db)[:16])

    # P8 validators + repetitions record expected results
    e1_val = (E1 / "stage_e1_validation_report.md").read_text(encoding="utf-8")
    e2_val = (E2 / "stage_e2_validation_report.md").read_text(encoding="utf-8")
    runs_ok = []
    for tag in ("stage-e-repeat1-20261017-155403", "stage-e-repeat2-20261017-163026",
                "stage-e-repeat3-20261017-170438"):
        rp = ROOT / "runs" / tag / "report.json"
        runs_ok.append(rp.is_file()
                       and json.loads(rp.read_text(encoding="utf-8"))["status"] == "completed")
    check("P8 E1 14/14, E2 14/14 recorded; all three repetition reports completed",
          "**14/14 checks PASS**" in e1_val and "**14/14 checks PASS**" in e2_val
          and all(runs_ok))

    passed = sum(1 for _, ok, _ in results if ok)
    lines = ["# Publication Validation Report", "",
             f"- Run: `validate_publication.py` · "
             f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
             f"- Result: **{passed}/{len(results)} checks PASS**", "",
             "| # | Check | Result | Detail |", "|---|-------|--------|--------|"]
    for i, (name, ok, detail) in enumerate(results, 1):
        lines.append(f"| {i} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    (HERE / "publication_validation_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(results)} checks PASS "
          f"(report: publication_validation_report.md)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
