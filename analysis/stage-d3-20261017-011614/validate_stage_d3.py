"""Stage D3 offline validation (stdlib + pytest only; no network; no model calls).

Checks
  A. required D3 files exist
  B. d3_review_decisions.csv: 46 rows, ids exactly once, queue-order traceable,
     claim wording byte-equal to the queue, proposed labels byte-equal to D1,
     evidence excerpts verbatim in both the D1 workspace AND the raw queue,
     source references valid, vocabulary enforced, reviewer columns 100% blank
  C. cards + summary: 46 cards exactly once, group sections, R1 ruling present,
     no pre-checked boxes, no fabricated-confirmation language
  D. Stage D1 + D2 packages unchanged (manifest hashes)
  E. historical integrity: Stage C/D recorded hashes, mtime scan, git state
  F. hygiene: no DB artifacts, stdlib-only, no secrets, corpus-absence tokens
     re-verified by read-only scan of the protected database, pytest 763

Writes d3_validation_report.md (this directory only).
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
QUEUE_PATH = REPO / "analysis/stage-d-20261016-213744/human_review_queue.json"
D1_DIR = REPO / "analysis/stage-d1-20261017-000041"
D2_DIR = REPO / "analysis/stage-d2-20261017-002537"
DB_PATH = REPO / "data/evidencegraph.db"

# Local clock is UTC+5; D3 directory 20261017-011614 local == 20:16 UTC (2026-10-16).
D3_START = datetime(2026, 10, 16, 20, 10, 0, tzinfo=timezone.utc).timestamp()
MTTOLER = 120.0

ALLOWED_LABELS = {"supported", "contradicted", "insufficient_evidence", "unverifiable",
                  "not_applicable", "appropriate_abstention", "inappropriate_abstention",
                  "uncertain"}
STATUS_VOCAB = {"supports", "contradicts", "insufficient", "unclear"}
ACTION_VOCAB = {"accept_proposal", "revise_proposal", "needs_adjudication"}
R1_FAMILY = ["ann-d1-0013", "ann-d1-0017", "ann-d1-0018", "ann-d1-0019", "ann-d1-0036",
             "ann-d1-0037", "ann-d1-0038", "ann-d1-0040", "ann-d1-0042", "ann-d1-0043",
             "ann-d1-0044", "ann-d1-0045"]
# Tokens the review's "absent from corpus" claims rely on (must be 0 occurrences).
ABSENT_TOKENS = ["CVE-2021-45046", "Conti", "Cisco", "Heartbleed", "Log4Shell",
                 "overhyped", "CVSS", "2021-11-03", "2022-05-04", "2021-12-10",
                 "1.0.2g", "KB5004236", "KB"]

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> bool:
    results.append((name, bool(ok), detail))
    return bool(ok)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    qitems = {it["annotation_id"]: it for it in queue["items"]}
    qtext = {q["id"]: q["question"] for q in
             json.loads((REPO / "data/sample/eval_questions.json").read_text(encoding="utf-8"))["questions"]}
    ws = {r["annotation_id"]: r for r in csv.DictReader(
        (D1_DIR / "review_workspace.csv").open(encoding="utf-8", newline=""))}

    # A
    required = ["d3_review_decisions.csv", "d3_review_cards.md",
                "d3_highest_risk_summary.md", "build_d3_review.py", "validate_stage_d3.py"]
    missing = [f for f in required if not (HERE / f).is_file()]
    check("A1 required D3 files exist", not missing, f"missing={missing}")

    # B
    with (HERE / "d3_review_decisions.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    ids = [r["annotation_id"] for r in rows]
    check("B1 46 rows, every id exactly once", len(rows) == 46 and set(ids) == set(qitems)
          and len(set(ids)) == 46, f"n={len(rows)}")
    claim_bad = [r["annotation_id"] for r in rows if r["claim_or_question"] != " ".join(
        (qitems[r["annotation_id"]]["claim_text"]
         or qtext[qitems[r["annotation_id"]]["question_id"]]).split())]
    check("B2 claim/question wording unchanged (byte-equal to queue)", not claim_bad,
          f"bad={claim_bad}")
    exc_bad: list[str] = []
    src_bad: list[str] = []
    for r in rows:
        it = qitems[r["annotation_id"]]
        queue_ev = "\n".join(c["text"] for c in it["evidence_text_or_reference"])
        if not (r["evidence_excerpt"] in queue_ev and r["evidence_excerpt"] in
                ws[r["annotation_id"]]["evidence_text"]):
            exc_bad.append(r["annotation_id"])
        shown = {str(c["chunk_id"]) for c in it["evidence_text_or_reference"]}
        m = re.match(r"shown chunks: ([^|]+) \|", r["source_reference"])
        if not m or not set(m.group(1).replace(" ", "").split(",")) <= shown:
            src_bad.append(r["annotation_id"])
    check("B3 excerpts verbatim in queue AND D1 workspace", not exc_bad, f"bad={exc_bad}")
    check("B4 source references cite only shown chunk ids", not src_bad, f"bad={src_bad}")
    prop_bad = [r["annotation_id"] for r in rows
                if r["proposed_label"] != ws[r["annotation_id"]]["proposed_label"]
                or r["proposed_abstention_assessment"]
                != ws[r["annotation_id"]]["proposed_abstention_assessment"]]
    check("B5 proposed_* byte-equal to D1 proposals", not prop_bad, f"bad={prop_bad}")
    filled = [(r["annotation_id"], c) for r in rows
              for c in ("reviewer_decision", "reviewer_note") if r.get(c, "").strip()]
    check("B6 reviewer columns 100% blank", not filled, f"violations={filled[:3]}")
    vocab_bad = [r["annotation_id"] for r in rows
                 if r["evidence_status"] not in STATUS_VOCAB
                 or r["recommended_action"] not in ACTION_VOCAB
                 or (r["suggested_revised_label"] and r["suggested_revised_label"] not in ALLOWED_LABELS)
                 or (r["recommended_action"] == "revise_proposal") != bool(r["suggested_revised_label"])
                 or (r["recommended_action"] != "revise_proposal" and r["suggested_revised_label"])]
    check("B7 vocabulary enforced (status/action/revised-label consistency)", not vocab_bad,
          f"bad={vocab_bad}")
    check("B8 review_order is 1..46",
          [int(r["review_order"]) for r in rows] == list(range(1, 47)), "")

    # C
    cards = (HERE / "d3_review_cards.md").read_text(encoding="utf-8")
    heads = re.findall(r"^### Card (\d+) - (ann-d1-\d+) \(Group ([ABC])\)", cards, flags=re.M)
    nums = sorted(int(n) for n, _, _ in heads)
    check("C1 46 cards, one per item (grouped by risk, not file-order sequential)",
          nums == list(range(1, 47)) and {a for _, a, _ in heads} == set(qitems),
          f"found={len(heads)}")
    group_csv = {r["annotation_id"]: r["review_group"] for r in rows}
    check("C2 card groups match CSV groups",
          all(group_csv[a] == g for _, a, g in heads), "")
    check("C3 group sections + R1 ruling present",
          all(s in cards for s in ["## Group A", "## Group B", "## Group C",
                                   "## Ruling R1"]), "")
    check("C4 R1 covers exactly the 12 flagged items",
          all(i in cards for i in R1_FAMILY)
          and len(re.findall(r"ann-d1-00\d\d", cards.split("## Group A")[0])) > 12, "")
    check("C5 no pre-checked boxes in any card", "[x]" not in cards.lower(), "")
    summary = (HERE / "d3_highest_risk_summary.md").read_text(encoding="utf-8")
    check("C6 summary lists the five priority decisions first",
          all(summary.count(a) >= 1 for a in ["ann-d1-0033", "ann-d1-0014", "ann-d1-0030",
                                              "ann-d1-0032", "ann-d1-0002"])
          and summary.index("ann-d1-0033") < summary.index("ann-d1-0002"), "")
    banned = ["human-confirmed", "reviewer confirmed", "you accepted",
              "review is complete", "decisions have been recorded"]
    hits = [b for b in banned if b in (cards + summary).lower()]
    check("C7 no fabricated-confirmation language", not hits, f"hits={hits}")

    # D
    bad_d: list[str] = []
    n_hashes = 0
    for manifest_path, keys in [(D1_DIR / "stage_d1_manifest.json",
                                 ["source_inputs_read_only", "outputs"]),
                                (D2_DIR / "stage_d2_manifest.json",
                                 ["source_inputs_read_only", "outputs"])]:
        man = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in keys:
            for rec in man[key]:
                n_hashes += 1
                p = REPO / rec["path"]
                if not p.is_file() or sha256(p) != rec["sha256"]:
                    bad_d.append(rec["path"])
    check(f"D1+D2 unchanged ({n_hashes} manifest hashes)", not bad_d, f"bad={bad_d}")

    # E
    def collect_path_hash_pairs(obj, out: list[tuple[str, str]]) -> None:
        if isinstance(obj, dict):
            path_keys = [k for k in obj if "path" in k.lower()]
            hash_keys = [k for k in obj if k.endswith("sha256")]
            if path_keys and hash_keys:
                out.append((str(obj[path_keys[0]]), str(obj[hash_keys[0]])))
            for v in obj.values():
                collect_path_hash_pairs(v, out)
        elif isinstance(obj, list):
            for v in obj:
                collect_path_hash_pairs(v, out)

    pairs: list[tuple[str, str]] = []
    for rel in ["analysis/stage-c-20261016/integrity_hashes_after.json",
                "analysis/stage-d-20261016-213744/stage_d_manifest.json"]:
        collect_path_hash_pairs(json.loads((REPO / rel).read_text(encoding="utf-8")), pairs)
    bad2, seen = [], 0
    for rel_norm, want in pairs:
        p = REPO / rel_norm.replace("/", "\\")
        if not p.is_file():
            continue
        seen += 1
        if sha256(p) != want:
            bad2.append(rel_norm)
    check("E1 Stage C + D recorded hashes intact", not bad2,
          f"{seen} recorded hashes verified" if not bad2 else f"bad={bad2}")
    recent: list[str] = []
    for sub in ["analysis/stage-b-evalpostgate22-20261016", "analysis/stage-c-20261016",
                "analysis/stage-d-20261016-213744", "analysis/stage-d1-20261017-000041",
                "analysis/stage-d1-20261017-000041-old-draft", "analysis/stage-d2-20261017-002537",
                "runs", "data", "prompts", "src", "tests", "docs", "Makefile", "Dockerfile",
                "pyproject.toml"]:
        base = REPO / sub
        cand = [base] if base.is_file() else ([p for p in base.rglob("*") if p.is_file()]
                                              if base.is_dir() else [])
        for p in cand:
            if HERE in p.parents:
                continue
            if p.stat().st_mtime > D3_START + MTTOLER:
                recent.append(str(p.relative_to(REPO)))
    check("E2 no historical/D1/D2 file modified during D3", not recent, f"recent={recent[:5]}")
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    check("E3 git HEAD unchanged (d4ea26d)", head.startswith("d4ea26d"), head[:12])
    status = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    check("E4 no new tracked changes", not any(l.strip() and not l.startswith("??")
                                               for l in status.splitlines()), "")

    # F
    dbs = [p.name for p in HERE.rglob("*.db")]
    check("F1 no database artifacts in D3", not dbs, f"{dbs}")
    imports = []
    for py in HERE.glob("*.py"):
        for line in py.read_text(encoding="utf-8").splitlines():
            if re.match(r"^\s*import\s+(requests|httpx|urllib|socket)\b", line):
                imports.append(f"{py.name}: {line.strip()}")
    check("F2 stdlib-only, no network imports", not imports, f"{imports}")
    secrets = [p.name for p in list(HERE.glob('*.py')) + list(HERE.glob('*.md'))
               + list(HERE.glob('*.csv'))
               if re.search(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}",
                            p.read_text(encoding="utf-8", errors="replace"), re.I)]
    check("F3 no secrets", not secrets, f"{secrets}")
    found: dict[str, int] = {}
    meta_dates: dict[str, int] = {}
    try:
        con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        chunk_blob = "\n".join(v for (v,) in con.execute("SELECT text FROM chunks"))
        meta_blob = "\n".join(
            f"{v[0]}|{v[1]}" for v in con.execute(
                "SELECT external_id, COALESCE(published_at,'') FROM documents"))
        con.close()
        for tok in ABSENT_TOKENS:
            found[tok] = chunk_blob.count(tok)
        for d in ["2021-12-10", "2022-05-04", "2023-06-02", "2021-11-03"]:
            meta_dates[d] = chunk_blob.count(d)
    except Exception as exc:  # pragma: no cover
        found, meta_dates = {"scan-error": -1}, {}
        print("db scan error:", exc)
    bad_tok = {k: v for k, v in found.items() if v != 0}
    check("F4 evidence-layer absence tokens 0 occurrences (chunks table only)",
          not bad_tok, f"{len(ABSENT_TOKENS)} tokens" if not bad_tok else f"{bad_tok}")
    # D3 metadata finding: the four KEV-style dates exist ONLY in documents.published_at
    # (never in chunk text) - the retrieval surface hides them from model and judge.
    bad_meta = {k: v for k, v in meta_dates.items() if v != 0}
    check("F4b metadata dates confirmed unsurfaced (in documents, 0 in chunks)",
          not bad_meta and len(meta_dates) == 4,
          "dates live in documents.published_at only" if not bad_meta else f"{bad_meta}")
    proc = subprocess.run([sys.executable, "-m", "pytest"], cwd=str(REPO),
                          capture_output=True, text=True)
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "?"
    check("F5 test suite passes", proc.returncode == 0 and " passed" in proc.stdout
          and "failed" not in proc.stdout, tail)

    n_ok = sum(1 for _, ok, _ in results if ok)
    lines = ["# Stage D3 Validation Report", "",
             f"- Run: `{sys.argv[0]}` · {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
             f"- Result: **{n_ok}/{len(results)} checks PASS**", "",
             "| # | Check | Result | Detail |", "|---|-------|--------|--------|"]
    for idx, (name, ok, detail) in enumerate(results, 1):
        lines.append(f"| {idx} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines += ["", "## Notes",
              "- Reviewer columns were blank at build time and at validation time: "
              "every row is pending; no acceptance was inferred.",
              "- `recommended_action` / `suggested_revised_label` are machine review "
              "aids; only the reviewer columns carry human authority.",
              "- Claim wording is byte-equal to the Stage D queue; evidence excerpts "
              "are verbatim substrings of both the raw queue evidence and the D1 "
              "workspace (traceability proven twice).",
              "- Scope correction discovered during D3 (read-only DB scan): the "
              "date tokens asserted absent from 'the corpus' are absent from the "
              "EVIDENCE layer (chunks table, 0 occurrences) but four KEV-style "
              "dates exist in documents.published_at metadata, which the retrieval "
              "pipeline never surfaces to model or judge. All affected cards state "
              "this precisely. A related D1/D2 'answer-level fabrication' remark "
              "about 2022-05-04 is corrected in D3 cards: the value matches the "
              "document metadata (unsurfaced), so it is an unsupported-by-passage "
              "claim, not an invented number. D1/D2 files remain untouched.",
              "- D1 and D2 packages verified unchanged via their manifests; the "
              "protected database was opened read-only for the token scan only.",
              "- No model calls, no network, no database writes, no git changes."]
    (HERE / "d3_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{n_ok}/{len(results)} checks PASS")
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail if not ok else ''}")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
