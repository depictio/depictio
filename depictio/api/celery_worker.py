"""
Celery worker entry point for the FastAPI-only Depictio backend.

With the Dash front end removed, this module exists solely so Celery workers
can be launched against the API's task registry. Importing
``depictio.api.v1.celery_tasks`` triggers the ``@celery_app.task`` decorators,
ensuring every task defined alongside the API is discoverable on the worker.

Usage:
    celery -A depictio.api.celery_worker:celery_app worker --loglevel=info
"""

from depictio.api.celery_app import celery_app
from depictio.api.v1 import celery_tasks  # noqa: F401  (import for side effects)
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

_registered_tasks = [name for name in celery_app.tasks.keys() if not name.startswith("celery.")]
logger.info("Celery worker ready: %d task(s) registered", len(_registered_tasks))

# Capture worker-side application logs into the monitoring ledger (tagged
# source="celery"). Best-effort: never block worker startup.
if settings.monitoring.enabled:
    try:
        from depictio.api.v1.monitoring.log_handler import install_app_log_handler

        install_app_log_handler(source="celery")
    except Exception as _exc:  # pragma: no cover - defensive
        logger.warning("monitoring: failed to install worker app-log handler: %s", _exc)

__all__ = ["celery_app"]
