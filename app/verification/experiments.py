"""Controlled-repetition experiment scaffolding (Stage E, authorized 2026-10-17).

What this module is
-------------------
Configuration, artifact loading, cross-repeat comparability checks, outcome
extraction, and aggregation for *controlled repetitions* of the tracked A/B
runner (`app.verification.runner`). It exists so that repeated runs are
recorded and compared under one predeclared configuration instead of being
stitched together by hand.

What it deliberately does NOT do
--------------------------------
- No model calls, no network, no database writes. Question outcomes are read
  from a run's own disposable copy of the eval database through a SQLite
  ``mode=ro`` URI; the corpus database and the source of record are never
  opened here.
- No statistical significance testing, no "winner" selection, no superiority
  claims. Aggregates are descriptive: counts, elapsed time, and honest token
  usage (which local Ollama runs do not report — totals stay ``null`` and are
  reported as unavailable rather than guessed).
- No label writing: ``verif_claims.gold_label`` is never touched; this module
  only reads ``label`` (the machine's verdict) and answer text.

Scope of any conclusion: repetitions over a 22-question set on a 6-chunk
corpus with one model are a reproducibility smoke signal for this fixture,
not a generalizable accuracy or stability figure.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Mapping, Sequence

VALID_ARMS = frozenset({"baseline", "verified"})
VALID_JUDGES = frozenset({"llm", "rules"})
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Manifest fields that must be identical across repetitions for the runs to
# be comparable at all. Any difference means the repetitions varied two
# things at once and must not be aggregated.
_COMPARABLE_FIELDS = (
    ("git", "commit"),
    ("git", "dirty"),
    ("dataset", "sha256"),
    ("corpus", "source_db_sha256_before"),
    ("provider", "name"),
    ("provider", "model"),
    ("provider", "base_url"),
    ("configuration", "temperature"),
    ("configuration", "max_tokens"),
    ("configuration", "retrieval_top_k"),
    ("configuration", "judge"),
    ("configuration", "prompt_version"),
    ("configuration", "judge_prompt_version"),
    ("configuration", "question_ids"),
)


class ExperimentError(RuntimeError):
    """A configuration, artifact, or comparability problem. Fail closed."""


@dataclass(frozen=True)
class ExperimentConfig:
    """Predeclared configuration for one experiment (N controlled repetitions)."""

    experiment_id: str
    question_ids: tuple[str, ...]
    repeats: int = 1
    arms: tuple[str, ...] = ("baseline", "verified")
    judge: str = "llm"
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.experiment_id, str) or not _ID_RE.match(self.experiment_id):
            raise ExperimentError(
                f"experiment_id must be a lowercase slug ([a-z0-9_-]), got {self.experiment_id!r}"
            )
        if not self.question_ids or any(not q for q in self.question_ids):
            raise ExperimentError("question_ids must be non-empty strings")
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ExperimentError("question_ids must be unique")
        if not isinstance(self.repeats, int) or self.repeats < 1:
            raise ExperimentError(f"repeats must be an int >= 1, got {self.repeats!r}")
        if not self.arms or any(a not in VALID_ARMS for a in self.arms):
            raise ExperimentError(
                f"arms must be a non-empty subset of {sorted(VALID_ARMS)}, got {self.arms!r}"
            )
        if len(set(self.arms)) != len(self.arms):
            raise ExperimentError("arms must not repeat")
        if self.judge not in VALID_JUDGES:
            raise ExperimentError(f"judge must be one of {sorted(VALID_JUDGES)}, got {self.judge!r}")

    @property
    def question_ids_list(self) -> list[str]:
        return list(self.question_ids)

    def labels(self) -> list[str]:
        """Run-directory labels, one per repetition (1-based)."""
        return [f"{self.experiment_id}-r{i}" for i in range(1, self.repeats + 1)]


def run_dir_names(config: ExperimentConfig) -> list[str]:
    """Expected run-directory labels in repetition order."""
    return config.labels()


def load_run_artifacts(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load (manifest, report) from a run directory; fail closed on absence.

    An unfinished or interrupted repetition may have a manifest without a
    report; that asymmetry is surfaced here as an ExperimentError so callers
    record it as a failure instead of silently dropping the repetition.
    """
    run_dir = Path(run_dir)
    m_path, r_path = run_dir / "manifest.json", run_dir / "report.json"
    if not m_path.is_file():
        raise ExperimentError(f"missing manifest.json in {run_dir}")
    if not r_path.is_file():
        raise ExperimentError(
            f"missing report.json in {run_dir} (interrupted repetition? record as failed)"
        )
    try:
        manifest = json.loads(m_path.read_text(encoding="utf-8"))
        report = json.loads(r_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"unreadable artifacts in {run_dir}: {exc}") from exc
    if manifest.get("run_id") != report.get("run_id"):
        raise ExperimentError(
            f"run_id mismatch in {run_dir}: manifest={manifest.get('run_id')!r} "
            f"report={report.get('run_id')!r}"
        )
    return manifest, report


def _field(manifest: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = manifest
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            return None
        cur = cur[key]
    return cur


def require_comparable(manifests: Sequence[Mapping[str, Any]]) -> None:
    """Raise ExperimentError listing every field that differs across runs.

    Comparability is a precondition, not a report footnote: repetitions that
    differ in commit, dataset, corpus, provider, sampling, judge, or question
    set answer a different question and must not be aggregated.
    """
    if len(manifests) < 2:
        return
    first = manifests[0]
    diffs: list[str] = []
    for path in _COMPARABLE_FIELDS:
        base = _field(first, path)
        for i, other in enumerate(manifests[1:], start=2):
            val = _field(other, path)
            if val != base:
                diffs.append(
                    f"{'.'.join(path)}: run1={base!r} run{i}={val!r}"
                )
    if diffs:
        raise ExperimentError(
            "repetitions are not comparable; differing configuration:\n  "
            + "\n  ".join(diffs)
        )


def question_outcomes(
    report_db: Path,
    question_id_by_text: Mapping[str, str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Read per-(question, system) outcomes from a run's eval DB (read-only).

    Returns ``{(question_id, system): {"answer_sha256", "answer_len",
    "claim_labels"}}``. Keyed by question id via the caller-supplied text map
    (``eval_results`` stores the question text, not its id). SQLite is opened
    through a ``mode=ro`` URI: this function cannot write, by construction.
    """
    db = Path(report_db)
    if not db.is_file():
        raise ExperimentError(f"eval database not found: {db}")
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT er.question, er.system, er.answer_text, "
            "       vc.label "
            "FROM eval_results er "
            "LEFT JOIN verif_claims vc ON vc.eval_result_id = er.id "
            "ORDER BY er.id, vc.claim_index"
        ).fetchall()
    except sqlite3.Error as exc:
        raise ExperimentError(f"cannot read outcomes from {db}: {exc}") from exc
    finally:
        con.close()

    out: dict[tuple[str, str], dict[str, Any]] = {}
    unknown: set[str] = set()
    for question_text, system, answer_text, label in rows:
        qid = question_id_by_text.get(question_text)
        if qid is None:
            unknown.add(question_text)
            continue
        key = (qid, system)
        slot = out.setdefault(
            key,
            {
                "answer_sha256": hashlib.sha256(
                    (answer_text or "").encode("utf-8")
                ).hexdigest(),
                "answer_len": len(answer_text or ""),
                "claim_labels": [],
            },
        )
        if label is not None:
            slot["claim_labels"].append(label)
    if unknown:
        raise ExperimentError(
            f"{len(unknown)} question text(s) in {db.name} not found in the supplied "
            f"id map, e.g. {sorted(unknown)[0][:60]!r}"
        )
    for slot in out.values():
        slot["claim_labels"] = tuple(slot["claim_labels"])
    return out


def compare_repetitions(
    outcomes: Sequence[Mapping[tuple[str, str], Mapping[str, Any]]],
) -> dict[str, Any]:
    """Describe answer/label stability across repetitions (descriptive only).

    Stability here means byte-identical stored answers and identical
    claim-label sequences at the same configuration — a reproducibility
    smoke signal for this fixture, not an accuracy measure.
    """
    if not outcomes:
        raise ExperimentError("no repetitions to compare")
    keys = sorted({k for rep in outcomes for k in rep})
    identical_answers: list[tuple[str, str]] = []
    identical_labels: list[tuple[str, str]] = []
    differing: list[dict[str, Any]] = []
    for key in keys:
        reps = [rep.get(key) for rep in outcomes]
        if any(r is None for r in reps):
            differing.append({"key": key, "reason": "missing in at least one repetition"})
            continue
        answers = {r["answer_sha256"] for r in reps}
        labels = {r["claim_labels"] for r in reps}
        if len(answers) == 1:
            identical_answers.append(key)
        if len(labels) == 1:
            identical_labels.append(key)
        if len(answers) != 1 or len(labels) != 1:
            differing.append(
                {
                    "key": key,
                    "distinct_answers": len(answers),
                    "distinct_label_sequences": len(labels),
                }
            )
    return {
        "repetitions": len(outcomes),
        "units_total": len(keys),
        "answer_identical_all_repetitions": len(identical_answers),
        "claim_labels_identical_all_repetitions": len(identical_labels),
        "answer_stability": round(len(identical_answers) / len(keys), 4) if keys else None,
        "differing": differing,
    }


def aggregate_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate repetition reports: status, latency, usage — honestly.

    Token totals are summed only when *every* repetition reports them;
    otherwise the total stays ``null`` with an explicit unavailable count
    (local Ollama reports no token usage — that is recorded, never guessed).
    """
    if not reports:
        raise ExperimentError("no reports to aggregate")
    statuses: dict[str, int] = {}
    elapsed: list[float] = []
    calls = calls_ok = calls_failed = 0
    purposes: dict[str, int] = {}
    token_rows: list[tuple[Any, Any]] = []
    for rep in reports:
        st = str(rep.get("status", "unknown"))
        statuses[st] = statuses.get(st, 0) + 1
        if isinstance(rep.get("elapsed_s"), (int, float)):
            elapsed.append(float(rep["elapsed_s"]))
        usage = rep.get("usage") or {}
        summary = usage.get("summary") or {}
        calls += int(summary.get("calls") or 0)
        calls_ok += int(summary.get("calls_ok") or 0)
        calls_failed += int(summary.get("calls_failed") or 0)
        for purpose, n in (usage.get("calls_by_purpose") or {}).items():
            purposes[purpose] = purposes.get(purpose, 0) + int(n)
        token_rows.append(
            (summary.get("total_input_tokens"), summary.get("total_output_tokens"))
        )

    all_tokens = all(inp is not None and out is not None for inp, out in token_rows)
    missing_tokens = sum(1 for inp, out in token_rows if inp is None or out is None)
    return {
        "repetitions": len(reports),
        "status_counts": statuses,
        "all_completed": statuses.get("completed", 0) == len(reports),
        "elapsed_s": {
            "n": len(elapsed),
            "mean": round(mean(elapsed), 3) if elapsed else None,
            "stdev": round(stdev(elapsed), 3) if len(elapsed) >= 2 else None,
            "min": min(elapsed) if elapsed else None,
            "max": max(elapsed) if elapsed else None,
        },
        "usage": {
            "calls": calls,
            "calls_ok": calls_ok,
            "calls_failed": calls_failed,
            "calls_by_purpose": dict(sorted(purposes.items())),
            "total_input_tokens": (
                sum(int(inp) for inp, _ in token_rows) if all_tokens else None
            ),
            "total_output_tokens": (
                sum(int(out) for _, out in token_rows) if all_tokens else None
            ),
            "token_totals_available": all_tokens,
            "repetitions_without_token_usage": missing_tokens,
        },
        "scope_caveat": (
            "Descriptive aggregate of small-N repetitions over one fixture; "
            "no significance, superiority, or generalization claim follows."
        ),
    }
