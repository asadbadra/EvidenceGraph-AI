"""Stage E scaffolding tests — offline, deterministic, no model calls.

Covers app.verification.experiments: configuration fail-closed validation,
run-artifact loading, cross-repeat comparability, read-only outcome
extraction, stability comparison, and honest aggregation. The autouse
network block in tests/conftest.py guarantees no socket access; the SQLite
fixtures below are tiny local files created and owned by the test.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app.verification.experiments import (
    ExperimentConfig,
    ExperimentError,
    aggregate_reports,
    compare_repetitions,
    load_run_artifacts,
    question_outcomes,
    require_comparable,
    run_dir_names,
)


def _cfg(**overrides) -> ExperimentConfig:
    base = dict(
        experiment_id="stage-e-smoke",
        question_ids=("q-01", "q-02"),
        repeats=3,
    )
    base.update(overrides)
    return ExperimentConfig(**base)


# --------------------------------------------------------------------------
# ExperimentConfig
# --------------------------------------------------------------------------


def test_config_valid_and_labels_are_one_based():
    cfg = _cfg()
    assert cfg.labels() == ["stage-e-smoke-r1", "stage-e-smoke-r2", "stage-e-smoke-r3"]
    assert run_dir_names(cfg) == cfg.labels()
    assert cfg.question_ids_list == ["q-01", "q-02"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"experiment_id": ""},                       # empty
        {"experiment_id": "Stage-E"},                # uppercase not a slug
        {"experiment_id": "-leading-dash"},          # must start [a-z0-9]
        {"question_ids": ()},                        # empty question set
        {"question_ids": ("q-01", "q-01")},          # duplicates
        {"question_ids": ("",)},                      # empty id
        {"repeats": 0},                              # must be >= 1
        {"repeats": -2},
        {"repeats": "3"},                            # not an int
        {"arms": ()},                                # empty arms
        {"arms": ("baseline", "bogus")},             # unknown arm
        {"arms": ("verified", "verified")},          # repeated arm
        {"judge": "gpt"},                            # unknown judge
    ],
)
def test_config_rejects_invalid_input(overrides):
    with pytest.raises(ExperimentError):
        _cfg(**overrides)


# --------------------------------------------------------------------------
# load_run_artifacts
# --------------------------------------------------------------------------


def _write_run(dir_path: Path, run_id: str, report_overrides: dict | None = None):
    dir_path.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": run_id, "label": run_id, "git": {"commit": "d4ea26d"}}
    report = {"run_id": run_id, "status": "completed", "elapsed_s": 10.0,
              "usage": {"summary": {"calls": 5, "calls_ok": 5, "calls_failed": 0},
                        "calls_by_purpose": {"judge": 2}}}
    if report_overrides:
        report.update(report_overrides)
    (dir_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (dir_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return manifest, report


def test_load_run_artifacts_happy_path(tmp_path: Path):
    _write_run(tmp_path / "run-a", "run-a")
    manifest, report = load_run_artifacts(tmp_path / "run-a")
    assert manifest["run_id"] == "run-a"
    assert report["status"] == "completed"


def test_load_run_artifacts_missing_manifest(tmp_path: Path):
    (tmp_path / "run-b").mkdir()
    with pytest.raises(ExperimentError, match="missing manifest"):
        load_run_artifacts(tmp_path / "run-b")


def test_load_run_artifacts_interrupted_run_has_no_report(tmp_path: Path):
    d = tmp_path / "run-c"
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({"run_id": "run-c"}), encoding="utf-8"
    )
    with pytest.raises(ExperimentError, match="interrupted"):
        load_run_artifacts(d)


def test_load_run_artifacts_rejects_run_id_mismatch(tmp_path: Path):
    d = tmp_path / "run-d"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"run_id": "x"}), encoding="utf-8")
    (d / "report.json").write_text(json.dumps({"run_id": "y"}), encoding="utf-8")
    with pytest.raises(ExperimentError, match="run_id mismatch"):
        load_run_artifacts(d)


def test_load_run_artifacts_rejects_unreadable_json(tmp_path: Path):
    d = tmp_path / "run-e"
    d.mkdir()
    (d / "manifest.json").write_text("{not json", encoding="utf-8")
    (d / "report.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ExperimentError, match="unreadable"):
        load_run_artifacts(d)


# --------------------------------------------------------------------------
# require_comparable
# --------------------------------------------------------------------------


def _manifest(temperature=0.0, judge="llm", model="llama3.2:latest",
              source_sha="abc", question_ids=("q-01", "q-02"),
              commit="d4ea26d", prompt_version="baseline-v1") -> dict:
    return {
        "git": {"commit": commit, "dirty": True},
        "dataset": {"sha256": "ds"},
        "corpus": {"source_db_sha256_before": source_sha},
        "provider": {"name": "openai", "model": model,
                     "base_url": "http://localhost:11434/v1"},
        "configuration": {
            "temperature": temperature,
            "max_tokens": 700,
            "retrieval_top_k": 4,
            "judge": judge,
            "prompt_version": prompt_version,
            "judge_prompt_version": "judge-v1",
            "question_ids": list(question_ids),
        },
    }


def test_comparable_accepts_identical_and_single_run():
    require_comparable([_manifest()])
    require_comparable([_manifest(), _manifest(), _manifest()])


@pytest.mark.parametrize(
    "overrides,needle",
    [
        ({"temperature": 0.7}, "configuration.temperature"),
        ({"judge": "rules"}, "configuration.judge"),
        ({"model": "other:latest"}, "provider.model"),
        ({"source_sha": "zzz"}, "corpus.source_db_sha256_before"),
        ({"question_ids": ("q-01",)}, "configuration.question_ids"),
        ({"commit": "deadbee"}, "git.commit"),
        ({"prompt_version": "baseline-v2"}, "configuration.prompt_version"),
    ],
)
def test_comparable_rejects_differing_configuration(overrides, needle):
    with pytest.raises(ExperimentError) as exc:
        require_comparable([_manifest(), _manifest(**overrides)])
    assert needle in str(exc.value)


# --------------------------------------------------------------------------
# question_outcomes (read-only)
# --------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE eval_results (
    id INTEGER PRIMARY KEY,
    eval_run_id INTEGER,
    system TEXT,
    question TEXT,
    answer_text TEXT
);
CREATE TABLE verif_claims (
    id INTEGER PRIMARY KEY,
    eval_result_id INTEGER,
    claim_index INTEGER,
    claim_text TEXT,
    label TEXT,
    gold_label TEXT
);
"""


def _make_eval_db(path: Path, with_gold: str | None = None) -> None:
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA)
    rows = [
        (1, 1, "baseline", "Question A?", "Answer A baseline."),
        (2, 1, "verified", "Question A?", "Answer A verified."),
        (3, 1, "baseline", "Question B?", "Answer B baseline."),
        (4, 1, "verified", "Question B?", "Answer B verified."),
    ]
    con.executemany(
        "INSERT INTO eval_results (id, eval_run_id, system, question, answer_text) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    claims = [
        (1, 2, 0, "Claim A1", "supported", with_gold),
        (2, 2, 1, "Claim A2", "insufficient_evidence", None),
        (3, 4, 0, "Claim B1", "contradicted", None),
    ]
    con.executemany(
        "INSERT INTO verif_claims (id, eval_result_id, claim_index, claim_text, "
        "label, gold_label) VALUES (?, ?, ?, ?, ?, ?)",
        claims,
    )
    con.commit()
    con.close()


_ID_MAP = {"Question A?": "q-01", "Question B?": "q-02"}


def test_question_outcomes_extracts_keys_hashes_and_label_sequences(tmp_path: Path):
    db = tmp_path / "eval.db"
    _make_eval_db(db, with_gold="contradicted")
    out = question_outcomes(db, _ID_MAP)
    assert set(out) == {
        ("q-01", "baseline"), ("q-01", "verified"),
        ("q-02", "baseline"), ("q-02", "verified"),
    }
    assert out[("q-01", "verified")]["claim_labels"] == (
        "supported", "insufficient_evidence",
    )
    assert out[("q-01", "baseline")]["claim_labels"] == ()
    expected_sha = hashlib.sha256(b"Answer A baseline.").hexdigest()
    assert out[("q-01", "baseline")]["answer_sha256"] == expected_sha
    assert out[("q-02", "verified")]["answer_len"] == len("Answer B verified.")


def test_question_outcomes_never_writes_gold_labels(tmp_path: Path):
    db = tmp_path / "eval.db"
    _make_eval_db(db, with_gold="contradicted")
    question_outcomes(db, _ID_MAP)
    # Confirm the run database is byte-identical after reading (read-only).
    before = db.read_bytes()
    question_outcomes(db, _ID_MAP)
    assert db.read_bytes() == before
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("UPDATE verif_claims SET gold_label = 'x' WHERE id = 1")
    con.close()


def test_question_outcomes_rejects_unknown_question_text(tmp_path: Path):
    db = tmp_path / "eval.db"
    _make_eval_db(db)
    with pytest.raises(ExperimentError, match="not found in the supplied"):
        question_outcomes(db, {"Question A?": "q-01"})  # Question B missing


def test_question_outcomes_rejects_missing_db(tmp_path: Path):
    with pytest.raises(ExperimentError, match="eval database not found"):
        question_outcomes(tmp_path / "nope.db", _ID_MAP)


def test_question_outcomes_fails_closed_on_bad_schema(tmp_path: Path):
    db = tmp_path / "broken.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE eval_results (id INTEGER);")
    con.close()
    with pytest.raises(ExperimentError, match="cannot read outcomes"):
        question_outcomes(db, _ID_MAP)


# --------------------------------------------------------------------------
# compare_repetitions
# --------------------------------------------------------------------------


def _outcomes(answer: str, labels: tuple) -> dict:
    return {
        ("q-01", "verified"): {
            "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
            "answer_len": len(answer),
            "claim_labels": labels,
        },
        ("q-02", "verified"): {
            "answer_sha256": hashlib.sha256(b"same").hexdigest(),
            "answer_len": 4,
            "claim_labels": ("supported",),
        },
    }


def test_compare_repetitions_identical_is_fully_stable():
    result = compare_repetitions([_outcomes("A", ("supported",)),
                                  _outcomes("A", ("supported",))])
    assert result["repetitions"] == 2
    assert result["units_total"] == 2
    assert result["answer_identical_all_repetitions"] == 2
    assert result["answer_stability"] == 1.0
    assert result["differing"] == []


def test_compare_repetitions_reports_answer_and_label_drift():
    result = compare_repetitions([
        _outcomes("A", ("supported",)),
        _outcomes("B", ("supported",)),          # answer drift on q-01
        _outcomes("A", ("contradicted",)),       # label drift on q-01
    ])
    assert result["answer_identical_all_repetitions"] == 1   # q-02 stable
    assert result["claim_labels_identical_all_repetitions"] == 1
    assert result["answer_stability"] == 0.5
    drifted = {d["key"]: d for d in result["differing"]}
    assert drifted[("q-01", "verified")]["distinct_answers"] == 2
    assert drifted[("q-01", "verified")]["distinct_label_sequences"] == 2


def test_compare_repetitions_flags_missing_unit():
    a = _outcomes("A", ("supported",))
    b = {k: v for k, v in _outcomes("A", ("supported",)).items()
         if k != ("q-02", "verified")}
    result = compare_repetitions([a, b])
    reasons = [d.get("reason") for d in result["differing"] if "reason" in d]
    assert reasons == ["missing in at least one repetition"]


def test_compare_repetitions_rejects_empty_input():
    with pytest.raises(ExperimentError):
        compare_repetitions([])


# --------------------------------------------------------------------------
# aggregate_reports
# --------------------------------------------------------------------------


def _report(status="completed", elapsed=10.0, calls=5, inp=100, out=50,
            purposes=None) -> dict:
    return {
        "status": status,
        "elapsed_s": elapsed,
        "usage": {
            "summary": {
                "calls": calls, "calls_ok": calls if status == "completed" else 0,
                "calls_failed": 0 if status == "completed" else calls,
                "total_input_tokens": inp, "total_output_tokens": out,
            },
            "calls_by_purpose": purposes or {"judge": calls},
        },
    }


def test_aggregate_reports_stats_and_token_totals():
    agg = aggregate_reports([_report(elapsed=10.0, calls=4),
                             _report(elapsed=20.0, calls=6)])
    assert agg["repetitions"] == 2
    assert agg["status_counts"] == {"completed": 2}
    assert agg["all_completed"] is True
    assert agg["elapsed_s"] == {"n": 2, "mean": 15.0, "stdev": 7.071,
                                "min": 10.0, "max": 20.0}
    assert agg["usage"]["calls"] == 10
    assert agg["usage"]["total_input_tokens"] == 200
    assert agg["usage"]["total_output_tokens"] == 100
    assert agg["usage"]["token_totals_available"] is True
    assert agg["usage"]["repetitions_without_token_usage"] == 0
    assert "no significance" in agg["scope_caveat"]


def test_aggregate_reports_stdev_and_single_run_degeneracy():
    three = aggregate_reports([_report(elapsed=10.0), _report(elapsed=20.0),
                               _report(elapsed=30.0)])
    assert three["elapsed_s"] == {"n": 3, "mean": 20.0, "stdev": 10.0,
                                  "min": 10.0, "max": 30.0}
    one = aggregate_reports([_report(elapsed=12.5)])
    assert one["elapsed_s"] == {"n": 1, "mean": 12.5, "stdev": None,
                                "min": 12.5, "max": 12.5}


def test_aggregate_reports_marks_failure_runs_incomplete():
    agg = aggregate_reports([_report(), _report(status="failed")])
    assert agg["status_counts"] == {"completed": 1, "failed": 1}
    assert agg["all_completed"] is False
    assert agg["usage"]["calls_failed"] == 5


def test_aggregate_reports_refuses_to_guess_missing_token_totals():
    # Local Ollama reports no token usage: totals are None, never invented.
    agg = aggregate_reports([_report(inp=100, out=50), _report(inp=None, out=None)])
    assert agg["usage"]["total_input_tokens"] is None
    assert agg["usage"]["total_output_tokens"] is None
    assert agg["usage"]["token_totals_available"] is False
    assert agg["usage"]["repetitions_without_token_usage"] == 1
    assert agg["usage"]["calls"] == 10  # call counts still summed honestly


def test_aggregate_reports_rejects_empty_input():
    with pytest.raises(ExperimentError):
        aggregate_reports([])
