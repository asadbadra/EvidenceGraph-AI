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


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance (tests can clear the cache)."""
    return Settings()
