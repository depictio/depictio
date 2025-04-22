from contextlib import asynccontextmanager
import logging
from typing import Any
from beanie import PydanticObjectId, init_beanie
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio

from depictio.api.v1.endpoints.routers import router
from depictio.api.v1.initialization import run_initialization
from depictio.api.v1.endpoints.utils_endpoints.process_data_collections import process_initial_data_collections
from depictio import BASE_PATH
from depictio.api.v1.configs.config import settings, MONGODB_URL

from depictio.models.utils import get_depictio_context
from depictio.models.models.users import TokenBeanie, GroupBeanie, UserBeanie
from depictio.models.models.projects import ProjectBeanie

DEPICTIO_CONTEXT = get_depictio_context()

load_dotenv(BASE_PATH.parent / ".env", override=False)
print(f"Current os env vars after loading .env: {os.environ}")


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
    # await run_initialization()

    # Create a background task to process data collections after the API is fully started
    background_task = delayed_process_data_collections()
    
    # Start the app
    yield
    
    # Shutdown: add cleanup tasks if needed
    # await shutdown_db()
    
    # Cancel the background task if it's still running
    if not background_task.done():
        background_task.cancel()


def delayed_process_data_collections():
    """
    Process initial data collections after a delay to ensure the API is fully started.
    """
    import time
    import threading
    
    # Wait longer to ensure the API has fully started
    time.sleep(5)
    
    def process_collections():
        try:
            print(f"Checking if API is ready at http://127.0.0.1:{settings.fastapi.port}/depictio/api/v1/utils/status...")
            
            # Use 127.0.0.1 instead of localhost to avoid potential DNS issues
            response = httpx.get(
                f"http://127.0.0.1:{settings.fastapi.port}/depictio/api/v1/utils/status",
                timeout=10.0
            )
                        
            if response.status_code == 200:
                print("API is ready. Processing initial data collections...")
                
                # Call the synchronous version of process_initial_data_collections
                from depictio.api.v1.endpoints.utils_endpoints.process_data_collections import sync_process_initial_data_collections
                
                result = sync_process_initial_data_collections()
                
                if result["success"]:
                    print("Initial data collections processed successfully")
                else:
                    print(f"Failed to process initial data collections: {result['message']}")
            else:
                print(f"API returned status code {response.status_code}. Skipping data collection processing.")
        except Exception as e:
            print(f"Error checking API status or processing data collections: {str(e)}")
    
    # Run the processing in a separate thread to avoid blocking
    thread = threading.Thread(target=process_collections)
    thread.daemon = True
    thread.start()
    
    return asyncio.Future()  # Return a future to make the function compatible with the cancel() call


# Define a custom type adapter for PydanticObjectId
def objectid_serializer(oid: PydanticObjectId | ObjectId) -> str:
    return str(oid)


# Updated JSON Response class that utilizes the serializer
class CustomJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        # Convert PydanticObjectId and ObjectId to str when serializing
        return super().render(
            jsonable_encoder(
                content,
                custom_encoder={
                    PydanticObjectId: objectid_serializer,
                    ObjectId: objectid_serializer,
                },
            )
        )


app = FastAPI(
    title="Depictio API",
    version="0.1.0",
    debug=True,
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

api_version = "v1"
api_prefix = f"/depictio/api/{api_version}"
app.include_router(router, prefix=api_prefix)
