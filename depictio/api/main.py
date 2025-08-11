import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, cast

import pymongo
from beanie import PydanticObjectId, init_beanie
from bson import ObjectId

# from dotenv import load_dotenv
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
from depictio.models.utils import get_depictio_context
from depictio.version import get_api_version, get_version

# Ensure context is loaded before first use
DEPICTIO_CONTEXT = get_depictio_context()


# Database initialization
async def init_motor_beanie():
    client = AsyncIOMotorClient(MONGODB_URL)
    await init_beanie(
        database=cast(AsyncDatabase, client[settings.mongodb.db_name]),
        document_models=[
            TokenBeanie,
            GroupBeanie,
            UserBeanie,
            ProjectBeanie,
            UserSession,
            UserActivity,
        ],
    )


async def check_and_set_initialization():
    """
    Atomically check if initialization is needed and mark it as in-progress.
    Returns True if this worker should perform initialization.
    """
    from depictio.api.v1.db import initialization_collection

    try:
        # First check if initialization is already complete
        existing = initialization_collection.find_one({"initialization_complete": True})
        if existing:
            return False

        # Try to insert an initialization document atomically
        # This will only succeed for the first worker that tries
        initialization_collection.insert_one(
            {
                "_id": "init_lock",  # Use fixed _id for uniqueness
                "initialization_complete": False,
                "initialization_in_progress": True,
                "worker_id": os.getpid(),  # Track which worker is doing init
                "started_at": datetime.now(timezone.utc),
            }
        )
        print(f"Worker {os.getpid()}: Acquired initialization lock")
        return True  # This worker should do initialization
    except pymongo.errors.DuplicateKeyError:  # type: ignore[unresolved-attribute]
        # Another worker already started initialization
        print(f"Worker {os.getpid()}: Another worker is handling initialization")
        return False
    except Exception as e:
        print(f"Worker {os.getpid()}: Error checking initialization: {e}")
        # Check if initialization was already completed
        existing = initialization_collection.find_one({"initialization_complete": True})
        return existing is None


async def mark_initialization_complete():
    """Mark initialization as complete atomically."""
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
    print(f"Worker {os.getpid()}: Marked initialization as complete")
    return result.modified_count > 0


async def cleanup_failed_initialization():
    """Clean up initialization lock if initialization fails."""
    from depictio.api.v1.db import initialization_collection

    initialization_collection.delete_one({"_id": "init_lock", "initialization_in_progress": True})
    print(f"Worker {os.getpid()}: Cleaned up failed initialization lock")


async def wait_for_initialization_complete(timeout=300):
    """Wait for another worker to complete initialization."""
    import time

    from depictio.api.v1.db import initialization_collection

    print(f"Worker {os.getpid()}: Waiting for initialization to complete...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        result = initialization_collection.find_one({"initialization_complete": True})
        if result:
            print(f"Worker {os.getpid()}: Initialization completed by another worker")
            return True
        await asyncio.sleep(1)  # Wait 1 second before checking again

    raise TimeoutError("Initialization did not complete within timeout period")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database, etc.
    await init_motor_beanie()

    # Determine if this worker should perform initialization
    should_initialize = False

    if settings.mongodb.wipe:
        print(f"Worker {os.getpid()}: Database wipe requested")
        # If wiping, we need to clear any existing initialization markers
        from depictio.api.v1.db import initialization_collection

        initialization_collection.delete_many({})
        should_initialize = await check_and_set_initialization()
    else:
        # Normal startup - check if initialization is needed
        should_initialize = await check_and_set_initialization()

    if should_initialize:
        print(f"Worker {os.getpid()}: Running initialization...")
        try:
            await run_initialization()
            await mark_initialization_complete()
            # Clean up screenshots directory (each worker can do this safely)
            print(f"Worker {os.getpid()}: Initialization completed successfully")
            await clean_screenshots()
            print(f"Worker {os.getpid()}: Screenshots directory cleaned up")
        except Exception as e:
            print(f"Worker {os.getpid()}: Initialization failed: {e}")
            await cleanup_failed_initialization()
            raise
    else:
        # Wait for another worker to complete initialization
        try:
            await wait_for_initialization_complete()
        except TimeoutError as e:
            print(f"Worker {os.getpid()}: {e}")
            raise

    # Only start background task on the worker that did initialization
    background_task = None
    if should_initialize:
        print(f"Worker {os.getpid()}: Starting background data collection processing")
        background_task = delayed_process_data_collections()

    # Start cleanup tasks on every worker (not just the initializing one)
    print(f"Worker {os.getpid()}: Starting cleanup tasks")
    start_cleanup_tasks()

    # Start the app
    yield

    # Shutdown: add cleanup tasks if needed
    if background_task and not background_task.done():
        print(f"Worker {os.getpid()}: Cancelling background task")
        background_task.cancel()


def delayed_process_data_collections():
    """
    Process initial data collections after a delay to ensure the API is fully started.
    """
    import threading
    import time

    # Check first if files exist
    from depictio.api.v1.db import deltatables_collection, projects_collection

    # Retrieve only DC id for the iris_table by using projection
    dc_id = projects_collection.find_one(
        {"workflows.data_collections.data_collection_tag": "iris_table"}
    )

    if dc_id:
        dc_id = dc_id.get("workflows", [{}])[0].get("data_collections", [{}])[0].get("_id")
        if dc_id:
            _check_deltatables = deltatables_collection.find_one(
                {"data_collection_id": dc_id}, {"_id": 1}
            )
            if _check_deltatables:
                print(f"Worker {os.getpid()}: Data collections already processed, skipping")
                return

    # Wait longer to ensure the API has fully started
    print(f"Worker {os.getpid()}: Waiting 5 seconds before processing data collections")
    time.sleep(5)

    # Run the processing in a separate thread to avoid blocking
    print(f"Worker {os.getpid()}: Starting data collection processing thread")
    thread = threading.Thread(target=process_collections)
    thread.daemon = True
    thread.start()

    return (
        asyncio.Future()
    )  # Return a future to make the function compatible with the cancel() call


# Define a custom type adapter for PydanticObjectId
def objectid_serializer(oid: PydanticObjectId | ObjectId | PyObjectId) -> str:
    return str(oid)


# Custom JSON encoder function to handle ObjectId serialization
def custom_jsonable_encoder(obj, **kwargs):
    if isinstance(obj, ObjectId | PydanticObjectId | PyObjectId):
        return str(obj)

    # Handle dictionaries
    if isinstance(obj, dict):
        return {k: custom_jsonable_encoder(v, **kwargs) for k, v in obj.items()}

    # Handle lists or other iterables
    if isinstance(obj, list | tuple | set):
        return [custom_jsonable_encoder(i, **kwargs) for i in obj]

    # Use the default jsonable_encoder for other types
    try:
        return jsonable_encoder(obj, **kwargs)
    except Exception:
        # If jsonable_encoder fails, try to convert to string
        try:
            return str(obj)
        except Exception:
            return f"<Unserializable object: {type(obj).__name__}>"


# Updated JSON Response class that utilizes the serializer
class CustomJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        # Use our custom encoder that recursively handles ObjectId instances
        serialized_content = custom_jsonable_encoder(
            content,
            custom_encoder={
                PydanticObjectId: objectid_serializer,
                ObjectId: objectid_serializer,
                PyObjectId: objectid_serializer,
            },
        )
        return super().render(serialized_content)


# Check if in development mode
dev_mode = os.environ.get("DEV_MODE", "false").lower() == "true"


app = FastAPI(
    title="Depictio API",
    version=get_version(),
    debug=dev_mode,
    lifespan=lifespan,
    default_response_class=CustomJSONResponse,
)

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

api_version = get_api_version()
api_prefix = f"/depictio/api/{api_version}"
app.include_router(router, prefix=api_prefix)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    _ = request  # Suppress unused parameter warning
    return JSONResponse(status_code=422, content={"detail": [str(error) for error in exc.errors()]})
