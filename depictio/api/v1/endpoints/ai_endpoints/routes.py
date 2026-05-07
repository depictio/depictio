"""HTTP routes for the AI endpoints.

Three flows, all consume the user's LLM API key from the `X-LLM-API-Key`
header (set per-dashboard from the React Settings Drawer; not persisted).

* `POST /ai/suggest-figures` — data-driven figure suggestions
* `POST /ai/figure-from-prompt` — prompt-driven viz creation
* `POST /ai/analyze` — prompt-driven analysis with execution trace and
  optional dashboard mutations (filters + existing-figure patches)

The analyze endpoint streams; suggest/figure-from-prompt are single-shot
JSON responses. Streaming is HTTP chunked + SSE-formatted events so the
realtime WebSocket is left alone (different lifecycle, different auth
model — see PR description).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from depictio.api.v1.endpoints.ai_endpoints import llm_client, prompts
from depictio.api.v1.endpoints.ai_endpoints.code_gen import figure_python_code
from depictio.api.v1.endpoints.ai_endpoints.context import (
    build_dashboard_context,
    build_data_context,
)
from depictio.api.v1.endpoints.ai_endpoints.executor import execute_polars
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    AnalysisResult,
    AnalyzeRequest,
    DashboardActions,
    ExecutionStep,
    FigureFromPromptRequest,
    FigureFromPromptResponse,
    PlotSuggestion,
    StreamEvent,
    SuggestFiguresRequest,
    SuggestFiguresResponse,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.users import User

logger = logging.getLogger(__name__)

ai_endpoint_router = APIRouter()


def _llm_key(x_llm_api_key: str | None = Header(default=None)) -> str | None:
    """Per-request user LLM key. Never logged, never stored."""
    return x_llm_api_key


def _try_plot_suggestion(payload: dict) -> PlotSuggestion | None:
    try:
        suggestion = PlotSuggestion.model_validate(payload)
    except ValidationError as e:
        logger.warning("PlotSuggestion validation failed: %s", e)
        return None
    # Synthesize the Plotly Express code so the React drawer can show
    # the user how they'd reproduce the chart in Python.
    suggestion = suggestion.model_copy(
        update={"code": figure_python_code(suggestion.visu_type, suggestion.dict_kwargs)}
    )
    return suggestion


@ai_endpoint_router.post("/suggest-figures", response_model=SuggestFiguresResponse)
async def suggest_figures(
    body: SuggestFiguresRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> SuggestFiguresResponse:
    """Data-driven flow: propose N figures for a data collection.

    Loads the DC, builds a schema/sample/metadata prompt, asks the LLM for a
    JSON envelope of suggestions, validates each through `PlotSuggestion`,
    drops any that fail (and logs them) so a single bad item never blocks
    the whole response.
    """
    ctx = await build_data_context(body.data_collection_id, current_user)
    messages = prompts.suggest_figures_messages(ctx, body.n)
    raw = llm_client.completion(messages, user_api_key=user_api_key)

    try:
        parsed = llm_client.parse_json(raw)
    except Exception as e:  # noqa: BLE001
        logger.error("suggest-figures: JSON parse failed: %s", e)
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON.")

    raw_items = parsed.get("suggestions", []) if isinstance(parsed, dict) else []
    suggestions = [s for s in (_try_plot_suggestion(item) for item in raw_items) if s]

    if not suggestions:
        raise HTTPException(
            status_code=502,
            detail="LLM produced no usable suggestions (all failed schema validation).",
        )
    return SuggestFiguresResponse(suggestions=suggestions)


@ai_endpoint_router.post("/figure-from-prompt", response_model=FigureFromPromptResponse)
async def figure_from_prompt(
    body: FigureFromPromptRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> FigureFromPromptResponse:
    """Prompt-driven viz creation. Single suggestion, retried once on parse fail."""
    ctx = await build_data_context(body.data_collection_id, current_user)
    messages = prompts.figure_from_prompt_messages(
        ctx,
        body.prompt,
        previous_visu_type=body.previous_visu_type,
        previous_dict_kwargs=body.previous_dict_kwargs,
        previous_code=body.previous_code,
    )

    last_error: str | None = None
    for attempt in range(2):
        raw = llm_client.completion(
            messages,
            user_api_key=user_api_key,
            response_format=PlotSuggestion if attempt == 0 else None,
        )
        try:
            payload = llm_client.parse_json(raw)
        except Exception as e:  # noqa: BLE001
            last_error = f"json: {e}"
            continue
        suggestion = _try_plot_suggestion(payload)
        if suggestion:
            return FigureFromPromptResponse(suggestion=suggestion)
        last_error = "schema validation failed"

    raise HTTPException(
        status_code=502,
        detail=f"LLM did not return a valid suggestion: {last_error}",
    )


def _sse(event: StreamEvent) -> bytes:
    """Format a StreamEvent as one SSE-style chunk (event + data + blank)."""
    # Emit the inner ``data`` dict directly. `model_dump_json(exclude={"type"})`
    # wraps it in `{"data": {...}}` because StreamEvent has both `type` and
    # `data` fields, which forces the React parser to read
    # ``event.data.detail`` as ``event.data.data.detail`` — every error event
    # silently surfaces "unknown error" in the UI.
    import json

    payload = json.dumps(event.data, default=str)
    return f"event: {event.type}\ndata: {payload}\n\n".encode()


MAX_ANALYZE_STEPS = 4


async def _run_analyze(
    body: AnalyzeRequest,
    current_user: User,
    user_api_key: str | None,
) -> AsyncIterator[bytes]:
    """Drive the analyze loop and yield SSE-formatted events.

    Single-pass for v1: ask the LLM for {thought, code, answer, actions},
    optionally execute one Polars expression, return the resulting answer
    and DashboardActions. Multi-step ReAct loop (re-prompt with the
    observation) is gated behind MAX_ANALYZE_STEPS for the future.
    """
    yield _sse(StreamEvent(type="status", data={"message": "loading dashboard"}))

    try:
        dashboard_ctx, primary_dc = await build_dashboard_context(body.dashboard_id, current_user)
    except Exception as e:  # noqa: BLE001
        yield _sse(StreamEvent(type="error", data={"detail": str(e)}))
        yield _sse(StreamEvent(type="done"))
        return

    if not primary_dc:
        yield _sse(
            StreamEvent(
                type="error",
                data={"detail": "Dashboard has no data collection to analyze yet."},
            )
        )
        yield _sse(StreamEvent(type="done"))
        return

    yield _sse(StreamEvent(type="status", data={"message": "loading data"}))

    try:
        data_ctx = await build_data_context(primary_dc, current_user)
    except Exception as e:  # noqa: BLE001
        yield _sse(StreamEvent(type="error", data={"detail": str(e)}))
        yield _sse(StreamEvent(type="done"))
        return

    yield _sse(StreamEvent(type="status", data={"message": "thinking"}))

    messages = prompts.analyze_messages(
        data_ctx, dashboard_ctx, body.prompt, body.selected_component_id
    )

    steps: list[ExecutionStep] = []
    answer = ""
    actions = DashboardActions()

    for i in range(MAX_ANALYZE_STEPS):
        try:
            raw = await asyncio.to_thread(
                llm_client.completion,
                messages,
                user_api_key=user_api_key,
            )
        except Exception as e:  # noqa: BLE001
            yield _sse(StreamEvent(type="error", data={"detail": f"LLM error: {e}"}))
            yield _sse(StreamEvent(type="done"))
            return

        try:
            payload = llm_client.parse_json(raw)
        except Exception as e:  # noqa: BLE001
            yield _sse(
                StreamEvent(
                    type="error",
                    data={"detail": f"LLM returned invalid JSON: {e}"},
                )
            )
            yield _sse(StreamEvent(type="done"))
            return

        thought = str(payload.get("thought", "")).strip()
        code = str(payload.get("code", "")).strip()
        candidate_answer = str(payload.get("answer", "")).strip()
        actions_payload = payload.get("actions") or {}

        if code:
            yield _sse(
                StreamEvent(
                    type="step",
                    data={"thought": thought, "code": code, "status": "running"},
                )
            )
            df = await asyncio.to_thread(_load_df_for_analyze, data_ctx)
            step = await asyncio.to_thread(execute_polars, code, df)
            step.thought = thought
            steps.append(step)
            yield _sse(
                StreamEvent(
                    type="step",
                    data=step.model_dump(),
                )
            )
            # If this was the final pass (the LLM also gave an answer)
            # or we've run out of steps, stop looping.
            if candidate_answer or i == MAX_ANALYZE_STEPS - 1:
                answer = candidate_answer or "(no answer provided)"
                try:
                    actions = DashboardActions.model_validate(actions_payload)
                except ValidationError as e:
                    logger.warning("DashboardActions validation: %s", e)
                    actions = DashboardActions()
                break
            # Otherwise, feed the observation back and ask again.
            messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Observation:\n"
                        + step.output
                        + "\n\nNow respond with the same JSON envelope. "
                        + "Set 'code' to '' and fill 'answer'."
                    ),
                },
            ]
            continue

        # No code requested — terminal step.
        steps.append(ExecutionStep(thought=thought, code="", output="", status="success"))
        answer = candidate_answer or "(no answer provided)"
        try:
            actions = DashboardActions.model_validate(actions_payload)
        except ValidationError as e:
            logger.warning("DashboardActions validation: %s", e)
            actions = DashboardActions()
        break

    result = AnalysisResult(answer=answer, steps=steps, actions=actions)
    yield _sse(StreamEvent(type="answer", data={"answer": answer}))
    yield _sse(StreamEvent(type="actions", data=actions.model_dump()))
    yield _sse(StreamEvent(type="result", data=result.model_dump()))
    yield _sse(StreamEvent(type="done"))


def _load_df_for_analyze(data_ctx):
    """Re-load the DataFrame for the executor.

    Kept as a tiny wrapper so `asyncio.to_thread` only sees a sync function.
    The DataContext already holds row counts/columns; we re-load to keep
    the executor's `df` up to date and to avoid serializing it across
    coroutine boundaries.
    """
    from bson import ObjectId as _OID

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    return load_deltatable_lite(
        workflow_id=_OID(data_ctx.workflow_id),
        data_collection_id=_OID(data_ctx.data_collection_id),
    )


@ai_endpoint_router.post("/analyze")
async def analyze(
    body: AnalyzeRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> StreamingResponse:
    """Prompt-driven analysis. Streams `StreamEvent` chunks as SSE."""
    return StreamingResponse(
        _run_analyze(body, current_user, user_api_key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
