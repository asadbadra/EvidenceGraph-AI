"""Claim-level evidence verification (Phase 2).

Stage 2.1 provides claim extraction and the verdict/no-fabrication types:

- `claims.py`    -- extract checkable claims from a generated answer,
                    keeping a character span back to the exact source text.
- `verdicts.py`  -- the four verdict labels and the no-fabrication
                    invariant that makes an unsupported "supported" verdict
                    structurally impossible rather than merely discouraged.

Stage 2.2 adds evidence linking:

- `evidence.py`  -- candidate sets built from the passages a claim cited
                    plus a fresh claim-level retrieval, deduplicated by
                    chunk id, validated against known records, and capped.
                    `make_evidence_verdict` wires the candidate set into
                    the no-fabrication invariant.

Stage 2.3 adds the judge:

- `judge.py`     -- `LLMJudge` (NLI prompt, temperature 0) and a
                    deterministic `RuleBasedJudge` offline stand-in. Malformed
                    output degrades to `unverifiable`, never `supported`.

Stage 2.4 adds the verified pipeline:

- `pipeline.py`   -- `VerifiedRAG`: baseline generation, unchanged and shared
                     with `BaselineRAG`, followed by claim extraction, evidence
                     linking, and judging. `make_chunk_exists` wires candidate
                     ids to real database records.

Stage 2.5-2.6 add the evaluation layer:

- `metrics.py`   -- mechanism metrics (what the verifier said) kept strictly
                    separate from judge-vs-human agreement (whether it was
                    right, and only on labelled claims).
- `harness.py`   -- the shared A/B runner: both systems, same corpus,
                    retriever, prompt and model; only the verified pipeline
                    adds the post-generation check.

Stage 2.8 adds honest usage and cost tracking:

- `usage.py`     -- provider-reported token counts (never inferred, never
                    zeroed when absent) and cost estimates that are only
                    computed when explicit prices are configured. See its
                    docstring for the measured/estimated/unknowable split.

The eval tables live in `app/db.py` as additive schema. This package does
not modify the baseline RAG pipeline.

IMPORTANT SCOPE NOTE: these modules define *invariants and mechanics*, not
accuracy. A passing unit test says the downgrade rules fire correctly; it
says nothing about whether the verifier agrees with a human label on real
data. Verifier accuracy is only measurable against the manually labelled
evaluation set (Stage 2.6) and must be reported separately.
"""

from __future__ import annotations

from app.verification.claims import (
    ABSTENTION_SENTENCES,
    Claim,
    ClaimExtraction,
    SkippedFragment,
    extract_claims,
)
from app.verification.evidence import (
    CLAIM_RETRIEVAL_TOP_K,
    DEFAULT_CANDIDATE_LIMIT,
    ORIGIN_CITED,
    ORIGIN_RETRIEVED,
    EvidenceCandidate,
    EvidenceSet,
    link_evidence,
    make_evidence_verdict,
    resolve_cited_chunks,
)
from app.verification.harness import (
    SYSTEM_BASELINE,
    SYSTEM_VERIFIED,
    EvalOutcome,
    QuestionResult,
    citation_quality_for_run,
    judge_agreement_for_run,
    load_questions,
    run_ab_eval,
)
from app.verification.judge import (
    JUDGE_PROMPT_VERSION,
    Judge,
    JudgeError,
    LLMJudge,
    RuleBasedJudge,
    build_judge_prompt,
    parse_judge_output,
)
from app.verification.metrics import (
    Agreement,
    CitationQuality,
    MechanismMetrics,
    citation_quality,
    judge_agreement,
    match_claims_to_gold,
    mechanism_metrics,
    normalize_claim,
)
from app.verification.pipeline import (
    VerifiedAnswerResult,
    VerifiedRAG,
    make_chunk_exists,
)
from app.verification.verdicts import (
    ClaimVerdict,
    Verdict,
    VerdictSummary,
    make_verdict,
    summarize,
)
from app.verification.usage import (
    COST_ESTIMATED,
    COST_UNAVAILABLE,
    USAGE_PROVIDER,
    USAGE_UNAVAILABLE,
    CostEstimate,
    Pricing,
    PricingError,
    TokenUsage,
    TrackingLLMClient,
    UsageAwareOpenAIClient,
    UsageRecord,
    UsageSummary,
    UsageTracker,
    estimate_cost,
    load_pricing,
)

__all__ = [
    "ABSTENTION_SENTENCES",
    "CLAIM_RETRIEVAL_TOP_K",
    "COST_ESTIMATED",
    "COST_UNAVAILABLE",
    "DEFAULT_CANDIDATE_LIMIT",
    "JUDGE_PROMPT_VERSION",
    "ORIGIN_CITED",
    "ORIGIN_RETRIEVED",
    "SYSTEM_BASELINE",
    "SYSTEM_VERIFIED",
    "USAGE_PROVIDER",
    "USAGE_UNAVAILABLE",
    "Agreement",
    "Claim",
    "ClaimExtraction",
    "ClaimVerdict",
    "CitationQuality",
    "CostEstimate",
    "EvalOutcome",
    "EvidenceCandidate",
    "EvidenceSet",
    "Judge",
    "JudgeError",
    "LLMJudge",
    "MechanismMetrics",
    "Pricing",
    "PricingError",
    "QuestionResult",
    "RuleBasedJudge",
    "SkippedFragment",
    "TokenUsage",
    "TrackingLLMClient",
    "UsageAwareOpenAIClient",
    "UsageRecord",
    "UsageSummary",
    "UsageTracker",
    "Verdict",
    "VerdictSummary",
    "VerifiedAnswerResult",
    "VerifiedRAG",
    "build_judge_prompt",
    "citation_quality",
    "citation_quality_for_run",
    "estimate_cost",
    "extract_claims",
    "judge_agreement",
    "judge_agreement_for_run",
    "link_evidence",
    "load_questions",
    "load_pricing",
    "make_chunk_exists",
    "make_evidence_verdict",
    "make_verdict",
    "match_claims_to_gold",
    "mechanism_metrics",
    "normalize_claim",
    "parse_judge_output",
    "resolve_cited_chunks",
    "run_ab_eval",
    "summarize",
]
