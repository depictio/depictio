# in /app/api/v1/routers.py
from fastapi import APIRouter
from depictio.api.v1.endpoints.workflow_endpoints.routes import workflows_endpoint_router
from depictio.api.v1.endpoints.datacollections_endpoints.routes import datacollections_endpoint_router
from depictio.api.v1.endpoints.user_endpoints.auth import auth_endpoint_router

router = APIRouter()

# initialize_db(settings)
router.include_router(
    workflows_endpoint_router,
    prefix="/workflows",
    tags=["Workflows"],
)
router.include_router(
    datacollections_endpoint_router,
    prefix="/datacollections",
    tags=["Data Collections"],
)
router.include_router(
    auth_endpoint_router,
    prefix="/auth",
    tags=["Authentication"],
)
