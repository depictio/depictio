# in /app/api/v1/routers.py
from fastapi import APIRouter
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.workflow_endpoints.routes import workflows_endpoint_router
from depictio.api.v1.endpoints.datacollections_endpoints.routes import datacollections_endpoint_router
from depictio.api.v1.endpoints.files_endpoints.routes import files_endpoint_router
from depictio.api.v1.endpoints.deltatables_endpoints.routes import deltatables_endpoint_router
from depictio.api.v1.endpoints.user_endpoints.auth import auth_endpoint_router
from depictio.api.v1.endpoints.jbrowse_endpoints.routes import jbrowse_endpoints_router
from depictio.api.v1.endpoints.utils_endpoints.routes import utils_endpoint_router

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
    files_endpoint_router,
    prefix="/files",
    tags=["Files"],
)
router.include_router(
    deltatables_endpoint_router,
    prefix="/deltatables",
    tags=["DeltaTables"],
)
if settings.jbrowse.enabled:
    router.include_router(
        jbrowse_endpoints_router,
        prefix="/jbrowse",
        tags=["JBrowse"],
    )
router.include_router(
    auth_endpoint_router,
    prefix="/auth",
    tags=["Authentication"],
)

router.include_router(
    utils_endpoint_router,
    prefix="/utils",
    tags=["Utils"],
)
