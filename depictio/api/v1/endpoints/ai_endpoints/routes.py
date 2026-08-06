"""HTTP routes for the AI endpoints.

All flows consume the user's LLM API key from the ``X-LLM-API-Key`` header
(set from the React Settings Drawer; never persisted server-side), falling
back to the server-side ``settings.ai.api_key`` when absent.

The router is only registered when ``settings.ai.enabled`` is true (see
``depictio/api/v1/endpoints/routers.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.users import User

ai_endpoint_router = APIRouter()


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
