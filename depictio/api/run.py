import uvicorn

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

RELOAD_DIRS = [
    "/app/depictio/api",
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
        # `watchfiles` n'est pas une dépendance, donc uvicorn retombe sur
        # StatReload : à chaque passe il fait rglob("*.py") + stat() + resolve()
        # sur tout RELOAD_DIRS, et `reload_excludes` est ignoré (uvicorn le
        # signale explicitement). Le défaut de 0.25s donne ~4 passes/s à travers
        # le bind mount macOS, pour rien la plupart du temps. 1s garde un reload
        # confortable en divisant par ~4 le CPU idle du reloader.
        reload_delay=1.0,
    )


if __name__ == "__main__":
    main()
