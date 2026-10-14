"""Offline tests for the HTTP fetch layer (Phase 1, Step 3).

Every test drives `HttpClient` through `httpx.MockTransport`, so the suite
makes **no real network requests** (enforced globally by the autouse
`_block_real_network` fixture in conftest.py). `sleep` and `clock` are
injected so retry/backoff/rate-limit behaviour is asserted exactly, in
milliseconds, without real waiting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from app.config import Settings, get_settings
from app.ingestion.fetchers import (
    FetchError,
    KevFetcher,
    NvdFetcher,
    build_http_client,
    build_kev_fetcher,
    build_nvd_fetcher,
)
from app.ingestion.http_client import (
    DEFAULT_USER_AGENT,
    HttpClient,
    HttpDecodeError,
    HttpError,
    HttpNetworkError,
    HttpStatusError,
    HttpTimeoutError,
)
from app.ingestion.parsers import KEV_FEED_URL, NVD_API_URL


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

class SleepRecorder:
    """Stand-in for time.sleep plus a fake monotonic clock."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


class ScriptedHandler:
    """Queue of responses (or exceptions) served one per request."""

    def __init__(self, *steps: httpx.Response | Exception) -> None:
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.steps:
            raise AssertionError("handler received more requests than expected")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    @property
    def call_count(self) -> int:
        return len(self.requests)


def json_response(
    payload: Any, status_code: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
    return httpx.Response(status_code, text=body, headers=headers)


def make_client(
    handler: ScriptedHandler,
    rec: SleepRecorder,
    **kwargs: Any,
) -> HttpClient:
    kwargs.setdefault("max_retries", 3)
    kwargs.setdefault("backoff_base_seconds", 1.0)
    kwargs.setdefault("backoff_max_seconds", 30.0)
    return HttpClient(
        transport=httpx.MockTransport(handler),
        sleep=rec.sleep,
        clock=rec.clock,
        **kwargs,
    )


def make_nvd_fetcher(
    client: HttpClient,
    rec: SleepRecorder,
    *,
    interval: float | None = None,
    **kwargs: Any,
) -> NvdFetcher:
    """Build an NvdFetcher whose pacing sleep/clock are the recorded fakes.

    Forgetting to inject these is expensive: the fetcher would otherwise
    call the real time.sleep and stall the suite by the pacing interval.
    """
    if interval is not None:
        kwargs["min_request_interval_seconds"] = interval
    return NvdFetcher(client, sleep=rec.sleep, clock=rec.clock, **kwargs)


KEV_PAYLOAD = {
    "catalogVersion": "2024.10.01",
    "dateReleased": "2024-10-01T00:00:00.000Z",
    "count": 1,
    "vulnerabilities": [{"cveID": "CVE-2021-44228"}],
}

NVD_PAYLOAD = {
    "resultsPerPage": 1,
    "startIndex": 0,
    "totalResults": 1,
    "format": "NVD_CVE",
    "vulnerabilities": [{"cve": {"id": "CVE-2021-44228"}}],
}


# --------------------------------------------------------------------------
# Success paths
# --------------------------------------------------------------------------

def test_kev_fetch_returns_decoded_payload() -> None:
    handler = ScriptedHandler(json_response(KEV_PAYLOAD))
    rec = SleepRecorder()
    with make_client(handler, rec) as client:
        payload = KevFetcher(client).fetch()

    assert payload == KEV_PAYLOAD
    assert payload["vulnerabilities"][0]["cveID"] == "CVE-2021-44228"
    assert handler.call_count == 1
    request = handler.requests[0]
    assert request.url == KEV_FEED_URL
    assert request.method == "GET"
    assert request.headers["Accept"] == "application/json"
    assert "evidencegraph-ai" in request.headers["User-Agent"]
    assert rec.sleeps == []  # success on the first attempt: no sleeping


def test_nvd_fetch_passes_params_and_omits_header_without_key() -> None:
    handler = ScriptedHandler(json_response(NVD_PAYLOAD))
    rec = SleepRecorder()
    with make_client(handler, rec) as client:
        fetcher = make_nvd_fetcher(client, rec, api_key="", interval=0.0)
        payload = fetcher.fetch({"resultsPerPage": 10, "startIndex": 0})

    assert payload == NVD_PAYLOAD
    request = handler.requests[0]
    assert str(request.url).startswith(NVD_API_URL)
    assert request.url.params["resultsPerPage"] == "10"
    assert "apiKey" not in request.headers


def test_nvd_sends_api_key_in_header_not_query() -> None:
    handler = ScriptedHandler(json_response(NVD_PAYLOAD))
    rec = SleepRecorder()
    with make_client(handler, rec) as client:
        fetcher = make_nvd_fetcher(client, rec, api_key="s3cret-key", interval=0.0)
        fetcher.fetch_cve("CVE-2021-44228")

    request = handler.requests[0]
    assert request.headers["apiKey"] == "s3cret-key"
    assert "s3cret-key" not in str(request.url)  # header only, never the URL
    assert request.url.params["cveId"] == "CVE-2021-44228"


def test_fetcher_returns_payload_unparsed() -> None:
    """Fetchers stop at decoded JSON; record conversion is the parser's job."""
    handler = ScriptedHandler(json_response(NVD_PAYLOAD))
    rec = SleepRecorder()
    with make_client(handler, rec) as client:
        payload = make_nvd_fetcher(client, rec, interval=0.0).fetch()
    assert set(payload) == {
        "resultsPerPage",
        "startIndex",
        "totalResults",
        "format",
        "vulnerabilities",
    }


def test_nvd_rejects_invalid_cve_id_before_any_request() -> None:
    handler = ScriptedHandler()
    rec = SleepRecorder()
    with make_client(handler, rec) as client:
        fetcher = make_nvd_fetcher(client, rec, interval=0.0)
        with pytest.raises(FetchError, match="invalid CVE identifier"):
            fetcher.fetch_cve("not-a-cve")
    assert handler.call_count == 0  # no request was made


# --------------------------------------------------------------------------
# Timeouts and network failures
# --------------------------------------------------------------------------

def test_timeout_is_retried_then_raises_typed_error() -> None:
    handler = ScriptedHandler(*[httpx.ConnectTimeout("timed out")] * 4)
    rec = SleepRecorder()
    client = make_client(handler, rec, max_retries=2)
    with pytest.raises(HttpTimeoutError, match="timed out"):
        client.get_json("https://example.test/feed.json")
    # 1 initial attempt + 2 retries, with exponential backoff between them.
    assert handler.call_count == 3
    assert rec.sleeps == [1.0, 2.0]


def test_timeout_error_is_an_http_error() -> None:
    handler = ScriptedHandler(*[httpx.ReadTimeout("slow")] * 2)
    rec = SleepRecorder()
    client = make_client(handler, rec, max_retries=1)
    with pytest.raises(HttpError):
        client.get_json("https://example.test/slow.json")


def test_network_failure_is_retried_and_typed() -> None:
    handler = ScriptedHandler(*[httpx.ConnectError("dns down")] * 5)
    rec = SleepRecorder()
    client = make_client(handler, rec, max_retries=2)
    with pytest.raises(HttpNetworkError, match="network error"):
        client.get_json("https://example.test/feed.json")
    assert handler.call_count == 3
    assert rec.sleeps == [1.0, 2.0]


def test_timeout_recovers_on_retry() -> None:
    handler = ScriptedHandler(httpx.ConnectTimeout("blip"), json_response(KEV_PAYLOAD))
    rec = SleepRecorder()
    client = make_client(handler, rec)
    assert client.get_json("https://example.test/feed.json") == KEV_PAYLOAD
    assert handler.call_count == 2
    assert rec.sleeps == [1.0]


# --------------------------------------------------------------------------
# Rate limiting (429 + Retry-After) and server errors (503)
# --------------------------------------------------------------------------

def test_429_honours_retry_after_seconds() -> None:
    handler = ScriptedHandler(
        json_response({"error": "rate limited"}, 429, headers={"Retry-After": "7"}),
        json_response({"error": "rate limited"}, 429, headers={"Retry-After": "7"}),
        json_response(KEV_PAYLOAD),
    )
    rec = SleepRecorder()
    client = make_client(handler, rec)
    assert client.get_json("https://example.test/feed.json") == KEV_PAYLOAD
    assert handler.call_count == 3
    assert rec.sleeps == [7.0, 7.0]


def test_429_without_retry_after_uses_exponential_backoff() -> None:
    handler = ScriptedHandler(
        json_response({"error": "slow down"}, 429),
        json_response(KEV_PAYLOAD),
    )
    rec = SleepRecorder()
    client = make_client(handler, rec, backoff_base_seconds=0.5)
    assert client.get_json("https://example.test/feed.json") == KEV_PAYLOAD
    assert rec.sleeps == [0.5]


def test_429_without_retry_after_uses_exponential_backoff_step2() -> None:
    handler = ScriptedHandler(
        json_response({"error": "slow down"}, 429),
        json_response({"error": "slow down"}, 429),
        json_response(KEV_PAYLOAD),
    )
    rec = SleepRecorder()
    client = make_client(handler, rec, backoff_base_seconds=1.0)
    assert client.get_json("https://example.test/feed.json") == KEV_PAYLOAD
    assert rec.sleeps == [1.0, 2.0]


def test_retry_after_is_capped_to_bound_a_hostile_server() -> None:
    handler = ScriptedHandler(
        json_response({}, 429, headers={"Retry-After": "86400"}),
        json_response(KEV_PAYLOAD),
    )
    rec = SleepRecorder()
    client = make_client(handler, rec, max_retry_after_seconds=15.0)
    assert client.get_json("https://example.test/feed.json") == KEV_PAYLOAD
    assert rec.sleeps == [15.0]


def test_retry_after_http_date_is_converted_to_seconds() -> None:
    header_at = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
    handler = ScriptedHandler(
        json_response({}, 429, headers={"Retry-After": format_datetime(header_at)}),
        json_response(KEV_PAYLOAD),
    )
    rec = SleepRecorder()
    # Fake clock pinned 12 seconds before the HTTP-date the server named.
    rec.clock = lambda: header_at.timestamp() - 12.0  # type: ignore[method-assign]
    client = make_client(handler, rec)
    assert client.get_json("https://example.test/feed.json") == KEV_PAYLOAD
    assert rec.sleeps == [12.0]


def test_unparseable_retry_after_falls_back_to_backoff() -> None:
    handler = ScriptedHandler(
        json_response({}, 429, headers={"Retry-After": "soonish"}),
        json_response(KEV_PAYLOAD),
    )
    rec = SleepRecorder()
    client = make_client(handler, rec, backoff_base_seconds=1.0)
    assert client.get_json("https://example.test/feed.json") == KEV_PAYLOAD
    assert rec.sleeps == [1.0]


def test_persistent_503_raises_status_error_with_bounded_retries() -> None:
    handler = ScriptedHandler(*[json_response({}, 503)] * 10)
    rec = SleepRecorder()
    client = make_client(handler, rec, max_retries=2)
    with pytest.raises(HttpStatusError) as excinfo:
        client.get_json("https://example.test/feed.json")
    error = excinfo.value
    assert error.status_code == 503
    assert handler.call_count == 3  # never more than max_retries + 1
    assert rec.sleeps == [1.0, 2.0]
    assert "HTTP 503" in str(error)


def test_503_with_retry_after_is_honoured() -> None:
    handler = ScriptedHandler(
        json_response({}, 503, headers={"Retry-After": "3"}),
        json_response(KEV_PAYLOAD),
    )
    rec = SleepRecorder()
    client = make_client(handler, rec)
    assert client.get_json("https://example.test/feed.json") == KEV_PAYLOAD
    assert rec.sleeps == [3.0]


# --------------------------------------------------------------------------
# Client errors (403 / 404): clear errors, no retries
# --------------------------------------------------------------------------

def test_403_fails_fast_with_clear_message_and_server_detail() -> None:
    handler = ScriptedHandler(
        json_response({"error": "forbidden"}, 403, headers={"message": "Invalid apiKey."})
    )
    rec = SleepRecorder()
    client = make_client(handler, rec)
    with pytest.raises(HttpStatusError) as excinfo:
        client.get_json("https://services.nvd.nist.gov/rest/json/cves/2.0")
    error = excinfo.value
    assert error.status_code == 403
    assert handler.call_count == 1  # 403 is never retried
    assert rec.sleeps == []
    assert "HTTP 403" in str(error)
    assert "apiKey" in error.server_message
    assert "Not retried" in str(error)


def test_404_is_not_retried() -> None:
    handler = ScriptedHandler(json_response("missing", 404))
    rec = SleepRecorder()
    client = make_client(handler, rec)
    with pytest.raises(HttpStatusError) as excinfo:
        client.get_json("https://example.test/gone.json")
    assert excinfo.value.status_code == 404
    assert handler.call_count == 1


def test_status_error_exposes_url_and_body_snippet() -> None:
    handler = ScriptedHandler(json_response({"detail": "nope"}, 422))
    rec = SleepRecorder()
    client = make_client(handler, rec)
    with pytest.raises(HttpStatusError) as excinfo:
        client.get_json("https://example.test/bad.json")
    error = excinfo.value
    assert error.url == "https://example.test/bad.json"
    assert "nope" in error.body_snippet


# --------------------------------------------------------------------------
# Malformed JSON
# --------------------------------------------------------------------------

def test_malformed_json_raises_decode_error_without_retry() -> None:
    handler = ScriptedHandler(httpx.Response(200, text="<html>not json</html>"))
    rec = SleepRecorder()
    client = make_client(handler, rec)
    with pytest.raises(HttpDecodeError, match="malformed JSON"):
        client.get_json("https://example.test/feed.json")
    assert handler.call_count == 1  # a 200 with a bad body is not retried


def test_empty_body_raises_decode_error() -> None:
    handler = ScriptedHandler(httpx.Response(200, text=""))
    rec = SleepRecorder()
    client = make_client(handler, rec)
    with pytest.raises(HttpDecodeError):
        client.get_json("https://example.test/feed.json")


# --------------------------------------------------------------------------
# NVD pacing (rate-limit courtesy)
# --------------------------------------------------------------------------

def test_nvd_paces_requests_without_a_key() -> None:
    handler = ScriptedHandler(json_response(NVD_PAYLOAD), json_response(NVD_PAYLOAD))
    rec = SleepRecorder()
    with make_client(handler, rec) as client:
        fetcher = make_nvd_fetcher(client, rec)  # default interval: 6s unkeyed
        assert fetcher.min_request_interval_seconds == 6.0
        fetcher.fetch_cve("CVE-2021-44228")
        fetcher.fetch_cve("CVE-2022-22965")
    assert rec.sleeps == [6.0]  # one pacing sleep between two requests


def test_nvd_default_interval_is_shorter_with_a_key() -> None:
    handler = ScriptedHandler(json_response(NVD_PAYLOAD), json_response(NVD_PAYLOAD))
    rec = SleepRecorder()
    with make_client(handler, rec) as client:
        fetcher = make_nvd_fetcher(client, rec, api_key="k")
        assert fetcher.min_request_interval_seconds == 1.0
        fetcher.fetch_cve("CVE-2021-44228")
        fetcher.fetch_cve("CVE-2022-22965")
    assert rec.sleeps == [1.0]


def test_nvd_does_not_sleep_when_interval_already_elapsed() -> None:
    handler = ScriptedHandler(json_response(NVD_PAYLOAD), json_response(NVD_PAYLOAD))
    rec = SleepRecorder()
    with make_client(handler, rec) as client:
        fetcher = make_nvd_fetcher(client, rec, interval=6.0)
        fetcher.fetch()
        rec.now += 10.0  # more than the interval has passed
        fetcher.fetch()
    assert rec.sleeps == []


def test_nvd_rejects_negative_interval() -> None:
    handler = ScriptedHandler()
    rec = SleepRecorder()
    with make_client(handler, rec) as client:
        with pytest.raises(ValueError, match="min_request_interval_seconds"):
            make_nvd_fetcher(client, rec, interval=-1)


# --------------------------------------------------------------------------
# Client construction guards
# --------------------------------------------------------------------------

def test_client_rejects_invalid_settings() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        HttpClient(max_retries=-1)
    with pytest.raises(ValueError, match="timeout_seconds"):
        HttpClient(timeout_seconds=0)


def test_retry_budget_of_zero_means_single_attempt() -> None:
    handler = ScriptedHandler(json_response({}, 503))
    rec = SleepRecorder()
    client = make_client(handler, rec, max_retries=0)
    with pytest.raises(HttpStatusError):
        client.get_json("https://example.test/feed.json")
    assert handler.call_count == 1
    assert rec.sleeps == []


def test_default_user_agent_is_stable_and_identifying() -> None:
    assert DEFAULT_USER_AGENT.startswith("evidencegraph-ai/")


# --------------------------------------------------------------------------
# Settings wiring (still offline)
# --------------------------------------------------------------------------

def test_settings_carry_fetch_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.http_timeout_seconds == 30.0
    assert settings.http_max_retries == 3
    assert settings.kev_feed_url == KEV_FEED_URL
    assert settings.nvd_api_url == NVD_API_URL
    assert settings.nvd_min_request_interval_seconds is None


def test_builders_wire_settings_into_fetchers() -> None:
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    client = build_http_client(settings)
    try:
        kev = build_kev_fetcher(settings, client)
        nvd = build_nvd_fetcher(settings, client)
        assert kev.feed_url == KEV_FEED_URL
        assert nvd.api_url == NVD_API_URL
        assert nvd.min_request_interval_seconds == 6.0  # unkeyed default
    finally:
        client.close()
        get_settings.cache_clear()


# --------------------------------------------------------------------------
# Guard: this module must never open a real socket
# --------------------------------------------------------------------------

def test_module_uses_injected_transport_only() -> None:
    """Sanity check that the autouse network guard is actually active."""
    import socket

    with pytest.raises(RuntimeError, match="blocked in tests"):
        socket.create_connection(("example.com", 80), timeout=1)
