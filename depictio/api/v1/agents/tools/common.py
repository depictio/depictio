"""Helpers shared by the tool modules. Registers no tools."""

from __future__ import annotations

from bson import ObjectId

from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.registry import ToolError
from depictio.models.models.comments import AgentInfo

MAX_AGENT_NAME_CHARS = 120


def parse_oid(value: str, what: str) -> ObjectId:
    """``ObjectId(value)``, or a 400 naming the argument."""
    try:
        return ObjectId(value)
    except Exception as exc:
        raise ToolError(f"Invalid {what}: {value!r}", status=400) from exc


def agent_info(ctx: ToolContext, *, on_behalf_of: str | None = None) -> AgentInfo:
    """The ``AgentInfo`` stamped on what this call writes."""
    return AgentInfo(
        name=ctx.agent_name[:MAX_AGENT_NAME_CHARS],
        model=ctx.agent_model,
        run_id=ctx.run_id,
        on_behalf_of=on_behalf_of,
    )


def viewer_path(dashboard_id: str) -> str:
    """The viewer page of a dashboard tab. Threads and reports have no deep link yet."""
    return f"/dashboard/{dashboard_id}"


def editor_path(dashboard_id: str) -> str:
    """Where a user reviews an AI draft: the editor, which carries the review panel."""
    return f"/dashboard-edit/{dashboard_id}"
