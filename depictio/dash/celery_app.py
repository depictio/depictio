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


# Import Dash app to register background callbacks
# This must be AFTER celery_app is created to avoid circular import
# The import happens at module level so Celery workers can discover background callback tasks
logger.info("🔧 CELERY: Importing Dash app to register background callbacks...")
try:
    from depictio.dash.app import app  # noqa: F401

    logger.info("✅ CELERY: Dash app imported successfully, background callbacks registered")
except Exception as e:
    logger.error(f"❌ CELERY: Failed to import Dash app: {e}")
    logger.warning("⚠️  CELERY: Background callbacks will not be available")


# Auto-discovery of tasks on app start
if __name__ == "__main__":
    logger.info("🚀 CELERY: Starting worker directly...")
    celery_app.start()
