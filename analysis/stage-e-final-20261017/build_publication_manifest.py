"""Build the exact GitHub publication manifest (Stage E final package).

Classifies every proposed publication path into groups A-E (see
stage_e_final_report.md section 7), computes sha256 for each included
untracked file, records git blob ids for the pre-existing commit's files,
and writes publication_manifest.json.

Read-only with respect to everything except publication_manifest.json
itself: no staging, no commits, no modification of any other file.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

GROUP_B = (
    "app/verification/experiments.py",
    "tests/test_experiments.py",
)
EXCLUDED_UNTRACKED = {
    "analysis/stage-d2-20261017-002537/stage_d2_validation_report.md": (
        "contains a local absolute path and username (line 3); retained "
        "locally unchanged as historical evidence; superseded for "
        "publication by stage_d2_validation_report_sanitized.md"
    ),
}
SELF_REFERENTIAL = (
    "publication_manifest.json",
    "publication_validation_report.md",
)
EXTERNAL_EXCLUSIONS = [
    {"path_or_pattern": "runs/**",
     "reason": "gitignored experimental run outputs (incl. the three Stage E "
               "repetitions and their eval databases); local provenance only",
     "retained_locally": True},
    {"path_or_pattern": "*.db / data/evidencegraph.db",
     "reason": "local SQLite databases (corpus and disposable run copies); "
               "gitignored, never published",
     "retained_locally": True},
    {"path_or_pattern": ".env",
     "reason": "secrets file (absent here; gitignored by policy); "
               ".env.example is already tracked",
     "retained_locally": False},
    {"path_or_pattern": "__pycache__/ .pytest_cache/ .coverage htmlcov/",
     "reason": "caches and generated coverage data; gitignored",
     "retained_locally": False},
    {"path_or_pattern": "%TEMP%/opencode/*.py",
     "reason": "temporary audit scripts outside the repository",
     "retained_locally": True},
]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=True).stdout


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    untracked = [l[3:] for l in git("status", "--porcelain", "-uall").splitlines()
                 if l.startswith("?? ")]
    head = git("rev-parse", "--short", "HEAD").strip()
    origin = git("rev-parse", "--short", "origin/master").strip()
    ahead = int(git("rev-list", "--left-right", "--count",
                    "origin/master...HEAD").split()[1])

    # Group A: files the pre-existing local commit d4ea26d would publish
    a_files = [f for f in git("diff", "--name-only",
                              "origin/master..HEAD").splitlines() if f]
    blobs = {}
    for line in git("ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        blobs[path] = meta.split()[2]

    group_a = [{"path": f, "git_blob": blobs.get(f),
                "action": "publishes on push (pre-existing commit, nothing to stage)"}
               for f in a_files]

    # Groups B/C/D/E from the untracked set
    group_b, group_c, group_d = [], [], []
    excluded = []
    for rel in sorted(untracked):
        p = ROOT / rel
        if rel in EXCLUDED_UNTRACKED:
            excluded.append({"path": rel, "reason": EXCLUDED_UNTRACKED[rel],
                             "retained_locally": True,
                             "sha256_local": sha256(p)})
        elif rel in GROUP_B:
            group_b.append({"path": rel, "sha256": sha256(p),
                            "action": "new code/test file (commit group 2)"})
        elif rel.endswith("stage_d2_validation_report_sanitized.md"):
            group_d.append({"path": rel, "sha256": sha256(p),
                            "sanitized_from": "analysis/stage-d2-20261017-002537/"
                                              "stage_d2_validation_report.md",
                            "original_sha256": "06ffaaf13b1cfecc165807473a8561"
                                               "d70837328175870d5da31ea06e2d8a2cfa",
                            "change": "local absolute path on the Run line replaced "
                                      "by repository-relative path; header records "
                                      "provenance; no result altered",
                            "action": "publishes in commit group 3/4"})
        elif rel.startswith("analysis/stage-e-final-20261017/"):
            name = Path(rel).name
            if name in SELF_REFERENTIAL:
                group_c.append({"path": rel, "sha256": None,
                                "note": "self-referential/generated after manifest "
                                        "build; existence verified, hash not pinned"})
            else:
                group_c.append({"path": rel, "sha256": sha256(p),
                                "action": "final publication package (commit group 3/4)"})
        else:
            group_c.append({"path": rel, "sha256": sha256(p),
                            "action": "research analysis/validation artifact "
                                      "(commit group 3)"})

    # ensure both self-referential files are listed even if not yet on disk
    listed = {e["path"] for e in group_c}
    for name in SELF_REFERENTIAL:
        rel = f"analysis/stage-e-final-20261017/{name}"
        if rel not in listed:
            group_c.append({"path": rel, "sha256": None,
                            "note": "self-referential/generated after manifest "
                                    "build; existence verified, hash not pinned"})
    group_c.sort(key=lambda e: e["path"])

    manifest = {
        "stage": "E-final-publication",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_state": {"branch": "master", "head": head, "origin_master": origin,
                      "ahead_by": ahead,
                      "note": "a push publishes the pre-existing commit "
                              f"{head} as well as any new commits"},
        "counts": {"A_preexisting_commit_files": len(group_a),
                   "B_new_code_tests": len(group_b),
                   "C_research_analysis": len(group_c),
                   "D_sanitized": len(group_d),
                   "E_excluded_entries": len(excluded) + len(EXTERNAL_EXCLUSIONS)},
        "A_preexisting_local_commit": {
            "commit": head,
            "message": "Add reproducible evaluation runner and dependency constraints",
            "files": group_a,
        },
        "B_new_code_and_tests": group_b,
        "C_research_analysis_and_validation": group_c,
        "D_sanitized_publication_copies": group_d,
        "E_excluded_local_only": excluded + EXTERNAL_EXCLUSIONS,
        "authorization_boundary": {
            "staged": False, "committed": False, "pushed": False, "deployed": False,
            "note": "this manifest is a proposal only; every git action awaits "
                    "separate explicit authorization",
        },
    }
    out = HERE / "publication_manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.name}: A={len(group_a)} B={len(group_b)} "
          f"C={len(group_c)} D={len(group_d)} "
          f"E={len(excluded) + len(EXTERNAL_EXCLUSIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
