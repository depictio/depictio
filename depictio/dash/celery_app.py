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

# Configure Celery with settings from config
# celery_app.conf.update(
#     # Task routing - Dash background callbacks will register their own routes
#     task_routes={},
#     # Serialization
#     task_serializer="json",
#     accept_content=["json"],
#     result_serializer="json",
#     timezone="UTC",
#     enable_utc=True,
#     # Result backend settings
#     result_expires=settings.celery.result_expires,
#     # Worker settings
#     worker_prefetch_multiplier=settings.celery.worker_prefetch_multiplier,
#     task_acks_late=True,
#     worker_max_tasks_per_child=settings.celery.worker_max_tasks_per_child,
#     # Task timeouts
#     task_soft_time_limit=settings.celery.task_soft_time_limit,
#     task_time_limit=settings.celery.task_time_limit,
#     # Monitoring
#     worker_send_task_events=settings.celery.worker_send_task_events,
#     task_send_sent_event=settings.celery.task_send_sent_event,
#     # Queue settings
#     task_default_queue=settings.celery.default_queue,
#     # Error handling
#     task_reject_on_worker_lost=True,
#     task_ignore_result=False,
#     # Performance optimizations
#     worker_disable_rate_limits=True,  # Better performance for background callbacks
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


# Auto-discovery of tasks on app start
if __name__ == "__main__":
    logger.info("🚀 CELERY: Starting worker directly...")
    celery_app.start()
else:
    logger.info("📦 CELERY: App imported successfully")
