import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from beanie import PydanticObjectId, init_beanie
from bson import ObjectId

# from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient

from depictio import BASE_PATH
from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.endpoints.routers import router
from depictio.api.v1.endpoints.utils_endpoints.process_data_collections import (
    process_collections,
)
from depictio.api.v1.initialization import run_initialization
from depictio.api.v1.utils import clean_screenshots
from depictio.models.models.base import PyObjectId
from depictio.models.models.projects import ProjectBeanie
from depictio.models.models.users import GroupBeanie, TokenBeanie, UserBeanie
from depictio.models.utils import get_depictio_context
from depictio.version import get_api_version, get_version

# Detailed .env file debugging
# print(f"BASE_PATH: {BASE_PATH}")
# print(f"BASE_PATH.parent: {BASE_PATH.parent}")
# print(f"Attempting to load .env from: {BASE_PATH.parent / '.env'}")
# print(f"Does .env file exist? {os.path.exists(BASE_PATH.parent / '.env')}")
# print(f"Full .env file path: {os.path.abspath(BASE_PATH.parent / '.env')}")

# Try alternative loading methods
# try:
#     from dotenv import dotenv_values

#     env_values = dotenv_values(BASE_PATH.parent / ".env")
#     print(f"Dotenv values: {env_values}")
# except Exception as e:
#     print(f"Error loading .env with dotenv_values: {e}")

# Ensure context is loaded before first use
DEPICTIO_CONTEXT = get_depictio_context()
print(f"DEPICTIO_CONTEXT set to: {DEPICTIO_CONTEXT}")


# Database initialization
async def init_motor_beanie():
    client = AsyncIOMotorClient(MONGODB_URL)
    await init_beanie(
        database=client[settings.mongodb.db_name],
        document_models=[TokenBeanie, GroupBeanie, UserBeanie, ProjectBeanie],
    )


async def check_initialization():
    from depictio.api.v1.db import initialization_collection

    result = initialization_collection.find_one({"initialization_complete": True})
    if result:
        return True
    else:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database, etc.
    await init_motor_beanie()

    # Initialize system before creating the app if not already initialized
    if not await check_initialization() or settings.mongodb.wipe:
        print("Initialization not complete. Running initialization...")
        await run_initialization()
    else:
        print("Initialization already complete. Skipping...")

    # Clean up screenshots directory
    await clean_screenshots()

    # Create a background task to process data collections after the API is fully started
    background_task = delayed_process_data_collections()

    # Start the app
    yield

    # Shutdown: add cleanup tasks if needed
    # await shutdown_db()

    # Cancel the background task if it's still running
    if background_task:
        if not background_task.done():
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
    dc_id = dc_id.get("workflows", [{}])[0].get("data_collections", [{}])[0].get("_id")
    print(f"DC id: {dc_id}")
    print(f"DC id type: {type(dc_id)}")

    if dc_id:
        _check_deltatables = deltatables_collection.find_one(
            {"data_collection_id": dc_id}, {"_id": 1}
        )
        print(f"Check deltatables: {_check_deltatables}")
        if _check_deltatables:
            print(
                f"Data collection with ID {dc_id} already exists in deltatables_collection."
            )
            return

    # Wait longer to ensure the API has fully started
    time.sleep(5)

    # Run the processing in a separate thread to avoid blocking
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
    if isinstance(obj, (ObjectId, PydanticObjectId, PyObjectId)):
        return str(obj)

    # Handle dictionaries
    if isinstance(obj, dict):
        return {k: custom_jsonable_encoder(v, **kwargs) for k, v in obj.items()}

    # Handle lists or other iterables
    if isinstance(obj, (list, tuple, set)):
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

api_version = get_api_version()
api_prefix = f"/depictio/api/{api_version}"
app.include_router(router, prefix=api_prefix)
