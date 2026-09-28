"""HTTP routes of agent-team runs (``/ai/agent-runs*``, ``/ai/agent-profiles``).

Included in the ``/ai`` router, so they exist only when ``settings.ai.enabled``;
each route also answers 404 unless ``settings.ai.agents_enabled``.

* ``GET  /ai/agent-profiles``: the roles and topics a team is built from.
* ``POST /ai/agent-runs/route``: dry run of the router (no LLM call unless the
  rules cannot decide).
* ``POST /ai/agent-runs``: route, then run the team; streams SSE events
  (``run_started`` ... ``run_finished``, then ``done``).
* ``GET  /ai/agent-runs?dashboard_id=``: the caller's runs, newest first.
* ``GET  /ai/agent-runs/{run_id}``: one run in full.
* ``POST /ai/agent-runs/{run_id}/cancel``: stop a running run at its next check.

Runs belong to the user who started them; others get 404.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from depictio.api.v1.agents import router as team_router
from depictio.api.v1.agents import runs
from depictio.api.v1.agents.budget import BudgetLedger
from depictio.api.v1.agents.profiles import ProfileError, load_profiles
from depictio.api.v1.agents.runner import CancelToken, LiteLLMClient, LLMClient, Toolbox
from depictio.api.v1.agents.team import (
    InProcessExecutor,
    RunExecutor,
    TeamDeps,
    TeamRun,
    format_sse,
    new_run,
)
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.endpoints.user_endpoints.token_scopes import (
    current_token_id,
    current_token_scopes,
)
from depictio.models.models.users import User, effective_scopes

MAX_QUESTION_CHARS = 2_000


def require_agents_enabled() -> None:
    if not (settings.ai.enabled and settings.ai.agents_enabled):
        raise HTTPException(status_code=404, detail="Not Found")


agent_runs_router = APIRouter(dependencies=[Depends(require_agents_enabled)])


# ---------------------------------------------------------------------------
# Dependencies (overridden in tests)
# ---------------------------------------------------------------------------
LLMFactory = Callable[[str | None], LLMClient | None]
RouteContextBuilder = Callable[[Any, str], team_router.RouteContext]

_executor = InProcessExecutor()


def _llm_key(x_llm_api_key: str | None = Header(default=None)) -> str | None:
    """Per-request user LLM key. Never logged, never stored."""
    return x_llm_api_key


def default_llm(user_api_key: str | None) -> LLMClient | None:
    """The team's LLM client, or None when no key can pay for it."""
    client = LiteLLMClient(user_api_key=user_api_key)
    if client.has_key() or client.model.startswith("ollama"):
        return client
    return None


def get_llm_factory() -> LLMFactory:
    return default_llm


def get_toolbox() -> Toolbox:
    return Toolbox()


def get_executor() -> RunExecutor:
    return _executor


def get_route_context_builder() -> RouteContextBuilder:
    return team_router.build_route_context


# ---------------------------------------------------------------------------
# Bodies
# ---------------------------------------------------------------------------
class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteRequest(_Body):
    dashboard_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    team: list[str] | None = Field(
        default=None, max_length=10, description="Agent ids; overrides the routing."
    )


class AgentRunRequest(RouteRequest):
    budget_usd: float | None = Field(
        default=None, gt=0, description="Cost ceiling; capped by settings.ai.agents_max_cost_usd."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _plan(
    body: RouteRequest,
    user: User,
    llm: LLMClient | None,
    build: RouteContextBuilder,
) -> tuple[team_router.RouteContext, team_router.TeamPlan]:
    profiles = load_profiles()
    route_ctx = await asyncio.to_thread(build, user, body.dashboard_id)
    try:
        plan = await team_router.route(profiles, route_ctx, body.question, llm=llm, team=body.team)
    except ProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return route_ctx, plan


async def _own_run(run_id: str, user: User) -> runs.AgentRun:
    run = await asyncio.to_thread(runs.get, run_id)
    if run is None or run.user_id != str(user.id):
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return run


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@agent_runs_router.get("/agent-profiles")
async def list_agent_profiles(
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return [p.summary() for p in load_profiles().all()]


@agent_runs_router.post("/agent-runs/route")
async def route_agent_run(
    body: RouteRequest,
    current_user: User = Depends(get_current_user),
    user_api_key: str | None = Depends(_llm_key),
    llm_factory: LLMFactory = Depends(get_llm_factory),
    build: RouteContextBuilder = Depends(get_route_context_builder),
) -> dict[str, Any]:
    """The team the router would pick. Spends LLM tokens only when the rules cannot decide."""
    _, plan = await _plan(body, current_user, llm_factory(user_api_key), build)
    return plan.public()


@agent_runs_router.post("/agent-runs")
async def start_agent_run(
    body: AgentRunRequest,
    current_user: User = Depends(get_current_user),
    user_api_key: str | None = Depends(_llm_key),
    llm_factory: LLMFactory = Depends(get_llm_factory),
    toolbox: Toolbox = Depends(get_toolbox),
    executor: RunExecutor = Depends(get_executor),
    build: RouteContextBuilder = Depends(get_route_context_builder),
) -> StreamingResponse:
    """Route and run a team on a dashboard. Streams the run's events as SSE."""
    llm = llm_factory(user_api_key)
    if llm is None:
        raise HTTPException(
            status_code=400,
            detail="No LLM API key is configured; set one in the AI settings.",
        )
    route_ctx, plan = await _plan(body, current_user, llm, build)

    cap = settings.ai.agents_max_cost_usd
    ledger = BudgetLedger(
        max_tool_calls=settings.ai.agents_max_tool_calls,
        limit_usd=min(body.budget_usd, cap) if body.budget_usd else cap,
        max_tokens=settings.ai.agents_max_tokens_total,
    )
    profiles = load_profiles()
    run_id = runs.new_run_id()
    run = new_run(
        run_id=run_id,
        user_id=str(current_user.id),
        dashboard_id=route_ctx.dashboard_id,
        question=body.question,
        plan=plan,
        profiles=profiles,
        model=llm.model,
        ledger=ledger,
    )
    job = TeamRun(
        run=run,
        plan=plan,
        route_ctx=route_ctx,
        user=current_user,
        user_scopes=effective_scopes(current_token_scopes.get()),
        deps=TeamDeps(
            llm=llm,
            profiles=profiles,
            toolbox=toolbox,
            max_parallel=settings.ai.agents_max_parallel,
            token_id=current_token_id.get(),
        ),
        ledger=ledger,
        cancel=CancelToken(poll=lambda: runs.cancel_requested(run_id)),
    )

    async def stream() -> AsyncIterator[bytes]:
        async for event, data in executor.events(job):
            yield format_sse(event, data)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@agent_runs_router.get("/agent-runs")
async def list_agent_runs(
    dashboard_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    found = await asyncio.to_thread(runs.list_runs, str(current_user.id), dashboard_id, limit)
    return [r.summary() for r in found]


@agent_runs_router.get("/agent-runs/{run_id}")
async def get_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return (await _own_run(run_id, current_user)).detail()


@agent_runs_router.post("/agent-runs/{run_id}/cancel")
async def cancel_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    executor: RunExecutor = Depends(get_executor),
) -> dict[str, Any]:
    """Ask a running run to stop. It ends with status ``cancelled`` at its next check."""
    run = await _own_run(run_id, current_user)
    flagged = await asyncio.to_thread(runs.request_cancel, run_id)
    local = executor.cancel(run_id)
    return {"run_id": run_id, "cancelled": flagged or local, "status": run.status}
