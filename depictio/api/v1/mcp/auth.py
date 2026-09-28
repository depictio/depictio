"""Bearer token -> ``ToolContext`` for MCP requests. No anonymous fallback."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.users import TokenBeanie, UserBeanie, effective_scopes

AGENT_HEADER = "x-depictio-agent"
RUN_ID_HEADER = "x-depictio-run-id"
_MAX_LABEL_CHARS = 120


def bearer_token(headers: Mapping[str, str]) -> str | None:
    value = headers.get("authorization") or ""
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def fetch_user_and_token(token: str) -> tuple[UserBeanie, TokenBeanie] | None:
    """Same checks as the REST API (JWT signature, expiry, revocation), plus the token doc."""
    from depictio.api.v1.endpoints.user_endpoints.core_functions import (
        _async_fetch_user_from_token,
    )

    user = await _async_fetch_user_from_token(token)
    if user is None:
        return None
    # The helper validated the token and found its document; look it up again
    # for the scopes and id it does not return.
    token_doc = await TokenBeanie.find_one({"access_token": token})
    if token_doc is None:
        return None
    return user, token_doc


def _label(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    return cleaned[:_MAX_LABEL_CHARS] or None


async def resolve_context(headers: Mapping[str, str]) -> ToolContext | None:
    """Build the caller's context from request headers, or None when unauthenticated."""
    token = bearer_token(headers)
    if token is None:
        return None
    try:
        found = await fetch_user_and_token(token)
    except Exception as exc:
        logger.warning(f"mcp: token lookup failed: {exc}")
        return None
    if found is None:
        return None
    user, token_doc = found
    return ToolContext(
        user=user,
        scopes=effective_scopes(token_doc.scopes),
        agent_name=_label(headers.get(AGENT_HEADER)) or _label(token_doc.name) or "mcp-client",
        run_id=_label(headers.get(RUN_ID_HEADER)) or uuid4().hex,
        token_id=str(token_doc.id),
    )
