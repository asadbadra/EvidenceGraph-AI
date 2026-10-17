"""Stage E2 — repetition-analysis validator (writes only stage_e2_validation_report.md).

Re-verifies, from live artifacts: manifest hashes, cross-repetition
comparability, safety invariants (source DB unchanged, gold_label NULL),
stability/aggregate numbers quoted in the report against a fresh
recomputation from the run databases, git state, and honesty wording.
Imports the scaffolding under test but nothing else outside the stdlib;
opens SQLite mode=ro only; makes no model calls.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.verification.experiments import (  # noqa: E402
    aggregate_reports,
    compare_repetitions,
    load_run_artifacts,
    question_outcomes,
    require_comparable,
)

QUESTIONS = ROOT / "data" / "sample" / "eval_questions.json"
QUESTIONS_SHA = "500ed32d5546683392616685f024d9f5feebefec19806c53e1f03a34b33f3a3a"
SOURCE_DB_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
EXPECTED_LABELS = ("stage-e-repeat1", "stage-e-repeat2", "stage-e-repeat3")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== Stage E2 repetition-analysis validation ===")

    # V1 required files
    required = ["build_repetition_analysis.py", "validate_repetition_analysis.py",
                "repetition_results.json", "repetition_report.md",
                "stage_e2_manifest.json"]
    check("V1 required E2 files exist",
          all((HERE / f).is_file() for f in required),
          f"missing={[f for f in required if not (HERE / f).is_file()]}")

    res = json.loads((HERE / "repetition_results.json").read_text(encoding="utf-8"))
    report = (HERE / "repetition_report.md").read_text(encoding="utf-8")
    man = json.loads((HERE / "stage_e2_manifest.json").read_text(encoding="utf-8"))

    # V2 manifest hashes
    bad_in = [i["path"] for i in man["inputs"]
              if not (ROOT / i["path"]).is_file() or sha256(ROOT / i["path"]) != i["sha256"]]
    bad_out = [o["path"] for o in man["outputs"]
               if not (HERE / o["path"]).is_file() or sha256(HERE / o["path"]) != o["sha256"]]
    check("V2 manifest input/output hashes match live files", not bad_in and not bad_out,
          f"in={bad_in[:2]} out={bad_out[:2]}")
    check("V2b manifest declares no label/db writes and no model calls",
          man.get("gold_label_written") is False
          and man.get("source_db_written") is False
          and man.get("model_calls_made") is False)

    # V3 discovery + comparability (fresh)
    dirs = {}
    for label in EXPECTED_LABELS:
        m = sorted(p for p in (ROOT / "runs").glob(f"{label}-*") if p.is_dir())
        if len(m) != 1:
            check(f"V3 exactly one run dir for {label}", False, f"found={len(m)}")
            return _finish()
        dirs[label] = m[0]
    check("V3 exactly one run dir per expected label", True,
          ", ".join(dirs[l].name for l in EXPECTED_LABELS))
    manifests, reports = [], {}
    load_fail = []
    for label in EXPECTED_LABELS:
        try:
            m, r = load_run_artifacts(dirs[label])
        except Exception as exc:  # noqa: BLE001
            load_fail.append(f"{label}: {exc}")
            continue
        manifests.append(m)
        reports[label] = r
    check("V4a every repetition has readable manifest+report", not load_fail,
          f"fail={load_fail[:2]}")
    if load_fail or len(manifests) < 2:
        return _finish()
    try:
        require_comparable(manifests)
        check("V4 repetitions comparable (fresh check)", True)
    except Exception as exc:  # noqa: BLE001
        check("V4 repetitions comparable (fresh check)", False, str(exc)[:160])

    # V5 safety invariants (fresh)
    bad5 = []
    for label in EXPECTED_LABELS:
        rep = reports[label]
        corpus = rep.get("corpus", {})
        if not corpus.get("source_db_unchanged") or \
                corpus.get("source_db_sha256_before") != SOURCE_DB_SHA:
            bad5.append(f"{label}:source")
        db = dirs[label] / "evidencegraph-eval.db"
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM verif_claims WHERE gold_label IS NOT NULL"
            ).fetchone()[0]
        finally:
            con.close()
        if n:
            bad5.append(f"{label}:gold={n}")
    check("V5 source DB unchanged in every run; gold_label NULL everywhere",
          not bad5, f"bad={bad5}")
    check("V6 eval_questions.json hash unchanged",
          QUESTIONS.is_file() and sha256(QUESTIONS) == QUESTIONS_SHA)

    # V7 stability + aggregate recomputed fresh from run databases vs results JSON.
    # NOTE (validator defect fixed 2026-10-17): the first version compared the
    # freshly computed dict (tuple keys/values) with the JSON round-trip
    # (lists), which can never be equal. Both sides are now normalized through
    # json.dumps/loads before comparison -- like for like, not a bypass: the
    # values themselves are still independently recomputed from the run DBs.
    id_by_text = {q["question"]: q["id"]
                  for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]}
    outcomes = [question_outcomes(dirs[l] / "evidencegraph-eval.db", id_by_text)
                for l in EXPECTED_LABELS]
    stab = compare_repetitions(outcomes)
    agg = aggregate_reports([reports[l] for l in EXPECTED_LABELS])
    check("V7a stability recomputed == results.json",
          json.loads(json.dumps(stab)) == res.get("stability"),
          f"answers_identical={stab['answer_identical_all_repetitions']}/"
          f"{stab['units_total']}")
    check("V7b aggregate recomputed == results.json",
          json.loads(json.dumps(agg)) == res.get("aggregate"),
          f"all_completed={agg['all_completed']} calls={agg['usage']['calls']}")

    # V8 report quotes the numbers actually in results.json
    s = res["stability"]
    a = res["aggregate"]
    needles = [
        f"{s['answer_identical_all_repetitions']}/{s['units_total']}",
        f"answer_stability={s['answer_stability']}",
        f"calls={a['usage']['calls']}",
        f"all_completed={a['all_completed']}",
        f"stdev {a['elapsed_s']['stdev']}",
        str(res["between_run_variability"]["verified_claims_total_per_run"]),
        "**PASS** — " if res["comparability"]["pass"] else "**FAIL** — ",
    ]
    missing = [n for n in needles if n not in report]
    check("V8 report quotes recomputed numbers verbatim", not missing, f"missing={missing}")

    # V9 git untouched by this analysis
    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *a],
                              capture_output=True, text=True).stdout.strip()
    head, staged, mod = git("rev-parse", "--short", "HEAD"), git("diff", "--cached",
                                                                "--name-only"), git("diff", "--name-only")
    check("V9 git HEAD d4ea26d; no staged or tracked changes",
          head == "d4ea26d" and not staged and not mod, f"head={head}")

    # V10 honesty wording ("no significance" matches the report's own phrasing
    # "no significance testing, no superiority claim")
    must = ["smoke signal", "no significance", "never writes labels",
            "not independently validated", "does not prove the research hypothesis",
            "null rather than estimated"]
    banned = ["human-verified", "publication-ready", "proves the research hypothesis",
              "bit-perfect", "fully deterministic"]
    miss = [m for m in must if m not in report]
    hit = [b for b in banned if b in report]
    check("V10 mandated caveats present; banned victory phrases absent",
          not miss and not hit, f"missing={miss} banned={hit}")

    # V11 script hygiene (app.scaffolding import allowed; network/secrets banned)
    import re
    net_re = re.compile(
        r"^\s*(?:import|from)\s+(requests|httpx|socket|urllib|smtplib|ftplib)\b", re.M)
    sec_re = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}")
    bad11 = []
    for f in ("build_repetition_analysis.py", "validate_repetition_analysis.py"):
        txt = (HERE / f).read_text(encoding="utf-8")
        if net_re.search(txt):
            bad11.append(f"{f}:network")
        if sec_re.search(txt):
            bad11.append(f"{f}:secret")
    check("V11 scripts: no network imports, no secrets", not bad11, f"bad={bad11}")

    return _finish()


def _finish() -> int:
    passed = sum(1 for _, ok, _ in results if ok)
    lines = ["# Stage E2 Validation Report", "",
             f"- Run: `validate_repetition_analysis.py` · "
             f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
             f"- Result: **{passed}/{len(results)} checks PASS**", "",
             "| # | Check | Result | Detail |", "|---|-------|--------|--------|"]
    for i, (name, ok, detail) in enumerate(results, 1):
        lines.append(f"| {i} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    (HERE / "stage_e2_validation_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(results)} checks PASS "
          f"(report: stage_e2_validation_report.md)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
