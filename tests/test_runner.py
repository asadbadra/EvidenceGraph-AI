"""Tests for the tracked evaluation runner (app.verification.runner, Stage A).

Offline by construction: the mock provider or an injected scripted client, a
temporary SQLite corpus copied per run, and the autouse blocked-socket fixture
from conftest. No live API calls, no writes to any tracked location.

SCOPE: these tests establish that a run (1) records full provenance --
git commit, provider/model, configuration, dataset and corpus hashes,
timestamp, output locations; (2) never opens the source database for
writing; (3) never overwrites an existing run directory; (4) never writes
gold labels; (5) refuses unsafe endpoints unless explicitly allowed; and
(6) rolls back and records an honest failed report when a run dies
mid-way. They make NO claim about the quality of any run's results.
"""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.verification.runner as runner_module
from app.config import Settings
from app.db import (
    EvalResult,
    EvalRun,
    VerifClaim,
    init_db,
    make_engine,
    make_session_factory,
)
from app.ingestion.loader import load_advisories
from app.llm.prompts import PROMPT_VERSION
from app.verification.judge import JUDGE_PROMPT_VERSION
from app.verification.runner import (
    RunnerError,
    check_endpoint,
    copy_source_db,
    git_provenance,
    main,
    prepare_run_dir,
    run_evaluation,
    sha256_of,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "data" / "sample" / "advisories.json"
PILOT = REPO / "data" / "sample" / "eval_questions.json"

ANSWER = "Apache Log4j2 allows remote code execution [1]."


class ScriptedLLM:
    """Deterministic client: pops one scripted response per call."""

    def __init__(self, responses: list[str], model: str = "scripted") -> None:
        self.model = model
        self._responses = list(responses)

    def complete(self, prompt: str) -> str:
        if not self._responses:
            raise AssertionError("scripted LLM exhausted")
        return self._responses.pop(0)


def _pilot_ids(n: int = 2) -> list[str]:
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    return [str(q["id"]) for q in payload["questions"][:n]]


def _mock_settings(**overrides) -> Settings:
    values = dict(
        llm_provider="mock",
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="",
        llm_model="offline-mock",
        llm_temperature=0.0,
        llm_max_tokens=700,
        llm_timeout_seconds=60.0,
        retrieval_top_k=4,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def source_db(tmp_path: Path) -> Path:
    """A corpus database FILE with the five sample records ingested."""
    path = tmp_path / "corpus.db"
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    init_db(engine)
    session = make_session_factory(engine)()
    report = load_advisories(session, FIXTURE)
    assert report.documents == 5, "sample fixture should contain 5 valid records"
    session.commit()
    session.close()
    engine.dispose()
    return path


def _read_eval_rows(db_path: Path) -> tuple[int, int, list]:
    """(eval_runs, eval_results, gold labels) from a database file."""
    session = make_session_factory(make_engine(f"sqlite:///{db_path.as_posix()}"))()
    try:
        gold = [c.gold_label for c in session.query(VerifClaim).all()]
        return (
            session.query(EvalRun).count(),
            session.query(EvalResult).count(),
            gold,
        )
    finally:
        session.close()


# --------------------------------------------------------------------------
# Provenance: what a completed run records
# --------------------------------------------------------------------------


def test_run_evaluation_records_full_provenance(source_db: Path, tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    ids = _pilot_ids(2)
    artifacts = run_evaluation(
        settings=_mock_settings(),
        questions_path=PILOT,
        source_db=source_db,
        runs_root=runs_root,
        label="provenance-test",
        question_ids=ids,
        judge_kind="rules",
        notes="stage-a runner test",
    )
    manifest = artifacts.manifest
    # On-disk and in-memory copies agree.
    assert json.loads(artifacts.manifest_path.read_text(encoding="utf-8")) == manifest

    # Git provenance: best-effort, recorded, never guessed.
    git = manifest["git"]
    assert set(git) == {"commit", "dirty", "error"}
    if git["commit"] is not None:
        assert re.fullmatch(r"[0-9a-f]{40}", git["commit"])
        assert isinstance(git["dirty"], bool)

    # Provider and configuration.
    provider = manifest["provider"]
    assert provider["name"] == "mock"
    assert provider["model"] == "offline-mock"
    assert provider["is_mock"] is True
    assert provider["remote_endpoint_allowed"] is False
    config = manifest["configuration"]
    assert config["temperature"] == 0.0
    assert config["max_tokens"] == 700
    assert config["retrieval_top_k"] == 4
    assert config["judge"] == "rules"
    assert config["question_ids"] == ids
    assert config["question_count"] == 2
    assert config["notes"] == "stage-a runner test"
    assert config["prompt_version"] == PROMPT_VERSION
    assert config["judge_prompt_version"] == JUDGE_PROMPT_VERSION

    # Dataset and corpus hashes.
    assert manifest["dataset"]["sha256"] == sha256_of(PILOT)
    assert manifest["corpus"]["source_db_sha256_before"] == sha256_of(source_db)
    assert manifest["corpus"]["documents"] == 5
    assert manifest["corpus"]["chunks"] > 0

    # Timestamp, environment, and output locations.
    datetime.fromisoformat(manifest["created_utc"])  # parses
    assert manifest["environment"]["python"]
    outputs = manifest["outputs"]
    assert Path(outputs["run_dir"]) == artifacts.run_dir
    assert Path(outputs["manifest_path"]) == artifacts.manifest_path
    assert Path(outputs["report_path"]) == artifacts.report_path
    assert Path(outputs["eval_db"]) == artifacts.eval_db_path

    # Secrets stay out of the provenance record.
    assert "llm_api_key" not in json.dumps(manifest)


def test_completed_run_stays_in_the_copy_and_writes_no_labels(
    source_db: Path, tmp_path: Path
) -> None:
    source_before = sha256_of(source_db)
    artifacts = run_evaluation(
        settings=_mock_settings(),
        questions_path=PILOT,
        source_db=source_db,
        runs_root=tmp_path / "runs",
        label="copy-test",
        question_ids=_pilot_ids(2),
        judge_kind="rules",
    )
    report = artifacts.report
    assert json.loads(artifacts.report_path.read_text(encoding="utf-8")) == report
    assert report["status"] == "completed"
    assert isinstance(report["eval_run_id"], int)
    assert report["corpus"]["source_db_unchanged"] is True
    assert sha256_of(source_db) == source_before  # provably read-only

    # One row per system per question; the check flags distinguish the arms.
    assert report["per_system"]["baseline"]["questions"] == 2
    assert report["per_system"]["verified"]["questions"] == 2
    assert report["per_system"]["baseline"]["claim_check_performed"] is False
    assert report["per_system"]["verified"]["claim_check_performed"] is True
    assert set(report["citation_quality"]) == {"baseline", "verified"}

    # Rows live in the COPY only, and every gold_label is NULL.
    runs, results, gold = _read_eval_rows(artifacts.eval_db_path)
    assert runs == 1
    assert results == 4  # 2 questions x 2 systems
    assert gold == [None] * len(gold)
    source_runs, _, _ = _read_eval_rows(source_db)
    assert source_runs == 0


def test_llm_judge_with_mock_provider_degrades_honestly(
    source_db: Path, tmp_path: Path
) -> None:
    """Mock judge output is malformed -> unverifiable, an honest outcome."""
    artifacts = run_evaluation(
        settings=_mock_settings(),
        questions_path=PILOT,
        source_db=source_db,
        runs_root=tmp_path / "runs",
        label="judge-test",
        question_ids=_pilot_ids(1),
        judge_kind="llm",
    )
    verified = artifacts.report["per_system"]["verified"]
    assert artifacts.report["status"] == "completed"
    assert verified["claim_check_performed"] is True
    if verified["claims_total"]:
        assert (
            verified["supported"]
            + verified["contradicted"]
            + verified["insufficient_evidence"]
            + verified["unverifiable"]
            == verified["claims_total"]
        )


# --------------------------------------------------------------------------
# Safety: endpoints, overwrite guards, side-effect ordering
# --------------------------------------------------------------------------


def test_endpoint_guard_unit() -> None:
    local = _mock_settings(
        llm_provider="openai", llm_base_url="http://localhost:11434/v1"
    )
    check_endpoint(local, allow_remote_endpoint=False)  # localhost is fine

    remote = _mock_settings(
        llm_provider="openai", llm_base_url="https://api.openai.com/v1"
    )
    with pytest.raises(RunnerError, match="non-local"):
        check_endpoint(remote, allow_remote_endpoint=False)
    check_endpoint(remote, allow_remote_endpoint=True)  # explicit override

    mock = _mock_settings(
        llm_provider="mock", llm_base_url="https://api.openai.com/v1"
    )
    check_endpoint(mock, allow_remote_endpoint=False)  # mock never calls out


def test_remote_endpoint_refused_without_override(
    source_db: Path, tmp_path: Path
) -> None:
    runs_root = tmp_path / "runs"
    settings = _mock_settings(
        llm_provider="openai",
        llm_base_url="https://api.openai.com/v1",
        llm_api_key="sk-must-not-be-used",
    )
    with pytest.raises(RunnerError, match="non-local"):
        run_evaluation(
            settings=settings,
            questions_path=PILOT,
            source_db=source_db,
            runs_root=runs_root,
            label="guard-test",
            question_ids=_pilot_ids(1),
            judge_kind="rules",
        )
    assert not runs_root.exists()  # refused before any side effect


def test_allow_remote_endpoint_is_recorded_in_the_manifest(
    source_db: Path, tmp_path: Path
) -> None:
    settings = _mock_settings(
        llm_provider="openai",
        llm_base_url="https://api.example.invalid/v1",
        llm_api_key="sk-test-key-123",
        llm_model="remote-test-model",
    )

    def scripted(_settings: Settings) -> ScriptedLLM:
        return ScriptedLLM([ANSWER, ANSWER], model="remote-test-model")

    artifacts = run_evaluation(
        settings=settings,
        questions_path=PILOT,
        source_db=source_db,
        runs_root=tmp_path / "runs",
        label="remote-test",
        question_ids=_pilot_ids(1),
        judge_kind="rules",
        allow_remote_endpoint=True,
        llm_factory=scripted,
    )
    provider = artifacts.manifest["provider"]
    assert provider["remote_endpoint_allowed"] is True
    assert provider["base_url"] == "https://api.example.invalid/v1"
    assert provider["name"] == "openai"
    # The API key never lands in either artifact.
    assert "sk-test-key-123" not in artifacts.manifest_path.read_text(encoding="utf-8")
    assert "sk-test-key-123" not in artifacts.report_path.read_text(encoding="utf-8")


def test_prepare_run_dir_refuses_to_overwrite_an_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    monkeypatch.setattr(runner_module, "datetime", _FixedDateTime)
    first = prepare_run_dir(tmp_path, "eval")
    assert first == tmp_path / "eval-20260102-030405"
    with pytest.raises(RunnerError, match="refusing to overwrite"):
        prepare_run_dir(tmp_path, "eval")


def test_invalid_run_labels_are_refused(tmp_path: Path) -> None:
    for bad in ("", ".", "..", "a/b", "a\\b"):
        with pytest.raises(RunnerError, match="invalid run label"):
            prepare_run_dir(tmp_path, bad)


def test_copy_source_db_refuses_overwrite_and_missing_source(
    source_db: Path, tmp_path: Path
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    target = copy_source_db(source_db, run_dir)
    assert target.is_file()
    assert sha256_of(target) == sha256_of(source_db)
    with pytest.raises(RunnerError, match="refusing to overwrite"):
        copy_source_db(source_db, run_dir)
    with pytest.raises(RunnerError, match="not found"):
        copy_source_db(tmp_path / "missing.db", run_dir)


def test_unknown_question_id_leaves_no_run_directory(
    source_db: Path, tmp_path: Path
) -> None:
    runs_root = tmp_path / "runs"
    with pytest.raises(RunnerError, match="unknown question ids"):
        run_evaluation(
            settings=_mock_settings(),
            questions_path=PILOT,
            source_db=source_db,
            runs_root=runs_root,
            label="typo-test",
            question_ids=["no-such-id"],
            judge_kind="rules",
        )
    assert not runs_root.exists()


# --------------------------------------------------------------------------
# Failure honesty: rollback, failed reports, best-effort provenance
# --------------------------------------------------------------------------


def test_empty_corpus_run_fails_with_honest_report(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    empty_db = tmp_path / "empty.db"
    engine = make_engine(f"sqlite:///{empty_db.as_posix()}")
    init_db(engine)
    engine.dispose()

    with pytest.raises(ValueError, match="corpus is empty"):
        run_evaluation(
            settings=_mock_settings(),
            questions_path=PILOT,
            source_db=empty_db,
            runs_root=runs_root,
            label="failure-test",
            question_ids=_pilot_ids(1),
            judge_kind="rules",
        )
    run_dirs = list(runs_root.iterdir())
    assert len(run_dirs) == 1  # the failed run still leaves its artifacts
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "corpus is empty" in report["failure_note"]
    assert report["eval_run_id"] is None
    runs, _, _ = _read_eval_rows(run_dirs[0] / "evidencegraph-eval.db")
    assert runs == 0  # nothing was committed


def test_mid_run_failure_rolls_back_partial_rows(
    source_db: Path, tmp_path: Path
) -> None:
    """The baseline arm finishes, the verified arm dies: no rows survive."""

    class ExhaustedLLM:
        model = "exhausted"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt: str) -> str:
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("scripted LLM exhausted")
            return ANSWER

    runs_root = tmp_path / "runs"
    with pytest.raises(AssertionError, match="exhausted"):
        run_evaluation(
            settings=_mock_settings(),
            questions_path=PILOT,
            source_db=source_db,
            runs_root=runs_root,
            label="rollback-test",
            question_ids=_pilot_ids(1),
            judge_kind="rules",
            llm_factory=lambda _settings: ExhaustedLLM(),
        )
    run_dirs = list(runs_root.iterdir())
    assert len(run_dirs) == 1
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "exhausted" in report["failure_note"]
    # The one call that DID complete is still recorded, honestly partial.
    assert report["usage"]["calls_by_purpose"] == {"baseline_generation": 1}
    # Single transaction: the baseline's flushed row never reached the file.
    runs, results, _ = _read_eval_rows(run_dirs[0] / "evidencegraph-eval.db")
    assert (runs, results) == (0, 0)


def test_pre_manifest_failure_still_writes_auditable_record(
    source_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A migration error BEFORE the manifest exists still leaves a record.

    The report must say the manifest was never written (no guessing), and
    the source database must be untouched.
    """

    def boom(_engine) -> None:
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(runner_module, "init_db", boom)
    runs_root = tmp_path / "runs"
    with pytest.raises(RuntimeError, match="simulated migration failure"):
        run_evaluation(
            settings=_mock_settings(),
            questions_path=PILOT,
            source_db=source_db,
            runs_root=runs_root,
            label="pre-manifest-test",
            question_ids=_pilot_ids(1),
            judge_kind="rules",
        )
    run_dirs = list(runs_root.iterdir())
    assert len(run_dirs) == 1
    report = json.loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["phase"] == "pre_manifest"
    assert report["manifest_written"] is False
    assert "simulated migration failure" in report["failure_note"]
    assert report["usage"] is None  # the tracker did not exist yet
    assert not (run_dirs[0] / "manifest.json").exists()  # honestly not written
    assert report["corpus"]["source_db_unchanged"] is True
    # The failed run never wrote anything into the SOURCE database.
    runs, results, labels = _read_eval_rows(source_db)
    assert (runs, results, labels) == (0, 0, [])


def test_manifest_db_hash_is_taken_before_any_migration(
    source_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``eval_db_sha256_at_copy`` is the copied bytes, not post-migration bytes.

    The monkeypatched init_db simulates a migration that CHANGES the copy,
    so the recorded hash can only match if it was taken before that change.
    """
    runs_root = tmp_path / "runs"
    seen: dict[str, str] = {}

    def migrating_init(engine) -> None:
        copies = list(runs_root.rglob("evidencegraph-eval.db"))
        assert len(copies) == 1
        seen["before"] = runner_module.sha256_of(copies[0])
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS _migration_probe (id INTEGER)"
            )
        seen["after"] = runner_module.sha256_of(copies[0])
        assert seen["before"] != seen["after"], "probe must change the bytes"

    monkeypatch.setattr(runner_module, "init_db", migrating_init)
    artifacts = run_evaluation(
        settings=_mock_settings(),
        questions_path=PILOT,
        source_db=source_db,
        runs_root=runs_root,
        label="hash-order-test",
        question_ids=_pilot_ids(1),
        judge_kind="rules",
    )
    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    recorded = manifest["corpus"]["eval_db_sha256_at_copy"]
    assert recorded == seen["before"]
    assert recorded != seen["after"]  # the old post-init position would fail here


def test_git_provenance_is_best_effort(tmp_path: Path) -> None:
    inside = git_provenance(REPO)
    outside = git_provenance(tmp_path)  # not a repository
    for prov in (inside, outside):
        assert set(prov) == {"commit", "dirty", "error"}
        if prov["commit"] is not None:
            assert re.fullmatch(r"[0-9a-f]{40}", prov["commit"])
    assert inside["error"] is None
    assert inside["commit"] is not None
    assert isinstance(inside["dirty"], bool)
    # A non-repository records the error rather than raising or guessing.
    assert outside["commit"] is None
    assert outside["error"]


# --------------------------------------------------------------------------
# CLI wiring and packaging regression
# --------------------------------------------------------------------------


def test_main_runs_end_to_end_with_the_mock_provider(
    source_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    rc = main(
        [
            "--source-db",
            str(source_db),
            "--runs-root",
            str(tmp_path / "runs"),
            "--questions",
            str(PILOT),
            "--question-id",
            _pilot_ids(1)[0],
            "--judge",
            "rules",
            "--label",
            "cli-test",
            "--notes",
            "stage-a cli test",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "status:" in out and "completed" in out
    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    assert run_dirs[0].name.startswith("cli-test-")
    assert (run_dirs[0] / "manifest.json").is_file()
    assert (run_dirs[0] / "report.json").is_file()


def test_packaging_config_covers_every_app_subpackage() -> None:
    """`pip install .` must ship the whole package, not only app/*.py.

    Regression guard for the setuptools config: an explicit ``packages =
    ["app"]`` list silently drops every subpackage (app.ingestion,
    app.llm, app.pipelines, app.retrieval, app.verification) from wheels.
    """
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    include = config["tool"]["setuptools"]["packages"]["find"]["include"]
    expected = {"app"} | {
        f"app.{path.name}"
        for path in (REPO / "app").iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    unmissed = [
        name
        for name in expected
        if not any(fnmatch.fnmatch(name, pattern) for pattern in include)
    ]
    assert unmissed == [], f"packaging config would drop: {unmissed}"
