"""
LLM Client Adapters — supports Anthropic Claude and Google Gemini.

Design decisions:
- Single interface: complete(system, user) -> str
- Built-in retry with backoff for rate limits and server errors
- Token usage tracking for cost monitoring
- No streaming — agents need full responses for JSON parsing
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_requests: int = 0
    total_errors: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def record_gemini(self, usage: Any) -> None:
        self.input_tokens += getattr(usage, "prompt_token_count", 0)
        self.output_tokens += getattr(usage, "candidates_token_count", 0)
        self.total_requests += 1

    def record_anthropic(self, usage: Any) -> None:
        self.input_tokens += getattr(usage, "input_tokens", 0)
        self.output_tokens += getattr(usage, "output_tokens", 0)
        self.total_requests += 1


# ---------------------------------------------------------------------------
# Google Gemini Client
# ---------------------------------------------------------------------------

class GeminiClient:
    """
    Wrapper around the new google-genai SDK.

    Usage:
        client = GeminiClient(api_key="AIza...", model="gemini-2.5-flash-lite")
        result = await client.complete(system="...", user="...")
    """

    # Class-level rate limiter shared across all instances (free tier: 10 RPM)
    _last_call_time: float = 0.0
    _rate_lock: asyncio.Lock | None = None
    _min_interval: float = 7.0  # seconds between calls (10 RPM = 6s, add buffer)

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash-lite",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_retries: int = 5,
        base_delay: float = 10.0,
    ):
        from google import genai
        from google.genai import types

        self._client = genai.Client(api_key=api_key)
        self._types = types
        self.model_name = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.usage = TokenUsage()

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between API calls (free tier protection)."""
        if GeminiClient._rate_lock is None:
            GeminiClient._rate_lock = asyncio.Lock()
        async with GeminiClient._rate_lock:
            now = time.time()
            elapsed = now - GeminiClient._last_call_time
            if elapsed < self._min_interval:
                wait = self._min_interval - elapsed
                logger.debug("Rate limiter: waiting %.1fs", wait)
                await asyncio.sleep(wait)
            GeminiClient._last_call_time = time.time()

    async def complete(self, system: str, user: str) -> str:
        """
        Send a completion request to Gemini. Returns text content.
        Retries on rate limits (429) and transient errors.
        """
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                # Rate limit: space calls to stay within free tier RPM
                await self._rate_limit()

                # Run synchronous SDK in a thread
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self.model_name,
                    contents=user,
                    config=self._types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=self.max_tokens,
                        temperature=self.temperature,
                    ),
                )

                # Track usage
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    um = response.usage_metadata
                    self.usage.input_tokens += getattr(um, "prompt_token_count", 0) or 0
                    self.usage.output_tokens += getattr(um, "candidates_token_count", 0) or 0
                self.usage.total_requests += 1

                result = response.text

                if not result or not result.strip():
                    raise ValueError("Gemini returned empty response")

                logger.debug(
                    "Gemini call: model=%s attempt=%d len=%d",
                    self.model_name, attempt, len(result),
                )
                return result

            except Exception as e:
                error_str = str(e).lower()
                last_error = e
                self.usage.total_errors += 1

                is_rate_limit = any(k in error_str for k in ["429", "resource_exhausted", "quota"])
                is_server_err = any(k in error_str for k in ["500", "503", "internal"])
                is_safety = any(k in error_str for k in ["safety", "blocked"])

                if is_safety:
                    logger.error("Gemini safety filter: %s", str(e)[:200])
                    raise RuntimeError(f"Gemini safety filter blocked: {e}")

                if is_rate_limit or is_server_err or attempt < self.max_retries:
                    delay = min(self.base_delay * (2 ** (attempt - 1)), 60.0)  # cap at 60s
                    kind = "rate limit" if is_rate_limit else "server error" if is_server_err else "error"
                    logger.warning(
                        "Gemini %s (attempt %d/%d), retrying in %.1fs: %s",
                        kind, attempt, self.max_retries, delay, str(e)[:100],
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        raise RuntimeError(
            f"Gemini call failed after {self.max_retries} attempts: {last_error}"
        )

    async def close(self) -> None:
        pass

    def get_usage_summary(self) -> dict[str, Any]:
        return {
            "provider": "google_gemini",
            "model": self.model_name,
            "total_requests": self.usage.total_requests,
            "total_errors": self.usage.total_errors,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "total_tokens": self.usage.total_tokens,
        }


# ---------------------------------------------------------------------------
# Anthropic Claude Client (kept for future use)
# ---------------------------------------------------------------------------

class AnthropicClient:
    """Async wrapper around Anthropic Claude SDK."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ):
        import anthropic
        self._anthropic = anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.usage = TokenUsage()

    async def complete(self, system: str, user: str) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=[
                        {
                            "type": "text",
                            "text": system,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user}],
                )

                self.usage.record_anthropic(response.usage)

                text_parts = []
                for block in response.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)

                result = "\n".join(text_parts)

                if not result.strip():
                    raise ValueError("Claude returned empty response")

                return result

            except self._anthropic.RateLimitError as e:
                last_error = e
                self.usage.total_errors += 1
                delay = self.base_delay * (2 ** (attempt - 1))
                logger.warning("Rate limited (attempt %d/%d)", attempt, self.max_retries)
                await asyncio.sleep(delay)

            except self._anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    last_error = e
                    self.usage.total_errors += 1
                    await asyncio.sleep(self.base_delay * (2 ** (attempt - 1)))
                else:
                    raise

            except self._anthropic.APIConnectionError as e:
                last_error = e
                self.usage.total_errors += 1
                await asyncio.sleep(self.base_delay * (2 ** (attempt - 1)))

        raise RuntimeError(
            f"Claude call failed after {self.max_retries} attempts: {last_error}"
        )

    async def close(self) -> None:
        await self._client.close()

    def get_usage_summary(self) -> dict[str, Any]:
        return {
            "provider": "anthropic",
            "model": self.model,
            "total_requests": self.usage.total_requests,
            "total_errors": self.usage.total_errors,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "total_tokens": self.usage.total_tokens,
        }


# ---------------------------------------------------------------------------
# Groq Client (llama-3.3-70b-versatile and compatible models)
# ---------------------------------------------------------------------------

class GroqClient:
    """Async wrapper around the Groq SDK (OpenAI-compatible interface)."""

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_retries: int = 3,
        base_delay: float = 2.0,
    ):
        from groq import AsyncGroq
        self._client = AsyncGroq(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.usage = TokenUsage()

    async def complete(self, system: str, user: str) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )

                if response.usage:
                    self.usage.input_tokens += response.usage.prompt_tokens or 0
                    self.usage.output_tokens += response.usage.completion_tokens or 0
                self.usage.total_requests += 1

                result = response.choices[0].message.content or ""
                if not result.strip():
                    raise ValueError("Groq returned empty response")

                logger.debug(
                    "Groq call: model=%s attempt=%d len=%d",
                    self.model, attempt, len(result),
                )
                return result

            except Exception as e:
                error_str = str(e).lower()
                last_error = e
                self.usage.total_errors += 1

                is_rate_limit = any(k in error_str for k in ["429", "rate_limit", "too many"])
                is_server_err = any(k in error_str for k in ["500", "503", "internal"])

                if (is_rate_limit or is_server_err) and attempt < self.max_retries:
                    delay = self.base_delay * (2 ** (attempt - 1))
                    kind = "rate limit" if is_rate_limit else "server error"
                    logger.warning(
                        "Groq %s (attempt %d/%d), retrying in %.1fs: %s",
                        kind, attempt, self.max_retries, delay, str(e)[:100],
                    )
                    await asyncio.sleep(delay)
                elif attempt < self.max_retries:
                    await asyncio.sleep(self.base_delay)
                else:
                    raise

        raise RuntimeError(
            f"Groq call failed after {self.max_retries} attempts: {last_error}"
        )

    async def close(self) -> None:
        await self._client.close()

    def get_usage_summary(self) -> dict[str, Any]:
        return {
            "provider": "groq",
            "model": self.model,
            "total_requests": self.usage.total_requests,
            "total_errors": self.usage.total_errors,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "total_tokens": self.usage.total_tokens,
        }


# ---------------------------------------------------------------------------
# OpenAI Client (gpt-4o, gpt-4o-mini, o1, etc.)
# ---------------------------------------------------------------------------

class OpenAIClient:
    """Async wrapper around the OpenAI SDK."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_retries: int = 3,
        base_delay: float = 2.0,
    ):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.usage = TokenUsage()

    async def complete(self, system: str, user: str) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_completion_tokens=self.max_tokens,
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                )

                if response.usage:
                    self.usage.input_tokens += response.usage.prompt_tokens or 0
                    self.usage.output_tokens += response.usage.completion_tokens or 0
                self.usage.total_requests += 1

                result = response.choices[0].message.content or ""
                if not result.strip():
                    raise ValueError("OpenAI returned empty response")

                logger.debug(
                    "OpenAI call: model=%s attempt=%d len=%d",
                    self.model, attempt, len(result),
                )
                return result

            except Exception as e:
                error_str = str(e).lower()
                last_error = e
                self.usage.total_errors += 1

                is_rate_limit = any(k in error_str for k in ["429", "rate_limit", "too many"])
                is_server_err = any(k in error_str for k in ["500", "503", "internal"])

                if (is_rate_limit or is_server_err) and attempt < self.max_retries:
                    delay = self.base_delay * (2 ** (attempt - 1))
                    kind = "rate limit" if is_rate_limit else "server error"
                    logger.warning(
                        "OpenAI %s (attempt %d/%d), retrying in %.1fs: %s",
                        kind, attempt, self.max_retries, delay, str(e)[:100],
                    )
                    await asyncio.sleep(delay)
                elif attempt < self.max_retries:
                    await asyncio.sleep(self.base_delay)
                else:
                    raise

        raise RuntimeError(
            f"OpenAI call failed after {self.max_retries} attempts: {last_error}"
        )

    async def close(self) -> None:
        await self._client.close()

    def get_usage_summary(self) -> dict[str, Any]:
        return {
            "provider": "openai",
            "model": self.model,
            "total_requests": self.usage.total_requests,
            "total_errors": self.usage.total_errors,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "total_tokens": self.usage.total_tokens,
        }
