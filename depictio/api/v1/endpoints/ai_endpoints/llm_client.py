"""Provider-agnostic LLM client built on LiteLLM.

Ported from the `claude/ai-compatible-depictio-gR9q7` exploration branch.
Differences from that version:
- Model, server key and token caps come from ``settings.ai`` instead of raw
  environment reads, so one config object drives router gating and client
  behaviour alike.
- ``litellm`` is imported lazily inside the call sites: deployments with
  ``DEPICTIO_AI_ENABLED=false`` never pay the import (and the API boots even
  if the package is broken or absent).

The API key resolves per request: a user-supplied key (``X-LLM-API-Key``
header, when ``settings.ai.allow_user_keys``) wins, otherwise the
server-side ``settings.ai.api_key``. Never persisted, never logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Iterator
from typing import Any, NamedTuple

from depictio.api.v1.configs.config import settings

logger = logging.getLogger(__name__)


class CompletionUsage(NamedTuple):
    """Token accounting for one completion, as the provider reported it."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Completion(NamedTuple):
    content: str
    usage: CompletionUsage
    cached: bool


# Process-local completion cache, bounded FIFO. The key includes a hash of
# the resolved API key: without it, a keyless user could be served a
# completion another user paid for with their own key. (Two users sharing
# the *server* key still share entries, which is fine — same payer.)
_CACHE_MAX_ENTRIES = 256
_cache: OrderedDict[str, Completion] = OrderedDict()


def _litellm():
    """Lazy litellm import (see module docstring)."""
    import litellm

    litellm.suppress_debug_info = True
    return litellm


def get_default_model() -> str:
    return settings.ai.default_model


def _resolve_api_key(user_key: str | None) -> str | None:
    """User-supplied key wins (when allowed); otherwise the server key."""
    if user_key and settings.ai.allow_user_keys:
        return user_key
    if settings.ai.api_key is not None:
        return settings.ai.api_key.get_secret_value() or None
    return None


def _cache_key(messages: list[dict[str, Any]], model: str, fmt: str, api_key: str | None) -> str:
    payload = json.dumps(
        {
            "messages": messages,
            "model": model,
            "fmt": fmt,
            # Hash, never the key itself: the cache key shows up in logs.
            "key": hashlib.sha256((api_key or "").encode()).hexdigest(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _log_messages(messages: list[dict[str, Any]]) -> None:
    for msg in messages:
        role = str(msg.get("role", "?")).upper()
        logger.debug("─── %s Prompt ───", role)
        logger.debug("%s", msg.get("content", ""))


def completion_with_usage(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    user_api_key: str | None = None,
    response_format: type | None = None,
    temperature: float = 0,
    max_tokens: int | None = None,
) -> Completion:
    """Non-streaming completion returning content plus token usage.

    The analysis budget needs the numbers `completion` was already
    computing for its log line; this sibling returns them instead of
    changing the signature the other four flows are written against.
    A cache hit reports the *original* usage with `cached=True`, so the
    budget can choose not to charge for it.
    """
    model = model or get_default_model()
    max_tokens = max_tokens or settings.ai.max_tokens
    fmt_name = response_format.__name__ if response_format else "None"
    api_key = _resolve_api_key(user_api_key)
    key = _cache_key(messages, model, fmt_name, api_key)

    if key in _cache:
        logger.info("═══ Cache HIT ═══  key=%s format=%s", key[:12], fmt_name)
        hit = _cache[key]
        return Completion(content=hit.content, usage=hit.usage, cached=True)

    logger.info(
        "═══ LLM Request ═══  model=%s fmt=%s key=%s",
        model,
        fmt_name,
        "user" if user_api_key else ("server" if api_key else "none"),
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
    response = _litellm().completion(**kwargs)
    elapsed = time.perf_counter() - t0
    content = response.choices[0].message.content or ""

    raw_usage = getattr(response, "usage", None)
    usage = CompletionUsage(
        prompt_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(raw_usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(raw_usage, "total_tokens", 0) or 0),
    )
    if raw_usage:
        logger.info(
            "═══ LLM Response (%.1fs) ═══  Tokens: %d + %d = %d",
            elapsed,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens,
        )
    else:
        logger.info("═══ LLM Response (%.1fs) ═══", elapsed)
    logger.debug("─── Raw Response ───\n%s", content)

    result = Completion(content=content, usage=usage, cached=False)
    _cache[key] = result
    while len(_cache) > _CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)
    return result


def completion(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    user_api_key: str | None = None,
    response_format: type | None = None,
    temperature: float = 0,
    max_tokens: int | None = None,
) -> str:
    """Single non-streaming completion. Returns the assistant message content."""
    return completion_with_usage(
        messages,
        model=model,
        user_api_key=user_api_key,
        response_format=response_format,
        temperature=temperature,
        max_tokens=max_tokens,
    ).content


def stream_completion(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    user_api_key: str | None = None,
    temperature: float = 0,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Yield content deltas as they arrive from the provider."""
    model = model or get_default_model()
    max_tokens = max_tokens or settings.ai.max_tokens
    api_key = _resolve_api_key(user_api_key)
    logger.info(
        "═══ LLM Stream Request ═══  model=%s key=%s",
        model,
        "user" if user_api_key else ("server" if api_key else "none"),
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
    for chunk in _litellm().completion(**kwargs):
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
