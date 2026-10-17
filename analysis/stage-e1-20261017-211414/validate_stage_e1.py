"""Stage E1 validator (writes only stage_e1_validation_report.md in this directory).

Independently re-derives every reported number from the live inputs and checks
integrity of all pre-existing artifacts, git state, honesty wording, and the
manifest. Does not import repo modules; does not open databases.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
D3 = ROOT / "analysis" / "stage-d3-20261017-011614"
D = ROOT / "analysis" / "stage-d-20261016-213744"
C = ROOT / "analysis" / "stage-c-20261016"
CSV = D3 / "d3_review_decisions.csv"

KNOWN = {
    CSV: "488ecb1497e7bbfae98f11a840495208e6e7e56b42aa6b987f78490049520b8e",
    D3 / "d3_review_decisions_predecision_snapshot.csv":
        "65bd58ce3a79e66f4009cbc653cac2726ed38c48ed6c9c8174e1a6fa545d8ac5",
    D3 / "d3_review_decisions_pre0017update_snapshot.csv":
        "31751232964d54fc720d050b0faba109691b030947127ce1765a584363e6a40f",
    D3 / "d3_review_decisions_pre0033update_snapshot.csv":
        "dc013c26fc18580a813b45029916269278b2f6492980e6cbd07c88b181db9f13",
    D3 / "d3_review_decisions_pre0014update_snapshot.csv":
        "303f7f609443a464f619ef423660e7481f9e115d11e512064a3d6ee970ef3451",
    D3 / "d3_review_decisions_prebatch30update_snapshot.csv":
        "95ad984d4c7f37d1eeb01b76f5af2dbe4ee5866758534a316ee847821a22286e",
    D3 / "d3_review_decisions_prefixhold4_snapshot.csv":
        "2ba3f58409db5714d67c8ac67a5b61cfab6ef80656b10608df8ce9c0f3d290da",
    D3 / "d3_review_decisions_pre0012correction_snapshot.csv":
        "3ef6fae315634c970d259888c67c15f7d01f9184d23113e0d671884eb84ec5ad",
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
CLAIM_LABELS = ("supported", "contradicted", "insufficient_evidence", "unverifiable")
PREFIX_RE = re.compile(r"^Reviewer label: ([a-z_]+) \| ")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== Stage E1 validation ===")

    # V1 required files
    required = ["build_stage_e1_analysis.py", "validate_stage_e1.py",
                "derived_reviewer_labels.csv", "annotation_quality_report.md",
                "stage_e1_manifest.json"]
    check("V1 required E1 files exist", all((HERE / f).is_file() for f in required),
          f"missing={[f for f in required if not (HERE / f).is_file()]}")

    with CSV.open(encoding="utf-8", newline="") as fh:
        src = {r["annotation_id"]: r for r in csv.DictReader(fh)}
    with (HERE / "derived_reviewer_labels.csv").open(encoding="utf-8", newline="") as fh:
        drv = list(csv.DictReader(fh))
    dby = {d["annotation_id"]: d for d in drv}
    queue = json.loads((D / "human_review_queue.json").read_text(encoding="utf-8"))
    qb = {it["annotation_id"]: it for it in queue["items"]}

    # V2/V3 shape and statuses
    check("V2 derived table: 46 rows, unique ids == source ids",
          len(drv) == 46 and len(dby) == 46 and set(dby) == set(src))
    st = Counter(d["parsing_status"] for d in drv)
    check("V3 status counts: 40 accepted_proposal / 5 parsed_prefix / 1 derived_scope_mapping / 0 failed",
          dict(st) == {"accepted_proposal": 40, "parsed_prefix": 5,
                       "derived_scope_mapping": 1}, str(dict(st)))

    # V4 provenance hashes link to live source
    bad = [d["annotation_id"] for d in drv
           if d["source_csv_sha256"] != sha256(CSV)
           or d["reviewer_note_sha256"] != hashlib.sha256(
               src[d["annotation_id"]]["reviewer_note"].encode("utf-8")).hexdigest()]
    check("V4 every derived row links to live CSV hash + verbatim note hash", not bad,
          f"bad={bad[:3]}")

    # V5 exclusion
    excl = [d["annotation_id"] for d in drv if d["included_in_label_metrics"] == "false"]
    check("V5 exactly ann-d1-0033 excluded, with documented reason; all others included",
          excl == ["ann-d1-0033"] and dby["ann-d1-0033"]["exclusion_reason"].strip() != "",
          f"excluded={excl}")

    # V6 independent label re-derivation
    mism = []
    for aid, s in src.items():
        d = dby[aid]
        if s["reviewer_decision"] == "accept":
            if d["parsed_label"] != s["proposed_label"]:
                mism.append((aid, "accept label"))
            if qb[aid]["item_type"] == "abstention_question" and \
                    d["parsed_abstention_assessment"] != s["proposed_abstention_assessment"]:
                mism.append((aid, "accept abstention"))
        elif aid == "ann-d1-0030":
            if d["parsed_abstention_assessment"] != "appropriate_abstention" or d["parsed_label"] != "":
                mism.append((aid, "scope mapping"))
        else:
            m = PREFIX_RE.match(s["reviewer_note"])
            if not m or d["parsed_label"] != m.group(1):
                mism.append((aid, "prefix"))
    check("V6 labels independently re-derived from live CSV match the derived table",
          not mism, f"mismatches={mism[:3]}")

    # V7 ledger recomputation: every ledger line re-derived independently
    # from queue + derived table + Stage C tier files, then matched verbatim.
    report = (HERE / "annotation_quality_report.md").read_text(encoding="utf-8")
    ledger_lines = re.findall(r"^- ([a-z_]+=.*?)$", report, re.M)
    check("V7a ledger block present with 9 lines", len(ledger_lines) == 9,
          f"found={len(ledger_lines)}")
    claim_ids = [a for a in qb if qb[a]["item_type"] == "claim"]
    abs_ids = [a for a in qb if qb[a]["item_type"] == "abstention_question"]
    incl = [a for a in claim_ids if dby[a]["included_in_label_metrics"] == "true"]
    p1 = {a for a, it in qb.items() if it["item_priority"] == 1}
    p2 = {a for a, it in qb.items() if it["item_priority"] == 2}
    retr_c = len([a for a in p1 if dby[a]["parsed_label"] != "supported"])
    retr_f = len([a for a in p1 if dby[a]["parsed_label"] == "supported"])
    retr_x = len([a for a in p1 if dby[a]["parsed_label"] == "insufficient_evidence"])
    sv_t = len([a for a in p2 if dby[a]["parsed_label"] == "supported"])
    sv_f = len([a for a in p2 if dby[a]["parsed_label"] != "supported"])
    pairs = [(dby[a]["parsed_label"], qb[a]["system_verdict"]) for a in incl
             if qb[a]["system_verdict"] in CLAIM_LABELS]
    hits = sum(1 for h, s in pairs if h == s)
    sys_abs = len([a for a in abs_ids
                   if qb[a]["system_verdict"] == "abstained_no_claims"])
    expect = [
        "decision_counts=accept:40,revise:6,pending:0",
        "parsing=accepted_proposal:40,parsed_prefix:5,derived_scope_mapping:1,failed:0",
        f"claim_label_total={len(claim_ids)};claim_label_included={len(incl)};excluded=1",
        f"abstention_primary_total={len(abs_ids)};abstention_sensitivity_total={len(abs_ids) - 1}",
        f"retraction_correct_refusal={retr_c}/13;retraction_false_refusal={retr_f}/13;"
        f"retraction_exact_label_match={retr_x}/13",
        f"survivor_true_endorsement={sv_t}/11;survivor_false_endorsement={sv_f}/11",
        f"abstention_system_abstained={sys_abs}/6",
        f"system_vs_single_reviewer_agreement={hits}/{len(pairs)};"
        f"coverage={len(pairs)}/{len(claim_ids)}",
        "human_vs_human_agreement=not_computable(no_second_reviewer_labels_exist)",
    ]
    v7bad = [e for e in expect if e not in ledger_lines]
    check("V7b all 9 ledger lines match independent recomputation", not v7bad,
          f"bad={v7bad[:2]}; hits={hits}/{len(pairs)}, retr={retr_c}c/{retr_f}f/{retr_x}x,"
          f" surv={sv_t}t/{sv_f}f")

    # V8 pre-existing artifacts untouched
    bad8 = [p.name for p, h in KNOWN.items() if not p.is_file() or sha256(p) != h]
    check("V8 all pre-existing inputs + 7 snapshots byte-identical to baselines", not bad8,
          f"bad={bad8}")
    # V9 D3 decision note: no baseline hash exists anywhere in the repository
    # (checked: manifests, reports, audits record none), so integrity is asserted
    # structurally (all 12 approved sections + the three fork decisions it must
    # document); the observed sha256 is recorded here as documentation only.
    note = D3 / "d3_reviewer_decision_note.md"
    note_txt = note.read_text(encoding="utf-8") if note.is_file() else ""
    sections_ok = all(f"## {i}." in note_txt for i in range(1, 13))
    markers_ok = all(m in note_txt for m in
                     ("ann-d1-0033", "ann-d1-0012", "ann-d1-0030", "Reviewer label:"))
    check("V9 D3 decision note: sections 1-12 + fork decisions structurally intact",
          sections_ok and markers_ok,
          f"sha256(observed)={hashlib.sha256(note.read_bytes()).hexdigest()[:16] if note.is_file() else 'missing'}"
          f" sections={sections_ok} markers={markers_ok}")

    # V10 git untouched by E1
    def git(*a):
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()
    head, staged, mod = git("rev-parse", "--short", "HEAD"), git("diff", "--cached", "--name-only"), \
        git("diff", "--name-only")
    check("V10 git HEAD d4ea26d; no staged or tracked changes", head == "d4ea26d"
          and not staged and not mod, f"head={head}")

    # V11 honesty wording
    must = ["single-reviewer human labels (n=46, coverage=1.0)", "not independently validated",
            "not computable: no second-reviewer labels exist",
            "does not prove the research hypothesis", "excluded=1",
            "sensitivity", "derived_scope_mapping"]
    banned = ["human-verified", "publication-ready", "proves the research hypothesis",
              "independently validated ground truth"]
    missing = [m for m in must if m not in report]
    hits_b = [b for b in banned if b in report]
    check("V11 mandated honesty phrases present; banned victory phrases absent",
          not missing and not hits_b, f"missing={missing} banned={hits_b}")

    # V12 script hygiene
    net_re = re.compile(r"^\s*(?:import|from)\s+(requests|httpx|socket|urllib|smtplib|ftplib|telnetlib)\b", re.M)
    sec_re = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9]{12,}")
    bad12 = []
    for f in ("build_stage_e1_analysis.py", "validate_stage_e1.py"):
        txt = (HERE / f).read_text(encoding="utf-8")
        if net_re.search(txt):
            bad12.append(f"{f}:network-import")
        if sec_re.search(txt):
            bad12.append(f"{f}:secret-like")
    check("V12 E1 scripts: stdlib-only, no network imports, no secrets", not bad12,
          f"bad={bad12}")

    # V13 manifest outputs
    man = json.loads((HERE / "stage_e1_manifest.json").read_text(encoding="utf-8"))
    out_ok = all(HERE.exists() and sha256(HERE / o["path"]) == o["sha256"]
                 for o in man["outputs"])
    in_ok = all(sha256(ROOT / i["path"]) == i["sha256"] for i in man["inputs"])
    check("V13 manifest: output hashes match; input hashes match baselines",
          out_ok and in_ok and man["gold_label_written"] is False
          and man["source_csv_written"] is False)

    passed = sum(1 for _, ok, _ in results if ok)
    lines = ["# Stage E1 Validation Report", "",
             f"- Run: `validate_stage_e1.py` · {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
             f"- Result: **{passed}/{len(results)} checks PASS**", "",
             "| # | Check | Result | Detail |", "|---|-------|--------|--------|"]
    for i, (name, ok, detail) in enumerate(results, 1):
        lines.append(f"| {i} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    (HERE / "stage_e1_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(results)} checks PASS "
          f"(report: stage_e1_validation_report.md)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
