
import sys

sys.path.append("/Users/tweber/Gits/depictio")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi_backend.modules.workflow_endpoints.routes import workflows_endpoint_router
from fastapi_backend.modules.datacollections_endpoints.routes import datacollections_endpoint_router

# from db import initialize_db
from fastapi_backend.configs.config import settings

app = FastAPI(title="Depictio Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# initialize_db(settings)
app.include_router(
    workflows_endpoint_router,
    prefix="/workflows",
    tags=["Workflows"],
)
app.include_router(
    datacollections_endpoint_router,
    prefix="/datacollections",
    tags=["Data Collections"],
)
