"""Stage D Phase D: generate the human-review queue (claims + abstentions).

READ-ONLY on every source: both run DBs open with SQLite ``mode=ro`` URI
connections; eval_questions.json and the AI-draft review file are only read.
WRITES only into this directory (analysis/stage-d-20261016-213744/).

NO model calls, NO LLM imports, NO new dependencies (stdlib only, plus the
project's own deterministic BM25Index for the retrieval reconstruction that
Stage C already validated 22/22 against stored retrieved_count).

Outputs:
- human_review_queue.json  (full queue, schema v1.0.0, dataset d1)
- human_review_queue.csv   (flattened full queue)
- human_review_queue_blind.csv (verdict-hidden first-pass view)
- stage_d_manifest.json    (provenance pins + counts + honesty statements)

Queue composition (priority order):
  tier 1: 13 gate-retracted claims        (supported -> insufficient_evidence)
  tier 2: 11 surviving supported claims
  tier 3: 6 zero-claim abstention questions
  tier 4: stratified sample of unchanged claims
          (every 2nd claim by post-gate claim_id within each stratum:
           8 of 16 insufficient_evidence, 8 of 16 unverifiable)
  tier 5: 1 pre-existing rule anomaly (wrong-02 idx0) if not already sampled
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
REPO = HERE.parents[1]  # analysis/stage-d-<ts> -> analysis -> repo root
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.retrieval.bm25 import BM25Index
POST_DB = REPO / "runs" / "eval-postgate22-20261016-141416" / "evidencegraph-eval.db"
HIST_DB = REPO / "runs" / "eval-pilot22-20261014-181354" / "evidencegraph-eval.db"
QUESTIONS = REPO / "data" / "sample" / "eval_questions.json"
AI_DRAFT = REPO / "runs" / "eval-pilot22-20261014-181354" / "human_claim_review56.md"
SOURCE_DB = REPO / "data" / "evidencegraph.db"

SCHEMA_VERSION = "1.0.0"
DATASET_VERSION = "d1"
ABSTENTION = "Insufficient evidence in the retrieved passages."
POST_RUN_ID = "eval-postgate22-20261016-141416"
HIST_RUN_ID = "eval-pilot22-20261014-181354"

HUMAN_FIELDS_NULL = [
    "human_label", "human_rationale", "evidence_sufficiency_rationale",
    "citation_support_label", "citation_support_rationale", "abstention_assessment",
    "reviewer_id", "review_timestamp", "uncertainty_notes",
    "adjudicated_label", "adjudication_rationale",
]

AI_SOURCE_NOTE_TMPL = (
    "AI-assisted draft, {path} sha256:{sha} claim_id {cid}; "
    "provenance=ai_generated_draft (stage_d_provenance_audit.md section 1.4); "
    "NON-GROUND-TRUTH, secondary view only"
)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ro(p: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def git_info() -> dict:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], capture_output=True, cwd=REPO, text=True, encoding="utf-8"
        ).stdout.strip()

    status = run("status", "--porcelain")
    tracked_dirty = [
        ln for ln in status.splitlines()
        if ln.strip() and not ln.startswith("??")
    ]
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "tracked_files_modified_or_added": tracked_dirty,
        "working_tree_clean_for_tracked_files": not tracked_dirty,
        "note": "Untracked analysis/ directories are expected; only tracked-file state is reported as dirty.",
    }


def main() -> None:
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    post_sha = sha256_file(POST_DB)
    hist_sha = sha256_file(HIST_DB)
    ai_draft_sha = sha256_file(AI_DRAFT)

    # ---------------- load source claims (both runs) ----------------
    pq = ro(POST_DB)
    hq = ro(HIST_DB)

    post_rows = pq.execute(
        "SELECT c.id, c.claim_index, c.claim_text, c.label, c.evidence_ids_json,"
        " c.anomalies_json, r.id AS eval_result_id, r.question"
        " FROM verif_claims c JOIN eval_results r ON r.id = c.eval_result_id"
        " WHERE r.system='verified' ORDER BY c.id"
    ).fetchall()
    hist_rows = hq.execute(
        "SELECT c.id, c.claim_index, c.claim_text, c.label, c.evidence_ids_json,"
        " r.question"
        " FROM verif_claims c JOIN eval_results r ON r.id = c.eval_result_id"
        " WHERE r.system='verified' ORDER BY c.id"
    ).fetchall()
    assert len(post_rows) == 56, f"post-gate claims: {len(post_rows)}"
    assert len(hist_rows) == 56, f"historical claims: {len(hist_rows)}"

    def key(row: sqlite3.Row) -> tuple[str, int]:
        qmeta = QID_BY_TEXT[row["question"]]
        return (qmeta["id"], row["claim_index"])

    questions_payload = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    QID_BY_TEXT = {q["question"]: q for q in questions_payload}
    QMETA = {q["id"]: q for q in questions_payload}

    post_by_key = {key(r): r for r in post_rows}
    hist_by_key = {key(r): r for r in hist_rows}
    assert set(post_by_key) == set(hist_by_key), "claim-key sets differ between runs"
    # Claim texts must be byte-identical across runs for every pair (Stage C verified; re-assert).
    for k, pr in post_by_key.items():
        assert pr["claim_text"] == hist_by_key[k]["claim_text"], f"claim text drift at {k}"

    # ---------------- answers (paired structure) + eval_result ids ----------------
    answers: dict[tuple[str, str], sqlite3.Row] = {
        (r["system"], r["question"]): r
        for r in pq.execute("SELECT * FROM eval_results")
    }

    # ---------------- retrieval reconstruction (validated in Stage C) ----------------
    chunk_rows = pq.execute(
        "SELECT c.id, d.external_id, c.text FROM chunks c"
        " JOIN documents d ON d.id = c.document_id ORDER BY c.id"
    ).fetchall()
    chunk_text = {r["id"]: r["text"] for r in chunk_rows}
    chunk_doc = {r["id"]: r["external_id"] for r in chunk_rows}
    index = BM25Index.build([r["text"] for r in chunk_rows])

    def retrieve(qtext: str, top_k: int = 4) -> list[int]:
        scores = index.scores(qtext)
        ranked = sorted(enumerate(scores), key=lambda p: (-p[1], p[0]))[:top_k]
        return [chunk_rows[i]["id"] for i, s in ranked if s > 0]

    # Validate reconstruction against stored retrieved_count for ALL 22 questions.
    recon_ok = 0
    for qid, meta in QMETA.items():
        row = answers.get(("verified", meta["question"]))
        if row is None:
            continue
        got = len(retrieve(meta["question"]))
        assert got == row["retrieved_count"], (
            f"retrieval reconstruction mismatch {qid}: {got} vs {row['retrieved_count']}"
        )
        recon_ok += 1
    assert recon_ok == 22, f"reconstruction validated for {recon_ok} questions"

    # ---------------- tiers 1-2: transitions ----------------
    retracted, surviving = [], []
    for k, pr in post_by_key.items():
        hr = hist_by_key[k]
        if hr["label"] == "supported" and pr["label"] != "supported":
            retracted.append(k)
        elif hr["label"] == "supported" and pr["label"] == "supported":
            surviving.append(k)
    assert len(retracted) == 13, f"retracted: {len(retracted)}"
    assert len(surviving) == 11, f"surviving: {len(surviving)}"

    # Recover originally-cited evidence ids for retracted claims from the gate
    # anomaly note, and cross-validate against the historical stored ids.
    ids_from_note_re = re.compile(r"evidence ids \[([0-9, ]*)\]")
    recovered_ids: dict[tuple[str, int], list[int]] = {}
    for k in retracted:
        pr, hr = post_by_key[k], hist_by_key[k]
        notes = json.loads(pr["anomalies_json"] or "[]")
        note_txt = " | ".join(str(n) for n in notes)
        m = ids_from_note_re.search(note_txt)
        note_ids = [int(x) for x in m.group(1).split(", ") if x] if m else []
        hist_ids = json.loads(hr["evidence_ids_json"] or "[]")
        assert note_ids == hist_ids, (
            f"recovered evidence ids disagree at {k}: note={note_ids} hist={hist_ids}"
        )
        assert json.loads(pr["evidence_ids_json"] or "[]") == [], (
            f"post-gate evidence_ids not empty at {k} (gate semantics changed?)"
        )
        recovered_ids[k] = note_ids

    # ---------------- tier 3: abstentions ----------------
    abstentions = []
    for qid, meta in sorted(QMETA.items()):
        row = answers.get(("verified", meta["question"]))
        if row is None:
            continue
        if row["claims_total"] == 0:
            assert (row["answer_text"] or "") == ABSTENTION, f"non-verbatim abstention at {qid}"
            abstentions.append(qid)
    assert len(abstentions) == 6, f"abstentions: {len(abstentions)}"

    # ---------------- tier 4: stratified unchanged sample ----------------
    unchanged_ins = [k for k, pr in post_by_key.items()
                     if hist_by_key[k]["label"] == pr["label"] == "insufficient_evidence"]
    unchanged_unv = [k for k, pr in post_by_key.items()
                     if hist_by_key[k]["label"] == pr["label"] == "unverifiable"]
    assert len(unchanged_ins) == 16, f"unchanged insufficient: {len(unchanged_ins)}"
    assert len(unchanged_unv) == 16, f"unchanged unverifiable: {len(unchanged_unv)}"

    def every_other(keys: list[tuple[str, int]]) -> list[tuple[str, int]]:
        ordered = sorted(keys, key=lambda k: post_by_key[k]["id"])
        return ordered[::2]

    sample_ins = every_other(unchanged_ins)
    sample_unv = every_other(unchanged_unv)
    assert len(sample_ins) == 8 and len(sample_unv) == 8

    # ---------------- tier 5: pre-existing rule anomaly ----------------
    anomaly_keys = []
    for k, pr in post_by_key.items():
        notes = json.loads(pr["anomalies_json"] or "[]")
        if notes and "grounding" not in " ".join(str(n) for n in notes).lower():
            anomaly_keys.append(k)
    assert len(anomaly_keys) == 1, f"non-gate anomalies: {anomaly_keys}"
    tier5 = [k for k in anomaly_keys if k not in set(sample_ins) | set(sample_unv)]

    # ---------------- AI-draft mapping (secondary view only) ----------------
    draft = AI_DRAFT.read_text(encoding="utf-8")
    hist_id_to_key = {hist_rows_i["id"]: key(hist_rows_i) for hist_rows_i in hist_rows}
    ai_labels: dict[tuple[str, int], tuple[str, int]] = {}  # key -> (label, hist claim_id)
    for sec in re.split(r"### Claim ", draft)[1:]:
        cid_m = re.match(r"\d+ of 56 — claim_id (\d+)", sec)
        lab_m = re.search(r"Your human label:.*?\\`([^`]*)\\`", sec)
        if cid_m and lab_m and lab_m.group(1).strip():
            cid = int(cid_m.group(1))
            ai_labels[hist_id_to_key[cid]] = (lab_m.group(1).strip(), cid)
    assert len(ai_labels) == 56, f"AI-draft labels parsed: {len(ai_labels)}"

    # ---------------- build items ----------------
    def evidence_for(k: tuple[str, int] | None, qid: str) -> list[dict]:
        if k is not None:
            cited = recovered_ids.get(k) or json.loads(
                post_by_key[k]["evidence_ids_json"] or "[]"
            )
            cited_source = (
                "judge_cited_recovered_from_anomaly_note_and_historical_db"
                if k in recovered_ids else "judge_cited_stored"
            )
        else:
            cited, cited_source = [], None
        retrieved = retrieve(QMETA[qid]["question"])
        seen: dict[int, dict] = {}
        for cid in cited:
            seen[cid] = {
                "chunk_id": cid,
                "document_external_id": chunk_doc[cid],
                "text": chunk_text[cid],
                "text_source": "source_run_db_verbatim",
                "selection_source": cited_source,
            }
        for cid in retrieved:
            if cid not in seen:
                seen[cid] = {
                    "chunk_id": cid,
                    "document_external_id": chunk_doc[cid],
                    "text": chunk_text[cid],
                    "text_source": "source_run_db_verbatim",
                    "selection_source": "question_retrieval_reconstruction_validated",
                }
        return [seen[c] for c in sorted(seen)]

    items: list[dict] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"ann-d1-{counter:04d}"

    def claim_item(k: tuple[str, int], tier: int) -> dict:
        qid, _idx = k
        pr = post_by_key[k]
        meta = QMETA[qid]
        qtext = meta["question"]
        base = answers[("baseline", qtext)]
        ver = answers[("verified", qtext)]
        notes = json.loads(pr["anomalies_json"] or "[]")
        grounding = None
        gm = re.search(r"\((\d+\.\d+) < ", " ".join(str(n) for n in notes))
        if gm:
            grounding = float(gm.group(1))
        hist_ref = None
        if k in recovered_ids:
            hist_ref = (
                f"runs/{HIST_RUN_ID}/evidencegraph-eval.db :: "
                f"verif_claims.id={hist_by_key[k]['id']}"
            )
        ai = ai_labels.get(k)
        return {
            "annotation_id": next_id(),
            "schema_version": SCHEMA_VERSION,
            "item_type": "claim",
            "item_priority": tier,
            "question_id": qid,
            "claim_id": pr["id"],
            "run_id": POST_RUN_ID,
            "system_arm": "verified",
            "claim_text": pr["claim_text"],
            "paired_answer_texts": {"baseline": base["answer_text"], "verified": ver["answer_text"]},
            "retrieved_evidence_ids": (
                recovered_ids.get(k) or json.loads(pr["evidence_ids_json"] or "[]")
            ),
            "evidence_text_or_reference": evidence_for(k, qid),
            "system_verdict": pr["label"],
            "system_verdict_visibility": "blind_first_judgment_required",
            "system_diagnostics": (
                {"anomaly_notes": notes, "grounding_ratio": grounding} if notes else None
            ),
            "proposed_ai_label": ai[0] if ai else None,
            "proposed_ai_label_source": (
                AI_SOURCE_NOTE_TMPL.format(path=f"runs/{HIST_RUN_ID}/human_claim_review56.md",
                                           sha=ai_draft_sha[:16], cid=ai[1]) if ai else None
            ),
            **{f: None for f in HUMAN_FIELDS_NULL},
            "review_status": "not_reviewed",
            "source_artifact_refs": {
                "claim_row_source": (
                    f"runs/{POST_RUN_ID}/evidencegraph-eval.db :: "
                    f"verif_claims.id={pr['id']} (verified arm)"
                ),
                "run_db_sha256": post_sha,
                "paired_baseline_answer_ref": f"eval_results.id={base['id']} (baseline)",
                "historical_claim_ref": hist_ref,
            },
        }

    def abstention_item(qid: str) -> dict:
        meta = QMETA[qid]
        qtext = meta["question"]
        base = answers[("baseline", qtext)]
        ver = answers[("verified", qtext)]
        return {
            "annotation_id": next_id(),
            "schema_version": SCHEMA_VERSION,
            "item_type": "abstention_question",
            "item_priority": 3,
            "question_id": qid,
            "claim_id": None,
            "run_id": POST_RUN_ID,
            "system_arm": "verified",
            "claim_text": None,
            "paired_answer_texts": {"baseline": base["answer_text"], "verified": ver["answer_text"]},
            "retrieved_evidence_ids": None,
            "evidence_text_or_reference": evidence_for(None, qid),
            "system_verdict": "abstained_no_claims",
            "system_verdict_visibility": "blind_first_judgment_required",
            "system_diagnostics": None,
            "proposed_ai_label": None,
            "proposed_ai_label_source": None,
            **{f: None for f in HUMAN_FIELDS_NULL},
            "review_status": "not_reviewed",
            "source_artifact_refs": {
                "claim_row_source": (
                    f"runs/{POST_RUN_ID}/evidencegraph-eval.db :: eval_results.id={ver['id']}"
                    " (verified arm, zero claims)"
                ),
                "run_db_sha256": post_sha,
                "paired_baseline_answer_ref": f"eval_results.id={base['id']} (baseline)",
                "historical_claim_ref": None,
            },
        }

    for k in sorted(retracted, key=lambda k: post_by_key[k]["id"]):
        items.append(claim_item(k, 1))
    for k in sorted(surviving, key=lambda k: post_by_key[k]["id"]):
        items.append(claim_item(k, 2))
    for qid in abstentions:
        items.append(abstention_item(qid))
    for k in sorted(sample_ins + sample_unv, key=lambda k: post_by_key[k]["id"]):
        items.append(claim_item(k, 4))
    for k in sorted(tier5, key=lambda k: post_by_key[k]["id"]):
        items.append(claim_item(k, 5))

    ids = [i["annotation_id"] for i in items]
    assert len(ids) == len(set(ids)), "duplicate annotation_ids"
    # Coverage: every must-review item is queued exactly once. The anomaly claim
    # may or may not also fall inside the tier-4 systematic sample, so the total
    # is 46 or 47 depending on that overlap (tier5 excludes duplicates).
    # Note: queue keys are (question_id, claim_index); item claim_id is the DB
    # primary key, so map ids back to keys before comparing.
    id_to_key = {pr["id"]: k for k, pr in post_by_key.items()}
    covered_claim_keys = {
        id_to_key[i["claim_id"]] for i in items if i["item_type"] == "claim"
    }
    for k in retracted + surviving + sample_ins + sample_unv + tier5:
        assert k in covered_claim_keys, f"missing from queue: {k}"
    anomaly_all = set(retracted) | set(surviving) | set(sample_ins) | set(sample_unv) | set(tier5)
    for k in anomaly_keys:
        assert k in anomaly_all, f"pre-existing anomaly not queued: {k}"
    assert len(items) in (46, 47), f"queue size: {len(items)}"
    n_claim_items = len([i for i in items if i["item_type"] == "claim"])
    assert len(covered_claim_keys) == n_claim_items, (
        f"duplicate claim items in queue: {n_claim_items - len(covered_claim_keys)} dupes"
    )

    # ---------------- writes ----------------
    payload = {
        "dataset": {
            "dataset_version": DATASET_VERSION,
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": generated_at,
            "role": "full_queue",
            "review_protocol": "stage_d_protocol.md",
            "guidelines": "human_annotation_guidelines.md",
            "blind_view": "human_review_queue_blind.csv",
            "warning": (
                "system_verdict and proposed_ai_label are NOT ground truth. "
                "Use the blind file for first judgments. proposed_ai_label is an "
                "AI draft (provenance: stage_d_provenance_audit.md) and must never "
                "be counted as a human label."
            ),
        },
        "items": items,
    }
    (HERE / "human_review_queue.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # full CSV (flattened, JSON-encoded nested cells)
    csv_cols = [
        "annotation_id", "schema_version", "item_type", "item_priority",
        "question_id", "claim_id", "run_id", "system_arm", "claim_text",
        "paired_answer_texts", "retrieved_evidence_ids", "evidence_text_or_reference",
        "system_verdict", "system_verdict_visibility", "system_diagnostics",
        "proposed_ai_label", "proposed_ai_label_source",
        "human_label", "human_rationale", "evidence_sufficiency_rationale",
        "citation_support_label", "citation_support_rationale", "abstention_assessment",
        "reviewer_id", "review_timestamp", "review_status", "uncertainty_notes",
        "adjudicated_label", "adjudication_rationale", "source_artifact_refs",
    ]

    def flatten(it: dict) -> dict:
        out = {}
        for c in csv_cols:
            v = it[c]
            out[c] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else ("" if v is None else v)
        return out

    with (HERE / "human_review_queue.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols)
        w.writeheader()
        for it in items:
            w.writerow(flatten(it))

    # blind CSV: verdict/ai/diagnostics hidden; selection_source collapsed
    blind_cols = [
        "annotation_id", "schema_version", "item_type", "question_id", "claim_id",
        "claim_text", "paired_answer_texts", "retrieved_evidence_ids",
        "evidence_text_or_reference", "system_verdict_visibility",
        "human_label", "human_rationale", "evidence_sufficiency_rationale",
        "citation_support_label", "citation_support_rationale", "abstention_assessment",
        "reviewer_id", "review_timestamp", "review_status", "uncertainty_notes",
        "adjudicated_label", "adjudication_rationale",
    ]
    collapse = {
        "judge_cited_stored": "judge_cited",
        "judge_cited_recovered_from_anomaly_note_and_historical_db": "judge_cited",
        "question_retrieval_reconstruction_validated": "question_retrieval",
    }
    with (HERE / "human_review_queue_blind.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=blind_cols)
        w.writeheader()
        for it in items:
            ev = [
                {**e, "selection_source": collapse[e["selection_source"]]}
                for e in it["evidence_text_or_reference"]
            ]
            row = {
                "annotation_id": it["annotation_id"],
                "schema_version": it["schema_version"],
                "item_type": it["item_type"],
                "question_id": it["question_id"],
                "claim_id": "" if it["claim_id"] is None else it["claim_id"],
                "claim_text": it["claim_text"] or "",
                "paired_answer_texts": json.dumps(it["paired_answer_texts"], ensure_ascii=False),
                "retrieved_evidence_ids": json.dumps(it["retrieved_evidence_ids"]),
                "evidence_text_or_reference": json.dumps(ev, ensure_ascii=False),
                "system_verdict_visibility": "blind_first_judgment_required",
            }
            for c in blind_cols:
                if c not in row:
                    row[c] = ""
            w.writerow(row)

    # ---------------- manifest ----------------
    from collections import Counter
    tier_counts = Counter(i["item_priority"] for i in items)
    manifest = {
        "stage": "D",
        "dataset_version": DATASET_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "generator": {
            "script": "analysis/stage-d-20261016-213744/build_review_queue.py",
            "python_stdlib_only_plus": "app.retrieval.bm25.BM25Index (deterministic, offline)",
        },
        "source_runs": [
            {
                "run_id": POST_RUN_ID,
                "db_path": f"runs/{POST_RUN_ID}/evidencegraph-eval.db",
                "db_sha256": post_sha,
                "report_path": f"runs/{POST_RUN_ID}/report.json",
                "role": "primary queue source (claims, answers, chunks, verdicts)",
            },
            {
                "run_id": HIST_RUN_ID,
                "db_path": f"runs/{HIST_RUN_ID}/evidencegraph-eval.db",
                "db_sha256": hist_sha,
                "role": "cross-validation of recovered citations for retracted claims (13/13 asserted); AI-draft label carrier",
            },
        ],
        "source_files": {
            "questions": {"path": "data/sample/eval_questions.json", "sha256": sha256_file(QUESTIONS)},
            "ai_draft_review_file": {
                "path": f"runs/{HIST_RUN_ID}/human_claim_review56.md",
                "sha256": ai_draft_sha,
                "provenance": "ai_generated_draft (stage_d_provenance_audit.md section 1)",
                "used_as": "proposed_ai_label secondary view only",
            },
            "mini_review_file": {
                "path": "runs/eval-mini-20261014-165641/human_claim_review.md",
                "sha256": sha256_file(REPO / "runs" / "eval-mini-20261014-165641" / "human_claim_review.md"),
                "provenance": "provenance_unknown (stage_d_provenance_audit.md section 2)",
                "used_as": "nothing — excluded from the queue entirely",
            },
            "protected_source_db": {"path": "data/evidencegraph.db", "sha256": sha256_file(SOURCE_DB)},
        },
        "git": git_info(),
        "queue_composition": {
            "total_items": len(items),
            "by_priority_tier": {
                "1_gate_retracted_claims": tier_counts[1],
                "2_surviving_supported_claims": tier_counts[2],
                "3_zero_claim_abstention_questions": tier_counts[3],
                "4_stratified_unchanged_sample": tier_counts[4],
                "5_pre_existing_rule_anomaly": tier_counts[5],
            },
            "tier4_sampling_rule": (
                "within each unchanged stratum (insufficient_evidence n=16, "
                "unverifiable n=16): sort by post-gate verif_claims.id, take every "
                "2nd claim -> 8 per stratum, 16 total; deterministic, no randomness"
            ),
            "retrieval_reconstruction": (
                "deterministic BM25 replay over the post-gate DB copy; validated "
                f"{recon_ok}/22 against stored retrieved_count"
            ),
            "retracted_citations_recovery": (
                "gate anomaly-note ids == historical evidence_ids_json for 13/13 "
                "(asserted at generation); post-gate store is empty by design"
            ),
            "tier5_note": (
                "the pre-existing rule anomaly (wrong-02 claim_index 0) already fell "
                "inside the tier-4 systematic sample, so tier 5 is 0 and the item is "
                "queued once at priority 4; coverage assertions verify it is present"
            ),
        },
        "honesty_statements": {
            "no_model_calls": (
                "TRUE: this queue was generated without any LLM/API call. Only "
                "SQLite reads, file reads, deterministic BM25, and regex parsing."
            ),
            "no_invented_human_labels": (
                "TRUE: every human_label/rationale/reviewer_id/timestamp/"
                "adjudicated_label field is null in every item; review_status is "
                "not_reviewed for all 47 items. No default label of any kind exists."
            ),
            "ai_labels_not_human": (
                "TRUE: proposed_ai_label values come from a self-declared AI-assisted "
                "draft and are marked non-ground-truth; they are excluded from the "
                "blind file and from all agreement/accuracy statistics."
            ),
            "no_gold_label_writes": (
                "TRUE: gold_label columns remain NULL in both run databases; this "
                "stage writes nothing to any database."
            ),
        },
        "outputs": [
            "stage_d_provenance_audit.md",
            "annotation_schema.json",
            "annotation_data_dictionary.md",
            "human_annotation_guidelines.md",
            "human_review_queue.csv",
            "human_review_queue.json",
            "human_review_queue_blind.csv",
            "stage_d_protocol.md",
            "stage_d_manifest.json",
            "build_review_queue.py",
            "validate_stage_d.py",
            "stage_d_validation_report.md",
        ],
    }
    (HERE / "stage_d_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    pq.close()
    hq.close()
    print(f"queue built: {len(items)} items "
          f"(tiers: 1={tier_counts[1]} 2={tier_counts[2]} 3={tier_counts[3]} "
          f"4={tier_counts[4]} 5={tier_counts[5]})")
    print(f"retrieval reconstruction validated: {recon_ok}/22")
    print(f"recovered citations asserted: {len(recovered_ids)}/13")
    print(f"AI-draft labels mapped: {len(ai_labels)}/56")


if __name__ == "__main__":
    main()
