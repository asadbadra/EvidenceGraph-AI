# Annotation Data Dictionary — Schema v1.0.0

**Companion to:** `annotation_schema.json` (schema id `evidencegraph-ai/annotation-schema/v1.0.0`)
**Dataset version:** `d1` (queue generated 2026-10-16; see `stage_d_manifest.json`)
**Rule zero:** Every field below is either *immutable provenance* (set by tooling from stored artifacts), *human judgment* (empty until a human writes it), or *workflow state*. Tooling never writes a human-judgment field. No field ever receives a default label.

## 1. Identifier and versioning fields (immutable)

| Field | Type | Allowed values | Set by | Meaning / rules |
|---|---|---|---|---|
| `annotation_id` | string | `ann-d1-NNNN` (4 digits) | tooling | Unique per annotation slot, within dataset version `d1`. Position in review-priority order. Never reused; a future `d2` dataset gets fresh ids. |
| `schema_version` | string | `1.0.0` (const) | tooling | The schema this record conforms to. Any field/allowed-value change bumps this; records are never edited in place under a new version. |
| `item_type` | enum | `claim`, `abstention_question` | tooling | `claim` = one extracted claim (reviewed at claim level). `abstention_question` = one of the six zero-claim questions (reviewed at question level). |
| `item_priority` | int 1–5 | 1=retracted, 2=surviving supported, 3=abstention, 4=unchanged sample, 5=anomaly extras | tooling | Review order tier from the Stage D protocol. |

## 2. Source-linkage fields (immutable; preserve original IDs)

| Field | Type | Allowed values | Set by | Meaning / rules |
|---|---|---|---|---|
| `question_id` | string | ids from `data/sample/eval_questions.json` (e.g. `direct-03`) | tooling | The question this item belongs to. |
| `claim_id` | int or null | `verif_claims.id` from the source run DB; **null** for abstention questions | tooling | Original database primary key, preserved verbatim — never renumbered or re-based. |
| `run_id` | enum | `eval-postgate22-20261016-141416` (queue v1 uses only this) | tooling | Source run. The historical pre-gate run is referenced only inside `source_artifact_refs` for recovered citations. |
| `system_arm` | enum | `verified` | tooling | Only the verified arm produces claims (baseline performs no claim verification by design). The paired baseline answer is referenced per item for question-level comparison. |
| `claim_text` | string or null | byte-verbatim `verif_claims.claim_text`; null for abstention questions | tooling | Verbatim from the run DB. Fragments/hedging are labeled as written, not "corrected". |
| `paired_answer_texts` | object `{baseline, verified}` | byte-verbatim `eval_results.answer_text` per arm; null arm if row missing | tooling | **Paired question structure:** both arms' answers to this question from the same run, so reviewers compare baseline vs verified answers without leaving the item. Immutable; the baseline arm has no claims (no claim verification by design), so claim-level items exist only on the verified arm while answer-level comparison stays available on every row. |
| `source_artifact_refs` | object | see below | tooling | Stable references back to immutable artifacts. |

### `source_artifact_refs` sub-fields

| Sub-field | Meaning |
|---|---|
| `claim_row_source` | Path + table + primary key of the originating claim row, e.g. `runs/eval-postgate22-20261016-141416/evidencegraph-eval.db :: verif_claims.id=37 (verified arm)`. |
| `run_db_sha256` | SHA-256 of the source run DB at queue-generation time — pins the exact bytes reviewed. |
| `paired_baseline_answer_ref` | Reference to the baseline-arm `eval_results` row for the same question (paired structure). |
| `historical_claim_ref` | For gate-retracted claims: the historical pre-gate row that still carries the original judge citations (the post-gate store is empty by design). Null otherwise. |

## 3. Evidence fields (immutable)

| Field | Type | Allowed values | Set by | Meaning / rules |
|---|---|---|---|---|
| `retrieved_evidence_ids` | int[] or null | chunk ids; `[]` = system cited nothing; null = not applicable (abstention question) | tooling | For retracted claims: originally-cited ids recovered from the gate anomaly note, cross-validated 13/13 against the historical DB in Stage C. Recovery is recorded in `evidence_text_or_reference[].text_source` handling and the manifest. |
| `evidence_text_or_reference` | array or null | `{chunk_id, document_external_id, text, text_source}` | tooling | Verbatim chunk text from the source run DB copy. `text_source=source_run_db_verbatim`. For abstention questions: retrieved passages from the Stage C–validated reconstruction (BM25 replay matched stored `retrieved_count` 22/22). **Unavailable text is marked `unavailable_not_stored`, never silently reconstructed.** |

## 4. System-output fields (visible only in the full queue)

| Field | Type | Allowed values | Set by | Meaning / rules |
|---|---|---|---|---|
| `system_verdict` | enum or null | `supported`, `contradicted`, `insufficient_evidence`, `unverifiable`, `abstained_no_claims` | tooling | The system's stored verdict (or abstention marker). **Not ground truth.** Hidden from the blind queue; shown only after first judgment or an acknowledged waiver. |
| `system_verdict_visibility` | enum | `blind_first_judgment_required`, `visible_acknowledged` | tooling / reviewer | Anti-confirmation-bias control. Default `blind_first_judgment_required`. If a reviewer judges with verdicts visible, tooling flips this to `visible_acknowledged` **only when the reviewer states so** (recorded in `uncertainty_notes`). |
| `system_diagnostics` | object or null | `{anomaly_notes: string[], grounding_ratio: number\|null}`; null = no anomalies | tooling | **Full queue only (always null in the blind file).** Verbatim anomaly notes from `verif_claims.anomalies_json` (gate retractions carry their grounding ratio; bar 0.50 is a judge configuration, not a human threshold) plus the parsed ratio. Context for adjudication and later analysis — never evidence for a label. |

## 5. AI secondary view (never human ground truth)

| Field | Type | Allowed values | Set by | Meaning / rules |
|---|---|---|---|---|
| `proposed_ai_label` | enum or null | 4 verdict labels or null | tooling | The AI-draft label from `human_claim_review56.md` where a mapping exists. **Excluded from the blind file; excluded from every agreement/accuracy statistic; never transferred to `gold_label`.** Null when no draft exists. |
| `proposed_ai_label_source` | string or null | free text | tooling | Provenance string citing the file, its hash, and the `ai_generated_draft` determination from `stage_d_provenance_audit.md`. Null when label is null. |

## 6. Human-judgment fields (EMPTY until a human writes them)

| Field | Type | Allowed values | Meaning / rules |
|---|---|---|---|
| `human_label` | enum or null | `supported`, `contradicted`, `insufficient_evidence`, `unverifiable`, `not_applicable` | **Dimension A+B (claim factuality, corpus-grounded):** does the available authoritative (corpus) evidence confirm, conflict with, or fail to bear on the claim *as written*? `not_applicable` only for abstention-question items at claim level (their assessment lives in `abstention_assessment`). **No default. Blank ≠ any label.** |
| `human_rationale` | string or null | free text | Reviewer's reasoning for `human_label`, citing chunk ids and quoting the decisive span. |
| `evidence_sufficiency_rationale` | string or null | free text | **Dimension B:** retrieved evidence supports the *specific claim*, not just the topic? Quote/name the exact span(s). |
| `citation_support_label` | enum or null | 4 verdict labels, `not_applicable` | **Dimension C:** does the cited passage actually support the attached claim? `not_applicable` = claim cites nothing or citations unavailable. |
| `citation_support_rationale` | string or null | free text | Rationale for `citation_support_label`. |
| `abstention_assessment` | enum or null | `appropriate_abstention`, `inappropriate_abstention`, `uncertain`, `not_applicable` | **Dimension F (question-level, abstention items only):** appropriate = answer not supported by corpus; inappropriate = answer-bearing evidence *was* present; `uncertain` = reviewer cannot decide; `not_applicable` on claim items. |
| `uncertainty_notes` | string or null | free text | Uncertainty, compound-claim flags, prompt-injection sightings, blinding waivers, disagreement notes. |

## 7. Reviewer identity and timing (only on actual review)

| Field | Type | Allowed values | Meaning / rules |
|---|---|---|---|
| `reviewer_id` | string or null | reviewer-chosen id (e.g. `reviewer-1`) | **Only if the human supplies one.** Tooling never invents an identity. Null = anonymous. |
| `review_timestamp` | string or null | UTC ISO-8601 | Written only when a real judgment arrives. Null in the initial queue. |

## 8. Workflow and adjudication fields

| Field | Type | Allowed values | Meaning / rules |
|---|---|---|---|
| `review_status` | enum | `not_reviewed`, `in_review`, `reviewed`, `needs_adjudication`, `adjudicated`, `deferred_out_of_scope` | All d1 records start `not_reviewed`. `needs_adjudication` set on reviewer disagreement; `adjudicated` only after `adjudicated_label` is written. `deferred_out_of_scope` = reviewer explicitly deferred (reason in `uncertainty_notes`). |
| `adjudicated_label` | enum or null | 4 verdict labels, `not_applicable`, `unresolved` | Final label after adjudication. `unresolved` = honest failure to adjudicate; not a correctness claim. |
| `adjudication_rationale` | string or null | free text | Adjudicator's reasoning. |

## 9. Cross-field invariants (enforced by the validation step)

1. `review_status = not_reviewed` ⟹ all of `human_label`, `human_rationale`, `evidence_sufficiency_rationale`, `citation_support_label`, `citation_support_rationale`, `abstention_assessment`, `reviewer_id`, `review_timestamp`, `adjudicated_label`, `adjudication_rationale` are null.
2. `item_type = abstention_question` ⟹ `claim_id`, `claim_text`, `retrieved_evidence_ids` null; `system_verdict = abstained_no_claims`; claim-level label fields null.
3. `item_type = claim` ⟹ `claim_id` non-null and present in the source run DB; `abstention_assessment` null.
4. `adjudicated_label` non-null ⟹ `review_status ∈ {adjudicated}`.
5. `proposed_ai_label` non-null ⟹ `proposed_ai_label_source` non-null.
6. No record in the **blind** queue file contains `system_verdict` or `proposed_ai_label` values.
