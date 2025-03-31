from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from depictio.api.v1.endpoints.routers import router
from depictio import BASE_PATH
import os 
os.environ["DEPICTIO_CONTEXT"] = "server"
from depictio_models.utils import get_depictio_context
DEPICTIO_CONTEXT = get_depictio_context()

from dotenv import load_dotenv
load_dotenv(BASE_PATH.parent / ".env")

# Import initialization module
from depictio.api.v1.initialization import run_initialization

# Initialize system before creating the app
try:
    run_initialization()
except Exception as e:
    print(f"Initialization failed: {e}")
    raise

app = FastAPI(title="Depictio API", version="0.1.0", debug=True)

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
