"""Honest token-usage and cost tracking (Phase 2, Stage 2.8).

WHAT IS MEASURED, WHAT IS ESTIMATED, WHAT IS UNKNOWABLE
-------------------------------------------------------
- **Measured** (provider-reported): input, output and total tokens. These
  are copied only from the `usage` block a provider actually returns. They
  are never inferred, never approximated, and never defaulted to zero.
- **Estimated**: USD cost. Computed only when explicit per-million-token
  prices are configured AND the token counts it multiplies were themselves
  provider-reported. It is labelled `estimated` because it is arithmetic on
  a price list, not an invoice.
- **Unknowable**: anything a provider omits. A response with no `usage`
  block is recorded as `unavailable` with null token counts. Recording `0`
  instead would look like a measurement while understating spend, which is
  the single most misleading thing a cost tracker can do.

WHY A SECOND CLIENT CLASS EXISTS (and why it is not a fork)
-----------------------------------------------------------
`app.llm.client.OpenAICompatibleClient` lives in a baseline module this
project does not modify, and its `complete()` discards the response's
`usage` block. `UsageAwareOpenAIClient` inherits that class's `__init__`
verbatim and issues the same request, but also retains `usage` on
`self.last_usage`. `tests/test_usage.py::test_sends_identical_request_to_
baseline_client` pins the two request signatures together byte for byte, so
the extra class cannot quietly drift into sending a different request than
the baseline. If the baseline client ever starts surfacing usage itself,
this class should be deleted rather than kept in parallel.

No API key, prompt text, or response body is ever stored in a record: a
`UsageRecord` carries counts and identifiers only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings
from app.llm.client import LLMClient, LLMError, OpenAICompatibleClient

# Usage provenance. `provider` means the counts came from the provider's own
# usage block; `unavailable` means it sent none. There is deliberately no
# "estimated tokens" state: this module never guesses token counts.
USAGE_PROVIDER = "provider"
USAGE_UNAVAILABLE = "unavailable"

# Cost provenance. `estimated` means configured prices were applied to
# provider-reported tokens; `unavailable` means the inputs were missing.
COST_ESTIMATED = "estimated"
COST_UNAVAILABLE = "unavailable"


class PricingError(ValueError):
    """Pricing configuration is partial or invalid."""


@dataclass(frozen=True)
class TokenUsage:
    """Token counts for one completion. None means 'not reported'."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    source: str = USAGE_UNAVAILABLE

    @property
    def is_reported(self) -> bool:
        return self.source == USAGE_PROVIDER

    @classmethod
    def unavailable(cls) -> "TokenUsage":
        return cls(source=USAGE_UNAVAILABLE)


@dataclass(frozen=True)
class Pricing:
    """Explicit USD prices per million tokens, as configured by the operator."""

    input_per_million: float
    output_per_million: float

    @classmethod
    def from_values(cls, input_price, output_price) -> "Pricing":
        """Validate and build pricing, or raise `PricingError`.

        Partial pricing is rejected on purpose: pricing only the input side
        would yield a cost that reads as complete but is not.
        """
        named = (("input", input_price), ("output", output_price))
        missing = [name for name, value in named if value is None]
        if missing:
            raise PricingError(
                "incomplete pricing: set both LLM_PRICE_INPUT_PER_MILLION and "
                "LLM_PRICE_OUTPUT_PER_MILLION to estimate cost (missing: "
                f"{', '.join(missing)}). Partial pricing would produce a "
                "misleading partial cost."
            )
        for name, value in named:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise PricingError(
                    f"{name} price must be a non-negative number, got {value!r}"
                )
        return cls(float(input_price), float(output_price))

    @classmethod
    def from_settings(cls, settings: Settings) -> "Pricing":
        return cls.from_values(
            settings.llm_price_input_per_million,
            settings.llm_price_output_per_million,
        )

    def cost_for(self, usage: TokenUsage) -> float:
        """Price one call. Refuses rather than guesses when counts are absent."""
        if usage.input_tokens is None or usage.output_tokens is None:
            raise ValueError(
                "cannot price a call whose input/output token counts are missing"
            )
        usd = (
            usage.input_tokens * self.input_per_million
            + usage.output_tokens * self.output_per_million
        ) / 1_000_000.0
        return round(usd, 8)


def load_pricing(settings: Settings) -> Pricing | None:
    """Return pricing when both prices are configured, None when neither is.

    Raises `PricingError` for partial or invalid configuration rather than
    degrading to "no pricing": a half-configured price list is an operator
    mistake that must surface, not silently disable cost tracking.
    """
    input_configured = settings.llm_price_input_per_million is not None
    output_configured = settings.llm_price_output_per_million is not None
    if not input_configured and not output_configured:
        return None
    return Pricing.from_settings(settings)


@dataclass(frozen=True)
class CostEstimate:
    """Estimated USD cost for one call, or the reason it cannot be given."""

    usd: float | None
    source: str  # COST_ESTIMATED | COST_UNAVAILABLE
    reason: str = ""

    @property
    def is_estimated(self) -> bool:
        return self.source == COST_ESTIMATED and self.usd is not None


def estimate_cost(usage: TokenUsage, pricing: Pricing | None) -> CostEstimate:
    """Estimate cost only when both a price list and real token counts exist."""
    if pricing is None:
        return CostEstimate(None, COST_UNAVAILABLE, "no per-token pricing configured")
    if usage.input_tokens is None or usage.output_tokens is None:
        return CostEstimate(
            None,
            COST_UNAVAILABLE,
            "provider did not report the token counts needed to price this call",
        )
    return CostEstimate(
        pricing.cost_for(usage),
        COST_ESTIMATED,
        "provider-reported tokens x configured prices",
    )


def _as_count(value: Any) -> int | None:
    """Coerce a provider token field to a non-negative int, or None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _usage_from_response(data: Any) -> TokenUsage:
    """Read the `usage` block of an OpenAI-compatible response.

    Absent or malformed usage yields `unavailable`, never zeros. Both the
    OpenAI spellings (prompt_tokens/completion_tokens) and the alias set
    some compatible servers use (input_tokens/output_tokens) are accepted.
    """
    raw = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return TokenUsage.unavailable()

    input_tokens = _as_count(raw.get("prompt_tokens"))
    if input_tokens is None:
        input_tokens = _as_count(raw.get("input_tokens"))
    output_tokens = _as_count(raw.get("completion_tokens"))
    if output_tokens is None:
        output_tokens = _as_count(raw.get("output_tokens"))
    total_tokens = _as_count(raw.get("total_tokens"))

    # A total is only ever the provider's own figure, or the exact sum of two
    # figures the provider reported. It is never derived from anything else.
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        source=USAGE_PROVIDER,
    )


class UsageAwareOpenAIClient(OpenAICompatibleClient):
    """`OpenAICompatibleClient` that also retains the provider's usage block.

    Inherits `__init__` so every request parameter (model, temperature,
    max_tokens, base URL, timeout, auth header) is constructed by the
    baseline code itself. Only `complete()` is overridden, to keep the
    `usage` block the baseline discards. See the module docstring for why
    this is not a behavioural fork, and for the parity test that enforces it.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.last_usage: TokenUsage = TokenUsage.unavailable()

    def complete(self, prompt: str) -> str:
        if not self._api_key or self._api_key == "changeme":
            raise LLMError(
                "LLM_API_KEY is not configured. Set it in .env (see .env.example) "
                "or use the mock provider for offline runs."
            )
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        try:
            response = httpx.post(
                url, headers=headers, json=payload, timeout=self._timeout
            )
        except httpx.HTTPError as exc:  # network-level failure
            raise LLMError(f"LLM request failed: {exc}") from exc
        if response.status_code >= 400:
            # Never include the Authorization header or full payload in errors.
            raise LLMError(
                f"LLM returned HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        # Retain usage before parsing content, so a malformed content field
        # does not erase usage the provider genuinely reported.
        self.last_usage = _usage_from_response(data)
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response missing choices[0].message.content") from exc


@dataclass(frozen=True)
class UsageRecord:
    """One completion's usage and cost status, plus enough context to audit it.

    Carries counts and identifiers only -- no key, prompt, or response body.
    """

    run_id: str
    provider: str
    model: str
    timestamp: str  # ISO 8601 UTC
    purpose: str  # e.g. "generation", "judge"
    usage: TokenUsage
    cost: CostEstimate
    call_ok: bool = True
    error: str | None = None


@dataclass(frozen=True)
class UsageSummary:
    """Aggregate over records, null rather than zero whenever data is missing."""

    calls: int = 0
    calls_ok: int = 0
    calls_failed: int = 0
    records_with_usage: int = 0
    records_without_usage: int = 0
    records_priced: int = 0
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_tokens: int | None = None
    total_cost_usd: float | None = None
    cost_source: str = COST_UNAVAILABLE
    cost_note: str = ""

    @property
    def usage_complete(self) -> bool:
        """True only when every recorded call reported usage."""
        return self.calls > 0 and self.records_without_usage == 0


class UsageTracker:
    """Collects one `UsageRecord` per completion and summarises them.

    Totals are null unless *every* record supports them: a partial sum
    presented as a total would understate spend and read as measured.
    """

    def __init__(
        self,
        *,
        run_id: str,
        provider: str,
        model: str,
        pricing: Pricing | None = None,
    ) -> None:
        self.run_id = run_id
        self.provider = provider
        self.model = model
        self.pricing = pricing
        self._records: list[UsageRecord] = []

    @property
    def records(self) -> tuple[UsageRecord, ...]:
        return tuple(self._records)

    def record(
        self,
        purpose: str,
        usage: TokenUsage,
        *,
        call_ok: bool = True,
        error: str | None = None,
    ) -> UsageRecord:
        entry = UsageRecord(
            run_id=self.run_id,
            provider=self.provider,
            model=self.model,
            timestamp=datetime.now(timezone.utc).isoformat(),
            purpose=purpose,
            usage=usage,
            cost=estimate_cost(usage, self.pricing),
            call_ok=call_ok,
            error=error,
        )
        self._records.append(entry)
        return entry

    @property
    def summary(self) -> UsageSummary:
        records = self._records
        calls = len(records)
        if calls == 0:
            return UsageSummary(cost_note="no calls recorded")

        with_usage = [r for r in records if r.usage.is_reported]
        priced = [r for r in records if r.cost.is_estimated]

        def _total(pick) -> int | None:
            if any(pick(r.usage) is None for r in records):
                return None
            return sum(pick(r.usage) for r in records)

        if len(priced) == calls:
            cost_source = COST_ESTIMATED
            total_cost: float | None = round(sum(r.cost.usd for r in priced), 8)
            cost_note = "every call priced from configured prices"
        else:
            cost_source = COST_UNAVAILABLE
            total_cost = None
            reasons = sorted({r.cost.reason for r in records if not r.cost.is_estimated})
            cost_note = (
                f"{len(priced)}/{calls} calls priceable: " + "; ".join(reasons)
            )

        return UsageSummary(
            calls=calls,
            calls_ok=sum(1 for r in records if r.call_ok),
            calls_failed=sum(1 for r in records if not r.call_ok),
            records_with_usage=len(with_usage),
            records_without_usage=calls - len(with_usage),
            records_priced=len(priced),
            total_input_tokens=_total(lambda u: u.input_tokens),
            total_output_tokens=_total(lambda u: u.output_tokens),
            total_tokens=_total(lambda u: u.total_tokens),
            total_cost_usd=total_cost,
            cost_source=cost_source,
            cost_note=cost_note,
        )


class TrackingLLMClient:
    """Wraps any `LLMClient`, recording one `UsageRecord` per call.

    Works with every provider this project supports: a client that exposes
    `last_usage` (like `UsageAwareOpenAIClient`) yields provider-reported
    counts, while one that does not (like `FakeLLMClient`) is recorded as
    `unavailable` -- never as zero. Failures are recorded and re-raised, so
    tracking can never swallow or alter a provider error.
    """

    def __init__(self, inner: LLMClient, tracker: UsageTracker, purpose: str) -> None:
        self._inner = inner
        self._tracker = tracker
        self._purpose = purpose

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "unknown")

    def complete(self, prompt: str) -> str:
        try:
            text = self._inner.complete(prompt)
        except LLMError as exc:
            self._tracker.record(
                self._purpose,
                TokenUsage.unavailable(),
                call_ok=False,
                error=str(exc),
            )
            raise
        usage = getattr(self._inner, "last_usage", None)
        if not isinstance(usage, TokenUsage):
            usage = TokenUsage.unavailable()
        self._tracker.record(self._purpose, usage)
        return text
