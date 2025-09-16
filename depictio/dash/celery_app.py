"""
Simple Celery application for Dash background callbacks.
"""

import time

from celery import Celery

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

# Simple Celery setup for Dash background callbacks
logger.info("🔧 CELERY: Setting up simple Celery app for Dash...")

# Use settings for Redis URL
broker_url = settings.celery.broker_url
backend_url = settings.celery.result_backend_url
logger.info(f"🔧 CELERY: Using broker: {broker_url}")

celery_app = Celery(__name__, broker=broker_url, backend=backend_url)

logger.info("✅ CELERY: Simple Celery app configured successfully")

logger.info("📦 CELERY: Celery app ready for background callbacks")


# Health check task for monitoring
@celery_app.task(bind=True, name="health_check")
def health_check(self):
    """Simple health check task for monitoring."""
    return {
        "status": "healthy",
        "worker_id": self.request.id,
        "timestamp": time.time(),
        "queue": "celery",
        "concurrency": 2,
    }


# Auto-discovery of tasks on app start
if __name__ == "__main__":
    logger.info("🚀 CELERY: Starting worker directly...")
    celery_app.start()
else:
    logger.info("📦 CELERY: App imported successfully")
