"""Tracked evaluation runner: runs the A/B harness and records provenance.

Why this exists
---------------
The two historical pilot runs (October 2026) were driven by one-off scripts
kept in the git-ignored ``runs/`` directories, so their artifacts record no
Git commit and cannot be tied to an exact code state. This module is the
tracked replacement: every run writes ``manifest.json`` (Git commit, dirty
flag, provider/model, configuration, dataset SHA-256, corpus SHA-256,
UTC timestamp, output locations) *before* the first model call, and
``report.json`` (status, stored-row summaries, usage) at the end, both
inside a fresh timestamped run directory.

Safety rules, enforced in code rather than by convention
--------------------------------------------------------
- ``data/evidencegraph.db`` is never opened for writing: the runner copies
  it into the run directory and points every session at the copy, refusing
  to proceed if the resolved paths were ever to match.
- Run directories are never reused: creation fails if the directory exists,
  so a historical run can never be overwritten.
- Non-local endpoints are refused unless ``allow_remote_endpoint=True``,
  and that override is recorded in the manifest. The mock provider is
  exempt because it performs no network calls.
- Gold labels are never written: ``verif_claims.gold_label`` stays NULL.
  Judge-vs-human agreement must be computed separately from reviewed
  labels via ``judge_agreement_for_run``.
- Any failure after the run directory is created writes ``report.json``
  with an honest failure note -- including a failure that occurs before
  the manifest could be written; ``manifest_written`` records which
  window the run died in.
- The source database is hashed before and after the run and both hashes
  (plus an ``unchanged`` flag) land in the report, so a run can prove it
  did not mutate the corpus it read.

Nothing in this module interprets results: mechanism metrics describe what
the verifier *said*, never whether a system is better.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlparse

from app.config import Settings
from app.db import (
    Chunk,
    Document,
    EvalResult,
    init_db,
    make_engine,
    make_session_factory,
)
from app.llm.client import FakeLLMClient, LLMClient, OpenAICompatibleClient
from app.llm.prompts import PROMPT_VERSION
from app.retrieval.retriever import Retriever
from app.verification.harness import (
    SYSTEM_BASELINE,
    SYSTEM_VERIFIED,
    citation_quality_for_run,
    load_questions,
    run_ab_eval,
)
from app.verification.judge import (
    JUDGE_PROMPT_VERSION,
    Judge,
    LLMJudge,
    RuleBasedJudge,
)
from app.verification.pipeline import make_chunk_exists
from app.verification.usage import (
    PricingError,
    TrackingLLMClient,
    UsageTracker,
    load_pricing,
)

RUNNER_ID = "app.verification.runner"
MANIFEST_VERSION = 1

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS = REPO_ROOT / "data" / "sample" / "eval_questions.json"
DEFAULT_SOURCE_DB = REPO_ROOT / "data" / "evidencegraph.db"
DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"

# Providers that perform no network calls and are therefore exempt from the
# endpoint guard.
_MOCK_PROVIDERS = frozenset({"mock", "fake", "offline"})
_LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})

_EVAL_DB_NAME = "evidencegraph-eval.db"


class RunnerError(RuntimeError):
    """Unsafe configuration or refused state; the run never starts."""


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------


def sha256_of(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_provenance(repo_root: Path = REPO_ROOT) -> dict:
    """Best-effort Git provenance: commit hash, dirty flag, and any error.

    A missing commit is recorded as ``None`` with an explanatory ``error``
    rather than guessed or raised: a run from an exported tree still works,
    and the manifest says plainly that the commit is unknown.
    """
    provenance: dict = {"commit": None, "dirty": None, "error": None}
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        provenance["commit"] = head or None
        provenance["dirty"] = bool(status.strip())
    except FileNotFoundError:
        provenance["error"] = "git executable not found"
    except subprocess.TimeoutExpired:
        provenance["error"] = "git command timed out"
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        provenance["error"] = f"git failed: {stderr or exc}"
    return provenance


def _is_mock(settings: Settings) -> bool:
    return settings.llm_provider.lower() in _MOCK_PROVIDERS


def _endpoint_is_local(base_url: str) -> bool:
    try:
        hostname = urlparse(base_url).hostname
    except ValueError:
        return False
    return hostname in _LOCAL_HOSTNAMES


def check_endpoint(settings: Settings, allow_remote_endpoint: bool) -> None:
    """Refuse non-local endpoints unless the caller explicitly allows them.

    The override is not silent: callers are expected to record it (the
    manifest does), so a report built from a remote run says so.
    """
    if _is_mock(settings) or allow_remote_endpoint:
        return
    if not _endpoint_is_local(settings.llm_base_url):
        raise RunnerError(
            f"refusing non-local LLM endpoint {settings.llm_base_url!r}; use a "
            "localhost URL, use the mock provider, or pass "
            "allow_remote_endpoint=True (recorded in the manifest)."
        )


def _validate_label(label: str) -> None:
    if not label or label in {".", ".."} or any(ch in label for ch in "/\\"):
        raise RunnerError(
            f"invalid run label {label!r}: use a plain name without path "
            "separators"
        )


def prepare_run_dir(runs_root: Path, label: str) -> Path:
    """Create a fresh timestamped run directory; never reuse an existing one.

    ``exist_ok=False`` is the overwrite guard: a directory that exists (a
    historical run, or a collision within the same second) is refused, not
    merged into.
    """
    _validate_label(label)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = Path(runs_root) / f"{label}-{stamp}"
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise RunnerError(
            f"run directory already exists; refusing to overwrite: {run_dir}"
        ) from None
    return run_dir


def copy_source_db(source_db: Path, run_dir: Path) -> Path:
    """Copy the corpus database into the run directory; the source is read-only."""
    source_db = Path(source_db)
    if not source_db.is_file():
        raise RunnerError(f"source database not found: {source_db}")
    target = Path(run_dir) / _EVAL_DB_NAME
    if target.exists():
        raise RunnerError(f"refusing to overwrite existing copy: {target}")
    if target.resolve() == source_db.resolve():
        raise RunnerError(
            "eval copy would resolve to the source database; aborting"
        )
    shutil.copy2(source_db, target)
    return target


def _make_llm_for_run(settings: Settings) -> LLMClient:
    """Build the provider client, mirroring ``app.cli._make_llm``.

    The mock provider gets the deterministic offline client (no network);
    every other provider gets the real OpenAI-compatible client.
    """
    if _is_mock(settings):
        return FakeLLMClient(
            model="offline-mock",
            scripted_response=(
                "Offline mock answer: configure a real LLM provider in .env "
                "for generated responses."
            ),
        )
    return OpenAICompatibleClient(settings)


def _build_judge(judge_kind: str, llm: LLMClient, tracker: UsageTracker) -> Judge:
    if judge_kind == "rules":
        return RuleBasedJudge()
    return LLMJudge(TrackingLLMClient(llm, tracker, "judge"))


# --------------------------------------------------------------------------
# Run + report
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RunArtifacts:
    """Paths and payloads produced by one runner invocation."""

    run_dir: Path
    manifest_path: Path
    report_path: Path
    eval_db_path: Path
    manifest: dict
    report: dict


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _per_system_counts(session, eval_run_id: int) -> dict:
    out = {}
    for system in (SYSTEM_BASELINE, SYSTEM_VERIFIED):
        rows = (
            session.query(EvalResult)
            .filter(
                EvalResult.eval_run_id == eval_run_id,
                EvalResult.system == system,
            )
            .all()
        )
        out[system] = {
            "questions": len(rows),
            "citations_total": sum(r.citation_count for r in rows),
            "invalid_markers_total": sum(r.invalid_marker_count for r in rows),
            "claims_total": sum(r.claims_total for r in rows),
            "supported": sum(r.supported_count for r in rows),
            "contradicted": sum(r.contradicted_count for r in rows),
            "insufficient_evidence": sum(r.insufficient_count for r in rows),
            "unverifiable": sum(r.unverifiable_count for r in rows),
            "with_anomalies": sum(r.with_anomalies for r in rows),
            # The baseline performs no support check; recording that
            # explicitly stops an all-zero column reading as "no problems".
            "claim_check_performed": system == SYSTEM_VERIFIED,
        }
    return out


def _citation_quality_report(session, eval_run_id: int) -> dict:
    return {
        system: {
            "citations": q.citations,
            "invalid_markers": q.invalid_markers,
            "invalid_marker_rate": round(q.invalid_marker_rate, 4),
            "verified_citations": q.verified_citations,
        }
        for system, q in citation_quality_for_run(session, eval_run_id).items()
    }


def _calls_by_purpose(tracker: UsageTracker) -> dict:
    counts: dict[str, int] = {}
    for record in tracker.records:
        key = record.purpose if record.call_ok else f"{record.purpose}_failed"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _write_pre_manifest_failure_report(
    *,
    report_path: Path,
    run_id: str,
    started_utc: datetime,
    exc: BaseException,
    question_count: int,
    source_db: Path,
    source_sha_before: str | None,
) -> None:
    """Record an honest failure for a run that died before the manifest.

    Fields that do not exist yet (no eval run row, no usage, no manifest)
    are null or absent rather than guessed, and the report states which
    window the run died in (``"phase": "pre_manifest"``). The source hash
    is re-checked when the source is still readable; if it is not, the
    field stays null rather than raising over the original error.
    """
    try:
        source_sha_after = sha256_of(source_db)
    except OSError:
        source_sha_after = None
    report = {
        "run_id": run_id,
        "status": "interrupted"
        if isinstance(exc, KeyboardInterrupt)
        else "failed",
        "phase": "pre_manifest",
        "manifest_written": False,
        "failure_note": f"{type(exc).__name__}: {exc}",
        "started_utc": started_utc.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "eval_run_id": None,
        "question_count": question_count,
        "usage": None,
        "corpus": {
            "source_db_sha256_before": source_sha_before,
            "source_db_sha256_after": source_sha_after,
            "source_db_unchanged": source_sha_after == source_sha_before,
        },
        "note_no_labels_written": (
            "verif_claims.gold_label is NULL for every row: a machine "
            "run never writes labels."
        ),
    }
    _write_json(report_path, report)


def run_evaluation(
    *,
    settings: Settings,
    questions_path: Path | str = DEFAULT_QUESTIONS,
    source_db: Path | str = DEFAULT_SOURCE_DB,
    runs_root: Path | str = DEFAULT_RUNS_ROOT,
    label: str = "eval",
    question_ids: Sequence[str] | None = None,
    judge_kind: str = "llm",
    allow_remote_endpoint: bool = False,
    notes: str = "",
    retriever_factory: Callable[[], Retriever] | None = None,
    llm_factory: Callable[[Settings], LLMClient] | None = None,
) -> RunArtifacts:
    """Run the A/B evaluation over a disposable copy of the corpus.

    Every safety check that can run before any side effect does: only after
    the configuration is proven safe does this create a run directory, copy
    the database, and start making model calls. A run that fails mid-way is
    rolled back (single transaction), records an honest ``failed``/
    ``interrupted`` report, and re-raises — failures are never hidden.
    """
    started_utc = datetime.now(timezone.utc)
    t0 = time.monotonic()
    questions_path = Path(questions_path)
    source_db = Path(source_db)
    runs_root = Path(runs_root)

    # ---- Preflight: no side effects yet ----
    _validate_label(label)
    if judge_kind not in ("llm", "rules"):
        raise RunnerError(
            f"unknown judge_kind {judge_kind!r}; expected 'llm' or 'rules'"
        )
    if not questions_path.is_file():
        raise RunnerError(f"question file not found: {questions_path}")
    if not source_db.is_file():
        raise RunnerError(f"source database not found: {source_db}")
    check_endpoint(settings, allow_remote_endpoint)

    questions = load_questions(questions_path)
    if question_ids is not None:
        by_id = {str(q.get("id")): q for q in questions}
        missing = sorted({str(qid) for qid in question_ids} - set(by_id))
        if missing:
            raise RunnerError(f"unknown question ids: {missing}")
        questions = [by_id[str(qid)] for qid in question_ids]
        if not questions:
            raise RunnerError("question filter selected no questions")

    llm = llm_factory(settings) if llm_factory else _make_llm_for_run(settings)
    try:
        pricing = load_pricing(settings)
    except PricingError:
        # A half-configured price list is recorded as "no pricing" rather
        # than guessed at; cost stays unavailable, never invented.
        pricing = None

    source_sha_before = sha256_of(source_db)
    dataset_sha = sha256_of(questions_path)
    git = git_provenance()

    run_dir = prepare_run_dir(runs_root, label)
    run_id = run_dir.name
    manifest_path = run_dir / "manifest.json"
    report_path = run_dir / "report.json"

    # From here to the manifest write, failures (e.g. a migration error on
    # the copy) still leave an auditable failure record in the run dir.
    engine = None
    session = None
    try:
        eval_db = copy_source_db(source_db, run_dir)
        # Hash the copy BEFORE any schema work, so the recorded value is
        # exactly the bytes copied from the source.
        eval_db_sha256_at_copy = sha256_of(eval_db)

        # ---- Point every session at the copy; prove the source unreachable ----
        run_settings = settings.model_copy(
            update={"database_url": f"sqlite:///{eval_db.as_posix()}"}
        )
        if Path(run_settings.database_url.removeprefix("sqlite:///")).resolve() == (
            source_db.resolve()
        ):
            raise RunnerError(
                "eval database copy resolves to the source database; aborting"
            )

        engine = make_engine(run_settings.database_url)
        init_db(engine)  # eval tables exist in the COPY only
        session = make_session_factory(engine)()

        tracker = UsageTracker(
            run_id=run_id,
            provider=settings.llm_provider,
            model=getattr(llm, "model", settings.llm_model),
            pricing=pricing,
        )
        judge = _build_judge(judge_kind, llm, tracker)

        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "runner": RUNNER_ID,
            "run_id": run_id,
            "label": label,
            "created_utc": started_utc.isoformat(),
            "git": git,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "provider": {
                "name": settings.llm_provider,
                "model": getattr(llm, "model", settings.llm_model),
                "base_url": settings.llm_base_url,
                "is_mock": _is_mock(settings),
                "remote_endpoint_allowed": bool(allow_remote_endpoint),
            },
            "configuration": {
                "temperature": settings.llm_temperature,
                "max_tokens": settings.llm_max_tokens,
                "timeout_seconds": settings.llm_timeout_seconds,
                "retrieval_top_k": settings.retrieval_top_k,
                "judge": judge_kind,
                "judge_class": type(judge).__name__,
                "prompt_version": PROMPT_VERSION,
                "judge_prompt_version": JUDGE_PROMPT_VERSION,
                "question_ids": [str(q["id"]) for q in questions],
                "question_count": len(questions),
                "notes": notes,
            },
            "dataset": {"path": str(questions_path), "sha256": dataset_sha},
            "corpus": {
                "source_db": str(source_db),
                "source_db_sha256_before": source_sha_before,
                "eval_db_copy": eval_db.name,
                "eval_db_sha256_at_copy": eval_db_sha256_at_copy,
                "documents": session.query(Document).count(),
                "chunks": session.query(Chunk).count(),
            },
            "outputs": {
                "run_dir": str(run_dir),
                "manifest_path": str(manifest_path),
                "report_path": str(report_path),
                "eval_db": str(eval_db),
            },
        }
        # Written BEFORE the first model call so a crashed run still leaves a
        # provenance record on disk.
        _write_json(manifest_path, manifest)
    except BaseException as exc:  # noqa: BLE001 - record, then re-raise
        try:
            _write_pre_manifest_failure_report(
                report_path=report_path,
                run_id=run_id,
                started_utc=started_utc,
                exc=exc,
                question_count=len(questions),
                source_db=source_db,
                source_sha_before=source_sha_before,
            )
        except Exception:
            pass  # reporting must never mask the original error
        if session is not None:
            session.close()
        if engine is not None:
            engine.dispose()
        raise

    # ---- Run: one transaction; rows reach the copy only on a clean finish ----
    t0 = time.monotonic()
    outcome = None
    try:
        outcome = run_ab_eval(
            session,
            questions,
            baseline_llm=TrackingLLMClient(llm, tracker, "baseline_generation"),
            verified_llm=TrackingLLMClient(llm, tracker, "verified_generation"),
            retriever_factory=retriever_factory or (lambda: Retriever(session)),
            judge=judge,
            top_k=settings.retrieval_top_k,
            corpus_tag=f"runner-copy:{run_id}",
            notes=notes,
            chunk_is_known=make_chunk_exists(session),
        )
        session.commit()
    except BaseException as exc:  # noqa: BLE001 - rollback, record, re-raise
        try:
            session.rollback()
        except Exception:
            pass  # a failing rollback must not mask the original error
        try:
            source_sha_after = sha256_of(source_db)
        except OSError:
            source_sha_after = None  # never mask the original error
        failure_report = {
            "run_id": run_id,
            "status": "interrupted"
            if isinstance(exc, KeyboardInterrupt)
            else "failed",
            "phase": "run",
            "manifest_written": True,
            "failure_note": f"{type(exc).__name__}: {exc}",
            "started_utc": started_utc.isoformat(),
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": round(time.monotonic() - t0, 1),
            "eval_run_id": None,
            "question_count": len(questions),
            "usage": {
                "summary": asdict(tracker.summary),
                "calls_by_purpose": _calls_by_purpose(tracker),
            },
            "corpus": {
                "source_db_sha256_before": source_sha_before,
                "source_db_sha256_after": source_sha_after,
                "source_db_unchanged": source_sha_after == source_sha_before,
            },
            "note_no_labels_written": (
                "verif_claims.gold_label is NULL for every row: a machine "
                "run never writes labels."
            ),
        }
        try:
            _write_json(report_path, failure_report)
        except OSError:
            pass  # the original failure must never be masked by reporting
        session.close()
        engine.dispose()
        raise

    # ---- Report: descriptive only; no comparative conclusion ----
    source_sha_after = sha256_of(source_db)
    report = {
        "run_id": run_id,
        "status": "completed",
        "failure_note": "",
        "started_utc": started_utc.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(time.monotonic() - t0, 1),
        "eval_run_id": outcome.eval_run_id,
        "question_count": len(questions),
        "per_system": _per_system_counts(session, outcome.eval_run_id),
        "citation_quality": _citation_quality_report(session, outcome.eval_run_id),
        "usage": {
            "summary": asdict(tracker.summary),
            "calls_by_purpose": _calls_by_purpose(tracker),
        },
        "corpus": {
            "source_db_sha256_before": source_sha_before,
            "source_db_sha256_after": source_sha_after,
            "source_db_unchanged": source_sha_after == source_sha_before,
            "eval_db_sha256_final": sha256_of(eval_db),
        },
        "note_no_labels_written": (
            "verif_claims.gold_label is NULL for every row: a machine run "
            "never writes labels. Judge-vs-human agreement must be computed "
            "separately from reviewed labels (judge_agreement_for_run)."
        ),
        "scope_caveats": [
            "Descriptive record of one run; no claim that one system is "
            "better than the other.",
            "Mechanism metrics describe what the verifier SAID, not whether "
            "it was right.",
        ],
    }
    _write_json(report_path, report)
    session.close()
    engine.dispose()
    return RunArtifacts(
        run_dir=run_dir,
        manifest_path=manifest_path,
        report_path=report_path,
        eval_db_path=eval_db,
        manifest=manifest,
        report=report,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.verification.runner",
        description=(
            "Run the A/B evaluation over a disposable copy of the corpus, "
            "recording Git commit, configuration, and content hashes."
        ),
    )
    parser.add_argument("--label", default="eval", help="run-directory prefix")
    parser.add_argument(
        "--questions", default=str(DEFAULT_QUESTIONS), help="question set JSON"
    )
    parser.add_argument(
        "--source-db", default=str(DEFAULT_SOURCE_DB), help="corpus database (read-only)"
    )
    parser.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="where run directories go"
    )
    parser.add_argument(
        "--question-id",
        action="append",
        dest="question_ids",
        default=None,
        help="run only this question id (repeatable)",
    )
    parser.add_argument(
        "--judge", choices=("llm", "rules"), default="llm", help="judge type"
    )
    parser.add_argument(
        "--notes", default="", help="free text stored in the manifest and eval_runs row"
    )
    parser.add_argument(
        "--allow-remote-endpoint",
        action="store_true",
        help="permit a non-local LLM_BASE_URL (recorded in the manifest)",
    )
    args = parser.parse_args(argv)

    try:
        artifacts = run_evaluation(
            settings=Settings(),
            questions_path=args.questions,
            source_db=args.source_db,
            runs_root=args.runs_root,
            label=args.label,
            question_ids=args.question_ids,
            judge_kind=args.judge,
            notes=args.notes,
            allow_remote_endpoint=args.allow_remote_endpoint,
        )
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # failed report (if any) is already on disk
        # Full diagnostics on stderr; the original exception is never hidden.
        traceback.print_exc()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"run dir:  {artifacts.run_dir}")
    print(f"manifest: {artifacts.manifest_path}")
    print(f"report:   {artifacts.report_path}")
    print(
        f"status:   {artifacts.report['status']} "
        f"(eval_run_id={artifacts.report['eval_run_id']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
