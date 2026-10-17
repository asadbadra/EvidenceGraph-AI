"""Stage C comparative analysis: historical pre-gate pilot vs Stage B post-gate run.

READ-ONLY with respect to every source artifact:
- Both run databases are opened with SQLite ``mode=ro`` URI connections.
- Historical runs, source DB, prompts, labels, and outputs are never written.
- All outputs are written into THIS directory only (analysis/stage-c-20261016).

No model calls: the only non-sqlite imports are deterministic project modules
(BM25 index, claim extraction), used exactly as the pipeline used them.

Outputs (all machine-readable):
- question_level_comparison.csv
- claim_transition_matrix.csv
- retracted_claims_13.csv
- supported_claims_11.csv
- anomaly_analysis.csv
- abstention_analysis.json
- citation_comparison.json
- resource_comparison.json
- input_verification.json
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from app.retrieval.bm25 import BM25Index
from app.verification.claims import CITATION_PATTERN, extract_claims

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
HIST_DB = REPO / "runs" / "eval-pilot22-20261014-181354" / "evidencegraph-eval.db"
HIST_REPORT = REPO / "runs" / "eval-pilot22-20261014-181354" / "report.json"
NEW_DB = REPO / "runs" / "eval-postgate22-20261016-141416" / "evidencegraph-eval.db"
NEW_REPORT = REPO / "runs" / "eval-postgate22-20261016-141416" / "report.json"
NEW_MANIFEST = REPO / "runs" / "eval-postgate22-20261016-141416" / "manifest.json"
QUESTIONS = REPO / "data" / "sample" / "eval_questions.json"

ABSTENTION = "Insufficient evidence in the retrieved passages."

# Analyst provisional categorization for the six zero-claim abstentions, tied to
# each question's declared category (data/sample/eval_questions.json) and the
# deterministic corpus check. These are NOT gold labels and NOT model output;
# they are documented hypotheses for human review in Stage D.
PROVISIONAL_ABSTENTION_REVIEW = {
    # not_in_corpus: question asks for a value the catalog does not carry.
    # The CVSS score string "10.0" is absent from every chunk; abstention is
    # the designed behavior for a question whose answer is outside the corpus.
    "absent-01": "appropriate_abstention_likely",
    # not_in_corpus: the endpoint count "2500" is absent; the corpus describes
    # the MOVEit vulnerability but not impact scale.
    "absent-02": "appropriate_abstention_likely",
    # not_in_corpus: the KB number "KB5004236" is absent; chunk 6 covers the
    # CVE but not Microsoft's patch article id.
    "absent-04": "appropriate_abstention_likely",
    # non_factual: a normative "should" question. Corpus contains no
    # prioritization guidance; gold label for the claim is "unverifiable".
    # Abstention is defensible; whether abstention vs an explicit "this is an
    # opinion" response is preferable is a product question for human review.
    "opinion-02": "appropriate_abstention_likely_opinion_question",
    # plausible_but_absent: the version string "1.0.2g" is absent; the corpus
    # covers CVE-2014-0160 (Heartbleed) but not this specific hotfix version.
    "plausible-02": "appropriate_abstention_likely",
    # plausible_but_absent: the catalog does not contain CVE-2021-45046; gold
    # label for the claim "CVE-2021-45046 is present in the catalog" is
    # "contradicted" (by absence). The model abstained ("insufficient
    # evidence") rather than asserting absence. A strict closed-world catalog
    # assumption could support a "contradicted" verdict instead; this is the
    # most interesting abstention case for human review.
    "plausible-04": "appropriate_abstention_but_gold_expects_contradicted_review_priority",
}


def _provisional_category(
    qid: str, category: str, value_tokens: list, value_missing: list
) -> str:
    """Deterministic category with documented analyst overrides per question."""
    if qid in PROVISIONAL_ABSTENTION_REVIEW:
        return PROVISIONAL_ABSTENTION_REVIEW[qid]
    if value_tokens and value_missing:
        return "appropriate_abstention_likely"
    return "requires_human_review"


def ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def qid_map() -> tuple[dict, dict]:
    payload = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    by_text = {q["question"]: q for q in payload}
    return by_text, {q["id"]: q for q in payload}


def load_run(con: sqlite3.Connection) -> dict:
    answers = {
        (r["system"], r["question"]): r
        for r in con.execute("SELECT * FROM eval_results")
    }
    claims = con.execute(
        "SELECT r.system, r.question, c.claim_index, c.claim_text, c.label,"
        " c.evidence_ids_json, c.rationale, c.anomalies_json, c.gold_label"
        " FROM verif_claims c JOIN eval_results r ON r.id = c.eval_result_id"
    ).fetchall()
    return {"answers": answers, "claims": claims}


def verdict_counts(claim_rows) -> dict:
    c = Counter(r["label"] for r in claim_rows)
    return {
        "supported": c.get("supported", 0),
        "contradicted": c.get("contradicted", 0),
        "insufficient_evidence": c.get("insufficient_evidence", 0),
        "unverifiable": c.get("unverifiable", 0),
        "total": sum(c.values()),
    }


def main() -> None:
    by_text, by_id = qid_map()
    hist_report = json.loads(HIST_REPORT.read_text(encoding="utf-8"))
    new_report = json.loads(NEW_REPORT.read_text(encoding="utf-8"))
    new_manifest = json.loads(NEW_MANIFEST.read_text(encoding="utf-8"))

    hist = load_run(ro(HIST_DB))
    new = load_run(ro(NEW_DB))

    # ---------------- input verification ----------------
    # NOTE: answers is keyed by (system, question) -> Row; iterate .values().
    hist_ids = sorted(
        by_text[r["question"]]["id"]
        for r in hist["answers"].values() if r["system"] == "verified"
    )
    new_ids = sorted(
        by_text[r["question"]]["id"]
        for r in new["answers"].values() if r["system"] == "verified"
    )
    manifest_ids = sorted(new_manifest["configuration"]["question_ids"])
    expected_excluded = ["direct-02", "wrong-04"]

    hist_tally = verdict_counts(
        [r for r in hist["claims"] if r["system"] == "verified"]
    )
    new_tally = verdict_counts(
        [r for r in new["claims"] if r["system"] == "verified"]
    )
    hist_rep = hist_report["per_system"]["verified"]
    new_rep = new_report["per_system"]["verified"]

    def rep_match(rep, tally) -> dict:
        return {
            "supported": rep["supported"] == tally["supported"],
            "contradicted": rep["contradicted"] == tally["contradicted"],
            "insufficient_evidence": rep["insufficient_evidence"] == tally["insufficient_evidence"],
            "unverifiable": rep["unverifiable"] == tally["unverifiable"],
            "claims_total": rep["claims_total"] == tally["total"],
        }

    input_verification = {
        "hist_question_ids_count": len(hist_ids),
        "new_question_ids_count": len(new_ids),
        "id_sets_identical": hist_ids == new_ids,
        "manifest_matches_db_ids": manifest_ids == new_ids,
        "excluded_from_24": sorted(
            set(by_id) - set(new_ids)
        ) == expected_excluded,
        "hist_report_vs_db": rep_match(hist_rep, hist_tally),
        "new_report_vs_db": rep_match(new_rep, new_tally),
        "hist_tally_from_db": hist_tally,
        "new_tally_from_db": new_tally,
        "hist_missing_git_provenance": "git" not in hist_report.get("conditions", {}),
        "hist_conditions": hist_report["conditions"],
        "new_git": new_manifest["git"],
        "new_provider": new_manifest["provider"],
        "new_configuration": new_manifest["configuration"],
        "gold_labels_nonnull_new": sum(
            1 for r in new["claims"] if r["gold_label"] is not None
        ),
        "report_status": {
            "hist": hist_report["status"],
            "new": new_report["status"],
        },
    }
    assert all(input_verification["hist_report_vs_db"].values()), "hist mismatch"
    assert all(input_verification["new_report_vs_db"].values()), "new mismatch"
    assert input_verification["id_sets_identical"], "id sets differ"
    assert input_verification["manifest_matches_db_ids"], "manifest ids differ"
    assert input_verification["excluded_from_24"], "exclusions differ"
    (OUT / "input_verification.json").write_text(
        json.dumps(input_verification, indent=2), encoding="utf-8"
    )

    # ---------------- question-level table ----------------
    questions = sorted(
        {by_text[r["question"]]["id"] for r in new["answers"].values()
         if r["system"] == "verified"}
    )
    qrows = []
    for qid in questions:
        qtext = by_id[qid]["question"]
        category = by_id[qid]["category"]
        hn = hist["answers"].get(("baseline", qtext))
        hv = hist["answers"].get(("verified", qtext))
        nn = new["answers"].get(("baseline", qtext))
        nv = new["answers"].get(("verified", qtext))
        hv_claims = [r for r in hist["claims"]
                     if r["system"] == "verified" and r["question"] == qtext]
        nv_claims = [r for r in new["claims"]
                     if r["system"] == "verified" and r["question"] == qtext]
        h_cnt, n_cnt = verdict_counts(hv_claims), verdict_counts(nv_claims)
        n_transitions = sum(
            1 for h, n in zip(
                sorted(hv_claims, key=lambda r: r["claim_index"]),
                sorted(nv_claims, key=lambda r: r["claim_index"]),
            ) if h["label"] != n["label"]
        ) if len(hv_claims) == len(nv_claims) else -1
        qrows.append({
            "question_id": qid,
            "category": category,
            "baseline_answer_new": ABSTENTION if (nn["answer_text"] or "") == ABSTENTION else "answered",
            "verified_answer_new": ABSTENTION if (nv["answer_text"] or "") == ABSTENTION else "answered",
            "answer_identical_hist_vs_new_baseline": (hn["answer_text"] == nn["answer_text"]),
            "answer_identical_hist_vs_new_verified": (hv["answer_text"] == nv["answer_text"]),
            "retrieved_hist": hv["retrieved_count"],
            "retrieved_new": nv["retrieved_count"],
            "claims_hist": h_cnt["total"],
            "claims_new": n_cnt["total"],
            "supported_hist": h_cnt["supported"],
            "supported_new": n_cnt["supported"],
            "contradicted_hist": h_cnt["contradicted"],
            "contradicted_new": n_cnt["contradicted"],
            "insufficient_hist": h_cnt["insufficient_evidence"],
            "insufficient_new": n_cnt["insufficient_evidence"],
            "unverifiable_hist": h_cnt["unverifiable"],
            "unverifiable_new": n_cnt["unverifiable"],
            "verdict_changes": n_transitions,
            "baseline_citations_new": nn["citation_count"],
            "verified_citations_new": nv["citation_count"],
            "baseline_invalid_markers_new": nn["invalid_marker_count"],
            "verified_invalid_markers_new": nv["invalid_marker_count"],
            "verified_anomalies_new": nv["with_anomalies"],
            "verified_anomalies_hist": hv["with_anomalies"],
            "per_question_latency": "unavailable (not stored)",
        })
    with (OUT / "question_level_comparison.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=list(qrows[0]))
        w.writeheader()
        w.writerows(qrows)

    # ---------------- claim transition matrix ----------------
    def keyed(claims, system="verified"):
        return {
            (by_text[r["question"]]["id"], r["claim_index"]): r
            for r in claims if r["system"] == system
        }

    hkey, nkey = keyed(hist["claims"]), keyed(new["claims"])
    assert set(hkey) == set(nkey), "claim key sets differ between runs"
    transitions = Counter()
    trans_rows = []
    for k in sorted(hkey):
        h, n = hkey[k], nkey[k]
        transitions[(h["label"], n["label"])] += 1
        trans_rows.append({
            "question_id": k[0],
            "claim_index": k[1],
            "claim_text": n["claim_text"],
            "hist_label": h["label"],
            "new_label": n["label"],
            "changed": h["label"] != n["label"],
            "claim_text_identical": h["claim_text"] == n["claim_text"],
            "new_anomaly_notes": n["anomalies_json"],
            "hist_anomaly_notes": h["anomalies_json"],
        })
    with (OUT / "claim_transition_matrix.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=list(trans_rows[0]))
        w.writeheader()
        w.writerows(trans_rows)

    # ---------------- retracted / surviving supported claims ----------------
    # Evidence text: chunk texts stored in the NEW run's disposable copy.
    con_new = ro(NEW_DB)
    chunk_text = {r["id"]: r["text"] for r in con_new.execute(
        "SELECT id, text FROM chunks"
    )}
    gate_note_re = re.compile(r"\((\d+(?:\.\d+)?) < (\d+(?:\.\d+)?)\)")

    retracted, surviving = [], []
    ids_from_note_re = re.compile(r"evidence ids \[([0-9, ]*)\]")
    for row in trans_rows:
        if row["hist_label"] == "supported" and row["new_label"] != "supported":
            n = nkey[(row["question_id"], row["claim_index"])]
            notes = json.loads(n["anomalies_json"] or "[]")
            note_txt = " | ".join(str(x) for x in notes)
            m = gate_note_re.search(note_txt)
            # The gate rebuilds the verdict as an abstention with NO evidence
            # ids (make_evidence_verdict default), so the post-gate
            # evidence_ids_json is empty by design. The originally-cited ids
            # survive in the anomaly-note text and in the historical run's
            # stored evidence_ids_json; we recover both and cross-check.
            note_ids = ids_from_note_re.search(note_txt)
            ids_from_note = (
                [int(x) for x in note_ids.group(1).split(", ") if x]
                if note_ids else []
            )
            h = hkey[(row["question_id"], row["claim_index"])]
            hist_ids = json.loads(h["evidence_ids_json"] or "[]")
            ids_agree = ids_from_note == hist_ids
            eids = ids_from_note or hist_ids
            ev_texts = {
                eid: chunk_text.get(eid, "[chunk id not in copy]")[:400]
                for eid in eids
            }
            retracted.append({
                "question_id": row["question_id"],
                "claim_index": row["claim_index"],
                "claim_text": row["claim_text"],
                "new_label": row["new_label"],
                "evidence_ids_from_anomaly_note": json.dumps(ids_from_note),
                "evidence_ids_from_hist_run": json.dumps(hist_ids),
                "evidence_ids_agree": ids_agree,
                "post_gate_evidence_ids_json_empty_by_design": (
                    json.loads(n["evidence_ids_json"] or "[]") == []
                ),
                "grounding_ratio": m.group(1) if m else "",
                "grounding_bar": m.group(2) if m else "",
                "gate_reason": note_txt,
                "evidence_text_by_id": json.dumps(ev_texts, ensure_ascii=False),
                "judge_rationale": n["rationale"],
            })
        elif row["hist_label"] == "supported" and row["new_label"] == "supported":
            n = nkey[(row["question_id"], row["claim_index"])]
            surviving.append({
                "question_id": row["question_id"],
                "claim_index": row["claim_index"],
                "claim_text": row["claim_text"],
                "label": n["label"],
                "evidence_ids": n["evidence_ids_json"],
                "judge_rationale": n["rationale"],
                "anomaly_notes": n["anomalies_json"],
            })
    for fname, rows in (
        ("retracted_claims_13.csv", retracted),
        ("supported_claims_11.csv", surviving),
    ):
        with (OUT / fname).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    # ---------------- anomaly analysis (14 post-gate) ----------------
    anomaly_rows = []
    for k in sorted(nkey):
        n = nkey[k]
        notes = json.loads(n["anomalies_json"] or "[]")
        if not notes:
            continue
        note_txt = " | ".join(str(x) for x in notes)
        is_gate = "grounding" in note_txt.lower()
        anomaly_rows.append({
            "question_id": k[0],
            "claim_index": k[1],
            "new_label": n["label"],
            "hist_label": hkey[k]["label"],
            "anomaly_class": "grounding_gate_retraction" if is_gate
                             else "pre_existing_supported_requires_evidence_rule",
            "notes": note_txt,
            "hist_anomaly_same_claim": hkey[k]["anomalies_json"],
        })
    with (OUT / "anomaly_analysis.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=list(anomaly_rows[0]))
        w.writeheader()
        w.writerows(anomaly_rows)

    # ---------------- six zero-claim abstentions ----------------
    # Deterministic reconstruction of retrieval: identical BM25Index, identical
    # chunk ordering (chunk.id), identical selection rule as Retriever.retrieve.
    rows = con_new.execute(
        "SELECT c.id, c.text FROM chunks c ORDER BY c.id"
    ).fetchall()
    texts = [r["text"] for r in rows]
    index = BM25Index.build(texts)

    def retrieve(query: str, top_k: int = 4) -> list[dict]:
        scores = index.scores(query)
        ranked = sorted(enumerate(scores), key=lambda p: (-p[1], p[0]))[:top_k]
        return [
            {"chunk_id": rows[i]["id"], "score": round(s, 4), "text": rows[i]["text"]}
            for i, s in ranked if s > 0
        ]

    # Reconstruction validation against stored retrieved_count for all questions.
    recon_ok, recon_bad = 0, []
    for qid in questions:
        qtext = by_id[qid]["question"]
        expected = new["answers"][("verified", qtext)]["retrieved_count"]
        got = len(retrieve(qtext))
        if got == expected:
            recon_ok += 1
        else:
            recon_bad.append({"question_id": qid, "expected": expected, "got": got})

    abstentions = []
    for qid in questions:
        qtext = by_id[qid]["question"]
        nv = new["answers"][("verified", qtext)]
        if nv["claims_total"] != 0:
            continue
        hn = hist["answers"][("verified", qtext)]
        gold = by_id[qid].get("gold_claims", [])
        # Deterministic replay of claim extraction on the STORED answer text.
        extraction = extract_claims(nv["answer_text"] or "")
        # Lexical sufficiency probe: term overlap between gold claim and corpus.
        gold_text = " ".join(str(g.get("text", g)) if isinstance(g, dict) else str(g)
                              for g in gold)
        gold_terms = {
            t for t in re.findall(r"[a-z0-9-]{4,}", gold_text.lower())
            if t not in {"with", "from", "that", "this", "were", "been"}
        }
        corpus = " ".join(texts).lower()
        corpus_hits = sorted(t for t in gold_terms if t in corpus)
        # Answer-bearing value tokens: digits (10.0, 2500), KB ids, versions.
        # Topical subject overlap (e.g. the CVE id itself, "endpoints") does
        # NOT imply the answer is present; only value tokens carry it.
        value_tokens = re.findall(
            r"\b\d+(?:\.\d+)*\b|\bkb\d+\b|\bcve-\d{4}-\d+\b", gold_text.lower()
        )
        value_tokens = [v for v in value_tokens if not v.startswith("cve-")]
        value_hits = [v for v in value_tokens if v in corpus]
        value_missing = [v for v in value_tokens if v not in corpus]
        abstentions.append({
            "question_id": qid,
            "category": by_id[qid]["category"],
            "question": qtext,
            "stored_answer_new": nv["answer_text"],
            "stored_answer_hist": hn["answer_text"],
            "answers_identical_across_runs": nv["answer_text"] == hn["answer_text"],
            "extraction_replay_claims": len(extraction.claims),
            "extraction_replay_skipped": [
                {"text": s.text, "reason": s.reason} for s in extraction.skipped
            ],
            "reconstructed_retrieval": retrieve(qtext),
            "gold_claims": gold,
            "gold_terms": sorted(gold_terms),
            "gold_terms_found_in_corpus": corpus_hits,
            "topical_overlap_note": (
                "gold_terms_found_in_corpus reflects topical subject overlap only "
                "(e.g. the CVE id itself, 'endpoints'); it is NOT evidence the "
                "answer is present. Answer-bearing value tokens are listed below."
            ),
            "answer_value_tokens": value_tokens,
            "answer_value_tokens_found": value_hits,
            "answer_value_tokens_missing": value_missing,
            "corpus_contains_answer_content": bool(value_tokens) and not value_missing,
            "provisional_review_category": _provisional_category(
                qid, by_id[qid]["category"], value_tokens, value_missing
            ),
            "note": (
                "Provisional review category from deterministic lexical probe only; "
                "not a gold label. Human answerability review required (Stage D)."
            ),
        })
    (OUT / "abstention_analysis.json").write_text(
        json.dumps(abstentions, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---------------- citation comparison ----------------
    def citation_block(con, which_report, claims, answers):
        # answers is keyed by (system, question) -> Row; iterate .values().
        base = [r for r in answers.values() if r["system"] == "baseline"]
        ver = [r for r in answers.values() if r["system"] == "verified"]
        base_cites = sum(r["citation_count"] for r in base)
        ver_cites = sum(r["citation_count"] for r in ver)
        base_inv = sum(r["invalid_marker_count"] for r in base)
        ver_inv = sum(r["invalid_marker_count"] for r in ver)
        # claims carrying citation markers (descriptive only)
        vclaims = [c for c in claims if c["system"] == "verified"]
        with_markers = sum(1 for c in vclaims if CITATION_PATTERN.search(c["claim_text"]))
        with_eids = sum(
            1 for c in vclaims
            if json.loads(c["evidence_ids_json"] or "[]")
        )
        return {
            "baseline_citation_markers": base_cites,
            "verified_citation_markers": ver_cites,
            "baseline_invalid_markers": base_inv,
            "verified_invalid_markers": ver_inv,
            "invalid_marker_rate": which_report["citation_quality"]["verified"]["invalid_marker_rate"],
            "verified_citations_support_label": which_report["citation_quality"]["verified"]["verified_citations"],
            "claims_with_citation_markers": with_markers,
            "claims_total": len(vclaims),
            "claims_with_judge_evidence_ids": with_eids,
            "unavailable_fields": [
                "verified_citations (per-citation support labels: null in report and absent from schema)",
                "citation precision: NOT COMPUTABLE - no stored label says whether a marker supports its claim",
                "claim-to-citation support rate: NOT COMPUTABLE for the same reason",
            ],
        }

    citation_comparison = {
        "historical": citation_block(ro(HIST_DB), hist_report, hist["claims"], hist["answers"]),
        "post_gate": citation_block(ro(NEW_DB), new_report, new["claims"], new["answers"]),
        "note": (
            "Only stored counts are reported. Citation precision and per-citation "
            "support require human labels that do not exist; neither report nor "
            "schema stores them. Do not read marker counts as support rates."
        ),
    }
    (OUT / "citation_comparison.json").write_text(
        json.dumps(citation_comparison, indent=2), encoding="utf-8"
    )

    # ---------------- resource comparison ----------------
    # NOTE the two reports use different usage schemas: the historical report
    # aggregates per system arm (usage.summaries.baseline / .verified where
    # "verified" includes generation + judge calls), the tracked runner
    # aggregates overall (usage.summary) and splits by purpose.
    hs = hist_report["usage"]["summaries"]
    nu = new_report["usage"]["summary"]
    h_total_tokens = (
        hs["baseline"]["total_tokens"] + hs["verified"]["total_tokens"]
        if hs["baseline"]["total_tokens"] is not None
        and hs["verified"]["total_tokens"] is not None else None
    )
    resource = {
        "historical": {
            "calls_total": hs["baseline"]["calls"] + hs["verified"]["calls"],
            "calls_failed": hs["baseline"]["calls_failed"] + hs["verified"]["calls_failed"],
            "calls_by_arm_schema_note": (
                "'verified' arm combines answer generation (22) + judging (56) = 78; "
                "per-purpose split not recorded by the historical script"
            ),
            "calls_by_arm": {
                "baseline": hs["baseline"]["calls"],
                "verified_incl_judge": hs["verified"]["calls"],
            },
            "elapsed_s": hist_report["elapsed_s"],
            "tokens": {
                "input": hs["baseline"]["total_input_tokens"] + hs["verified"]["total_input_tokens"],
                "output": hs["baseline"]["total_output_tokens"] + hs["verified"]["total_output_tokens"],
                "total": h_total_tokens,
                "records_with_usage": hs["baseline"]["records_with_usage"] + hs["verified"]["records_with_usage"],
                "source": "provider-reported (UsageAwareOpenAIClient in one-off script)",
            },
            "cost_usd": None,
            "cost_note": hs["baseline"]["cost_note"],
        },
        "post_gate": {
            "calls_total": nu["calls"],
            "calls_failed": nu["calls_failed"],
            "calls_by_purpose": new_report["usage"]["calls_by_purpose"],
            "elapsed_s": new_report["elapsed_s"],
            "tokens": {
                "input": nu["total_input_tokens"],
                "output": nu["total_output_tokens"],
                "total": nu["total_tokens"],
                "records_with_usage": nu["records_with_usage"],
                "records_without_usage": nu["records_without_usage"],
                "source": "UNAVAILABLE - tracked runner uses OpenAICompatibleClient "
                          "which discards the response usage block "
                          "(app/verification/runner.py::_make_llm_for_run). "
                          "Recorded as unavailable, never zero.",
            },
            "cost_usd": nu["total_cost_usd"],
            "cost_note": nu["cost_note"],
        },
        "explicitly_not_inferred": (
            "Post-gate token counts must NOT be estimated from the historical run: "
            "different run, no measurement exists."
        ),
        "per_question_latency": "not stored by either run; per-call latency not persisted",
    }
    (OUT / "resource_comparison.json").write_text(
        json.dumps(resource, indent=2), encoding="utf-8"
    )

    # ---------------- console summary ----------------
    print("== input verification: all assertions passed ==")
    print(f"paired questions: {len(questions)}; identical across runs: "
          f"{input_verification['id_sets_identical']}")
    print(f"hist tally: {hist_tally}")
    print(f"new  tally: {new_tally}")
    print("transitions:")
    for (h, n), c in sorted(transitions.items()):
        flag = "" if h == n else "  <-- changed"
        print(f"  {h} -> {n}: {c}{flag}")
    print(f"retracted claims: {len(retracted)}; surviving supported: {len(surviving)}")
    print(f"anomalies: {len(anomaly_rows)} "
          f"({sum(1 for a in anomaly_rows if a['anomaly_class'].startswith('grounding'))} gate, "
          f"{sum(1 for a in anomaly_rows if not a['anomaly_class'].startswith('grounding'))} pre-existing rule)")
    print(f"abstentions: {len(abstentions)}")
    print(f"retrieval reconstruction: {recon_ok}/{len(questions)} match stored counts; "
          f"mismatches: {recon_bad}")
    print(f"answer identity baseline: "
          f"{sum(1 for r in qrows if r['answer_identical_hist_vs_new_baseline'])}/{len(qrows)}; "
          f"verified: {sum(1 for r in qrows if r['answer_identical_hist_vs_new_verified'])}/{len(qrows)}")
    print(f"retrieval parity hist vs new: "
          f"{sum(1 for r in qrows if r['retrieved_hist'] == r['retrieved_new'])}/{len(qrows)}")


if __name__ == "__main__":
    main()
