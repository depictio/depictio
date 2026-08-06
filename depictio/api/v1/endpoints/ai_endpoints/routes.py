"""HTTP routes for the AI endpoints.

All flows consume the user's LLM API key from the ``X-LLM-API-Key`` header
(set from the React Settings Drawer; never persisted server-side), falling
back to the server-side ``settings.ai.api_key`` when absent.

The router is only registered when ``settings.ai.enabled`` is true (see
``depictio/api/v1/endpoints/routers.py``).

* ``POST /ai/suggest-figures`` — data-driven figure suggestions
* ``POST /ai/component-from-prompt`` — prompt-driven typed component
  creation (any of the 7 component types). Emits YAML validated through
  ``DashboardDataLite.from_yaml(...)`` — the same offline validator the
  CLI uses for ``depictio-cli dashboard import``.
* ``POST /ai/resolve-filters`` — direct NL → dashboard filters (widget
  values and/or validated ``filter_expr`` entries, percentile thresholds
  resolved server-side).
* ``POST /ai/analyze`` — prompt-driven analysis with execution trace and
  optional dashboard mutations (filter proposals + existing-figure
  patches).

The analyze endpoint streams; the others are single-shot JSON responses.
Streaming is HTTP chunked + SSE-formatted events so the realtime WebSocket
is left alone (different lifecycle, different auth model).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints import component_yaml, llm_client, prompts
from depictio.api.v1.endpoints.ai_endpoints import summaries as summaries_mod
from depictio.api.v1.endpoints.ai_endpoints.code_gen import figure_python_code
from depictio.api.v1.endpoints.ai_endpoints.context import (
    build_dashboard_context,
    build_data_context,
)
from depictio.api.v1.endpoints.ai_endpoints.executor import execute_polars
from depictio.api.v1.endpoints.ai_endpoints.filter_resolver import resolve_proposals
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    AnalysisResult,
    AnalyzeRequest,
    ComponentFromPromptRequest,
    ComponentFromPromptResponse,
    DashboardActions,
    ExecutionStep,
    PlotSuggestion,
    ResolveFiltersRequest,
    ResolveFiltersResponse,
    StreamEvent,
    SuggestFiguresRequest,
    SuggestFiguresResponse,
    SummariesResponse,
    SummarizeSectionRequest,
    SummarizeSectionResponse,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.users import User

logger = logging.getLogger(__name__)

ai_endpoint_router = APIRouter()


def _llm_key(x_llm_api_key: str | None = Header(default=None)) -> str | None:
    """Per-request user LLM key. Never logged, never stored."""
    return x_llm_api_key


@ai_endpoint_router.get("/health")
async def health(
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """Lightweight readiness probe for the AI feature.

    Reports the configured model and whether per-user keys are accepted so
    the UI can tailor its key section. Never exposes key material.
    """
    return {
        "status": "ok",
        "model": settings.ai.default_model,
        "allow_user_keys": settings.ai.allow_user_keys,
        "server_key_configured": settings.ai.api_key is not None,
    }


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
    try:
        raw = await asyncio.to_thread(
            llm_client.completion,
            messages,
            user_api_key=user_api_key,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

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


MAX_COMPONENT_ATTEMPTS = 2


@ai_endpoint_router.post("/component-from-prompt", response_model=ComponentFromPromptResponse)
async def component_from_prompt(
    body: ComponentFromPromptRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> ComponentFromPromptResponse:
    """Prompt-driven typed component creation.

    The LLM emits one YAML component block; we run it through the same
    offline validator the CLI uses for `dashboard import`
    (`DashboardDataLite.from_yaml`). On validation failure we feed the
    error back into the conversation and retry once before bailing out.
    """
    ctx = await build_data_context(body.data_collection_id, current_user)
    messages = prompts.component_from_prompt_messages(
        ctx,
        body.prompt,
        component_type=body.component_type,
        current=body.current,
    )

    last_error: str | None = None
    for attempt in range(MAX_COMPONENT_ATTEMPTS):
        try:
            raw = await asyncio.to_thread(
                llm_client.completion,
                messages,
                user_api_key=user_api_key,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

        try:
            parsed = await asyncio.to_thread(component_yaml.validate_single, raw)
        except (ValidationError, ValueError) as e:
            last_error = component_yaml.format_validation_error_for_llm(e)
            logger.warning("component_from_prompt attempt %d failed: %s", attempt + 1, last_error)
            messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"{last_error}\n\nRe-emit the corrected YAML only — no prose, no fences."
                    ),
                },
            ]
            continue

        title = parsed.get("title")
        return ComponentFromPromptResponse(
            component_type=parsed.get("component_type", body.component_type),
            yaml=component_yaml.dump_single(parsed),
            parsed=parsed,
            explanation=title.strip() if isinstance(title, str) else "",
            validation_attempts=attempt + 1,
        )

    raise HTTPException(
        status_code=422,
        detail=f"LLM did not produce a valid component: {last_error or '(unknown)'}",
    )


# ---------------------------------------------------------------------------
# resolve-filters — direct NL → dashboard filters
# ---------------------------------------------------------------------------


@ai_endpoint_router.post("/resolve-filters", response_model=ResolveFiltersResponse)
async def resolve_filters(
    body: ResolveFiltersRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> ResolveFiltersResponse:
    """Translate a prompt into applicable dashboard filters, single-shot.

    The LLM plans FilterProposals; the server validates/resolves them
    (widget existence check, `validate_filter_expr` gate, quantile
    thresholds computed on the live — filtered — data) and returns only
    what the client may safely apply.
    """
    dashboard_ctx, primary_dc = await build_dashboard_context(body.dashboard_id, current_user)
    if not primary_dc:
        raise HTTPException(
            status_code=422,
            detail="Dashboard has no data collection to filter yet.",
        )
    data_ctx = await build_data_context(primary_dc, current_user)

    messages = prompts.resolve_filters_messages(data_ctx, dashboard_ctx, body.prompt)
    try:
        raw = await asyncio.to_thread(
            llm_client.completion,
            messages,
            user_api_key=user_api_key,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

    try:
        parsed = llm_client.parse_json(raw)
    except Exception as e:  # noqa: BLE001
        logger.error("resolve-filters: JSON parse failed: %s", e)
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON.")

    try:
        actions = DashboardActions.model_validate(
            {"filter_proposals": parsed.get("proposals", []) if isinstance(parsed, dict) else []}
        )
    except ValidationError as e:
        logger.warning("resolve-filters: proposal validation failed: %s", e)
        raise HTTPException(status_code=502, detail="LLM returned invalid filter proposals.")

    resolved, warnings = await asyncio.to_thread(
        resolve_proposals,
        actions.filter_proposals,
        dashboard_ctx=dashboard_ctx,
        workflow_id=data_ctx.workflow_id,
        data_collection_id=data_ctx.data_collection_id,
        active_filters=body.filters,
    )
    explanation = str(parsed.get("explanation", "")) if isinstance(parsed, dict) else ""
    return ResolveFiltersResponse(applied=resolved, explanation=explanation, warnings=warnings)


# ---------------------------------------------------------------------------
# Section summaries
# ---------------------------------------------------------------------------


@ai_endpoint_router.post("/summarize-section", response_model=SummarizeSectionResponse)
async def summarize_section(
    body: SummarizeSectionRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> SummarizeSectionResponse:
    """Summarize one dashboard section from client-supplied rendered state.

    Cached by (dashboard, section, context hash): same visible data ⇒ the
    stored summary comes back without an LLM call. `force=true` regenerates
    regardless.
    """
    # Permission gate — same project-viewer rule as every other AI read.
    await build_dashboard_context(body.dashboard_id, current_user)

    components = [summaries_mod.trim_component(c) for c in body.components]
    context_hash = summaries_mod.compute_context_hash(body.section, body.filters, components)

    if not body.force:
        cached = await asyncio.to_thread(
            summaries_mod.get_cached, body.dashboard_id, body.section, context_hash
        )
        if cached:
            return SummarizeSectionResponse(
                summary_md=cached.get("summary_md", ""),
                generated_at=cached.get("generated_at", ""),
                model=cached.get("model", ""),
                context_hash=context_hash,
                cached=True,
            )

    if not components:
        raise HTTPException(status_code=422, detail="Nothing to summarize (no components).")

    messages = summaries_mod.summarize_section_messages(body.section, body.filters, components)
    try:
        summary_md = await asyncio.to_thread(
            llm_client.completion,
            messages,
            user_api_key=user_api_key,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

    model = llm_client.get_default_model()
    entry = await asyncio.to_thread(
        summaries_mod.put_cache,
        body.dashboard_id,
        body.section,
        context_hash,
        summary_md.strip(),
        model,
    )
    return SummarizeSectionResponse(
        summary_md=entry["summary_md"],
        generated_at=entry["generated_at"],
        model=model,
        context_hash=context_hash,
        cached=False,
    )


@ai_endpoint_router.get("/summaries/{dashboard_id}", response_model=SummariesResponse)
async def get_summaries(
    dashboard_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> SummariesResponse:
    """Stored summaries for a dashboard (one per section, latest wins).

    The client compares each entry's `context_hash` against the hash of
    what it currently renders to decide between "fresh" and "stale —
    regenerate?".
    """
    await build_dashboard_context(dashboard_id, current_user)
    entries = await asyncio.to_thread(summaries_mod.latest_for_dashboard, dashboard_id)
    return SummariesResponse(summaries=entries)


# ---------------------------------------------------------------------------
# analyze — streaming ReAct loop
# ---------------------------------------------------------------------------


def _sse(event: StreamEvent) -> bytes:
    """Format a StreamEvent as one SSE-style chunk (event + data + blank).

    Emits the inner ``data`` dict directly (not the model dump): wrapping
    it as ``{"data": {...}}`` forces the React parser to read
    ``event.data.data.detail``, which historically surfaced every error as
    "unknown error" in the UI.
    """
    payload = json.dumps(event.data, default=str)
    return f"event: {event.type}\ndata: {payload}\n\n".encode()


MAX_ANALYZE_STEPS = 4


def _load_df_for_analyze(data_ctx, active_filters: list[dict] | None):
    """Re-load the DataFrame for the executor (sync — runs via to_thread).

    The DataContext already holds row counts/columns; we re-load (with the
    user's active filters applied) so the executor sees the same rows the
    dashboard shows.
    """
    from bson import ObjectId as _OID

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    return load_deltatable_lite(
        workflow_id=_OID(data_ctx.workflow_id),
        data_collection_id=_OID(data_ctx.data_collection_id),
        metadata=active_filters or None,
    )


async def _run_analyze(
    body: AnalyzeRequest,
    current_user: User,
    user_api_key: str | None,
) -> AsyncIterator[bytes]:
    """Drive the analyze loop and yield SSE-formatted events.

    Ask the LLM for {thought, code, answer, actions}; optionally execute
    Polars expressions (AST-allowlisted) feeding observations back, up to
    MAX_ANALYZE_STEPS rounds; resolve any filter proposals; emit the
    result.
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
            df = await asyncio.to_thread(_load_df_for_analyze, data_ctx, body.filters)
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

    resolved, warnings = await asyncio.to_thread(
        resolve_proposals,
        actions.filter_proposals,
        dashboard_ctx=dashboard_ctx,
        workflow_id=data_ctx.workflow_id,
        data_collection_id=data_ctx.data_collection_id,
        active_filters=body.filters,
    )

    result = AnalysisResult(answer=answer, steps=steps, actions=actions, resolved_filters=resolved)
    yield _sse(StreamEvent(type="answer", data={"answer": answer}))
    yield _sse(
        StreamEvent(
            type="actions",
            data={
                **actions.model_dump(),
                "resolved_filters": [r.model_dump() for r in resolved],
                "warnings": warnings,
            },
        )
    )
    yield _sse(StreamEvent(type="result", data=result.model_dump()))
    yield _sse(StreamEvent(type="done"))


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
