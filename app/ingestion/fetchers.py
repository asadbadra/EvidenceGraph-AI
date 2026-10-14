"""Source-specific HTTP fetchers (network only: nothing else).

Scope is deliberately narrow:

    raw bytes on the wire  ->  (this module)  ->  decoded JSON payload
                                                   -> (parsers) AdvisoryRecord
                                                   -> (persistence, Step 4) SQLite

Fetchers return the *decoded payload*, not records. They never parse
records, never touch the database, and never sleep longer than the
documented backoff/pacing budgets. That separation is what makes the
parsers' pure-function tests reusable against real captured payloads.

Sources and their official interfaces (verified against vendor docs):

- CISA KEV catalog: a single static JSON file, no auth, CC0 1.0 licensed.
  CISA asks that reuse not imply CISA/DHS endorsement and that the CISA
  logo/DHS seal not be used. We fetch politely: one request, an
  identifiable User-Agent, no scraping of HTML pages.
  https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
- NVD API 2.0: JSON API. Public rate limit is 5 requests per rolling 30 s
  without an API key and 50 per 30 s with one; the key goes in the
  `apiKey` request header. NIST asks clients to sleep ~6 s between
  requests and to use the last-modified parameters rather than bulk
  re-downloads. `NvdFetcher` paces requests accordingly and sends the key
  only when configured.
  https://services.nvd.nist.gov/rest/json/cves/2.0
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from app.config import Settings
from app.ingestion.http_client import HttpClient
from app.ingestion.models import is_valid_cve_id
from app.ingestion.parsers import KEV_FEED_URL, NVD_API_URL


class FetchError(RuntimeError):
    """A fetcher was given an unusable request (client-side misuse)."""


def _default_nvd_interval(api_key: str) -> float:
    """Seconds to wait between NVD requests.

    Without a key: 6 s, matching NIST's published 5-requests-per-30 s limit
    and their own "sleep six seconds between requests" guidance.
    With a key: the limit rises to 50 per 30 s, but NIST still asks for a
    few seconds between requests, so we keep 1 s by default.
    """
    return 1.0 if api_key else 6.0


class KevFetcher:
    """Fetches the CISA KEV catalog JSON payload.

    The catalog is one static file, so there is no pagination, no query
    parameters and no authentication.
    """

    def __init__(self, client: HttpClient, *, feed_url: str = KEV_FEED_URL) -> None:
        self._client = client
        self._feed_url = feed_url

    @property
    def feed_url(self) -> str:
        return self._feed_url

    def fetch(self) -> Any:
        """Return the decoded KEV catalog payload (a JSON object)."""
        return self._client.get_json(self._feed_url)


class NvdFetcher:
    """Fetches NVD API 2.0 payloads with polite pacing and an optional key.

    Requests are spaced `min_request_interval_seconds` apart so a bulk run
    stays inside the published rate limit instead of earning a 429/403.
    """

    def __init__(
        self,
        client: HttpClient,
        *,
        api_url: str = NVD_API_URL,
        api_key: str = "",
        min_request_interval_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._api_url = api_url
        self._api_key = api_key
        self._interval = (
            _default_nvd_interval(api_key)
            if min_request_interval_seconds is None
            else float(min_request_interval_seconds)
        )
        if self._interval < 0:
            raise ValueError("min_request_interval_seconds must be >= 0")
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    @property
    def api_url(self) -> str:
        return self._api_url

    @property
    def min_request_interval_seconds(self) -> float:
        return self._interval

    def fetch(self, params: Mapping[str, Any] | None = None) -> Any:
        """Perform one GET against the NVD CVE API and return the payload.

        `params` are passed through verbatim (e.g. `resultsPerPage`,
        `startIndex`, `lastModStartDate`); the caller is responsible for
        knowing which combinations NVD accepts.
        """
        self._pace()
        headers = {"apiKey": self._api_key} if self._api_key else None
        return self._client.get_json(
            self._api_url, params=params, headers=headers
        )

    def fetch_cve(self, cve_id: str) -> Any:
        """Fetch a single CVE. NVD accepts at most one `cveId` per request."""
        if not is_valid_cve_id(cve_id):
            raise FetchError(f"invalid CVE identifier for NVD lookup: {cve_id!r}")
        return self.fetch({"cveId": cve_id})

    def _pace(self) -> None:
        """Sleep only if the previous request was less than the interval ago."""
        now = self._clock()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self._interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._clock()


# --------------------------------------------------------------------------
# Factories (wiring only; no work is performed here)
# --------------------------------------------------------------------------

def build_http_client(settings: Settings) -> HttpClient:
    """Build the shared HTTP client from application settings."""
    return HttpClient(
        timeout_seconds=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
        backoff_base_seconds=settings.http_backoff_base_seconds,
        backoff_max_seconds=settings.http_backoff_max_seconds,
        max_retry_after_seconds=settings.http_max_retry_after_seconds,
    )


def build_kev_fetcher(settings: Settings, client: HttpClient) -> KevFetcher:
    return KevFetcher(client, feed_url=settings.kev_feed_url)


def build_nvd_fetcher(settings: Settings, client: HttpClient) -> NvdFetcher:
    return NvdFetcher(
        client,
        api_url=settings.nvd_api_url,
        api_key=settings.nvd_api_key,
        min_request_interval_seconds=settings.nvd_min_request_interval_seconds,
    )
