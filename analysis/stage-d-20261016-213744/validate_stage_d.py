"""Stage D Phase F: validation of the annotation package (read-only + re-runnable builder).

Checks (each recorded PASS/FAIL in stage_d_validation_report.md):
  1  builder re-run determinism (items content identical across two runs)
  2  JSON-schema conformance of every queue item (required/enum/type/pattern,
     additionalProperties=false, nested objects)
  3  every queue claim maps to an existing source claim (post-gate DB row,
     byte-identical claim text, matching stored verdict)
  4  every queue question maps to an existing question in eval_questions.json
  5  ID uniqueness (annotation_id; (question_id, claim_id); abstention question_id)
  6  evidence references: chunk ids exist in the source run DB, every shown chunk
     text is byte-verbatim from that DB, recovered citations re-derived
     independently (anomaly note == historical stored ids) for all 13 retractions
  7  abstention items: stored answer is the verbatim abstention string,
     claims_total == 0, reconstructed retrieval length == stored retrieved_count
  8  all human-judgment fields null on all items; review_status == not_reviewed
  9  AI-label separation: proposed_ai_label absent from the blind file (columns
     and values); only null/nonexistent system verdict in blind; provenance
     strings present whenever proposed_ai_label is non-null
 10  historical artifacts unchanged (Stage C integrity baseline + both review
     files) and gold_label NULL in both run DBs
 11  git: no tracked-file modifications; HEAD matches manifest
 12  no credential-like secrets in any generated file
 13  manifest self-consistency (hashes recomputed, counts match the queue)
 14  full existing test suite passes

Writes: stage_d_validation_report.md (only file written by this script, plus
whatever build_review_queue.py rewrites inside this same directory).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ABSTENTION = "Insufficient evidence in the retrieved passages."
HUMAN_FIELDS = [
    "human_label", "human_rationale", "evidence_sufficiency_rationale",
    "citation_support_label", "citation_support_rationale", "abstention_assessment",
    "reviewer_id", "review_timestamp", "uncertainty_notes",
    "adjudicated_label", "adjudication_rationale",
]
REVIEW56_SHA = "86787635c4ba04a03ebfe52c9bc1d1e90397826740049470e0cc12c6700ae947"
MINIREVIEW_SHA = "f3522f9e34e1647ecfff441faf8b0791952f77a2a794071c8750e6a3ebfe0bc7"
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|client[_-]?secret|password)\b\s*[=:]\s*"
               r"[\"']?[A-Za-z0-9._~+/-]{12,}[\"']?"),
]

results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str, *, warn_only: bool = False) -> None:
    status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    results.append((name, status, detail))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ro(p: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------- schema check
def check_schema(items: list[dict], schema: dict) -> None:
    props = schema["properties"]
    required = set(schema["required"])
    problems: list[str] = []

    def check_type(value, spec, where: str) -> None:
        if spec is None:
            return
        type_spec = spec.get("type") if isinstance(spec, dict) else spec
        types = type_spec if isinstance(type_spec, list) else [type_spec]
        if value is None:
            if "null" in types:
                return
            problems.append(f"{where}: null not allowed")
            return
        basic = {"string": str, "integer": int, "number": (int, float),
                 "boolean": bool, "object": dict, "array": list}
        ok = False
        for t in types:
            if t in basic:
                if t == "integer" and isinstance(value, bool):
                    continue
                if isinstance(value, basic[t]):
                    ok = True
        if not ok:
            problems.append(f"{where}: type {type(value).__name__} not in {types}")
            return
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"{where}: {value!r} not in enum")
        if "const" in spec and value != spec["const"]:
            problems.append(f"{where}: {value!r} != const {spec['const']!r}")
        if "pattern" in spec and isinstance(value, str) and not re.search(spec["pattern"], value):
            problems.append(f"{where}: {value!r} !~ {spec['pattern']}")

    for idx, item in enumerate(items):
        aid = item.get("annotation_id", f"item[{idx}]")
        missing = required - set(item)
        if missing:
            problems.append(f"{aid}: missing required {sorted(missing)}")
        extra = set(item) - set(props)
        if extra:
            problems.append(f"{aid}: additionalProperties {sorted(extra)}")
        for k, v in item.items():
            spec = props.get(k)
            if spec is None:
                continue
            check_type(v, spec, f"{aid}.{k}")
            # nested objects
            if k == "paired_answer_texts" and isinstance(v, dict):
                for sk in spec.get("required", []):
                    if sk not in v:
                        problems.append(f"{aid}.paired_answer_texts missing {sk}")
            if k == "evidence_text_or_reference" and isinstance(v, list):
                ispec = spec["items"]
                for e in v:
                    for sk in ispec.get("required", []):
                        if sk not in e:
                            problems.append(f"{aid}.evidence missing {sk}")
                    for sk, sv in e.items():
                        s2 = ispec["properties"].get(sk)
                        if s2:
                            check_type(sv, s2, f"{aid}.evidence[{e.get('chunk_id')}].{sk}")
            if k == "source_artifact_refs" and isinstance(v, dict):
                for sk in spec.get("required", []):
                    if sk not in v:
                        problems.append(f"{aid}.source_artifact_refs missing {sk}")
            if k == "system_diagnostics" and isinstance(v, dict):
                for sk, sv in v.items():
                    s2 = spec["properties"].get(sk)
                    if s2:
                        check_type(sv, s2, f"{aid}.system_diagnostics.{sk}")

    record("2 schema conformance (all items, nested objects, enums, patterns)",
           not problems, "; ".join(problems[:8]) or "all items conform to schema v1.0.0")


def main() -> int:
    # ---------------- 1. builder determinism (two consecutive runs) ----------------
    script = HERE / "build_review_queue.py"
    runs_out = []
    for _ in range(2):
        cp = subprocess.run([sys.executable, str(script)], cwd=REPO,
                            capture_output=True, text=True, encoding="utf-8")
        if cp.returncode != 0:
            record("1 builder re-run determinism", False,
                   f"builder failed: {cp.stderr.strip()[-400:]}")
            break
        payload = json.loads((HERE / "human_review_queue.json").read_text(encoding="utf-8"))
        runs_out.append(hashlib.sha256(
            json.dumps(payload["items"], sort_keys=True).encode()).hexdigest())
    else:
        record("1 builder re-run determinism", len(set(runs_out)) == 1,
               f"items content hash across 2 runs: {runs_out}")

    # ---------------- load artifacts ----------------
    payload = json.loads((HERE / "human_review_queue.json").read_text(encoding="utf-8"))
    items = payload["items"]
    schema = json.loads((HERE / "annotation_schema.json").read_text(encoding="utf-8"))
    manifest = json.loads((HERE / "stage_d_manifest.json").read_text(encoding="utf-8"))
    with (HERE / "human_review_queue.csv").open(encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    with (HERE / "human_review_queue_blind.csv").open(encoding="utf-8") as f:
        blind_rows = list(csv.DictReader(f))

    check_schema(items, schema)

    # ---------------- open sources ----------------
    pq = ro(REPO / "runs/eval-postgate22-20261016-141416/evidencegraph-eval.db")
    hq = ro(REPO / "runs/eval-pilot22-20261014-181354/evidencegraph-eval.db")
    questions = {q["id"]: q for q in json.loads(
        (REPO / "data/sample/eval_questions.json").read_text(encoding="utf-8"))["questions"]}
    chunks = {r["id"]: r for r in pq.execute(
        "SELECT c.id, c.text FROM chunks c")}
    claims_db = {r["id"]: r for r in pq.execute(
        "SELECT c.id, c.claim_text, c.label, c.evidence_ids_json, c.anomalies_json, r.question "
        "FROM verif_claims c JOIN eval_results r ON r.id=c.eval_result_id WHERE r.system='verified'")}
    answers = {(r["system"], r["question"]): r for r in pq.execute("SELECT * FROM eval_results")}
    hist_claims = {r["id"]: r for r in hq.execute(
        "SELECT c.id, c.claim_text, c.label, c.evidence_ids_json, r.question "
        "FROM verif_claims c JOIN eval_results r ON r.id=c.eval_result_id WHERE r.system='verified'")}

    # ---------------- 3/4 mapping ----------------
    map_probs: list[str] = []
    for it in items:
        if it["question_id"] not in questions:
            map_probs.append(f"{it['annotation_id']}: question_id {it['question_id']} not in eval_questions.json")
        if it["item_type"] == "claim":
            row = claims_db.get(it["claim_id"])
            if row is None:
                map_probs.append(f"{it['annotation_id']}: claim_id {it['claim_id']} not in source DB")
                continue
            if row["claim_text"] != it["claim_text"]:
                map_probs.append(f"{it['annotation_id']}: claim_text drift vs source DB")
            if row["label"] != it["system_verdict"]:
                map_probs.append(f"{it['annotation_id']}: system_verdict != stored label")
            if row["question"] != questions[it["question_id"]]["question"]:
                map_probs.append(f"{it['annotation_id']}: question text mismatch")
    record("3 every claim maps to an existing source claim row (byte-identical)",
           not map_probs, "; ".join(map_probs[:8]) or f"all {sum(1 for i in items if i['item_type']=='claim')} claim items verified against source DB")
    record("4 every question_id exists in eval_questions.json",
           not [p for p in map_probs if "question_id" in p],
           "all question ids resolve")

    # ---------------- 5 uniqueness ----------------
    aids = [i["annotation_id"] for i in items]
    ckeys = [(i["question_id"], i["claim_id"]) for i in items if i["item_type"] == "claim"]
    abs_qids = [i["question_id"] for i in items if i["item_type"] == "abstention_question"]
    uniq_ok = (len(aids) == len(set(aids))
               and len(ckeys) == len(set(ckeys))
               and len(abs_qids) == len(set(abs_qids))
               and len(items) == 46 == len(csv_rows) == len(blind_rows)
               and aids == [r["annotation_id"] for r in csv_rows]
               and aids == [r["annotation_id"] for r in blind_rows])
    record("5 ID uniqueness + csv/json/blind row agreement (46/46/46, same order)",
           uniq_ok, f"items={len(items)} csv={len(csv_rows)} blind={len(blind_rows)} "
                    f"dup_ann={len(aids)-len(set(aids))} dup_claim={len(ckeys)-len(set(ckeys))} "
                    f"dup_abs={len(abs_qids)-len(set(abs_qids))}")

    # ---------------- 6 evidence references ----------------
    ev_probs: list[str] = []
    id_re = re.compile(r"evidence ids \[([0-9, ]*)\]")
    n_recovered = 0
    for it in items:
        if it["item_type"] != "claim":
            continue
        row = claims_db[it["claim_id"]]
        stored = json.loads(row["evidence_ids_json"] or "[]")
        note_ids = None
        for n in json.loads(row["anomalies_json"] or "[]"):
            m = id_re.search(str(n))
            if m:
                note_ids = [int(x) for x in m.group(1).split(", ") if x]
        expected = note_ids if note_ids is not None else stored
        if it["retrieved_evidence_ids"] != expected:
            ev_probs.append(f"{it['annotation_id']}: evidence ids {it['retrieved_evidence_ids']} != expected {expected}")
        if note_ids is not None:
            n_recovered += 1
            # independent historical cross-check by (question, claim text)
            hmatch = [h for h in hist_claims.values()
                      if h["question"] == row["question"]
                      and h["claim_text"] == row["claim_text"]]
            if len(hmatch) != 1 or json.loads(hmatch[0]["evidence_ids_json"] or "[]") != note_ids:
                ev_probs.append(f"{it['annotation_id']}: historical cross-check failed")
        for e in it["evidence_text_or_reference"]:
            cid = e["chunk_id"]
            if cid not in chunks:
                ev_probs.append(f"{it['annotation_id']}: chunk {cid} missing from source DB")
            elif e["text"] != chunks[cid]["text"]:
                ev_probs.append(f"{it['annotation_id']}: chunk {cid} text not verbatim")
            if e["text_source"] != "source_run_db_verbatim":
                ev_probs.append(f"{it['annotation_id']}: unexpected text_source {e['text_source']}")
    record("6 evidence references (verbatim chunk texts, recovered ids re-derived, 13/13 historical cross-check)",
           not ev_probs and n_recovered == 13,
           "; ".join(ev_probs[:8]) or f"recovered citations re-verified: {n_recovered}/13; all chunk texts verbatim")

    # ---------------- 7 abstention items ----------------
    abs_probs: list[str] = []
    for it in items:
        if it["item_type"] != "abstention_question":
            continue
        qtext = questions[it["question_id"]]["question"]
        ver = answers.get(("verified", qtext))
        if ver is None or ver["answer_text"] != ABSTENTION or ver["claims_total"] != 0:
            abs_probs.append(f"{it['annotation_id']}: not a stored zero-claim abstention")
            continue
        if len(it["evidence_text_or_reference"]) != ver["retrieved_count"]:
            abs_probs.append(f"{it['annotation_id']}: reconstructed retrieval length "
                             f"{len(it['evidence_text_or_reference'])} != stored {ver['retrieved_count']}")
        if it["retrieved_evidence_ids"] is not None or it["claim_text"] is not None:
            abs_probs.append(f"{it['annotation_id']}: claim fields must be null on abstention item")
        if it["system_verdict"] != "abstained_no_claims":
            abs_probs.append(f"{it['annotation_id']}: wrong system_verdict")
    record("7 abstention items (verbatim stored abstention, claims_total=0, retrieval == stored retrieved_count)",
           not abs_probs, "; ".join(abs_probs) or "6/6 abstention items verified")

    # ---------------- 8 emptiness ----------------
    dirty = [(i["annotation_id"], f) for i in items for f in HUMAN_FIELDS if i[f] is not None]
    dirty += [(i["annotation_id"], "review_status") for i in items if i["review_status"] != "not_reviewed"]
    record("8 all human-judgment fields null; review_status=not_reviewed everywhere",
           not dirty, f"non-null human fields: {dirty[:6] or 'NONE'}")

    # ---------------- 9 AI-label separation ----------------
    blind_hdr = list(blind_rows[0].keys()) if blind_rows else []
    leak_cols = [c for c in blind_hdr if c in
                 ("system_verdict", "proposed_ai_label", "proposed_ai_label_source", "system_diagnostics")]
    leak_vals = [r["annotation_id"] for r in blind_rows
                 if "recovered_from_anomaly" in r.get("evidence_text_or_reference", "")]
    src_missing = [i["annotation_id"] for i in items
                   if i["proposed_ai_label"] is not None and not i["proposed_ai_label_source"]]
    record("9 AI-label separation (blind file has no verdict/AI columns or recovery leaks; provenance strings present)",
           not leak_cols and not leak_vals and not src_missing,
           f"leak_cols={leak_cols} leak_vals={len(leak_vals)} src_missing={src_missing}")

    # ---------------- 10 historical integrity ----------------
    base = json.loads((REPO / "analysis/stage-c-20261016/integrity_hashes_after.json").read_text(encoding="utf-8"))
    changed = []
    for key, rec in base.items():
        p = REPO / rec["path"]
        if not p.exists():
            changed.append(f"{rec['path']} MISSING")
        elif sha256(p) != rec["sha256"]:
            changed.append(f"{rec['path']} hash changed")
    for rel, expect in [
        ("runs/eval-pilot22-20261014-181354/human_claim_review56.md", REVIEW56_SHA),
        ("runs/eval-mini-20261014-165641/human_claim_review.md", MINIREVIEW_SHA),
    ]:
        if sha256(REPO / rel) != expect:
            changed.append(f"{rel} hash changed")
    gold = 0
    for dbp in (REPO / "runs/eval-postgate22-20261016-141416/evidencegraph-eval.db",
                REPO / "runs/eval-pilot22-20261014-181354/evidencegraph-eval.db"):
        con = ro(dbp)
        gold += con.execute("SELECT COUNT(*) FROM verif_claims WHERE gold_label IS NOT NULL").fetchone()[0]
        con.close()
    if gold:
        changed.append(f"gold_label non-null count={gold}")
    # run-dir files must predate the Stage D directory
    stage_d_birth = (HERE).stat().st_mtime
    late = []
    for rundir in (REPO / "runs/eval-postgate22-20261016-141416",
                   REPO / "runs/eval-pilot22-20261014-181354"):
        for p in rundir.rglob("*"):
            if p.is_file() and "__pycache__" not in str(p) and p.stat().st_mtime > stage_d_birth + 1:
                late.append(str(p.relative_to(REPO)))
    record("10 historical artifacts unchanged (Stage C baseline + review files + gold_label NULL + run-dir mtimes)",
           not changed and not late,
           f"changed={changed or 'NONE'}; files modified after Stage D start={late or 'NONE'}")

    # ---------------- 11 git state ----------------
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=REPO, capture_output=True,
                              text=True, encoding="utf-8").stdout
    porcelain = [ln for ln in git("status", "--porcelain").splitlines() if ln.strip()]
    tracked_dirty = [ln for ln in porcelain if not ln.startswith("??")]
    head = git("rev-parse", "HEAD").strip()
    record("11 git: no tracked-file changes; HEAD matches manifest",
           not tracked_dirty and head == manifest["git"]["commit"],
           f"tracked_dirty={tracked_dirty or 'NONE'}; HEAD={head[:12]}; untracked={[ln for ln in porcelain if ln.startswith('??')]}")

    # ---------------- 12 secrets scan ----------------
    findings: list[str] = []
    for p in sorted(HERE.iterdir()):
        if p.suffix.lower() not in (".md", ".json", ".csv", ".py"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for pat in SECRET_PATTERNS:
            m = pat.search(text)
            if m:
                findings.append(f"{p.name}: {m.group(0)[:60]}")
    record("12 no credential-like secrets in generated files",
           not findings, findings or "no secret-like patterns in any Stage D file")

    # ---------------- 13 manifest consistency ----------------
    m_probs: list[str] = []
    for entry in manifest["source_runs"]:
        p = REPO / entry["db_path"]
        if sha256(p) != entry["db_sha256"]:
            m_probs.append(f"{entry['db_path']} hash mismatch")
    for key in ("questions", "ai_draft_review_file", "mini_review_file", "protected_source_db"):
        rec = manifest["source_files"][key]
        if sha256(REPO / rec["path"]) != rec["sha256"]:
            m_probs.append(f"{key} hash mismatch")
    comp = manifest["queue_composition"]
    if comp["total_items"] != len(items):
        m_probs.append("total_items mismatch")
    tier_counts = {t: sum(1 for i in items if i["item_priority"] == t) for t in (1, 2, 3, 4, 5)}
    by = comp["by_priority_tier"]
    if (by["1_gate_retracted_claims"], by["2_surviving_supported_claims"],
            by["3_zero_claim_abstention_questions"], by["4_stratified_unchanged_sample"],
            by["5_pre_existing_rule_anomaly"]) != (
            tier_counts[1], tier_counts[2], tier_counts[3], tier_counts[4], tier_counts[5]):
        m_probs.append(f"tier counts mismatch manifest={by} actual={tier_counts}")
    for k in ("no_model_calls", "no_invented_human_labels", "ai_labels_not_human", "no_gold_label_writes"):
        if not manifest["honesty_statements"].get(k, "").startswith("TRUE"):
            m_probs.append(f"honesty statement missing/invalid: {k}")
    record("13 manifest self-consistency (hashes recomputed, counts match queue, honesty statements)",
           not m_probs, "; ".join(m_probs) or "manifest verified against recomputed hashes and live queue")

    # ---------------- 14 test suite ----------------
    pytest_python = sys.executable
    probe = subprocess.run([pytest_python, "-m", "pytest", "--version"], cwd=REPO,
                           capture_output=True, text=True, encoding="utf-8")
    if probe.returncode != 0:
        venv_py = REPO / ".venv/Scripts/python.exe"
        if venv_py.exists():
            pytest_python = str(venv_py)
    # NOTE: pyproject addopts already includes "-q"; adding another -q would be
    # -qq which suppresses the final "N passed" summary line entirely.
    tp = subprocess.run([pytest_python, "-m", "pytest"], cwd=REPO,
                        capture_output=True, text=True, encoding="utf-8", timeout=600)
    out_lines = (tp.stdout + tp.stderr).strip().splitlines()
    summary = next((ln.strip() for ln in reversed(out_lines)
                    if re.search(r"\b\d+ (passed|failed|error)", ln)),
                   " | ".join(out_lines[-3:]) or "no output")
    record("14 full existing test suite passes",
           tp.returncode == 0, summary, warn_only=False)

    pq.close()
    hq.close()

    # ---------------- report ----------------
    n_fail = sum(1 for _, s, _ in results if s == "FAIL")
    n_warn = sum(1 for _, s, _ in results if s == "WARN")
    lines = [
        "# Stage D — Validation Report",
        "",
        f"**Generated:** {dt.datetime.now(dt.timezone.utc).isoformat()}  ",
        f"**Validator:** `analysis/{HERE.name}/validate_stage_d.py` (re-runnable; stdlib only)  ",
        f"**Overall:** {'PASS' if n_fail == 0 else 'FAIL'} "
        f"({len(results) - n_fail - n_warn}/{len(results)} checks passed"
        + (f", {n_warn} warnings" if n_warn else "") + ")",
        "",
        "| # | Check | Status | Detail |",
        "|---|---|---|---|",
    ]
    for i, (name, status, detail) in enumerate(results, 1):
        safe = detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i} | {name} | **{status}** | {safe} |")
    lines += [
        "",
        "## Interpretation",
        "",
        "- A PASS here means the package is mechanically consistent with the immutable artifacts: "
        "every queued item maps to a real stored claim/question, evidence text is byte-verbatim, "
        "recovered citations were re-derived independently of the builder, human fields are empty, "
        "AI labels are quarantined, no historical artifact or source DB changed, and no secret-like "
        "material was written.",
        "- **No check here evaluates any human label** — none exist yet. This report certifies "
        "readiness for review, not review quality.",
        "- If any row is FAIL, the package must not be used for review until the cause is fixed "
        "and this validator is re-run.",
        "",
    ]
    (HERE / "stage_d_validation_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"validation {'PASS' if n_fail == 0 else 'FAIL'}: "
          f"{len(results) - n_fail - n_warn}/{len(results)} passed, {n_fail} failed, {n_warn} warnings")
    for name, status, detail in results:
        print(f"  [{status}] {name}: {detail[:160]}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
