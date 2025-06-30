# in /app/api/v1/routers.py
from fastapi import APIRouter

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.backup_endpoints.routes import backup_endpoint_router
from depictio.api.v1.endpoints.cli_endpoints.routes import cli_endpoint_router
from depictio.api.v1.endpoints.dashboards_endpoints.routes import dashboards_endpoint_router
from depictio.api.v1.endpoints.datacollections_endpoints.routes import (
    datacollections_endpoint_router,
)
from depictio.api.v1.endpoints.deltatables_endpoints.routes import deltatables_endpoint_router
from depictio.api.v1.endpoints.files_endpoints.routes import files_endpoint_router
from depictio.api.v1.endpoints.jbrowse_endpoints.routes import jbrowse_endpoints_router
from depictio.api.v1.endpoints.projects_endpoints.routes import projects_endpoint_router
from depictio.api.v1.endpoints.runs_endpoints.routes import runs_endpoint_router
from depictio.api.v1.endpoints.user_endpoints.routes import auth_endpoint_router
from depictio.api.v1.endpoints.utils_endpoints.routes import utils_endpoint_router
from depictio.api.v1.endpoints.workflow_endpoints.routes import workflows_endpoint_router

router = APIRouter()


# initialize_db(settings)
router.include_router(
    projects_endpoint_router,
    prefix="/projects",
    tags=["Projects"],
)
router.include_router(
    workflows_endpoint_router,
    prefix="/workflows",
    tags=["Workflows"],
)
router.include_router(
    runs_endpoint_router,
    prefix="/runs",
    tags=["Workflows runs"],
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
    utils_endpoint_router,
    prefix="/utils",
    tags=["Utils"],
)

router.include_router(
    backup_endpoint_router,
    prefix="/backup",
    tags=["Backup"],
)

router.include_router(
    cli_endpoint_router,
    prefix="/cli",
    tags=["CLI"],
)

router.include_router(
    dashboards_endpoint_router,
    prefix="/dashboards",
    tags=["Dashboards"],
)


router.include_router(
    auth_endpoint_router,
    prefix="/auth",
    tags=["Authentication"],
)

# Include Google OAuth router (enabled/disabled check is done in endpoints)
router.include_router(
    google_oauth_router,
    prefix="/auth/google",
    tags=["Google OAuth"],
)
