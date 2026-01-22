"""
FastAPI application entry point for Depictio API.

This module initializes the FastAPI application with:
- MongoDB/Beanie ODM configuration
- CORS middleware
- Analytics middleware (optional)
- Background cleanup tasks
- Custom JSON serialization for ObjectId types

The application uses a lifespan context manager for proper startup/shutdown handling.
"""

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, cast

import pymongo
from beanie import PydanticObjectId, init_beanie
from bson import ObjectId
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.asynchronous.database import AsyncDatabase

from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.endpoints.routers import router
from depictio.api.v1.endpoints.utils_endpoints.process_data_collections import process_collections
from depictio.api.v1.initialization import run_initialization
from depictio.api.v1.middleware.analytics_middleware import AnalyticsMiddleware
from depictio.api.v1.tasks.cleanup_tasks import start_cleanup_tasks
from depictio.api.v1.utils import clean_screenshots
from depictio.models.models.analytics import UserActivity, UserSession
from depictio.models.models.base import PyObjectId
from depictio.models.models.projects import ProjectBeanie
from depictio.models.models.users import GroupBeanie, TokenBeanie, UserBeanie
from depictio.version import get_api_version, get_version


async def init_motor_beanie() -> None:
    """
    Initialize Motor (async MongoDB driver) and Beanie ODM.

    Sets up the async database connection and registers all document models
    for Beanie ODM operations. This must be called before any database
    operations can be performed.

    Raises:
        ConnectionError: If unable to connect to MongoDB.
    """
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(MONGODB_URL)
    await init_beanie(
        database=cast(AsyncDatabase[dict[str, Any]], client[settings.mongodb.db_name]),
        document_models=[
            TokenBeanie,
            GroupBeanie,
            UserBeanie,
            ProjectBeanie,
            UserSession,
            UserActivity,
        ],
    )


async def check_and_set_initialization() -> bool:
    """
    Atomically check if initialization is needed and mark it as in-progress.

    Uses MongoDB's atomic operations to ensure only one worker performs
    initialization in multi-worker deployments. This prevents race conditions
    where multiple workers might try to initialize simultaneously.

    Returns:
        True if this worker should perform initialization, False otherwise.
    """
    from depictio.api.v1.db import initialization_collection

    try:
        if initialization_collection.find_one({"initialization_complete": True}):
            return False

        initialization_collection.insert_one(
            {
                "_id": "init_lock",
                "initialization_complete": False,
                "initialization_in_progress": True,
                "worker_id": os.getpid(),
                "started_at": datetime.now(timezone.utc),
            }
        )
        return True
    except pymongo.errors.DuplicateKeyError:  # type: ignore[unresolved-attribute]
        return False
    except Exception:
        existing = initialization_collection.find_one({"initialization_complete": True})
        return existing is None


async def mark_initialization_complete() -> bool:
    """
    Mark initialization as complete atomically.

    Updates the initialization lock document to indicate that initialization
    has finished successfully.

    Returns:
        True if the update was successful, False otherwise.
    """
    from depictio.api.v1.db import initialization_collection

    result = initialization_collection.update_one(
        {"_id": "init_lock", "initialization_in_progress": True},
        {
            "$set": {
                "initialization_complete": True,
                "initialization_in_progress": False,
                "completed_at": datetime.now(timezone.utc),
            }
        },
    )
    return result.modified_count > 0


async def cleanup_failed_initialization() -> None:
    """
    Clean up initialization lock if initialization fails.

    Removes the initialization lock document to allow other workers
    to attempt initialization after a failure.
    """
    from depictio.api.v1.db import initialization_collection

    initialization_collection.delete_one({"_id": "init_lock", "initialization_in_progress": True})


async def wait_for_initialization_complete(timeout: int = 300) -> bool:
    """
    Wait for another worker to complete initialization.

    Polls the database until initialization is marked complete or timeout occurs.

    Args:
        timeout: Maximum time to wait in seconds.

    Returns:
        True if initialization completed successfully.

    Raises:
        TimeoutError: If initialization does not complete within timeout period.
    """
    from depictio.api.v1.db import initialization_collection

    start_time = time.time()
    while time.time() - start_time < timeout:
        if initialization_collection.find_one({"initialization_complete": True}):
            return True
        await asyncio.sleep(1)

    raise TimeoutError("Initialization did not complete within timeout period")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler for startup and shutdown.

    Manages the application lifecycle including:
    - Database initialization via Beanie ODM
    - Single-worker initialization coordination
    - Background task management for data collection processing
    - Cleanup task scheduling

    Args:
        app: FastAPI application instance.

    Yields:
        None during application runtime.

    Raises:
        Exception: Re-raises any initialization errors after cleanup.
    """
    await init_motor_beanie()

    if settings.mongodb.wipe:
        from depictio.api.v1.db import initialization_collection

        initialization_collection.delete_many({})

    should_initialize = await check_and_set_initialization()

    if should_initialize:
        try:
            await run_initialization()
            await mark_initialization_complete()
            await clean_screenshots()
        except Exception as e:
            await cleanup_failed_initialization()
            raise e
    else:
        await wait_for_initialization_complete()

    background_task: asyncio.Future[None] | None = None
    if should_initialize:
        background_task = delayed_process_data_collections()

    start_cleanup_tasks()

    yield

    if background_task and not background_task.done():
        background_task.cancel()


def delayed_process_data_collections() -> asyncio.Future[None]:
    """
    Process initial data collections after a delay to ensure the API is fully started.

    Checks if the iris_table data collection already exists before processing.
    Runs the collection processing in a daemon thread to avoid blocking.

    Returns:
        An asyncio Future that can be used to track/cancel the background task.
    """
    from depictio.api.v1.db import deltatables_collection, projects_collection

    dc_id = projects_collection.find_one(
        {"workflows.data_collections.data_collection_tag": "iris_table"}
    )

    if dc_id:
        dc_id = dc_id.get("workflows", [{}])[0].get("data_collections", [{}])[0].get("_id")
        if dc_id:
            if deltatables_collection.find_one({"data_collection_id": dc_id}, {"_id": 1}):
                return asyncio.Future()

    time.sleep(5)

    thread = threading.Thread(target=process_collections)
    thread.daemon = True
    thread.start()

    return asyncio.Future()


def custom_jsonable_encoder(obj: Any, **kwargs: Any) -> Any:
    """
    Custom JSON encoder that handles ObjectId serialization recursively.

    Extends FastAPI's default jsonable_encoder to properly serialize
    MongoDB ObjectId types throughout nested structures.

    Args:
        obj: Object to encode.
        **kwargs: Additional arguments passed to jsonable_encoder.

    Returns:
        JSON-serializable representation of the object.
    """
    if isinstance(obj, ObjectId | PydanticObjectId | PyObjectId):
        return str(obj)

    if isinstance(obj, dict):
        return {k: custom_jsonable_encoder(v, **kwargs) for k, v in obj.items()}

    if isinstance(obj, list | tuple | set):
        return [custom_jsonable_encoder(i, **kwargs) for i in obj]

    try:
        return jsonable_encoder(obj, **kwargs)
    except Exception:
        try:
            return str(obj)
        except Exception:
            return f"<Unserializable object: {type(obj).__name__}>"


class CustomJSONResponse(JSONResponse):
    """
    Custom JSON response class that handles ObjectId serialization.

    Extends FastAPI's JSONResponse to properly serialize MongoDB ObjectId
    types using the custom_jsonable_encoder.
    """

    def render(self, content: Any) -> bytes:
        """
        Render content to JSON bytes with ObjectId serialization support.

        Args:
            content: Content to render as JSON.

        Returns:
            JSON-encoded bytes.
        """
        return super().render(custom_jsonable_encoder(content))


# Check if in development mode
dev_mode = os.environ.get("DEPICTIO_DEV_MODE", "false").lower() == "true"


app = FastAPI(
    title="Depictio API",
    version=get_version(),
    debug=dev_mode,
    lifespan=lifespan,
    default_response_class=CustomJSONResponse,
)

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

api_version = get_api_version()
api_prefix = f"/depictio/api/{api_version}"
app.include_router(router, prefix=api_prefix)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: object, exc: RequestValidationError
) -> JSONResponse:
    """Handle validation errors with a simplified error response."""
    return JSONResponse(status_code=422, content={"detail": [str(error) for error in exc.errors()]})
