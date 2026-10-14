"""Environment-driven configuration.

All runtime settings come from environment variables (optionally a `.env` file).
Secrets such as API keys live only in the environment, never in Git.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        # utf-8-sig tolerates a leading BOM (Windows editors/PowerShell add one),
        # which would otherwise cause the whole .env file to be ignored.
        env_file=".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    # Storage
    database_url: str = "sqlite:///data/evidencegraph.db"

    # LLM provider (OpenAI-compatible chat completions endpoint)
    llm_provider: str = "openai"  # "openai" (real) or "mock" (offline, no key)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = Field(default="", repr=False)  # never printed
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 60.0
    llm_max_tokens: int = 700
    llm_temperature: float = 0.0

    # Retrieval
    retrieval_top_k: int = 4

    # Chunking
    chunk_max_chars: int = 900
    chunk_overlap_chars: int = 150

    # Fetching public feeds (Phase 1, Step 3)
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3  # extra attempts after the first one
    http_backoff_base_seconds: float = 1.0  # 1s, 2s, 4s ... exponential
    http_backoff_max_seconds: float = 30.0
    http_max_retry_after_seconds: float = 60.0  # bound on server Retry-After
    kev_feed_url: str = (
        "https://www.cisa.gov/sites/default/files/feeds/"
        "known_exploited_vulnerabilities.json"
    )
    nvd_api_url: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    nvd_api_key: str = Field(default="", repr=False)  # optional, never printed
    # None = pick automatically (6s without a key, 1s with one); NVD's public
    # limit is 5 req/30s unkeyed, 50 req/30s keyed.
    nvd_min_request_interval_seconds: float | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance (tests can clear the cache)."""
    return Settings()
