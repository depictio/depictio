"""HTTP routes for the AI endpoints.

All flows consume the user's LLM API key from the ``X-LLM-API-Key`` header
(set from the React Settings Drawer; never persisted server-side), falling
back to the server-side ``settings.ai.api_key`` when absent.

The router is only registered when ``settings.ai.enabled`` is true (see
``depictio/api/v1/endpoints/routers.py``).

* ``POST /ai/suggest-components``: typed suggestions for a dashboard
  ("what would you add?"): ranked table candidates built from the data
  (advanced_viz too when pinned) plus one LLM call for the other types,
  every item validated like a CLI import (see ``suggest``).
* ``POST /ai/suggest-figures`` — data-driven figure suggestions
  (deprecated: superseded by suggest-components, kept for older clients)
* ``POST /ai/component-from-prompt`` — prompt-driven typed component
  creation (any of the 9 builder types, text and advanced_viz included).
  Emits YAML validated through
  ``DashboardDataLite.from_yaml(...)`` — the same offline validator the
  CLI uses for ``depictio-cli dashboard import``.
* ``POST /ai/resolve-filters`` — direct NL → dashboard filters (widget
  values and/or validated ``filter_expr`` entries, percentile thresholds
  resolved server-side).
* ``POST /ai/analyze`` — prompt-driven analysis with execution trace and
  optional dashboard mutations (filter proposals + existing-figure
  patches).
* ``POST /ai/generate-dashboard``: a whole dashboard draft from a prompt
  (plan, per-component fill, render check, layout, persist; see
  ``dashboard_gen``), in one shot or in two phases (``plan_only`` returns
  the plan and stops, ``plan`` fills the plan that came back approved), and
  ``POST /ai/generated-dashboards/{id}/promote`` to clear its draft flag.
* Reviewing that draft:
  ``POST /ai/generated-dashboards/{id}/components/{index}/regenerate`` and
  ``.../sections/{section}/regenerate`` re-fill one tile or one section
  (streaming, same events as the generation),
  ``POST /ai/generated-dashboards/{id}/review`` keeps or unkeeps a tile,
  and ``GET /ai/generations/{project_id}`` lists the project's runs.

The analyze and generate endpoints stream; the others are single-shot JSON
responses.
Streaming is HTTP chunked + SSE-formatted events so the realtime WebSocket
is left alone (different lifecycle, different auth model).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints import (
    analyses,
    component_style,
    component_yaml,
    dashboard_gen,
    llm_client,
    prompts,
    routing,
)
from depictio.api.v1.endpoints.ai_endpoints import suggest as suggest_mod
from depictio.api.v1.endpoints.ai_endpoints import summaries as summaries_mod
from depictio.api.v1.endpoints.ai_endpoints.code_gen import figure_python_code
from depictio.api.v1.endpoints.ai_endpoints.context import (
    DataContext,
    build_dashboard_context,
    build_dashboard_data_context,
    build_data_context,
    build_project_inventory,
)
from depictio.api.v1.endpoints.ai_endpoints.dashboard_validate import (
    schema_error,
    substance_error,
)
from depictio.api.v1.endpoints.ai_endpoints.filter_resolver import resolve_proposals
from depictio.api.v1.endpoints.ai_endpoints.sandbox import AnalysisSandbox, FrameSpec
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    AnalysisResult,
    AnalyzeRequest,
    ComponentFromPromptRequest,
    ComponentFromPromptResponse,
    DashboardActions,
    ExecutionStep,
    GenerateDashboardRequest,
    GenerationsResponse,
    PlotSuggestion,
    PromoteResponse,
    RegenerateRequest,
    ResolvedFilter,
    ResolveFiltersRequest,
    ResolveFiltersResponse,
    ReviewRequest,
    ReviewResponse,
    RoutingInfo,
    StreamEvent,
    SuggestComponentsRequest,
    SuggestComponentsResponse,
    SuggestFiguresRequest,
    SuggestFiguresResponse,
    SummariesResponse,
    SummarizeSectionRequest,
    SummarizeSectionResponse,
)
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_current_user,
    get_user_or_anonymous,
)
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


@ai_endpoint_router.post("/suggest-components", response_model=SuggestComponentsResponse)
async def suggest_components(
    body: SuggestComponentsRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> SuggestComponentsResponse:
    """Typed suggestions for a dashboard: "what would you add to it?"

    The dashboard's project inventory says which collections exist and
    which component types they can back; its components say what is
    already shown. `component_type` and `data_collection_id` are optional
    pins. table suggestions are ranked deterministically from the data (so
    is advanced_viz when it is the pinned type: no LLM call); the other
    types come from one LLM call constrained to the legal spaces computed
    server-side, which in Auto mode include the ranked advanced_viz kinds
    with their config keys so the model can propose one when it is apt.
    Every item is validated through the CLI's offline validator before it
    is returned, so "Use this" lands a component the builder accepts.

    See `suggest.suggest_components` for the error mapping (404 / 403 /
    422 / 502).
    """
    return await suggest_mod.suggest_components(
        body,
        current_user,
        user_api_key=user_api_key,
        build_inventory=build_project_inventory,
        build_dashboard_ctx=build_dashboard_context,
        build_data_ctx=build_data_context,
    )


@ai_endpoint_router.post("/suggest-figures", response_model=SuggestFiguresResponse, deprecated=True)
async def suggest_figures(
    body: SuggestFiguresRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> SuggestFiguresResponse:
    """Data-driven flow: propose N figures for a data collection.

    Deprecated: `/ai/suggest-components` proposes figures and every other
    type against the whole dashboard, and the viewer calls that instead.
    Kept for older clients; no new behaviour goes here.

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


def _repair_turn(messages: list[dict], raw: str, finding: str) -> list[dict]:
    """`messages` with the rejected answer and the finding to correct appended.

    A new list, not an in-place append: the caller rebinds it for the next
    attempt and the original stays the conversation the first attempt saw.
    """
    return messages + [
        {"role": "assistant", "content": raw},
        {
            "role": "user",
            "content": f"{finding}\n\nRe-emit the corrected YAML only — no prose, no fences.",
        },
    ]


@ai_endpoint_router.post("/component-from-prompt", response_model=ComponentFromPromptResponse)
async def component_from_prompt(
    body: ComponentFromPromptRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> ComponentFromPromptResponse:
    """Prompt-driven typed component creation.

    The component type and the data collection are optional pins. When
    either is left open, the request is routed first (see `routing`):
    the dashboard's project inventory is built, no-LLM shortcuts are
    tried for a pinned type with a single fitting collection, and
    otherwise one routing completion names the type and the collection.

    Generation is then the same for every path: the LLM emits one YAML
    component block; we run it through the same offline validator the
    CLI uses for `dashboard import` (`DashboardDataLite.from_yaml`), then
    the two checks the whole-dashboard generator runs on every tile it
    fills: `substance_error` (a component that parses and would still draw
    nothing) and `schema_error` (the columns, aggregations and widget types
    against what the collection actually stores). On any of those failures
    we feed the error back into the conversation and retry once before
    bailing out, so a repair costs one of the two attempts rather than an
    extra one.

    What this path deliberately does not run is the render probe. The
    builder draws a real preview of the answer within the second, which is
    a better check than a one-row probe and one the user can see; the
    generator needs the probe only because nothing looks at its tiles until
    the draft is saved.

    A `text` component has no data source, so it skips the data context
    and is prompted with a summary of the dashboard it is being added to
    (when `dashboard_id` is given) instead.
    """
    component_type = body.component_type
    data_collection_id = body.data_collection_id
    routing_info: RoutingInfo | None = RoutingInfo(source="user")

    if body.needs_routing:
        if not body.dashboard_id:
            # The request model already enforces this; kept as a guard
            # against a bypassed validator.
            raise HTTPException(status_code=422, detail="dashboard_id is required for routing.")
        inventory = await build_project_inventory(
            body.dashboard_id,
            current_user,
            prioritize=[data_collection_id] if data_collection_id else None,
        )
        try:
            decision = await routing.route_component(
                body.prompt,
                inventory,
                pinned_type=component_type,
                pinned_dc_id=data_collection_id,
                complete=lambda messages: llm_client.completion(
                    messages, user_api_key=user_api_key
                ),
            )
        except routing.RoutingError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        component_type = decision.component_type
        data_collection_id = decision.entry.data_collection_id if decision.entry else None
        routing_info = decision.routing

    if component_type is None:  # pragma: no cover - routing always settles it
        raise HTTPException(status_code=500, detail="component_type was not resolved.")

    # `text` has no data source: it is prompted with the dashboard it is being
    # added to instead of a data context. Every other type is the reverse.
    ctx: DataContext | None = None
    dashboard_block: str | None = None
    if component_type == "text":
        if body.dashboard_id:
            dashboard_ctx, _ = await build_dashboard_context(body.dashboard_id, current_user)
            dashboard_block = dashboard_ctx.components_block()
    else:
        if not data_collection_id:  # pragma: no cover - routing always settles it
            raise HTTPException(status_code=422, detail="data_collection_id is required.")
        ctx = await build_data_context(data_collection_id, current_user)

    messages = prompts.component_from_prompt_messages(
        ctx,
        body.prompt,
        component_type=component_type,
        current=body.current,
        dashboard_block=dashboard_block,
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
            messages = _repair_turn(messages, raw, last_error)
            continue

        # Same gate the generator applies: an icon outside the builder's own
        # picker renders as a blank box under the CSP and blanks itself on the
        # first save, so it never reaches the builder.
        component_style.sanitize_style(parsed)

        # And the same two content checks. `text` has no collection behind it,
        # so there is nothing to check its columns against.
        try:
            finding = substance_error(parsed) or (schema_error(parsed, ctx) if ctx else None)
        except (ValidationError, ValueError) as e:
            # `schema_error` re-validates the tile inside a dashboard envelope,
            # which is stricter than the tile on its own, so it can reject what
            # `validate_single` accepted. That is a finding to repair like any
            # other, not a 500 out of the handler.
            finding = component_yaml.format_validation_error_for_llm(e)
        if finding:
            last_error = finding
            logger.warning("component_from_prompt attempt %d failed: %s", attempt + 1, last_error)
            messages = _repair_turn(messages, raw, finding)
            continue

        title = parsed.get("title")
        return ComponentFromPromptResponse(
            component_type=parsed.get("component_type", component_type),
            yaml=component_yaml.dump_single(parsed),
            parsed=parsed,
            explanation=title.strip() if isinstance(title, str) else "",
            validation_attempts=attempt + 1,
            data_collection_id=ctx.data_collection_id if ctx else None,
            workflow_id=ctx.workflow_id if ctx else None,
            routing=routing_info,
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
    dashboard_ctx = dashboard_ctx.with_active_filters(body.filters)
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


def _sandbox_factory(specs: list[FrameSpec]) -> AnalysisSandbox:
    """Indirection so tests can substitute an in-process sandbox.

    Spawning a real child per test would be slow and would need a live
    delta table; `sandbox.InlineSandbox` has the same surface.
    """
    return AnalysisSandbox(specs)


def _frame_specs(
    collections: list[DataContext], active_filters: list[dict] | None
) -> list[FrameSpec]:
    """Describe the frames the sandbox child should load (sync).

    One spec per collection the prompt advertises: telling the model
    `dc["meta"]` exists while loading only the primary frame would trade
    a visible limitation for a runtime "unknown data collection" error.

    The child loads the frames itself: a spec is a few strings, whereas
    the frame it names may be gigabytes that would otherwise be
    serialised across the pipe on every respawn.

    Active dashboard filters are baked into the *first* (default)
    collection only — their column names belong to that DC, and applying
    them to a different collection is the silent-FILTER-MISMATCH failure
    mode where a filter matches nothing or everything without a word.
    Cross-DC filter propagation goes through project links, which the
    dashboard render path owns; the analysis sees other collections
    unfiltered, and the row counts in the prompt say so.
    """
    from depictio.api.v1.endpoints.ai_endpoints.context import init_data_for_dc

    specs: list[FrameSpec] = []
    for i, c in enumerate(collections):
        specs.append(
            FrameSpec(
                tag=c.data_collection_tag or c.data_collection_id,
                workflow_id=str(c.workflow_id),
                data_collection_id=str(c.data_collection_id),
                init_data=init_data_for_dc(c.data_collection_id),
                filters=(active_filters or None) if i == 0 else None,
            )
        )
    return specs


def _coerce_actions(
    payload: Any,
    *,
    read_only: bool,
    warnings: list[str],
) -> DashboardActions:
    """Turn the envelope's `actions` key into a DashboardActions.

    In read-only mode the key is dropped outright: a stray `actions` from
    a model that ignored its instructions is a prompt-adherence slip, not
    a reason to fail the whole turn, so it is recorded and discarded.

    A validation failure used to degrade to an empty object in silence,
    which handed the user an answer with no hint that the change they
    asked for had been dropped. Surface it instead.
    """
    if not payload:
        return DashboardActions()
    if read_only:
        warnings.append(
            "Dashboard actions were proposed but discarded: this analysis is read-only."
        )
        return DashboardActions()
    try:
        return DashboardActions.model_validate(payload)
    except ValidationError as e:
        logger.warning("DashboardActions validation: %s", e)
        warnings.append(f"The proposed dashboard actions were malformed and were dropped: {e}")
        return DashboardActions()


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
        # The sandbox frames below are built from `body.filters`; the prompt
        # must describe the same state or the model sees narrowed data it
        # was told is unfiltered.
        dashboard_ctx = dashboard_ctx.with_active_filters(body.filters)
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

    # The mutating flow keeps its single default DC: its output is a
    # filter on one collection anyway. The read-only flow (multi-DC,
    # budget, report) lives in `_run_analysis`.
    messages = prompts.analyze_messages(
        data_ctx,
        dashboard_ctx,
        body.prompt,
        body.selected_component_id,
        body.mode,
    )

    warnings: list[str] = []
    steps: list[ExecutionStep] = []
    answer = ""
    actions = DashboardActions()
    read_only = False

    # Built now, started lazily on the first code step: a prompt that needs
    # no computation should not pay for a process spawn and a delta read.
    sandbox = _sandbox_factory(await asyncio.to_thread(_frame_specs, [data_ctx], body.filters))

    try:
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
                step = await asyncio.to_thread(sandbox.run, code)
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
                    actions = _coerce_actions(
                        actions_payload, read_only=read_only, warnings=warnings
                    )
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
            actions = _coerce_actions(actions_payload, read_only=read_only, warnings=warnings)
            break
    finally:
        # Covers the early returns above and, crucially, client
        # disconnect: aborting the fetch closes this generator, and an
        # unreaped child would sit on a whole DataFrame indefinitely.
        await asyncio.to_thread(sandbox.close)

    resolved: list[ResolvedFilter] = []
    if not read_only:
        # Unwrapped, this used to abort the generator mid-stream with no
        # `error` and no `done`, leaving the client waiting on a truncated
        # SSE response forever.
        try:
            resolved, resolve_warnings = await asyncio.to_thread(
                resolve_proposals,
                actions.filter_proposals,
                dashboard_ctx=dashboard_ctx,
                workflow_id=data_ctx.workflow_id,
                data_collection_id=data_ctx.data_collection_id,
                active_filters=body.filters,
            )
            warnings.extend(resolve_warnings)
        except Exception as e:  # noqa: BLE001 — never strand the stream
            logger.exception("resolve_proposals failed")
            warnings.append(f"Could not resolve the proposed filters: {e}")

    result = AnalysisResult(
        answer=answer,
        steps=steps,
        mode=body.mode,
        actions=actions,
        resolved_filters=resolved,
        warnings=warnings,
    )
    yield _sse(StreamEvent(type="answer", data={"answer": answer}))
    if not read_only:
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


async def _run_analysis(
    body: AnalyzeRequest,
    current_user: User,
    user_api_key: str | None,
) -> AsyncIterator[bytes]:
    """The read-only analysis loop: multi-DC, budgeted, persisted.

    Differences from `_run_analyze` that justify a separate generator:
    every DC on the dashboard is in scope (with the project's declared
    joins); the loop runs until one of three budget bounds trips (steps /
    tokens / wall clock), with the countdown shown to the model each
    turn; the output is an `AnalysisReport` persisted to `ai_analyses`
    with evidence-checked findings; and there is no actions surface at
    all — anything the model proposes is discarded and recorded.
    """
    yield _sse(StreamEvent(type="status", data={"message": "loading dashboard"}))

    try:
        dashboard_ctx, primary_dc = await build_dashboard_context(body.dashboard_id, current_user)
        # The sandbox frames below are built from `body.filters`; the prompt
        # must describe the same state or the model sees narrowed data it
        # was told is unfiltered.
        dashboard_ctx = dashboard_ctx.with_active_filters(body.filters)
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

    yield _sse(StreamEvent(type="status", data={"message": "reading data collections"}))

    try:
        data_ctx = await build_data_context(primary_dc, current_user)
    except Exception as e:  # noqa: BLE001
        yield _sse(StreamEvent(type="error", data={"detail": str(e)}))
        yield _sse(StreamEvent(type="done"))
        return

    warnings: list[str] = []
    multi = None
    try:
        multi, ctx_warnings = await build_dashboard_data_context(dashboard_ctx, current_user)
        warnings.extend(ctx_warnings)
    except Exception as e:  # noqa: BLE001 — degrade to the single-DC context
        logger.warning("multi-DC context failed, falling back to the default DC: %s", e)
        warnings.append("Only the default data collection could be read for this analysis.")

    messages = prompts.analyze_messages(
        data_ctx,
        dashboard_ctx,
        body.prompt,
        body.selected_component_id,
        "analyze",
        multi=multi,
        warnings=warnings,
    )

    report = analyses.new_report(body.dashboard_id, body.prompt, llm_client.get_default_model())
    await asyncio.to_thread(analyses.save, report)

    max_steps = settings.ai.analyze_max_steps
    max_tokens_total = settings.ai.analyze_max_tokens_total
    max_wall_s = settings.ai.analyze_max_wall_clock_s
    started = time.monotonic()
    tokens_used = 0
    plan_emitted = False
    conclude = False
    answer = ""
    findings_payload: Any = []

    frame_ctxs = multi.collections if multi and multi.collections else [data_ctx]
    sandbox = _sandbox_factory(await asyncio.to_thread(_frame_specs, frame_ctxs, body.filters))

    yield _sse(StreamEvent(type="status", data={"message": "thinking"}))

    try:
        # +1: when a bound trips mid-loop the model gets one grace call to
        # conclude from the evidence it already has.
        for _ in range(max_steps + 1):
            try:
                completion = await asyncio.to_thread(
                    llm_client.completion_with_usage,
                    messages,
                    user_api_key=user_api_key,
                )
            except Exception as e:  # noqa: BLE001
                report.status = "failed"
                report.warnings = warnings + [f"LLM error: {e}"]
                await asyncio.to_thread(analyses.save, report)
                yield _sse(StreamEvent(type="error", data={"detail": f"LLM error: {e}"}))
                yield _sse(StreamEvent(type="done"))
                return
            if not completion.cached:
                tokens_used += completion.usage.total_tokens

            try:
                payload = llm_client.parse_json(completion.content)
            except Exception as e:  # noqa: BLE001
                report.status = "failed"
                report.warnings = warnings + [f"LLM returned invalid JSON: {e}"]
                await asyncio.to_thread(analyses.save, report)
                yield _sse(
                    StreamEvent(type="error", data={"detail": f"LLM returned invalid JSON: {e}"})
                )
                yield _sse(StreamEvent(type="done"))
                return

            thought = str(payload.get("thought", "")).strip()
            code = str(payload.get("code", "")).strip()
            answer = str(payload.get("answer", "")).strip() or answer
            findings_payload = payload.get("findings") or findings_payload
            # Read-only contract: whatever the model proposed, drop it.
            _coerce_actions(payload.get("actions"), read_only=True, warnings=warnings)

            plan = str(payload.get("plan", "")).strip()
            if plan and not plan_emitted:
                plan_emitted = True
                yield _sse(StreamEvent(type="plan", data={"plan": plan}))

            elapsed = time.monotonic() - started
            yield _sse(
                StreamEvent(
                    type="budget",
                    data={
                        "steps_used": len(report.steps),
                        "tokens_used": tokens_used,
                        "seconds": round(elapsed, 1),
                        "max_steps": max_steps,
                        "max_tokens": max_tokens_total,
                        "max_seconds": max_wall_s,
                    },
                )
            )

            if not code or conclude:
                if conclude and code:
                    # The grace call was asked to conclude and tried to
                    # keep computing instead; end the run on the evidence
                    # already gathered and say so.
                    warnings.append("The analysis hit its budget before the model concluded.")
                break

            yield _sse(
                StreamEvent(
                    type="step",
                    data={"thought": thought, "code": code, "status": "running"},
                )
            )
            step = await asyncio.to_thread(sandbox.run, code)
            step.thought = thought
            report.steps.append(step)
            report.budget_spent = analyses.budget_spent(
                len(report.steps), tokens_used, started, time.monotonic()
            )
            await asyncio.to_thread(analyses.save, report)
            yield _sse(StreamEvent(type="step", data=step.model_dump()))

            elapsed = time.monotonic() - started
            steps_left = max_steps - len(report.steps)
            tokens_left = max_tokens_total - tokens_used
            seconds_left = max_wall_s - elapsed
            conclude = steps_left <= 0 or tokens_left <= 0 or seconds_left <= 0

            messages = messages + [
                {"role": "assistant", "content": completion.content},
                {
                    "role": "user",
                    "content": prompts.analysis_continuation(
                        len(report.steps) - 1,
                        step.output,
                        step.rows_in,
                        step.rows_out,
                        step.seconds,
                        steps_left=max(steps_left, 0),
                        tokens_left=max(tokens_left, 0),
                        seconds_left=max(seconds_left, 0.0),
                        conclude=conclude,
                    ),
                },
            ]
        report.findings = analyses.parse_findings(findings_payload, report.steps, warnings)
        report.narrative_md = answer or "(no answer provided)"
        report.status = "complete"
    finally:
        # Runs on client disconnect too: reap the sandbox child, and leave
        # an inspectable record instead of a report stuck in "running".
        await asyncio.to_thread(sandbox.close)
        if report.status == "running":
            report.status = "cancelled"
        report.warnings = warnings
        report.budget_spent = analyses.budget_spent(
            len(report.steps), tokens_used, started, time.monotonic()
        )
        await asyncio.to_thread(analyses.save, report)

    result = AnalysisResult(
        answer=report.narrative_md,
        steps=report.steps,
        mode="analyze",
        resolved_filters=[],
        warnings=warnings,
    )
    yield _sse(StreamEvent(type="answer", data={"answer": report.narrative_md}))
    yield _sse(StreamEvent(type="report", data=report.model_dump()))
    yield _sse(StreamEvent(type="result", data=result.model_dump()))
    yield _sse(StreamEvent(type="done"))


@ai_endpoint_router.post("/analyze")
async def analyze(
    body: AnalyzeRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> StreamingResponse:
    """Prompt-driven analysis. Streams `StreamEvent` chunks as SSE.

    `mode` picks the loop: `mutate` (default) is the short conversational
    flow with dashboard actions; `analyze` is the read-only, budgeted,
    report-producing flow.
    """
    runner = _run_analysis if body.mode == "analyze" else _run_analyze
    return StreamingResponse(
        runner(body, current_user, user_api_key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@ai_endpoint_router.get("/analyses/{dashboard_id}")
async def list_analyses(
    dashboard_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Recent analysis reports for a dashboard (newest first).

    The dashboard-context build doubles as the permission gate, exactly
    like `/ai/summaries/{dashboard_id}`.
    """
    await build_dashboard_context(dashboard_id, current_user)
    reports = await asyncio.to_thread(analyses.latest_for_dashboard, dashboard_id)
    return {"analyses": [r.model_dump() for r in reports]}


# ---------------------------------------------------------------------------
# generate-dashboard: whole-dashboard drafts
# ---------------------------------------------------------------------------


@ai_endpoint_router.post("/generate-dashboard")
async def generate_dashboard(
    body: GenerateDashboardRequest,
    current_user: User = Depends(get_current_user),
    user_api_key: str | None = Depends(_llm_key),
) -> StreamingResponse:
    """A whole dashboard draft from a prompt. Streams `StreamEvent` chunks as SSE.

    The gates run before the stream opens so they answer with real HTTP
    codes: 422 from the request model when `plan_only` and `plan` are sent
    together (they are the two phases of one flow, never one request), then
    `dashboard_gen.gate_generate_request`: 404 when
    `settings.ai.generate_dashboard_enabled` is off, 403 in public mode or
    for an anonymous user outside single-user mode (the YAML import rule),
    403 without editor permission on the project, 400 for a
    `data_collection_id` outside the project. Everything after that is
    reported inside the stream (`error` + `done`), the draft included
    (`dashboard` + `done`).

    Two-phase runs use the same route: `plan_only` stops on the plan event
    and saves nothing, and sending that plan back as `plan` skips the
    planning call and fills it. A `plan` that does not parse, or that names
    a data collection outside this request's subset, is an `error` event
    inside the stream, not an HTTP status: the body was well-formed, the
    plan was not usable.
    """
    project_doc = await asyncio.to_thread(dashboard_gen.gate_generate_request, body, current_user)
    return StreamingResponse(
        dashboard_gen.run_generation(
            body, current_user, user_api_key=user_api_key, project_doc=project_doc
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@ai_endpoint_router.post(
    "/generated-dashboards/{dashboard_id}/promote", response_model=PromoteResponse
)
async def promote_generated_dashboard(
    dashboard_id: str,
    current_user: User = Depends(get_current_user),
) -> PromoteResponse:
    """Clear the draft flag of a generated dashboard (`ai_generation.status` -> promoted).

    404 when the dashboard does not exist or was not generated, 403 without
    editor permission (dashboard owners included, as for every other
    mutation). Discarding a draft is the ordinary dashboard delete.
    """
    return await asyncio.to_thread(dashboard_gen.promote_dashboard, dashboard_id, current_user)


# ---------------------------------------------------------------------------
# Reviewing a draft: regenerate a tile or a section, keep a tile, read history
# ---------------------------------------------------------------------------


def _gate_regeneration(
    dashboard_id: str,
    current_user: User,
    locate: Callable[[dict[str, Any]], list[int]],
) -> tuple[dict[str, Any], list[int]]:
    """The gates of both regenerate routes; returns the draft and what to re-fill.

    Run before the stream opens so they answer with real HTTP codes: the
    generation feature's own (404 flag off, 403 public mode, 403 anonymous),
    then 404 for a dashboard that does not exist or was not generated, 403
    without editor permission, and 404 from `locate` for a component index
    or a section this draft does not have. Everything after that is reported
    inside the stream. Synchronous (pymongo); the routes run it in a thread.
    """
    dashboard_gen.gate_generation_feature(current_user)
    _, doc = dashboard_gen.require_draft_dashboard(dashboard_id, current_user)
    return doc, locate(doc)


def _regeneration_response(
    doc: dict[str, Any],
    current_user: User,
    *,
    positions: list[int],
    section: str | None,
    instruction: str | None,
    user_api_key: str | None,
) -> StreamingResponse:
    """The SSE response of both regenerate routes."""
    return StreamingResponse(
        dashboard_gen.run_regeneration(
            doc,
            current_user,
            positions=positions,
            section=section,
            instruction=instruction,
            user_api_key=user_api_key,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@ai_endpoint_router.post("/generated-dashboards/{dashboard_id}/components/{index}/regenerate")
async def regenerate_generated_component(
    dashboard_id: str,
    index: str,
    body: RegenerateRequest,
    current_user: User = Depends(get_current_user),
    user_api_key: str | None = Depends(_llm_key),
) -> StreamingResponse:
    """Re-fill one tile of a draft. Streams `StreamEvent` chunks as SSE.

    `index` addresses the tile either by its position in `stored_metadata`
    or by its own `index` uuid. The stream is `status`* -> `budget` ->
    `component` -> `regenerated` -> `done`; a tile that cannot be re-filled
    is left exactly as it was and reported as `component` (status
    `dropped`) + `error` + `done`.
    """
    doc, positions = await asyncio.to_thread(
        _gate_regeneration,
        dashboard_id,
        current_user,
        lambda d: [dashboard_gen.locate_component(d, index)],
    )
    return _regeneration_response(
        doc,
        current_user,
        positions=positions,
        section=None,
        instruction=body.instruction,
        user_api_key=user_api_key,
    )


@ai_endpoint_router.post("/generated-dashboards/{dashboard_id}/sections/{section}/regenerate")
async def regenerate_generated_section(
    dashboard_id: str,
    section: str,
    body: RegenerateRequest,
    current_user: User = Depends(get_current_user),
    user_api_key: str | None = Depends(_llm_key),
) -> StreamingResponse:
    """Re-fill every tile of one section of a draft. Streams `StreamEvent` chunks as SSE.

    One `component` event per tile, then the section's layout pass runs
    again (boxes are section-relative, so nothing else moves) and the new
    components arrive in the terminal `regenerated` event. Tiles that could
    not be re-filled keep what they had.
    """
    doc, positions = await asyncio.to_thread(
        _gate_regeneration,
        dashboard_id,
        current_user,
        lambda d: dashboard_gen.locate_section(d, section),
    )
    return _regeneration_response(
        doc,
        current_user,
        positions=positions,
        section=section,
        instruction=body.instruction,
        user_api_key=user_api_key,
    )


@ai_endpoint_router.post(
    "/generated-dashboards/{dashboard_id}/review", response_model=ReviewResponse
)
async def review_generated_dashboard(
    dashboard_id: str,
    body: ReviewRequest,
    current_user: User = Depends(get_current_user),
) -> ReviewResponse:
    """Mark one tile of a draft reviewed (`keep`) or take the mark back (`unkeep`).

    404 when the dashboard does not exist or was not generated, 403 without
    editor permission. Returns the counts the review panel shows; a tag
    whose tile has since been deleted is dropped from the count rather than
    inflating it.
    """
    return await asyncio.to_thread(dashboard_gen.review_dashboard, dashboard_id, body, current_user)


@ai_endpoint_router.get("/generations/{project_id}", response_model=GenerationsResponse)
async def list_generations(
    project_id: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
) -> GenerationsResponse:
    """The project's dashboard generation runs, newest first.

    Viewer permission on the project; `limit` defaults to 20 and is capped
    at 50. The rows carry the per-component counts and the warnings, never
    the YAML or the plan: this is the history list, not the draft. An
    authenticated user, like the rest of the generation surface: the rows
    quote the prompts their author wrote.
    """
    return await asyncio.to_thread(dashboard_gen.list_generations, project_id, current_user, limit)
