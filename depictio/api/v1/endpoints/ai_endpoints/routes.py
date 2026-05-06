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

from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    AnalyzeRequest,
    FigureFromPromptRequest,
    FigureFromPromptResponse,
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


@ai_endpoint_router.post("/suggest-figures", response_model=SuggestFiguresResponse)
async def suggest_figures(
    body: SuggestFiguresRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> SuggestFiguresResponse:
    """Data-driven: propose N figures for a data collection.

    Implementation lands in Layer 2 (executor + context builder).
    """
    raise HTTPException(status_code=501, detail="suggest-figures: not yet implemented")


@ai_endpoint_router.post("/figure-from-prompt", response_model=FigureFromPromptResponse)
async def figure_from_prompt(
    body: FigureFromPromptRequest,
    current_user: User = Depends(get_user_or_anonymous),
    user_api_key: str | None = Depends(_llm_key),
) -> FigureFromPromptResponse:
    """Prompt-driven viz creation. Implementation lands in Layer 2."""
    raise HTTPException(status_code=501, detail="figure-from-prompt: not yet implemented")


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
