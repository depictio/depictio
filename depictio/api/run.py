import uvicorn

from depictio.api.v1.configs.config import settings


def main():
    """
    Entry point for running the Depictio API server.
    """
    uvicorn.run(
        "depictio.api.main:app",
        host=settings.fastapi.host,
        port=settings.fastapi.external_port,
        reload=True,
        workers=settings.fastapi.workers,
        reload_dirs=[
            "/app/depictio/api",
            "/app/depictio/dash",
            "/app/depictio/cli",
            "/app/depictio/models",
        ],
    )


if __name__ == "__main__":
    main()
