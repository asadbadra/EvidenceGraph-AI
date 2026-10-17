"""Stage E2 — controlled-repetition analysis (build).

Authorized 2026-10-17: third Stage E step after the approved analysis (E1),
test-backed scaffolding (app/verification/experiments.py), and smoke tests.

What it does
------------
Discovers the three approved repetitions (`runs/stage-e-repeat{1,2,3}-*`),
loads their manifest/report pairs through the scaffolding, asserts that the
repetitions are comparable (same commit, dataset, corpus, provider, sampling,
prompts, judge, question set), extracts per-(question, system) outcomes
read-only from each run's disposable eval database, verifies the two safety
invariants (source corpus unchanged; gold_label never written), then writes:

- repetition_results.json    machine-readable results
- repetition_report.md       human-readable report with caveats
- stage_e2_manifest.json     input/output provenance hashes

Fail-closed: missing run directories, non-comparable configuration, a
missing artifact, or a violated invariant aborts BEFORE any write.

Reads only: SQLite is opened mode=ro; no repository file outside this
directory is written; no model calls are made here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.verification.experiments import (  # noqa: E402
    ExperimentError,
    aggregate_reports,
    compare_repetitions,
    load_run_artifacts,
    question_outcomes,
    require_comparable,
)

EXPECTED_LABELS = ("stage-e-repeat1", "stage-e-repeat2", "stage-e-repeat3")
QUESTIONS = ROOT / "data" / "sample" / "eval_questions.json"
QUESTIONS_SHA = "500ed32d5546683392616685f024d9f5feebefec19806c53e1f03a34b33f3a3a"
SOURCE_DB_SHA = "0b9cacbac61f99d79bf01d6dcea67084bb298e9b8340b6f66562f14e558fe9c1"
REFERENCE_RUN = "eval-postgate22-20261016-141416"  # excluded, see report


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def die(msg: str) -> None:
    print(f"BUILD ABORTED (no files written): {msg}")
    raise SystemExit(1)


def find_run_dirs() -> dict[str, Path]:
    runs_root = ROOT / "runs"
    found: dict[str, Path] = {}
    for label in EXPECTED_LABELS:
        matches = sorted(p for p in runs_root.glob(f"{label}-*") if p.is_dir())
        if len(matches) != 1:
            die(f"expected exactly 1 run dir for label {label!r}, found {len(matches)}: "
                f"{[m.name for m in matches]}")
        found[label] = matches[0]
    return found


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # 1. hash-assert the question file before anything else
    if not QUESTIONS.is_file() or sha256(QUESTIONS) != QUESTIONS_SHA:
        die("eval_questions.json missing or hash mismatch")
    id_by_text = {
        q["question"]: q["id"]
        for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    }
    print(f"[1] question file verified; {len(id_by_text)} questions mapped")

    # 2. discover the three repetition dirs (fail-closed)
    dirs = find_run_dirs()
    print("[2] run dirs: " + ", ".join(f"{k}={v.name}" for k, v in dirs.items()))

    # 3. load artifacts; a failed/interrupted repetition is recorded, not hidden
    manifests: dict[str, dict] = {}
    reports: dict[str, dict] = {}
    load_errors: dict[str, str] = {}
    for label, d in dirs.items():
        try:
            manifests[label], reports[label] = load_run_artifacts(d)
        except ExperimentError as exc:
            load_errors[label] = str(exc)
    print(f"[3] loaded {len(reports)}/{len(dirs)} report pairs; "
          f"load_errors={load_errors or 'none'}")
    if not manifests:
        die("no manifests readable")
    if not reports:
        die("no completed reports to analyze")

    # 4. comparability across ALL three repetition manifests
    try:
        require_comparable([manifests[l] for l in EXPECTED_LABELS if l in manifests])
        comparable = True
        comparability_detail = "all comparability fields identical across repetitions"
    except ExperimentError as exc:
        comparable = False
        comparability_detail = str(exc)
    if not comparable:
        die(f"repetitions not comparable: {comparability_detail}")
    print("[4] comparability: PASS")

    # 5. safety invariants per completed run
    invariants = {}
    for label, rep in reports.items():
        corpus = rep.get("corpus", {})
        invariants[label] = {
            "source_db_unchanged": corpus.get("source_db_unchanged"),
            "source_sha_before": corpus.get("source_db_sha256_before"),
            "sha_matches_known_source": corpus.get("source_db_sha256_before") == SOURCE_DB_SHA,
        }
        if not (corpus.get("source_db_unchanged") and
                corpus.get("source_db_sha256_before") == SOURCE_DB_SHA):
            die(f"{label}: source corpus invariant violated: {invariants[label]}")
        db = dirs[label] / "evidencegraph-eval.db"
        if not db.is_file():
            die(f"{label}: missing eval db")
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            dirty = con.execute(
                "SELECT COUNT(*) FROM verif_claims WHERE gold_label IS NOT NULL"
            ).fetchone()[0]
        finally:
            con.close()
        invariants[label]["gold_labels_written"] = dirty
        if dirty:
            die(f"{label}: {dirty} gold_label value(s) written by a machine run")
    print(f"[5] invariants OK for {sorted(invariants)} "
          f"(source unchanged, gold_label NULL everywhere)")

    # 6. outcomes + stability across completed repetitions
    outcomes = {
        label: question_outcomes(dirs[label] / "evidencegraph-eval.db", id_by_text)
        for label in reports
    }
    stability = compare_repetitions([outcomes[l] for l in sorted(outcomes)])
    agg = aggregate_reports([reports[l] for l in sorted(reports)])
    print(f"[6] stability: {stability['answer_identical_all_repetitions']}/"
          f"{stability['units_total']} answers identical across "
          f"{stability['repetitions']} repetitions; "
          f"aggregate completed={agg['all_completed']}")

    # 7. write outputs (only now)
    config = manifests[sorted(manifests)[0]]["configuration"]
    per_run = {}
    for label in EXPECTED_LABELS:
        m, r = manifests.get(label), reports.get(label)
        per_run[label] = {
            "run_dir": dirs[label].name,
            "run_id": (r or m or {}).get("run_id"),
            "status": (r or {}).get("status", "missing_or_interrupted"),
            "elapsed_s": (r or {}).get("elapsed_s"),
            "load_error": load_errors.get(label),
            "per_system": (r or {}).get("per_system"),
        }

    # within-run observations (per-system counts) and between-run variability
    def _sys(label: str, system: str, field: str):
        ps = per_run[label].get("per_system") or {}
        return (ps.get(system) or {}).get(field)

    v_claims = [_sys(l, "verified", "claims_total") for l in EXPECTED_LABELS]
    v_nums = [c for c in v_claims if isinstance(c, int)]
    between = {
        "verified_claims_total_per_run": v_claims,
        "verified_claims_mean": round(mean(v_nums), 3) if v_nums else None,
        "verified_claims_stdev": round(stdev(v_nums), 3) if len(v_nums) >= 2 else None,
        "verified_claims_range": (
            [min(v_nums), max(v_nums)] if v_nums else None
        ),
    }

    results = {
        "stage": "E2-repetitions",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "experiment": {
            "labels": list(EXPECTED_LABELS),
            "question_count": len(id_by_text),
            "judge": config.get("judge"),
            "temperature": config.get("temperature"),
            "max_tokens": config.get("max_tokens"),
            "model": manifests[sorted(manifests)[0]].get("provider", {}).get("model"),
            "git_commit": manifests[sorted(manifests)[0]].get("git", {}).get("commit"),
        },
        "comparability": {"pass": comparable, "detail": comparability_detail},
        "invariants": invariants,
        "per_run": per_run,
        "between_run_variability": between,
        "aggregate": agg,
        "stability": stability,
        "known_discrepancies": [
            "Repeat 1's free-text --notes says '22-question run matching "
            "eval-postgate22', but its machine-readable configuration "
            "(authoritative) ran all 24 fixture questions; repeats 2-3 carry "
            "corrected notes. Comparability is decided on machine fields only.",
            "The historical eval-postgate22 ran a 22-question subset "
            "(excluded direct-02 and wrong-04) with git.dirty=false; it is "
            "excluded from strict comparability for that reason (and recorded "
            "here), not silently pooled.",
        ],
        "excluded_runs": {
            REFERENCE_RUN: "pre-Stage-E reference run: git.dirty=false vs true "
                            "(untracked analysis/ present during Stage E); excluded "
                            "from strict comparability, not silently pooled",
            "eval-20261017-155111": "mock-provider wiring smoke (1 question), not a repetition",
            "eval-20261017-155226": "real-path smoke (1 question), not a repetition",
        },
        "token_usage_note": (
            "Local Ollama reports no per-token usage: totals are null "
            "(unavailable), never estimated."
        ),
        "scope_caveats": [
            "Reproducibility smoke signal for one fixture/model, not a "
            "generalizable stability figure.",
            "No significance, superiority, or accuracy claim follows from these "
            "repetitions.",
        ],
    }
    out_json = HERE / "repetition_results.json"
    out_json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    stab = stability
    differing_rows = "\n".join(
        f"| {d['key'][0]} | {d['key'][1]} | {d.get('reason', '')} "
        f"| {d.get('distinct_answers', '')} | {d.get('distinct_label_sequences', '')} |"
        for d in stab["differing"]
    ) or "| — | — | no differing units | | |"
    run_rows = "\n".join(
        f"| {lbl} | {v['run_dir']} | {v['status']} | {v['elapsed_s']} | {v['load_error'] or '—'} |"
        for lbl, v in per_run.items()
    )
    u = agg["usage"]
    e = agg["elapsed_s"]
    sys_rows = "\n".join(
        f"| {lbl} | {_sys(lbl, 'verified', 'claims_total')} "
        f"| {_sys(lbl, 'verified', 'supported')} "
        f"| {_sys(lbl, 'verified', 'contradicted')} "
        f"| {_sys(lbl, 'verified', 'insufficient_evidence')} "
        f"| {_sys(lbl, 'verified', 'unverifiable')} "
        f"| {_sys(lbl, 'baseline', 'claims_total')} "
        f"| {_sys(lbl, 'baseline', 'citations_total')} |"
        for lbl in EXPECTED_LABELS
    )
    discrepancy_rows = "\n".join(f"- {d}" for d in results["known_discrepancies"])
    report = f"""# Stage E2 — Controlled-Repetition Report

- Built by `build_repetition_analysis.py` · {results['created_utc']}
- Experiment: {len(EXPECTED_LABELS)} repetitions × {len(id_by_text)} questions,
  model `{results['experiment']['model']}`, judge `{config.get('judge')}`,
  temperature {config.get('temperature')}, max_tokens {config.get('max_tokens')},
  commit `{results['experiment']['git_commit']}`, prompts
  `{config.get('prompt_version')}`/`{config.get('judge_prompt_version')}`
- Scaffolding under test: `app/verification.experiments` (offline unit tests in
  `tests/test_experiments.py`, part of the full pytest suite)

## 1. Comparability (precondition, checked before any aggregation)

**{'PASS' if comparable else 'FAIL'}** — {comparability_detail}

## 2. Per-repetition record

| label | run dir | status | elapsed_s | load error |
|-------|---------|--------|-----------|------------|
{run_rows}

Between-run aggregate: all_completed={agg['all_completed']}; elapsed n={e['n']}, mean
{e['mean']}s, stdev {e['stdev']}, min {e['min']}, max {e['max']};
calls={u['calls']} (ok={u['calls_ok']}, failed={u['calls_failed']}), by purpose {u['calls_by_purpose']}.
Verified-claims per run: {between['verified_claims_total_per_run']} (mean
{between['verified_claims_mean']}, stdev {between['verified_claims_stdev']}, range
{between['verified_claims_range']}).
Token usage: totals_available={u['token_totals_available']}
({u['repetitions_without_token_usage']} repetition(s) without usage) — local Ollama
reports no token counts; totals stay null rather than estimated.

## 2b. Within-run observations (per-system counts per repetition)

| run | v claims | v supported | v contradicted | v insufficient | v unverifiable | b claims | b citations |
|-----|----------|-------------|----------------|----------------|-----------------|----------|-------------|
{sys_rows}

Within-run counts describe what each run's verifier SAID (mechanism metrics),
not whether it was right; between-run variability above describes only these
repetitions of one model on one fixture.

## 3. Reproducibility (descriptive)

- Units (question × system): {stab['units_total']}
- Answers byte-identical across ALL {stab['repetitions']} repetitions:
  {stab['answer_identical_all_repetitions']}/{stab['units_total']}
  (answer_stability={stab['answer_stability']})
- Claim-label sequences identical across all repetitions:
  {stab['claim_labels_identical_all_repetitions']}/{stab['units_total']}
- Differing units:

| question | system | reason | distinct answers | distinct label sequences |
|----------|--------|--------|------------------|--------------------------|
{differing_rows}

Interpretation: temperature 0 does not make the local model bit-deterministic;
these counts describe THIS fixture and model only and are a reproducibility
smoke signal, not an accuracy or quality figure.

## 4. Safety invariants (verified per run)

- Source corpus `data/evidencegraph.db` unchanged in every run
  (sha `{SOURCE_DB_SHA[:16]}…` before == after, `source_db_unchanged=True`).
- `verif_claims.gold_label IS NULL` for every row in every run database
  (a machine run never writes labels).
- Runs live under `runs/` (git-ignored): no run output is published by the
  planned repository update; run provenance stays local.

## 5. Exclusions (recorded, not silently pooled)

{chr(10).join(f"- **{k}** — {v}" for k, v in results['excluded_runs'].items())}

## 5b. Known discrepancies (recorded, not silently corrected)

{discrepancy_rows}

## 6. Limitations

- One model, one fixture corpus (6 chunks), {len(id_by_text)} questions,
  clustered claims: no significance testing, no superiority claim.
- `gold_label` remains NULL: these repetitions say nothing about correctness;
  judge-vs-single-reviewer comparisons live only in the Stage E1 annotation
  report (single-reviewer human labels, not independently validated).
- Completing repetitions does not prove the research hypothesis.
"""
    out_md = HERE / "repetition_report.md"
    out_md.write_text(report, encoding="utf-8")

    inputs = [dirs[l] / "manifest.json" for l in EXPECTED_LABELS]
    inputs += [dirs[l] / "report.json" for l in EXPECTED_LABELS if l in reports]
    inputs += [dirs[l] / "evidencegraph-eval.db" for l in EXPECTED_LABELS]
    inputs += [QUESTIONS]
    manifest = {
        "stage": "E2-repetitions",
        "created_utc": results["created_utc"],
        "inputs": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in inputs],
        "outputs": [
            {"path": out_json.name, "sha256": sha256(out_json)},
            {"path": out_md.name, "sha256": sha256(out_md)},
        ],
        "gold_label_written": False,
        "source_db_written": False,
        "model_calls_made": False,
    }
    (HERE / "stage_e2_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[7] wrote {out_json.name}, {out_md.name}, stage_e2_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
