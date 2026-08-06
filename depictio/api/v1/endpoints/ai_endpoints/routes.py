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
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ValidationError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints import component_yaml, llm_client, prompts
from depictio.api.v1.endpoints.ai_endpoints.code_gen import figure_python_code
from depictio.api.v1.endpoints.ai_endpoints.context import build_data_context
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    ComponentFromPromptRequest,
    ComponentFromPromptResponse,
    PlotSuggestion,
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
