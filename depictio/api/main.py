"""
Depictio FastAPI Application.

Main application entry point with middleware, routing, and error handling.
"""

import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.routers import router
from depictio.api.v1.json_response import CustomJSONResponse
from depictio.api.v1.middleware.analytics_middleware import AnalyticsMiddleware
from depictio.api.v1.services.lifespan import lifespan
from depictio.models.utils import get_depictio_context
from depictio.version import get_api_version, get_version

# Ensure context is loaded before first use
DEPICTIO_CONTEXT = get_depictio_context()

# Check if in development mode
dev_mode = os.environ.get("DEPICTIO_DEV_MODE", "false").lower() == "true"


# Create FastAPI application
app = FastAPI(
    title="Depictio API",
    version=get_version(),
    debug=dev_mode,
    lifespan=lifespan,
    default_response_class=CustomJSONResponse,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Add analytics middleware if enabled
if settings.analytics.enabled:
    app.add_middleware(AnalyticsMiddleware, enabled=settings.analytics.enabled)

# Include API router with versioned prefix
api_version = get_api_version()
api_prefix = f"/depictio/api/{api_version}"
app.include_router(router, prefix=api_prefix)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request, exc):
    """Handle request validation errors with formatted error details."""
    return JSONResponse(status_code=422, content={"detail": [str(error) for error in exc.errors()]})
