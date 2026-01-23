"""
Depictio FastAPI Application.

Main application entry point with middleware, routing, and error handling.
"""

import logging
import os
import re
from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.routers import router
from depictio.api.v1.json_response import CustomJSONResponse
from depictio.api.v1.middleware.analytics_middleware import AnalyticsMiddleware
from depictio.api.v1.services.lifespan import lifespan
from depictio.version import get_api_version, get_version


# Custom filter to mask tokens in Uvicorn access logs
class TokenMaskingFilter(logging.Filter):
    """Filter that masks sensitive tokens in log messages."""

    TOKEN_PATTERN = re.compile(r"(token|access_token|refresh_token)=([^&\s\"]+)")

    def filter(self, record: logging.LogRecord) -> bool:
        """Mask tokens in the log message."""
        if hasattr(record, "msg") and record.msg:
            record.msg = self.TOKEN_PATTERN.sub(r"\1=***", str(record.msg))
        if hasattr(record, "args") and record.args:
            masked_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    masked_args.append(self.TOKEN_PATTERN.sub(r"\1=***", arg))
                else:
                    masked_args.append(arg)
            record.args = tuple(masked_args)
        return True


# Apply token masking filter to uvicorn access logger
uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.addFilter(TokenMaskingFilter())

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
# Cast needed due to incomplete FastAPI middleware type stubs
app.add_middleware(
    cast(Any, CORSMiddleware),
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Add analytics middleware if enabled
if settings.analytics.enabled:
    app.add_middleware(cast(Any, AnalyticsMiddleware), enabled=settings.analytics.enabled)

# Include API router with versioned prefix
api_version = get_api_version()
api_prefix = f"/depictio/api/{api_version}"
app.include_router(router, prefix=api_prefix)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: object, exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors with formatted error details."""
    return JSONResponse(status_code=422, content={"detail": [str(error) for error in exc.errors()]})
