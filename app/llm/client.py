"""Configurable LLM provider abstraction.

`LLMClient` is the interface used by pipelines. Two implementations:

- `OpenAICompatibleClient`: calls any OpenAI-compatible /chat/completions
  endpoint (OpenAI, local Ollama, etc.) using httpx.
- `FakeLLMClient`: deterministic test double; requires no API key or network.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from app.config import Settings


class LLMError(RuntimeError):
    """Raised when the LLM provider cannot be reached or returns an error."""


class LLMClient(Protocol):
    """Minimal chat interface: a single user/system prompt in, text out."""

    model: str

    def complete(self, prompt: str) -> str:
        """Return the model's completion for `prompt`."""
        ...


class OpenAICompatibleClient:
    """Chat completions client for OpenAI-compatible endpoints."""

    def __init__(self, settings: Settings) -> None:
        self.model = settings.llm_model
        self._base_url = settings.llm_base_url.rstrip("/")
        self._api_key = settings.llm_api_key
        self._timeout = settings.llm_timeout_seconds
        self._max_tokens = settings.llm_max_tokens
        self._temperature = settings.llm_temperature

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
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response missing choices[0].message.content") from exc


class FakeLLMClient:
    """Deterministic test double. Set `scripted_response` to control output."""

    def __init__(self, model: str = "fake-model", scripted_response: str = "") -> None:
        self.model = model
        self.scripted_response = scripted_response
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts_seen.append(prompt)
        return self.scripted_response


def build_llm_client(settings: Settings) -> LLMClient:
    """Return the configured provider client."""
    return OpenAICompatibleClient(settings)
