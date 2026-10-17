"""Stage D1 integrity validation.

Run:  python validate_stage_d1.py        (writes stage_d1_validation_report.md)

Checks (each becomes one PASS/FAIL row in the report):
   1. Required files exist
   2. proposed_judgments.csv: 46 rows, ids/order == queue, vocabulary conformance
   3. proposed_judgments.csv: every proposal has rationale + evidence reference
   4. proposed_judgments.csv: no human-layer columns (no promotion surface)
   5. review_workspace.csv: 46 rows, identifiers/claim text/evidence copied verbatim
   6. review_workspace.csv: every human/adjudication field empty
   7. review_workspace.csv: no verdict/AI-draft column leakage (blind confirmer)
   8. review_workspace.csv: review_status vocabulary + claim/abstention category split
   9. Cross-file consistency: workspace proposals == proposal file
  10. Proposal data JSON: coverage, statuses, evidence-or-uncertainty per item
  11. Confirmation sheet: 46 items, machine-drafted warning present
  12. Builder determinism: rebuild reproduces identical bytes
  13. Historical integrity: Stage C + Stage D recorded hashes still match
  14. Historical integrity: no file outside this directory modified since D1 began
  15. Git state unchanged (HEAD, tracked files clean)
  16. No model/database artifacts created; no network/LLM imports in D1 scripts
  17. Secrets scan over Stage D1 files
  18. CSV structure: UTF-8, no BOM, uniform row length
  19. Full test suite (plain `python -m pytest`) still passes
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
QUEUE_PATH = REPO / "analysis/stage-d-20261016-213744/human_review_queue.json"
QUESTIONS_PATH = REPO / "data/sample/eval_questions.json"
SD_DIR = REPO / "analysis/stage-d-20261016-213744"
SC_DIR = REPO / "analysis/stage-c-20261016"
REPORT_PATH = HERE / "stage_d1_validation_report.md"

CLAIM_LABELS = {"supported", "contradicted", "insufficient_evidence", "unverifiable"}
CITATION_LABELS = CLAIM_LABELS | {"not_applicable"}
ABSTENTION_LABELS = {"appropriate_abstention", "inappropriate_abstention", "uncertain"}
PROPOSAL_STATUS = {"proposed_unconfirmed", "needs_adjudication"}
D1_REVIEW_STATUS = {"unreviewed", "proposed", "confirmed", "uncertain", "needs_adjudication"}

REQUIRED_FILES = [
    "d1_proposed_judgments.json",
    "build_workspace.py",
    "review_workspace.csv",
    "proposed_judgments.csv",
    "review_confirmation_sheet.md",
    "review_progress.md",
    "unresolved_evidence.md",
    "validate_stage_d1.py",
]

HUMAN_EMPTY_COLUMNS = [
    "human_label", "human_rationale", "evidence_sufficiency_rationale",
    "citation_support_label", "citation_support_rationale", "abstention_assessment",
    "reviewer_decision", "reviewer_id", "review_timestamp", "uncertainty_notes",
    "adjudicated_label", "adjudication_rationale",
]
LEAK_TOKENS = ("system_verdict", "verdict", "grounding_ratio", "proposed_ai_label", "diagnostics")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    mark = "PASS" if ok else "**FAIL**"
    print(f"{mark:>4}  {name}" + (f" :: {detail}" if detail else ""))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def collect_path_hash_pairs(obj, out: list[tuple[str, str]]) -> None:
    """Walk a manifest for {..path..sha256..} pairs (Stage C and Stage D shapes)."""
    if isinstance(obj, dict):
        path_keys = [k for k in obj if k.endswith("path")]
        hash_keys = [k for k in obj if k.endswith("sha256")]
        if path_keys and hash_keys:
            out.append((str(obj[path_keys[0]]), str(obj[hash_keys[0]])))
        for v in obj.values():
            collect_path_hash_pairs(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_path_hash_pairs(v, out)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # -- 1. required files ------------------------------------------------
    missing = [f for f in REQUIRED_FILES if not (HERE / f).is_file()]
    check("1. required files exist", not missing, "all 8 present" if not missing else f"missing {missing}")

    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    items = queue["items"]
    q_ids = [i["annotation_id"] for i in items]
    item_by_id = {i["annotation_id"]: i for i in items}
    questions = {q["id"]: q for q in json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]}

    pj_cols, pj_rows = read_csv(HERE / "proposed_judgments.csv")
    ws_cols, ws_rows = read_csv(HERE / "review_workspace.csv")
    pj_ids = [r["annotation_id"] for r in pj_rows]
    ws_ids = [r["annotation_id"] for r in ws_rows]

    # -- 2. proposal file structure/vocabulary ----------------------------
    problems = []
    if len(pj_rows) != 46 or pj_ids != q_ids:
        problems.append("row count/order mismatch vs queue")
    for r in pj_rows:
        item = item_by_id.get(r["annotation_id"], {})
        if r["proposed_abstention_assessment"] in ABSTENTION_LABELS:
            if item.get("item_type") != "abstention_question" or r["proposed_label"] != "not_applicable":
                problems.append(f"{r['annotation_id']}: abstention vocab/type conflict")
        else:
            if item.get("item_type") != "claim" or r["proposed_label"] not in CLAIM_LABELS:
                problems.append(f"{r['annotation_id']}: claim label vocab/type conflict")
            if r["proposed_abstention_assessment"] != "not_applicable":
                problems.append(f"{r['annotation_id']}: claim row must have abstention=not_applicable")
        if r["proposed_citation_support_label"] not in CITATION_LABELS:
            problems.append(f"{r['annotation_id']}: bad citation label")
        if r["proposal_status"] not in PROPOSAL_STATUS:
            problems.append(f"{r['annotation_id']}: bad proposal_status")
        if not r["proposed_by"].strip():
            problems.append(f"{r['annotation_id']}: proposed_by missing")
    check("2. proposals: 46 rows, ids/order match queue, vocabulary conformance",
          not problems, "; ".join(problems[:5]) or "46/46 conform")

    # -- 3. every proposal justified --------------------------------------
    empty = [r["annotation_id"] for r in pj_rows
             if not (r["proposed_rationale"].strip()
                     and r["proposed_evidence_sufficiency_rationale"].strip()
                     and r["proposed_citation_support_rationale"].strip()
                     and r["evidence_reference"].strip()
                     and (r["uncertainty_notes"].strip() or r["proposed_rationale"].strip()))]
    check("3. every proposal has rationale + evidence reference (evidence or explicit uncertainty)",
          not empty, "46/46 justified" if not empty else f"empty: {empty}")

    # -- 4. no human layer in proposal file --------------------------------
    # Brief section 5 mandates `uncertainty_notes` in the proposal file as a
    # MACHINE-authored field; the human uncertainty field exists only in
    # review_workspace.csv (empty - verified by check 6). Excluding it here.
    human_layer = [c for c in pj_cols
                   if (c in HUMAN_EMPTY_COLUMNS and c != "uncertainty_notes")
                   or c.startswith("human_")
                   or c in ("reviewer_id", "review_timestamp", "adjudicated_label",
                            "review_status", "adjudication_rationale")]
    check("4. proposals file contains no human-layer columns",
          not human_layer,
          "no human_label/reviewer_id/adjudicated fields; uncertainty_notes here is the "
          "machine-authored proposal note required by brief section 5" if not human_layer
          else str(human_layer))

    # -- 5. workspace verbatim identifiers/evidence ------------------------
    problems = []
    if len(ws_rows) != 46 or ws_ids != q_ids:
        problems.append("row count/order mismatch")
    for item, row in zip(items, ws_rows):
        if row["question_id"] != item["question_id"]:
            problems.append(f"{row['annotation_id']}: question_id changed")
        if row["claim_id"] != ("" if item["claim_id"] is None else str(item["claim_id"])):
            problems.append(f"{row['annotation_id']}: claim_id changed")
        if row["claim_text"] != (item["claim_text"] or ""):
            problems.append(f"{row['annotation_id']}: claim_text changed")
        if row["source_run_id"] != item["run_id"]:
            problems.append(f"{row['annotation_id']}: run_id changed")
        if row["source_claim_row_ref"] != item["source_artifact_refs"]["claim_row_source"]:
            problems.append(f"{row['annotation_id']}: source ref changed")
        if not row["evidence_text"].strip() or not row["evidence_chunk_ids"].strip():
            problems.append(f"{row['annotation_id']}: evidence missing")
        expected_cites = "" if item["retrieved_evidence_ids"] is None else json.dumps(item["retrieved_evidence_ids"])
        if row["stored_citation_ids"] != expected_cites:
            problems.append(f"{row['annotation_id']}: citations changed")
        if row["question_text"] != questions[item["question_id"]]["question"]:
            problems.append(f"{row['annotation_id']}: question text changed")
        if row["paired_baseline_answer"] != (item["paired_answer_texts"]["baseline"] or ""):
            problems.append(f"{row['annotation_id']}: baseline answer changed")
        if row["paired_verified_answer"] != (item["paired_answer_texts"]["verified"] or ""):
            problems.append(f"{row['annotation_id']}: verified answer changed")
    check("5. workspace: identifiers, claim text, answers, evidence copied verbatim from queue",
          not problems, "46/46 verbatim" if not problems else "; ".join(problems[:5]))

    # -- 6. human fields empty ---------------------------------------------
    filled = [f"{r['annotation_id']}:{c}" for r in ws_rows for c in HUMAN_EMPTY_COLUMNS if r[c].strip()]
    check("6. workspace: all human/adjudication fields empty (no silent promotion)",
          not filled, f"{len(HUMAN_EMPTY_COLUMNS)} columns x 46 rows all empty" if not filled else str(filled[:5]))

    # -- 7. blind surface ---------------------------------------------------
    leaky = [c for c in ws_cols if any(t in c.lower() for t in LEAK_TOKENS)]
    check("7. workspace: no system-verdict / old-AI-draft column (blind confirmer)",
          not leaky, "no verdict/grounding/proposed_ai_label columns" if not leaky else str(leaky))

    # -- 8. statuses/categories --------------------------------------------
    problems = []
    for row in ws_rows:
        if row["review_status"] not in D1_REVIEW_STATUS:
            problems.append(f"{row['annotation_id']}: bad review_status")
        want = "claim_level" if item_by_id[row["annotation_id"]]["item_type"] == "claim" else "question_level_abstention"
        if row["review_category"] != want:
            problems.append(f"{row['annotation_id']}: category mismatch")
    n_prop = sum(1 for r in ws_rows if r["review_status"] == "proposed")
    n_adj = sum(1 for r in ws_rows if r["review_status"] == "needs_adjudication")
    check("8. workspace: review_status vocabulary + claim/abstention category split",
          not problems and n_prop == 45 and n_adj == 1,
          f"proposed={n_prop}, needs_adjudication={n_adj}" if not problems else "; ".join(problems[:5]))

    # -- 9. cross-file consistency ------------------------------------------
    pj_by_id = {r["annotation_id"]: r for r in pj_rows}
    mism = [r["annotation_id"] for r in ws_rows
            if r["proposed_label"] != pj_by_id[r["annotation_id"]]["proposed_label"]
            or r["proposed_abstention_assessment"] != pj_by_id[r["annotation_id"]]["proposed_abstention_assessment"]
            or r["proposal_status"] != pj_by_id[r["annotation_id"]]["proposal_status"]]
    check("9. cross-file: workspace proposals == proposed_judgments.csv",
          not mism, "46/46 consistent" if not mism else str(mism))

    # -- 10. proposal source data -------------------------------------------
    data = json.loads((HERE / "d1_proposed_judgments.json").read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    problems = []
    if [e["annotation_id"] for e in entries] != q_ids:
        problems.append("entry ids/order mismatch")
    statuses = {"proposed_unconfirmed": 0, "needs_adjudication": 0}
    for e in entries:
        if e["proposal_status"] in statuses:
            statuses[e["proposal_status"]] += 1
        else:
            problems.append(f"{e['annotation_id']}: bad status")
        if not e.get("evidence_reference", "").strip():
            problems.append(f"{e['annotation_id']}: no evidence_reference")
        if (e.get("policy_alternative_label") or e["proposal_status"] == "needs_adjudication") \
                and not e.get("uncertainty_notes", "").strip():
            problems.append(f"{e['annotation_id']}: flagged but no uncertainty_notes")
    if "human" not in json.dumps(data.get("honesty", {})).lower():
        problems.append("honesty block missing human-label statement")
    check("10. proposal JSON: coverage, statuses, evidence-or-uncertainty per item",
          not problems and statuses["needs_adjudication"] >= 1,
          f"46 entries; {statuses}" if not problems else "; ".join(problems[:5]))

    # -- 11. confirmation sheet ----------------------------------------------
    sheet = (HERE / "review_confirmation_sheet.md").read_text(encoding="utf-8")
    ids_found = re.findall(r"ann-d1-\d{4}", sheet)
    problems = []
    if sorted(ids_found) != sorted(q_ids) or len(ids_found) != 46:
        problems.append(f"sheet ids: found {len(ids_found)}")
    if "MACHINE-DRAFTED" not in sheet or "No human has confirmed" not in sheet:
        problems.append("missing machine-drafted warning")
    check("11. confirmation sheet: 46 items + machine-drafted warning",
          not problems, "46 rows, warning present" if not problems else "; ".join(problems))

    # -- 12. builder determinism ----------------------------------------------
    before = {f: sha256(HERE / f) for f in
              ("review_workspace.csv", "proposed_judgments.csv", "review_confirmation_sheet.md")}
    proc = subprocess.run([sys.executable, str(HERE / "build_workspace.py")],
                          capture_output=True, text=True, cwd=str(REPO))
    after = {f: sha256(HERE / f) for f in before}
    same = proc.returncode == 0 and before == after
    check("12. builder determinism: rebuild reproduces identical bytes",
          same, "3 outputs byte-identical after rebuild" if same else f"rc={proc.returncode} {proc.stderr[:200]}")

    # -- 13. recorded hashes still match --------------------------------------
    pairs: list[tuple[str, str]] = []
    collect_path_hash_pairs(json.loads((SC_DIR / "integrity_hashes_after.json").read_text(encoding="utf-8")), pairs)
    collect_path_hash_pairs(json.loads((SD_DIR / "stage_d_manifest.json").read_text(encoding="utf-8")), pairs)
    bad = []
    seen = set()
    for rel, want in pairs:
        rel_norm = rel.replace("\\\\", "\\")
        key = (rel_norm, want)
        if key in seen:
            continue
        seen.add(key)
        path = REPO / rel_norm
        if not path.is_file():
            bad.append(f"missing {rel_norm}")
        else:
            got = sha256(path)
            if got != want:
                bad.append(f"hash changed {rel_norm}: {got[:12]} != {want[:12]}")
    check("13. historical integrity: Stage C + Stage D recorded hashes unchanged",
          not bad, f"{len(seen)} recorded hashes verified" if not bad else "; ".join(bad[:4]))

    # -- 14. nothing outside D1 modified since D1 began -------------------------
    d1_start = min(p.stat().st_mtime for p in HERE.iterdir() if p.is_file())
    scan_roots = [REPO / "runs", REPO / "data", REPO / "app",
                  SC_DIR, SD_DIR, REPO / "tests"]
    skip_parts = {"__pycache__", ".pytest_cache", ".git"}
    skip_suffix = {".pyc", ".pyo"}
    touched = []
    for root in scan_roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if skip_parts & set(p.parts) or p.suffix in skip_suffix:
                continue
            if p.stat().st_mtime >= d1_start:
                touched.append(str(p.relative_to(REPO)))
    check("14. no file outside stage-d1 dir modified since D1 work began",
          not touched, f"scanned {', '.join(r.name for r in scan_roots)}" if not touched else str(touched[:5]))

    # -- 15. git state ------------------------------------------------------------
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=str(REPO)).stdout.strip()
        porc = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                              cwd=str(REPO)).stdout.splitlines()
        tracked_changes = [l for l in porc if l.strip() and not l.startswith("??")]
        ok = head.startswith("d4ea26d") and not tracked_changes
        detail = f"HEAD={head[:7]}, untracked={sum(1 for l in porc if l.startswith('??'))}, tracked_changes={len(tracked_changes)}"
    except FileNotFoundError:
        ok, detail = False, "git not available"
    check("15. git: HEAD unchanged (d4ea26d), no tracked file modified, nothing committed",
          ok, detail)

    # -- 16. no model/database artifacts, no network imports ---------------------
    dbs = [p.name for p in HERE.rglob("*.db")]
    forbidden_imports = ("requests", "httpx", "urllib.request", "openai", "ollama", "socket")
    import_problems = []
    for py in HERE.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        for name in forbidden_imports:
            if re.search(rf"^\s*(import {re.escape(name)}|from {re.escape(name)} import)", src, re.M):
                import_problems.append(f"{py.name}: {name}")
    check("16. no model calls: no .db artifacts, no network/LLM imports in D1 scripts",
          not dbs and not import_problems,
          "no databases; stdlib-only scripts (model/API calls were never made)" if not dbs and not import_problems
          else f"dbs={dbs} imports={import_problems}")

    # -- 17. secrets scan ------------------------------------------------------------
    patterns = [
        (re.compile(r"sk-[A-Za-z0-9]{20,}"), "openai-style key"),
        (re.compile(r"AKIA[0-9A-Z]{16}"), "aws key"),
        (re.compile(r"ghp_[A-Za-z0-9]{36}"), "github token"),
        (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"), "bearer token"),
        (re.compile(r"(?i)api[_-]?key\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']"), "inline api key"),
    ]
    hits = []
    for p in sorted(HERE.iterdir()):
        if not p.is_file() or p.name == Path(__file__).name:
            continue  # validator excluded: it contains the detection patterns themselves
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for rx, label in patterns:
            if rx.search(text):
                hits.append(f"{p.name}:{label}")
    check("17. secrets scan over Stage D1 files: no keys/tokens",
          not hits, "clean (validator source excluded: holds the patterns)" if not hits else str(hits))

    # -- 18. CSV structure -------------------------------------------------------------
    struct_problems = []
    for name in ("review_workspace.csv", "proposed_judgments.csv"):
        p = HERE / name
        raw = p.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            struct_problems.append(f"{name}: BOM present")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            struct_problems.append(f"{name}: not utf-8 ({exc})")
        with p.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        widths = {len(r) for r in rows}
        if len(widths) != 1:
            struct_problems.append(f"{name}: uneven rows {widths}")
    check("18. CSV structure: UTF-8, no BOM, uniform column count",
          not struct_problems, "both CSVs clean" if not struct_problems else "; ".join(struct_problems))

    # -- 19. test suite -------------------------------------------------------------------
    proc = subprocess.run([sys.executable, "-m", "pytest"], capture_output=True, text=True,
                          cwd=str(REPO))
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    ok = proc.returncode == 0
    check("19. test suite (plain `python -m pytest`) passes",
          ok, tail or f"rc={proc.returncode}")

    # -- report ------------------------------------------------------------------------------
    n_pass = sum(1 for _, ok, _ in results if ok)
    lines = [
        "# Stage D1 — Validation Report",
        "",
        f"**Directory:** `{HERE.name}` · **Checks:** {n_pass}/{len(results)} PASS · "
        f"**Run:** `python validate_stage_d1.py` (stdlib + subprocess pytest)",
        "",
        "Scope: workspace construction integrity, proposal/human-layer separation, blind-confirmer surface,",
        "historical-artifact immutability, no-model-call evidence, and full test suite.",
        "",
        "| # | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for idx, (name, ok, detail) in enumerate(results, start=1):
        num = name.split(".", 1)[0]
        rest = name.split(".", 1)[1].strip() if "." in name else name
        det = (detail or "").replace("|", "/").replace("\n", " ")
        lines.append(f"| {num} | {rest} | {'PASS' if ok else '**FAIL**'} | {det} |")
    lines += [
        "",
        "## Interpretation",
        "",
        "- Checks 4, 6, 7 prove the layer separation required by the Stage D1 brief: proposals exist only in "
        "proposal columns, every human/adjudication field is empty, and the confirmer's surface carries no "
        "system verdict or old-AI-draft label.",
        "- Check 13 re-verifies every SHA-256 recorded by Stage C and Stage D (source DB, both run DBs and "
        "reports, eval questions, judge/claims/prompts sources, the 56-file and 8-file review artifacts); "
        "check 14 shows nothing outside this directory was modified after Stage D1 began.",
        "- Check 15 shows no commit was made and no tracked file changed; only untracked `analysis/` outputs exist.",
        "- Check 16/17: scripts are stdlib-only and make no network/model calls; no key material in any output.",
        "- Check 19 is the full repository test suite (plain invocation; `pyproject.toml` already supplies `-q`).",
        "",
        "**Nothing in this report is a human judgment; it validates structure and integrity only.**",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{n_pass}/{len(results)} checks PASS -> {REPORT_PATH.name}")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
