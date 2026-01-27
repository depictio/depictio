import uvicorn

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

RELOAD_DIRS = [
    "/app/depictio/api",
    "/app/depictio/dash",
    "/app/depictio/cli",
    "/app/depictio/models",
]


def main() -> None:
    """Entry point for running the Depictio API server in development mode."""
    host = settings.fastapi.host
    port = settings.fastapi.service_port

    logger.info(f"Starting FastAPI server on {host}:{port} (reload mode, single worker)")

    uvicorn.run(
        "depictio.api.main:app",
        host=host,
        port=port,
        reload=True,
        reload_dirs=RELOAD_DIRS,
    )


if __name__ == "__main__":
    main()
