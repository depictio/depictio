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

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from pydantic import ValidationError

from depictio.api.v1.endpoints.ai_endpoints import llm_client, prompts
from depictio.api.v1.endpoints.ai_endpoints.context import build_data_context
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    AnalyzeRequest,
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
        return PlotSuggestion.model_validate(payload)
    except ValidationError as e:
        logger.warning("PlotSuggestion validation failed: %s", e)
        return None


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
    messages = prompts.figure_from_prompt_messages(ctx, body.prompt)

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


async def _analyze_stream(
    body: AnalyzeRequest,
    current_user: User,
    user_api_key: str | None,
) -> AsyncIterator[bytes]:
    """SSE-formatted async generator for the analyze flow.

    Layer 3 fills in the actual analysis loop. This stub emits a single
    `error` + `done` pair so the React client wiring can be exercised.
    """
    err = StreamEvent(type="error", data={"detail": "analyze: not yet implemented"})
    yield f"event: {err.type}\ndata: {err.model_dump_json(exclude={'type'})}\n\n".encode()
    done = StreamEvent(type="done")
    yield f"event: {done.type}\ndata: {{}}\n\n".encode()


@ai_endpoint_router.post("/analyze")
async def analyze(
    body: AnalyzeRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> StreamingResponse:
    """Prompt-driven analysis. Streams `StreamEvent` chunks as SSE."""
    return StreamingResponse(
        _analyze_stream(body, current_user, user_api_key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
