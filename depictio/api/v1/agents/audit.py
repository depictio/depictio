"""One audit row per agent tool call, kept 90 days."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.configs.logging_init import logger

AUDIT_TTL_SECONDS = 90 * 24 * 3600
# Arguments are stored as a capped JSON string: enough to see what an agent
# asked for, without storing whole payloads.
_ARGS_MAX_CHARS = 2000


def _collection() -> Any:
    # Resolved at call time so tests can patch the module-level handle.
    from depictio.api.v1 import db

    return db.agent_tool_calls_collection


def _args_repr(args: Any) -> str:
    try:
        text = json.dumps(args, default=str, ensure_ascii=False)
    except Exception:
        text = repr(args)
    return text if len(text) <= _ARGS_MAX_CHARS else text[:_ARGS_MAX_CHARS] + "..."


def build_row(
    ctx: ToolContext,
    tool: str,
    args: Any,
    *,
    call_id: str,
    ok: bool,
    error: str | None,
    duration_ms: float,
    truncated: bool,
) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "tool": tool,
        "user_id": str(getattr(ctx.user, "id", "")),
        "token_id": ctx.token_id,
        "agent_name": ctx.agent_name,
        "agent_model": ctx.agent_model,
        "run_id": ctx.run_id,
        "args": _args_repr(args),
        "ok": ok,
        "error": error,
        "duration_ms": round(duration_ms, 1),
        "truncated": truncated,
        "ts": datetime.now(timezone.utc),
    }


async def record_call(
    ctx: ToolContext,
    tool: str,
    args: Any,
    ok: bool,
    error: str | None,
    duration_ms: float,
    truncated: bool,
    *,
    call_id: str,
) -> None:
    """Insert the audit row. Never raises: a failed audit must not fail the call."""
    try:
        row = build_row(
            ctx,
            tool,
            args,
            call_id=call_id,
            ok=ok,
            error=error,
            duration_ms=duration_ms,
            truncated=truncated,
        )
        await asyncio.to_thread(_collection().insert_one, row)
    except Exception as exc:
        logger.warning(f"agents: could not record audit row for {tool}: {exc}")


def ensure_agent_audit_indexes() -> None:
    """TTL on ``ts`` plus lookups by user and run. Idempotent, never raises."""
    try:
        coll = _collection()
        coll.create_index("ts", expireAfterSeconds=AUDIT_TTL_SECONDS, name="ts_ttl")
        coll.create_index([("user_id", ASCENDING), ("ts", DESCENDING)])
        coll.create_index("run_id")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"agents: failed to ensure agent_tool_calls indexes: {exc}")
