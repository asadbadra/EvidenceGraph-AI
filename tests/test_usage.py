"""Stage 2.8: honest token-usage and cost tracking.

Every test runs offline. The LLM client calls `httpx.post` directly (it has
no transport injection point like `HttpClient`), so these tests monkeypatch
`httpx.post` itself -- a real socket is never opened, which the autouse
network guard in conftest.py would otherwise fail loudly.

The tests cover the three states this stage exists to keep distinct:
provider-reported usage, an estimate derived from configured prices, and
unavailable data that must never be rendered as zero.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.llm.client import FakeLLMClient, LLMError, OpenAICompatibleClient
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
    UsageTracker,
    estimate_cost,
    load_pricing,
)

API_KEY = "unit-test-key-not-a-secret"


def make_settings(**overrides) -> Settings:
    kwargs = dict(
        llm_provider="openai",
        llm_base_url="https://example.invalid/v1",
        llm_api_key=API_KEY,
        llm_model="test-model",
        llm_timeout_seconds=5.0,
        llm_max_tokens=123,
        llm_temperature=0.0,
    )
    kwargs.update(overrides)
    return Settings(**kwargs)


class PostRecorder:
    """Stand-in for httpx.post: records the call, returns a canned response.

    Patching `httpx.post` (rather than injecting a transport) is required
    because the baseline client has no transport parameter. Both the
    baseline client and the usage-aware client resolve `httpx.post` through
    the same module object, so one patch drives both.
    """

    def __init__(self, response=None, exc: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self._response = response
        self._exc = exc

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._exc is not None:
            raise self._exc
        return self._response

    @property
    def call_count(self) -> int:
        return len(self.calls)


def usage_response(usage) -> httpx.Response:
    payload = {
        "choices": [{"message": {"content": "the answer"}}],
    }
    if usage is not ...:
        payload["usage"] = usage
    return httpx.Response(200, json=payload)


def record_usage(client) -> TokenUsage:
    """Complete one prompt and return what the client retained."""
    client.complete("What is CVE-2021-44228?")
    return client.last_usage


# --------------------------------------------------------------------------
# Successful usage reporting
# --------------------------------------------------------------------------


def test_full_usage_block_is_captured_and_marked_provider_reported(monkeypatch) -> None:
    recorder = PostRecorder(usage_response(
        {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}
    ))
    monkeypatch.setattr(httpx, "post", recorder)

    usage = record_usage(UsageAwareOpenAIClient(make_settings()))

    assert usage == TokenUsage(100, 40, 140, USAGE_PROVIDER)
    assert usage.is_reported


def test_answer_text_is_unchanged_by_usage_capture(monkeypatch) -> None:
    """Capturing usage must not alter the pipeline's actual output."""
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response(
        {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
    )))
    client = UsageAwareOpenAIClient(make_settings())
    assert client.complete("q") == "the answer"


def test_alias_token_field_names_are_accepted(monkeypatch) -> None:
    """Some OpenAI-compatible servers use input_tokens/output_tokens."""
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response(
        {"input_tokens": 7, "output_tokens": 3}
    )))
    usage = record_usage(UsageAwareOpenAIClient(make_settings()))
    assert usage == TokenUsage(7, 3, 10, USAGE_PROVIDER)


def test_last_usage_resets_to_unavailable_before_each_call(monkeypatch) -> None:
    """A stale reading from a prior call must not leak into the next one."""
    recorder = PostRecorder(usage_response(
        {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}
    ))
    monkeypatch.setattr(httpx, "post", recorder)
    client = UsageAwareOpenAIClient(make_settings())
    record_usage(client)

    recorder._response = usage_response(...)  # next response has no usage
    usage = record_usage(client)
    assert usage.source == USAGE_UNAVAILABLE
    assert usage.input_tokens is None


# --------------------------------------------------------------------------
# Missing and partial usage
# --------------------------------------------------------------------------


def test_missing_usage_block_is_unavailable_not_zero(monkeypatch) -> None:
    """The core honesty rule: absent usage is None, never 0."""
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response(...)))
    usage = record_usage(UsageAwareOpenAIClient(make_settings()))

    assert usage.source == USAGE_UNAVAILABLE
    assert not usage.is_reported
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (None, None, None)


def test_partial_usage_keeps_reported_fields_and_omits_the_rest(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response(
        {"prompt_tokens": 50}
    )))
    usage = record_usage(UsageAwareOpenAIClient(make_settings()))

    assert usage.input_tokens == 50
    assert usage.output_tokens is None, "an unreported field must stay None"
    assert usage.total_tokens is None, "a total needs both parts"
    assert usage.source == USAGE_PROVIDER


def test_total_taken_from_provider_even_when_parts_absent(monkeypatch) -> None:
    """A provider's own total is used as-is; it is never recomputed away."""
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response(
        {"total_tokens": 99}
    )))
    usage = record_usage(UsageAwareOpenAIClient(make_settings()))
    assert usage.total_tokens == 99
    assert usage.input_tokens is None and usage.output_tokens is None


@pytest.mark.parametrize(
    "raw",
    [
        {"prompt_tokens": "many", "completion_tokens": 1},
        {"prompt_tokens": -5, "completion_tokens": 1},
        {"prompt_tokens": True, "completion_tokens": 1},
        {"prompt_tokens": 1.5, "completion_tokens": 1},
        "not-a-dict",
        None,
    ],
)
def test_malformed_usage_fields_degrade_to_unavailable(monkeypatch, raw) -> None:
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response(raw)))
    usage = record_usage(UsageAwareOpenAIClient(make_settings()))
    assert usage.input_tokens is None
    assert usage.output_tokens in (None, 1)


# --------------------------------------------------------------------------
# Request parity with the baseline client
# --------------------------------------------------------------------------


def test_sends_identical_request_to_baseline_client(monkeypatch) -> None:
    """The usage-aware client must be request-for-request identical to baseline.

    This is the guard that keeps Stage 2.8 from quietly changing generation
    behaviour: both clients are built from the same settings, driven with the
    same prompt, and every argument to httpx.post must match exactly.
    """
    baseline_recorder = PostRecorder(usage_response(...))
    monkeypatch.setattr(httpx, "post", baseline_recorder)
    baseline_text = OpenAICompatibleClient(make_settings()).complete("same prompt")

    usage_recorder = PostRecorder(usage_response(
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    ))
    monkeypatch.setattr(httpx, "post", usage_recorder)
    usage_text = UsageAwareOpenAIClient(make_settings()).complete("same prompt")

    assert baseline_recorder.call_count == 1 and usage_recorder.call_count == 1
    base_url, base_kwargs = baseline_recorder.calls[0]
    live_url, live_kwargs = usage_recorder.calls[0]
    assert base_url == live_url
    assert base_kwargs == live_kwargs
    assert baseline_text == usage_text, "capturing usage must not change the answer"


def test_request_carries_the_configured_model_and_limits(monkeypatch) -> None:
    recorder = PostRecorder(usage_response(...))
    monkeypatch.setattr(httpx, "post", recorder)
    UsageAwareOpenAIClient(make_settings()).complete("q")

    _, kwargs = recorder.calls[0]
    assert kwargs["json"]["model"] == "test-model"
    assert kwargs["json"]["max_tokens"] == 123
    assert kwargs["json"]["temperature"] == 0.0
    assert kwargs["headers"]["Authorization"] == f"Bearer {API_KEY}"


def test_api_key_is_sent_as_a_header_and_never_in_the_url(monkeypatch) -> None:
    recorder = PostRecorder(usage_response(...))
    monkeypatch.setattr(httpx, "post", recorder)
    UsageAwareOpenAIClient(make_settings()).complete("q")

    url, kwargs = recorder.calls[0]
    assert API_KEY not in url
    assert kwargs["headers"]["Authorization"] == f"Bearer {API_KEY}"


def test_usage_aware_client_still_refuses_an_unconfigured_key() -> None:
    client = UsageAwareOpenAIClient(make_settings(llm_api_key=""))
    with pytest.raises(LLMError, match="LLM_API_KEY is not configured"):
        client.complete("q")


def test_malformed_content_still_raises_llm_error(monkeypatch) -> None:
    """Usage capture must not mask the baseline's response-shape checks."""
    bad = httpx.Response(200, json={"choices": [], "usage": {"prompt_tokens": 3}})
    monkeypatch.setattr(httpx, "post", PostRecorder(bad))
    with pytest.raises(LLMError, match="missing choices"):
        UsageAwareOpenAIClient(make_settings()).complete("q")


# --------------------------------------------------------------------------
# Pricing configuration and cost estimation
# --------------------------------------------------------------------------


def test_no_pricing_configured_loads_as_none() -> None:
    assert load_pricing(make_settings()) is None


def test_pricing_loads_when_both_prices_are_set() -> None:
    pricing = load_pricing(
        make_settings(llm_price_input_per_million=2.5, llm_price_output_per_million=10.0)
    )
    assert pricing == Pricing(2.5, 10.0)


@pytest.mark.parametrize(
    ("inp", "out"),
    [(2.5, None), (None, 10.0)],
    ids=["input-only", "output-only"],
)
def test_partial_pricing_is_rejected_not_silently_applied(inp, out) -> None:
    with pytest.raises(PricingError, match="incomplete pricing"):
        load_pricing(make_settings(
            llm_price_input_per_million=inp, llm_price_output_per_million=out
        ))


@pytest.mark.parametrize("value", [-1.0, -0.01])
def test_negative_pricing_is_rejected(value) -> None:
    with pytest.raises(PricingError, match="non-negative"):
        load_pricing(make_settings(
            llm_price_input_per_million=value, llm_price_output_per_million=1.0
        ))


def test_zero_pricing_is_allowed_and_yields_zero_cost() -> None:
    """Zero is a legitimate configured price (free tier), not a missing value."""
    pricing = load_pricing(make_settings(
        llm_price_input_per_million=0.0, llm_price_output_per_million=0.0
    ))
    usage = TokenUsage(1000, 1000, 2000, USAGE_PROVIDER)
    assert estimate_cost(usage, pricing) == CostEstimate(0.0, COST_ESTIMATED, "provider-reported tokens x configured prices")


def test_cost_is_estimated_only_when_pricing_and_usage_both_exist() -> None:
    pricing = Pricing(2.0, 10.0)
    usage = TokenUsage(1_000_000, 500_000, 1_500_000, USAGE_PROVIDER)
    assert estimate_cost(usage, pricing).usd == 2.0 + 5.0


def test_cost_is_unavailable_without_pricing_even_with_usage() -> None:
    usage = TokenUsage(1000, 1000, 2000, USAGE_PROVIDER)
    result = estimate_cost(usage, None)
    assert result.usd is None
    assert result.source == COST_UNAVAILABLE
    assert "no per-token pricing configured" in result.reason


def test_cost_is_unavailable_without_usage_even_with_pricing() -> None:
    result = estimate_cost(TokenUsage.unavailable(), Pricing(1.0, 1.0))
    assert result.usd is None
    assert result.source == COST_UNAVAILABLE
    assert "provider did not report" in result.reason


def test_cost_is_unavailable_on_partial_usage(monkeypatch) -> None:
    """Pricing cannot proceed when a required half of the usage is absent."""
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response({"prompt_tokens": 500})))
    usage = record_usage(UsageAwareOpenAIClient(make_settings()))
    result = estimate_cost(usage, Pricing(1.0, 2.0))
    assert result.usd is None and result.source == COST_UNAVAILABLE


# --------------------------------------------------------------------------
# Tracker: records, aggregation, and the null-not-zero rule
# --------------------------------------------------------------------------


def test_tracker_records_provider_model_run_and_timestamp() -> None:
    tracker = UsageTracker(run_id="run-7", provider="openai", model="m1")
    entry = tracker.record("generation", TokenUsage(10, 5, 15, USAGE_PROVIDER))

    assert entry.run_id == "run-7"
    assert entry.provider == "openai"
    assert entry.model == "m1"
    assert entry.purpose == "generation"
    assert entry.timestamp, "a timestamp must be recorded"
    assert "T" in entry.timestamp, "expected an ISO 8601 UTC timestamp"


def test_records_never_carry_the_api_key(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response(
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    )))
    tracker = UsageTracker(run_id="r", provider="openai", model="m")
    client = TrackingLLMClient(
        UsageAwareOpenAIClient(make_settings()), tracker, "generation"
    )
    client.complete("what is the answer?")

    entry = tracker.records[0]
    assert API_KEY not in repr(entry)
    assert API_KEY not in repr(tracker.summary)
    assert API_KEY not in str(entry.usage) + str(entry.cost)


def test_summary_sums_only_when_every_call_reported_usage() -> None:
    tracker = UsageTracker(run_id="r", provider="p", model="m")
    tracker.record("generation", TokenUsage(100, 50, 150, USAGE_PROVIDER))
    tracker.record("judge", TokenUsage(20, 10, 30, USAGE_PROVIDER))

    summary = tracker.summary
    assert summary.total_input_tokens == 120
    assert summary.total_output_tokens == 60
    assert summary.total_tokens == 180
    assert summary.calls == 2
    assert summary.usage_complete


def test_summary_totals_are_null_when_any_usage_is_missing() -> None:
    """A partial sum must not masquerade as a total."""
    tracker = UsageTracker(run_id="r", provider="p", model="m")
    tracker.record("generation", TokenUsage(100, 50, 150, USAGE_PROVIDER))
    tracker.record("judge", TokenUsage.unavailable())

    summary = tracker.summary
    assert summary.total_input_tokens is None
    assert summary.total_output_tokens is None
    assert summary.total_tokens is None
    assert summary.records_with_usage == 1
    assert summary.records_without_usage == 1
    assert not summary.usage_complete


def test_summary_of_no_calls_is_all_null_not_zero() -> None:
    summary = UsageTracker(run_id="r", provider="p", model="m").summary
    assert summary.total_input_tokens is None
    assert summary.total_cost_usd is None
    assert summary.cost_source == COST_UNAVAILABLE


def test_summary_reports_cost_only_when_every_call_is_priceable() -> None:
    tracker = UsageTracker(
        run_id="r", provider="p", model="m", pricing=Pricing(1.0, 2.0)
    )
    tracker.record("generation", TokenUsage(1_000_000, 0, 1_000_000, USAGE_PROVIDER))
    tracker.record("judge", TokenUsage.unavailable())

    summary = tracker.summary
    assert summary.total_cost_usd is None, "a partial cost must not be presented as total"
    assert summary.records_priced == 1
    assert summary.cost_source == COST_UNAVAILABLE
    assert "provider did not report" in summary.cost_note


def test_summary_costs_sum_when_all_calls_priceable() -> None:
    tracker = UsageTracker(
        run_id="r", provider="p", model="m", pricing=Pricing(1.0, 2.0)
    )
    tracker.record("generation", TokenUsage(1_000_000, 250_000, 1_250_000, USAGE_PROVIDER))
    tracker.record("judge", TokenUsage(1_000_000, 250_000, 1_250_000, USAGE_PROVIDER))

    summary = tracker.summary
    assert summary.total_cost_usd == 2 * (1.0 + 0.5)
    assert summary.cost_source == COST_ESTIMATED


# --------------------------------------------------------------------------
# TrackingLLMClient over real and fake providers
# --------------------------------------------------------------------------


def test_tracking_client_records_provider_usage(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response(
        {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
    )))
    tracker = UsageTracker(run_id="r", provider="openai", model="test-model")
    client = TrackingLLMClient(
        UsageAwareOpenAIClient(make_settings()), tracker, "judge"
    )

    assert client.complete("q") == "the answer"
    assert client.model == "test-model"
    entry = tracker.records[0]
    assert entry.usage == TokenUsage(8, 4, 12, USAGE_PROVIDER)
    assert entry.purpose == "judge"


def test_tracking_a_client_without_usage_records_unavailable(monkeypatch) -> None:
    """The mock provider surfaces no usage; that is recorded, not invented."""
    monkeypatch.setattr(httpx, "post", PostRecorder(usage_response(...)))
    tracker = UsageTracker(run_id="r", provider="mock", model="offline-mock")
    fake = FakeLLMClient(model="offline-mock", scripted_response="stub answer")

    client = TrackingLLMClient(fake, tracker, "generation")
    assert client.complete("q") == "stub answer"

    entry = tracker.records[0]
    assert entry.usage.source == USAGE_UNAVAILABLE
    assert entry.usage.input_tokens is None
    assert entry.cost.usd is None


def test_tracking_client_records_failures_and_reraises(monkeypatch) -> None:
    """A provider error is recorded as a failed call and still raised."""
    boom = httpx.ConnectError("connection refused")
    monkeypatch.setattr(httpx, "post", PostRecorder(exc=boom))
    tracker = UsageTracker(run_id="r", provider="openai", model="m")
    client = TrackingLLMClient(
        UsageAwareOpenAIClient(make_settings()), tracker, "generation"
    )

    with pytest.raises(LLMError, match="LLM request failed"):
        client.complete("q")

    entry = tracker.records[0]
    assert not entry.call_ok
    assert entry.error and "LLM request failed" in entry.error
    assert entry.usage.source == USAGE_UNAVAILABLE
    assert "connection refused" in entry.error


def test_failed_calls_counted_separately_in_summary(monkeypatch) -> None:
    boom = httpx.ConnectError("connection refused")
    monkeypatch.setattr(httpx, "post", PostRecorder(exc=boom))
    tracker = UsageTracker(run_id="r", provider="openai", model="m")
    client = TrackingLLMClient(
        UsageAwareOpenAIClient(make_settings()), tracker, "generation"
    )
    with pytest.raises(LLMError):
        client.complete("q")

    summary = tracker.summary
    assert summary.calls == 1
    assert summary.calls_failed == 1
    assert summary.calls_ok == 0
    assert summary.total_input_tokens is None


def test_error_message_never_contains_the_api_key(monkeypatch) -> None:
    boom = httpx.ConnectError("connection refused")
    monkeypatch.setattr(httpx, "post", PostRecorder(exc=boom))
    tracker = UsageTracker(run_id="r", provider="openai", model="m")
    client = TrackingLLMClient(
        UsageAwareOpenAIClient(make_settings()), tracker, "generation"
    )
    with pytest.raises(LLMError):
        client.complete("q")
    assert API_KEY not in (tracker.records[0].error or "")
