
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from depictio.api.v1.endpoints.routers import router

# from db import initialize_db
from depictio.api.v1.configs.config import settings

app = FastAPI(title="Depictio API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

api_version = "v1"
api_prefix = f"/api/{api_version}"
app.include_router(router, prefix=api_prefix)
