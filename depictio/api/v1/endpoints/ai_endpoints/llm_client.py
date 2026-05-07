"""Provider-agnostic LLM client built on LiteLLM.

Ported from `dev/litellm-prototype/llm_client.py`. Differences from the
prototype:
- API key arrives per-request from the React UI (the dashboard Settings
  Drawer); never persisted, never logged. Falls back to env var if absent
  so internal/trusted deployments still work.
- No LangChain pandas agent — code execution lives in `executor.py` so we
  can run Polars under an AST allowlist.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Iterator
from typing import Any

import litellm

logger = logging.getLogger(__name__)
litellm.suppress_debug_info = True

DEFAULT_MODEL = "openrouter/anthropic/claude-sonnet-4-6"

_cache: dict[str, str] = {}


def get_default_model() -> str:
    return os.getenv("DEPICTIO_LLM_MODEL", DEFAULT_MODEL)


def _provider_key_env(model: str) -> str | None:
    """Return the env var name that LiteLLM expects for `model`'s provider."""
    if model.startswith("openrouter/"):
        return "OPENROUTER_API_KEY"
    if model.startswith("anthropic/") or model.startswith("claude-"):
        return "ANTHROPIC_API_KEY"
    if model.startswith("openai/") or model.startswith("gpt-"):
        return "OPENAI_API_KEY"
    if model.startswith("gemini/") or model.startswith("google/"):
        return "GEMINI_API_KEY"
    if model.startswith("ollama/"):
        return None
    return None


def _resolve_api_key(model: str, user_key: str | None) -> str | None:
    """User-supplied key wins; otherwise fall back to the provider env var."""
    if user_key:
        return user_key
    env_name = _provider_key_env(model)
    return os.getenv(env_name) if env_name else None


def _cache_key(messages: list[dict[str, Any]], model: str, fmt: str) -> str:
    payload = json.dumps(
        {"messages": messages, "model": model, "fmt": fmt},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _log_messages(messages: list[dict[str, Any]]) -> None:
    for msg in messages:
        role = str(msg.get("role", "?")).upper()
        logger.debug("─── %s Prompt ───", role)
        logger.debug("%s", msg.get("content", ""))


def completion(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    user_api_key: str | None = None,
    response_format: type | None = None,
    temperature: float = 0,
    max_tokens: int = 2048,
) -> str:
    """Single non-streaming completion. Returns the assistant message content."""
    model = model or get_default_model()
    fmt_name = response_format.__name__ if response_format else "None"
    key = _cache_key(messages, model, fmt_name)

    if key in _cache:
        logger.info("═══ Cache HIT ═══  key=%s format=%s", key[:12], fmt_name)
        return _cache[key]

    api_key = _resolve_api_key(model, user_api_key)
    logger.info(
        "═══ LLM Request ═══  model=%s fmt=%s key=%s",
        model,
        fmt_name,
        "user" if user_api_key else ("env" if api_key else "none"),
    )
    _log_messages(messages)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if response_format is not None:
        kwargs["response_format"] = response_format

    t0 = time.perf_counter()
    response = litellm.completion(**kwargs)
    elapsed = time.perf_counter() - t0
    content = response.choices[0].message.content or ""

    usage = getattr(response, "usage", None)
    if usage:
        logger.info(
            "═══ LLM Response (%.1fs) ═══  Tokens: %d + %d = %d",
            elapsed,
            getattr(usage, "prompt_tokens", 0),
            getattr(usage, "completion_tokens", 0),
            getattr(usage, "total_tokens", 0),
        )
    else:
        logger.info("═══ LLM Response (%.1fs) ═══", elapsed)
    logger.debug("─── Raw Response ───\n%s", content)

    _cache[key] = content
    return content


def stream_completion(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    user_api_key: str | None = None,
    temperature: float = 0,
    max_tokens: int = 2048,
) -> Iterator[str]:
    """Yield content deltas as they arrive from the provider."""
    model = model or get_default_model()
    api_key = _resolve_api_key(model, user_api_key)
    logger.info(
        "═══ LLM Stream Request ═══  model=%s key=%s",
        model,
        "user" if user_api_key else ("env" if api_key else "none"),
    )
    _log_messages(messages)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if api_key:
        kwargs["api_key"] = api_key

    t0 = time.perf_counter()
    for chunk in litellm.completion(**kwargs):
        try:
            delta = chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            delta = None
        if delta:
            yield delta
    logger.info("═══ LLM Stream Done (%.1fs) ═══", time.perf_counter() - t0)


def parse_json(content: str) -> Any:
    """Best-effort JSON parser that strips ``` fences."""
    text = content.strip()
    if text.startswith("```"):
        # Drop opening fence (``` or ```json) and the trailing ```
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text.strip())
