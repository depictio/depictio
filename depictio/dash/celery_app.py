"""
Celery application for background task processing.
Integrated with FastAPI backend for dashboard component generation.
"""

from celery import Celery

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

# Create Celery app with configuration from settings
logger.info("🔧 CELERY SETUP: Initializing Celery app...")
logger.info(f"🔧 CELERY BROKER: {settings.celery.broker_url}")
logger.info(f"🔧 CELERY BACKEND: {settings.celery.result_backend_url}")

celery_app = Celery(
    __name__,
    broker=settings.celery.broker_url,
    backend=settings.celery.broker_url,
)

# Configure Celery - keep it simple for Dash background callbacks
# celery_app.conf.update(
#     task_serializer="json",
#     accept_content=["json"],
#     result_serializer="json",
#     result_expires=7200,
#     broker_connection_retry_on_startup=True,
# )

logger.info(f"✅ CELERY: App configured successfully with queue '{settings.celery.default_queue}'")


# Health check task for monitoring
@celery_app.task(bind=True, name="health_check")
def health_check(self):
    """Simple health check task for monitoring."""
    import time

    return {
        "status": "healthy",
        "worker_id": self.request.id,
        "timestamp": time.time(),
        "queue": settings.celery.default_queue,
        "concurrency": settings.celery.worker_concurrency,
    }


# NOTE: Dash apps will import celery_app when they're created in flask_dispatcher.py
# Background callbacks are registered automatically when apps are initialized
# No need to import apps here - that would create a circular dependency:
#   1. flask_dispatcher.py imports celery_app (to create background_callback_manager)
#   2. If celery_app.py imported flask_dispatcher, it would fail (flask_dispatcher not fully loaded)
#
# The multi-app architecture in flask_dispatcher.py handles callback registration:
#   - Line 379: Apps are created with background_callback_manager
#   - Background callbacks are registered when app modules wire up their callbacks
#   - Celery workers discover tasks through the apps, not through this module

logger.info("✅ CELERY: Celery app ready for background callbacks")
logger.info(
    "   - Background callbacks will be registered by flask_dispatcher.py when apps are created"
)
logger.info("   - Management, Viewer, and Editor apps each have their own callback registry")


# Auto-discovery of tasks on app start
if __name__ == "__main__":
    logger.info("🚀 CELERY: Starting worker directly...")
    celery_app.start()
