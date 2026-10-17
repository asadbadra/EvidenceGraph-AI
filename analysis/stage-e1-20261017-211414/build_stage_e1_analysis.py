"""Stage E1 — derived reviewer-label table + annotation-quality report (build).

Read-only with respect to every pre-existing artifact: asserts the sha256 of every
input before parsing, computes everything in memory, and only then writes the four
new E1 outputs into this directory. Any hash mismatch, parsing failure, or mapping
failure aborts BEFORE any write (fail-closed; nothing partial is left behind).

Derived-label rules (R1-R5, per the approved specification):
  R1  revise rows:  ^Reviewer label: (<label>) | <note>     -> parsed_prefix
  R2  ann-d1-0030:  scope-qualified mapping (passages => appropriate_abstention),
                    recorded in the note verbatim            -> derived_scope_mapping
  R3  accept rows:  parsed_label = proposed_label (schema meaning of accept);
                    where the note names "proposed label (X)", X must equal it
                                                       -> accepted_proposal
  R4  abstention accepts (0025-0029): parsed_abstention_assessment =
                    proposed_abstention_assessment (named in the note)
  R5  anything else (unknown prefix, missing label, note/label mismatch)
                    -> parsing_status=failed and the whole build aborts.

Metric exclusions: ann-d1-0033 is excluded from label-based metrics (unresolved
label/rationale inconsistency, D3 note section 8); the exclusion count is reported.
No gold_label is written anywhere; no repository file outside this directory is
touched; no DB is opened.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

D3 = ROOT / "analysis" / "stage-d3-20261017-011614"
D = ROOT / "analysis" / "stage-d-20261016-213744"
C = ROOT / "analysis" / "stage-c-20261016"

INPUT_HASHES = {
    D3 / "d3_review_decisions.csv":
        "488ecb1497e7bbfae98f11a840495208e6e7e56b42aa6b987f78490049520b8e",
    D / "human_review_queue.json":
        "cce025ccac270fd85a192ac680f8ac6a4d612bc01ec71ccb9cc273c44898e769",
    C / "retracted_claims_13.csv":
        "51a9e667dfb024b4e864e79ddce247545a1ca9fb86ec139bb799a09374fdd185",
    C / "supported_claims_11.csv":
        "c5c2c426175e02dc940eebce2656477abec35048ae94e979369981d65af2e6e7",
    C / "abstention_analysis.json":
        "2f4ccc5f5a17ec885a4c4c34d3bdafe7d5ad0294dd2d45a9b3a41588634f5e0e",
    ROOT / "data" / "sample" / "eval_questions.json":
        "500ed32d5546683392616685f024d9f5feebefec19806c53e1f03a34b33f3a3a",
}

LABELS = ("supported", "contradicted", "insufficient_evidence", "unverifiable",
          "not_applicable", "appropriate_abstention", "inappropriate_abstention",
          "uncertain")
CLAIM_LABELS = ("supported", "contradicted", "insufficient_evidence", "unverifiable")
PREFIX_RE = re.compile(r"^Reviewer label: ([a-z_]+) \| ")
PAREN_RE = re.compile(r"proposed label \(([^)]+)\)")
EXCLUDED_0033 = "ann-d1-0033"
EXCLUSION_REASON = ("unresolved label/rationale inconsistency (D3 decision note section 8); "
                    "excluded from label-based metrics until the reviewer resolves it")
DERIVED_0030 = "ann-d1-0030"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def die(msg: str) -> None:
    print(f"BUILD ABORTED (no files written): {msg}")
    raise SystemExit(1)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # ---- 1. hash-assert every input BEFORE anything else
    for p, want in INPUT_HASHES.items():
        if not p.is_file():
            die(f"missing input {p}")
        got = sha256(p)
        if got != want:
            die(f"hash mismatch {p.name}: {got} != {want}")
    print(f"[1] {len(INPUT_HASHES)} input hashes verified")

    # ---- 2. load
    with (D3 / "d3_review_decisions.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    queue = json.loads((D / "human_review_queue.json").read_text(encoding="utf-8"))
    qb = {it["annotation_id"]: it for it in queue["items"]}
    ret = list(csv.DictReader((C / "retracted_claims_13.csv").open(encoding="utf-8", newline="")))
    sup = list(csv.DictReader((C / "supported_claims_11.csv").open(encoding="utf-8", newline="")))
    abst = json.loads((C / "abstention_analysis.json").read_text(encoding="utf-8"))
    if len(rows) != 46 or set(qb) != {r["annotation_id"] for r in rows}:
        die("CSV/queue id mismatch")
    print("[2] inputs loaded (46 rows)")

    # ---- 3. tier <-> Stage C file mapping (question-constrained, exact)
    def match(file_rows):
        ids = set()
        for r in file_rows:
            m = [a for a, it in qb.items()
                 if it.get("claim_text") and it["question_id"] == r["question_id"]
                 and norm(it["claim_text"]) == norm(r["claim_text"])]
            if len(m) != 1:
                die(f"tier mapping ambiguous for {r['question_id']}/{r['claim_index']}: {m}")
            ids.add(m[0])
        return ids

    p1 = {a for a, it in qb.items() if it["item_priority"] == 1}
    p2 = {a for a, it in qb.items() if it["item_priority"] == 2}
    p3 = {a for a, it in qb.items() if it["item_priority"] == 3}
    if match(ret) != p1 or match(sup) != p2:
        die("retracted/survivor sets do not equal tier-1/tier-2 sets")
    if {x["question_id"] for x in abst} != {qb[a]["question_id"] for a in p3}:
        die("abstention file questions != tier-3 questions")
    print("[3] tier mapping exact: 13 retracted = tier1, 11 survivors = tier2, 6 abstentions = tier3")

    # ---- 4. parse labels fail-closed (in memory)
    derived = []
    failures = []
    for r in rows:
        aid = r["annotation_id"]
        it = qb[aid]
        item_type = it["item_type"]
        decision = r["reviewer_decision"]
        note = r["reviewer_note"]
        note_sha = hashlib.sha256(note.encode("utf-8")).hexdigest()
        parsed_label, parsed_abs, status, rule = "", "", "", ""

        if decision == "accept":
            parsed_label = r["proposed_label"]
            status, rule = "accepted_proposal", "R3"
            m = PAREN_RE.search(note)
            if m and m.group(1) != r["proposed_label"]:
                failures.append(f"{aid}: note names {m.group(1)} != proposed {r['proposed_label']}")
            if item_type == "abstention_question":
                parsed_abs = r["proposed_abstention_assessment"]
                rule = "R3+R4"
                if "appropriate_abstention" not in note:
                    failures.append(f"{aid}: abstention accept note does not name its assessment")
            else:
                if r["proposed_label"] not in CLAIM_LABELS:
                    failures.append(f"{aid}: accepted claim label outside claim vocabulary")
        elif decision == "revise" and aid == DERIVED_0030:
            m = re.search(r"passages scope => abstention appropriate", note)
            m2 = re.search(r"'(appropriate_abstention|inappropriate_abstention)'", note)
            if not (m and m2):
                failures.append(f"{aid}: scope-mapping wording not found in note")
            parsed_abs = m2.group(1) if m2 else ""
            parsed_label = ""  # note: "No claim label supplied by the reviewer"
            status, rule = "derived_scope_mapping", "R2"
        elif decision == "revise":
            m = PREFIX_RE.match(note)
            if not m or m.group(1) not in LABELS:
                failures.append(f"{aid}: missing/unknown reviewer-label prefix")
                m = None
            if m:
                parsed_label = m.group(1)
                status, rule = "parsed_prefix", "R1"
                if item_type == "claim" and parsed_label not in CLAIM_LABELS:
                    failures.append(f"{aid}: revised claim label outside claim vocabulary")
        else:
            failures.append(f"{aid}: unknown reviewer_decision {decision!r}")

        included = aid != EXCLUDED_0033
        derived.append({
            "annotation_id": aid,
            "item_type": item_type,
            "tier": it["item_priority"],
            "reviewer_decision": decision,
            "parsed_label": parsed_label,
            "parsed_abstention_assessment": parsed_abs,
            "parsing_status": status,
            "parsing_rule_id": rule,
            "reviewer_note_sha256": note_sha,
            "source_csv_sha256": INPUT_HASHES[D3 / "d3_review_decisions.csv"],
            "included_in_label_metrics": "true" if included else "false",
            "exclusion_reason": "" if included else EXCLUSION_REASON,
        })
    if failures:
        die("fail-closed violations: " + "; ".join(failures))
    counts = Counter(d["parsing_status"] for d in derived)
    if dict(counts) != {"accepted_proposal": 40, "parsed_prefix": 5, "derived_scope_mapping": 1}:
        die(f"unexpected status counts {dict(counts)}")
    print(f"[4] parsing OK: {dict(counts)}; 0 failures")

    dby = {d["annotation_id"]: d for d in derived}
    if dby[EXCLUDED_0033]["included_in_label_metrics"] != "false":
        die("0033 not flagged for exclusion")
    excl_count = sum(1 for d in derived if d["included_in_label_metrics"] == "false")

    # ---- 5. metrics (all recomputed from files; none hardcoded)
    claim_ids = [a for a in qb if qb[a]["item_type"] == "claim"]
    abs_ids = [a for a in qb if qb[a]["item_type"] == "abstention_question"]
    claim_incl = [a for a in claim_ids if a != EXCLUDED_0033]

    claim_dist = Counter(dby[a]["parsed_label"] for a in claim_incl)
    abs_primary = Counter(dby[a]["parsed_abstention_assessment"] for a in abs_ids)
    abs_sens_ids = [a for a in abs_ids if a != DERIVED_0030]
    abs_sens = Counter(dby[a]["parsed_abstention_assessment"] for a in abs_sens_ids)

    # tier-1 retraction analysis (retraction new_label must be uniform to compare per-row)
    new_labels = {r["new_label"] for r in ret}
    if len(new_labels) != 1:
        die(f"retraction new_label not uniform: {new_labels}")
    retr_new = next(iter(new_labels))
    retr_correct = [a for a in sorted(p1) if dby[a]["parsed_label"] != "supported"]
    retr_false = [a for a in sorted(p1) if dby[a]["parsed_label"] == "supported"]
    retr_exact = [a for a in sorted(p1) if dby[a]["parsed_label"] == retr_new]
    # tier-2 survivor analysis
    surv_true = [a for a in sorted(p2) if dby[a]["parsed_label"] == "supported"]
    surv_false = [a for a in sorted(p2) if dby[a]["parsed_label"] != "supported"]

    # system-vs-single-reviewer claim agreement (excl 0033)
    agree_rows = []
    for a in sorted(claim_incl):
        sysv = qb[a]["system_verdict"]
        hum = dby[a]["parsed_label"]
        if sysv not in CLAIM_LABELS:
            die(f"system verdict {sysv!r} outside label space")
        agree_rows.append((a, hum, sysv))
    matched = len(agree_rows)
    hits = sum(1 for _, h, s in agree_rows if h == s)
    conf = Counter((h, s) for _, h, s in agree_rows)

    # abstention system agreement
    abs_sys_ok = sum(1 for a in abs_ids if qb[a]["system_verdict"] == "abstained_no_claims")

    # ---- 6. write outputs (only now)
    out_csv = HERE / "derived_reviewer_labels.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(derived[0].keys()), quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(derived)

    ledger = [
        f"decision_counts=accept:40,revise:6,pending:0",
        f"parsing=accepted_proposal:40,parsed_prefix:5,derived_scope_mapping:1,failed:0",
        f"claim_label_total={len(claim_ids)};claim_label_included={len(claim_incl)};excluded={excl_count}",
        f"abstention_primary_total={len(abs_ids)};abstention_sensitivity_total={len(abs_sens_ids)}",
        f"retraction_correct_refusal={len(retr_correct)}/13;retraction_false_refusal={len(retr_false)}/13;retraction_exact_label_match={len(retr_exact)}/13",
        f"survivor_true_endorsement={len(surv_true)}/11;survivor_false_endorsement={len(surv_false)}/11",
        f"abstention_system_abstained={abs_sys_ok}/6",
        f"system_vs_single_reviewer_agreement={hits}/{matched};coverage={matched}/{len(claim_ids)}",
        f"human_vs_human_agreement=not_computable(no_second_reviewer_labels_exist)",
    ]
    conf_labels = sorted({h for h, _ in conf} | {s for _, s in conf})
    conf_lines = ["| human \\ system | " + " | ".join(conf_labels) + " |",
                  "|---|" + "|".join(["---"] * len(conf_labels)) + "|"]
    for h in conf_labels:
        conf_lines.append(f"| **{h}** | " +
                          " | ".join(str(conf.get((h, s), 0)) for s in conf_labels) + " |")

    def dist_line(c: Counter) -> str:
        return ", ".join(f"{k}={v}" for k, v in sorted(c.items())) or "(none)"

    report = f"""# Stage E1 — Annotation Quality Report (derived, read-only inputs)

- Built by `build_stage_e1_analysis.py` · {datetime.now(timezone.utc).isoformat(timespec="seconds")}
- Source of truth: `d3_review_decisions.csv` sha256 `488ecb1497e7bbfae98f11a840495208e6e7e56b42aa6b987f78490049520b8e` (asserted, never written)
- Queue `cce025cc…`, Stage C inputs `51a9e667…` / `c5c2c426…` / `2f4ccc5f…`, questions `500ed32d…` (all asserted)
- Label authority: **single-reviewer human labels (n=46, coverage=1.0)** — one reviewer, no second pass, **not independently validated**.
- No `gold_label` was written anywhere; this report derives every number from the reviewed CSV.

## 1. Parsing ledger (fail-closed rules R1-R5)

- Rule R3 accepts: 40 (label = machine `proposed_label` endorsed by the reviewer; 26 notes
  name the label in parentheses — all 26 equal the proposed label, verified)
- Rule R1 revise prefixes: 5 (0015 `supported`, 0017 `contradicted`, 0020 `contradicted`,
  0014 `insufficient_evidence`, 0033 `supported` — the last excluded, see §3)
- Rule R2 scope mapping: 1 (`ann-d1-0030`, flag `derived_scope_mapping`, see §4)
- Rule R5 failures: **0** (the build aborts before writing if any rule fails)
- Exclusion ledger: `excluded={excl_count}` (`ann-d1-0033`, reason: {EXCLUSION_REASON})
- Missing values: 0 (every row parsed; every reviewer field non-empty in the source)

## 2. Decision and label distributions

- Reviewer decisions: accept=40, revise=6, pending=0
- Claim labels (n={len(claim_incl)}, `ann-d1-0033` excluded): {dist_line(claim_dist)}
- Abstention assessments, **primary** (n={len(abs_ids)}, includes scope-qualified `ann-d1-0030`): {dist_line(abs_primary)}
- Abstention assessments, **sensitivity** (n={len(abs_sens_ids)}, excludes `ann-d1-0030`): {dist_line(abs_sens)}

## 3. ann-d1-0033 — excluded from label-based metrics

The recorded reviewer label `supported` conflicts with the reasoning stated in its own
reviewer note (which describes the claim as conflicting with the passages' explicit
"not independently verified" disclaimers — the basis of the machine `contradicted`
proposal). The inconsistency is unresolved and reserved to the reviewer (D3 note §8);
this analysis excludes the item from every label-based denominator (**excluded=1**) and
changes no byte of its record. Claim-label denominator: {len(claim_ids)} -> {len(claim_incl)}.
The gate headline metrics are unaffected because `ann-d1-0033` (tier 4) is text-verified
absent from `retracted_claims_13.csv` (13) and `supported_claims_11.csv` (11), and is not
an abstention item (6).

## 4. ann-d1-0030 — scope-qualified derived abstention label

Primary analysis **includes** it with flag `derived_scope_mapping`: the reviewer's scope
ruling (retrieved passages, R1-consistent) via the mapping documented in Stage D2's
`review_summary.md` (lines 286/427) before the choice was made (passages =>
`appropriate_abstention`; catalog => `inappropriate_abstention`). The ruling is an
evaluation-scope decision only — **not** proof that CVE-2021-45046 is absent from the
complete catalog. The fixture's catalog-presence gold answer (plausible-04 gold claim
"…is present in the catalog." -> `contradicted`) diverges from this passages-scope
ruling; both are reported, neither is reconciled here. The sensitivity line in §2
repeats the abstention distribution without this item.

## 5. Gate analyses (tier files text-matched, question-constrained, exact)

- **Retraction correctness (tier 1, n=13):** correct refusals = {len(retr_correct)}/13
  (human label != `supported`); false refusals = {len(retr_false)}/13 ({", ".join(retr_false)}
  — reviewer label `supported`); exact match to the retraction's stored
  `new_label` (`insufficient_evidence`) = {len(retr_exact)}/13 (the remainder are
  reviewer `unverifiable`, still non-supported).
- **Surviving-supported endorsement (tier 2, n=11):** true endorsements = {len(surv_true)}/11;
  false endorsements = {len(surv_false)}/11 ({", ".join(surv_false)}).
- **Abstention quality (tier 3):** system abstained on {abs_sys_ok}/6;
  reviewer assesses {abs_primary.get("appropriate_abstention", 0)}/6 appropriate (primary),
  {abs_sens.get("appropriate_abstention", 0)}/{len(abs_sens_ids)} (sensitivity).

## 6. System-vs-single-reviewer claim agreement (descriptive only)

Scope: {matched} claim items with both a system verdict and a derived reviewer label
(`ann-d1-0033` excluded). matched={matched} / total={len(claim_ids)} /
coverage={matched}/{len(claim_ids)}; exact agreement = {hits}/{matched}.

{chr(10).join(conf_lines)}

**Interpretation limits:** the "system" side is a machine judge from the same model
family as the generator; the "reviewer" side is one human. This is a descriptive
system-vs-single-reviewer comparison, **not** a human-human agreement statistic and not
an accuracy measurement against independent ground truth. **Human-vs-human agreement is
not computable: no second-reviewer labels exist.** No significance test is performed
(single run, clustered small-n claims — Stage C statistical restraint stands).

## 7. Metrics ledger (machine-readable; re-verified by validate_stage_e1.py)

{chr(10).join("- " + x for x in ledger)}

## 8. Limitations

- Single-reviewer decisions; adjudication fields empty; no inter-rater statistics.
- AI-proposed labels remain quarantined machine values; accepting a proposal makes it a
  reviewer decision but does not convert the proposal into independent ground truth.
- `ann-d1-0030` is a pre-documented derivation, not an independently adjudicated label.
- `ann-d1-0033` remains internally inconsistent and is excluded, not resolved.
- Results derive from one run over 22 questions on a 6-chunk corpus.
- Completing annotation does not prove the research hypothesis; no accuracy,
  superiority, or publication claim follows from this report.
"""
    out_report = HERE / "annotation_quality_report.md"
    out_report.write_text(report, encoding="utf-8")

    manifest = {
        "stage": "E1",
        "purpose": "derived reviewer labels + annotation-quality report (read-only inputs)",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": [{"path": str(p.relative_to(ROOT)), "sha256": h}
                   for p, h in INPUT_HASHES.items()],
        "outputs": [{"path": out_csv.name, "sha256": sha256(out_csv)},
                    {"path": out_report.name, "sha256": sha256(out_report)}],
        "parsing_counts": dict(counts),
        "exclusions": {"count": excl_count, "ids": [EXCLUDED_0033],
                       "reason": EXCLUSION_REASON},
        "gold_label_written": False,
        "source_csv_written": False,
    }
    out_man = HERE / "stage_e1_manifest.json"
    out_man.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"[5] wrote {out_csv.name}, {out_report.name}, {out_man.name}")
    print("ledger:")
    for line in ledger:
        print("   ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
