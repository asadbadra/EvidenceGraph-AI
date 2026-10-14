"""Shared HTTP client wrapper for advisory source fetchers.

Everything network-specific lives here: explicit timeouts, bounded retries,
exponential backoff, `Retry-After` handling, and typed, human-readable
errors. Fetchers (`app.ingestion.fetchers`) only decide *what* to request;
this module decides *how* the request is made and what happens when it
fails. Parsing and persistence never see the network.

Retry policy (deliberately conservative and documented, not magic):

- Retried: HTTP 429, 500, 502, 503, 504, connect/read timeouts, and
  transport-level network failures.
- Never retried: 401/403/404/422 and any other 4xx. These are client
  errors; retrying them hammers the source and hides the real problem.
  (NVD can report rate-limit violations as 403 as well as 429. We surface a
  clear error instead of guessing, because a blocked API key and a
  rate-limited request need different fixes.)
- Delay: `Retry-After` if the server sent one (seconds or HTTP-date),
  otherwise `base * 2**attempt`, both capped by `max_retry_after_seconds`
  so a hostile or broken server cannot stall a run unboundedly.
- The retry budget is fixed: `max_retries` extra attempts, never more.

No jitter is added, so backoff is deterministic and testable offline.
"""

from __future__ import annotations

import time
from datetime import timezone as dt_timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

import httpx

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_MAX_SECONDS = 30.0
DEFAULT_MAX_RETRY_AFTER_SECONDS = 60.0

# Server errors and rate limiting: worth another attempt.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Identifies this client to source operators (NIST/CISA ask for a contact
# string rather than a bare library User-Agent).
DEFAULT_USER_AGENT = "evidencegraph-ai/0.1 (research prototype; contact via repository)"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class HttpError(RuntimeError):
    """Base class for every failure raised by this module."""


class HttpTimeoutError(HttpError):
    """The request did not complete within the configured timeout."""


class HttpNetworkError(HttpError):
    """DNS/connection/TLS-level failure before a response was received."""


class HttpDecodeError(HttpError):
    """The server returned something that is not valid JSON."""


class HttpStatusError(HttpError):
    """The server answered with an HTTP error status."""

    def __init__(
        self,
        status_code: int,
        url: str,
        message: str,
        *,
        body_snippet: str = "",
        server_message: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.body_snippet = body_snippet
        # NVD 2.0 puts diagnostic text in a `message` response header.
        self.server_message = server_message
        self.retry_after = retry_after


def _parse_retry_after(value: str | None, now: Callable[[], float]) -> float | None:
    """Parse a `Retry-After` header (delta-seconds or HTTP-date) -> seconds.

    Returns None when absent or unparseable, so callers fall back to
    exponential backoff instead of trusting a malformed header. `now` is
    injectable so HTTP-date parsing stays testable without real waiting.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        # RFC 7231 HTTP-date is GMT; naive datetimes are treated as UTC.
        when = when.replace(tzinfo=dt_timezone.utc)
    return max(0.0, when.timestamp() - now())


def _body_snippet(response: httpx.Response, limit: int = 300) -> str:
    """First `limit` characters of the body, safe to embed in an error."""
    try:
        return response.text[:limit]
    except Exception:  # noqa: BLE001 - never let diagnostics break error paths
        return ""


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

class HttpClient:
    """Thin, retrying JSON-over-HTTP client built on `httpx.Client`.

    `transport` exists so tests can inject `httpx.MockTransport` and run
    fully offline; production code leaves it as None (real network).
    `sleep` and `clock` are injectable for the same reason: retry and
    rate-limit behaviour must be assertable without waiting in real time.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
        max_retry_after_seconds: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
        headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self._max_retries = int(max_retries)
        self._backoff_base = float(backoff_base_seconds)
        self._backoff_max = float(backoff_max_seconds)
        self._max_retry_after = float(max_retry_after_seconds)
        self._sleep = sleep
        self._clock = clock
        self.attempts_log: list[int] = []  # attempts per call, for tests/debug

        merged = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
        }
        if headers:
            merged.update(headers)

        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            headers=merged,
            transport=transport,
            follow_redirects=True,
        )

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- public API --------------------------------------------------------
    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """GET `url` and return the decoded JSON body.

        Raises `HttpTimeoutError`, `HttpNetworkError`, `HttpStatusError`,
        or `HttpDecodeError` — never a bare `httpx` exception.
        """
        response = self._request_with_retries(
            "GET", url, params=params, headers=headers
        )
        try:
            return response.json()
        except ValueError as exc:
            raise HttpDecodeError(
                f"{url} returned malformed JSON (content-type "
                f"{response.headers.get('content-type', 'unknown')!r}, "
                f"HTTP {response.status_code}): {exc}"
            ) from exc

    # -- internals ---------------------------------------------------------
    def _request_with_retries(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        attempts = self._max_retries + 1
        last_error: HttpError | None = None
        delay = 0.0

        for attempt in range(attempts):
            if attempt:
                self._sleep(delay)
            try:
                response = self._client.request(
                    method, url, params=params, headers=headers
                )
            except httpx.TimeoutException as exc:
                last_error = HttpTimeoutError(
                    f"{method} {url} timed out after "
                    f"{self._client.timeout.read or 'unknown'}s "
                    f"(attempt {attempt + 1}/{attempts}): {exc}"
                )
                if attempt >= self._max_retries:
                    break
                delay = self._backoff_delay(attempt)
                continue
            except httpx.TransportError as exc:
                last_error = HttpNetworkError(
                    f"{method} {url} failed with a network error "
                    f"(attempt {attempt + 1}/{attempts}): {exc}"
                )
                if attempt >= self._max_retries:
                    break
                delay = self._backoff_delay(attempt)
                continue

            if response.status_code < 400:
                self.attempts_log.append(attempt + 1)
                return response

            error = self._status_error(response, url, attempts, attempt)
            if (
                response.status_code in RETRYABLE_STATUS_CODES
                and attempt < self._max_retries
            ):
                last_error = error
                retry_after = error.retry_after
                if retry_after is not None:
                    delay = min(retry_after, self._max_retry_after)
                else:
                    delay = self._backoff_delay(attempt)
                continue
            self.attempts_log.append(attempt + 1)
            raise error

        self.attempts_log.append(attempts)
        if last_error is None:  # unreachable; keeps the type checker happy
            raise HttpError(f"{method} {url} failed with no recorded error")
        raise last_error

    def _backoff_delay(self, attempt: int) -> float:
        """Deterministic exponential backoff, capped (no jitter)."""
        return min(self._backoff_max, self._backoff_base * (2 ** attempt))

    def _status_error(
        self, response: httpx.Response, url: str, attempts: int, attempt: int
    ) -> HttpStatusError:
        status = response.status_code
        server_message = response.headers.get("message", "").strip()
        retry_after = _parse_retry_after(response.headers.get("retry-after"), self._clock)
        snippet = _body_snippet(response)

        if status == 403:
            hint = (
                " Access denied. For the NVD API this usually means a "
                "missing/invalid `apiKey` header or that the client was "
                "blocked for exceeding the published rate limit. Not retried."
            )
        elif status == 429:
            hint = " Rate limited; retrying with backoff." if attempt < attempts - 1 else (
                " Rate limited and the retry budget is exhausted."
            )
        elif status >= 500:
            hint = " Server-side error."
        else:
            hint = ""

        detail = f" [{server_message}]" if server_message else ""
        message = (
            f"{url} returned HTTP {status}{detail} "
            f"(attempt {attempt + 1}/{attempts}).{hint}"
            + (f" Body starts: {snippet!r}" if snippet else "")
        )
        return HttpStatusError(
            status,
            url,
            message,
            body_snippet=snippet,
            server_message=server_message,
            retry_after=retry_after,
        )
