"""
Celery application for background task processing.
Integrated with FastAPI backend for dashboard component generation.
"""

from celery import Celery

from depictio.api.v1.configs.config import settings

# Create Celery app with configuration from settings

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


@celery_app.task(bind=True, name="generate_dashboard_screenshot")
def generate_dashboard_screenshot(self, dashboard_id: str) -> dict:
    """
    Generate dashboard screenshot in background (legacy single-theme).

    This task is fire-and-forget - the user doesn't wait for it.
    Screenshot failures are logged but don't affect the save operation.

    NOTE: This is the legacy single-theme screenshot task. For new code,
    use generate_dashboard_screenshot_dual for dual-theme support.

    Args:
        dashboard_id: The dashboard ID to screenshot.

    Returns:
        dict with status and details.
    """
    import httpx

    from depictio.api.v1.configs.config import API_BASE_URL
    from depictio.api.v1.configs.logging_init import logger

    try:
        screenshot_timeout = settings.performance.screenshot_api_timeout
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/utils/screenshot-dash-fixed/{dashboard_id}",
            timeout=screenshot_timeout,
        )

        if response.status_code == 200:
            logger.info(f"Background screenshot completed for dashboard {dashboard_id}")
            return {"status": "success", "dashboard_id": dashboard_id}
        else:
            logger.warning(
                f"Background screenshot failed for {dashboard_id}: {response.status_code}"
            )
            return {"status": "failed", "dashboard_id": dashboard_id, "code": response.status_code}

    except Exception as e:
        logger.error(f"Background screenshot error for {dashboard_id}: {e}")
        return {"status": "error", "dashboard_id": dashboard_id, "error": str(e)}


@celery_app.task(bind=True, name="generate_dashboard_screenshot_dual")
def generate_dashboard_screenshot_dual(self, dashboard_id: str, user_id: str) -> dict:
    """
    Generate dual-theme dashboard screenshots asynchronously with deduplication and permission validation.

    Captures both light and dark mode screenshots in a single browser call
    for efficiency (~40% time savings vs. two separate calls).

    Includes:
    - Deduplication logic to prevent duplicate screenshot requests for the same dashboard
    - Permission validation to ensure only dashboard owners can generate screenshots

    This task is fire-and-forget - the user doesn't wait for it.
    Screenshot failures are logged but don't affect the save operation.

    **Architecture**: Uses direct Playwright execution (no HTTP indirection)
    for better performance (~200-500ms faster) and centralized logging.

    Args:
        dashboard_id: The dashboard ID to screenshot.
        user_id: The user ID requesting the screenshot (for permission validation).

    Returns:
        dict with status and screenshot paths, or forbidden status if user is not owner.
    """
    import asyncio

    from beanie import init_beanie
    from celery.exceptions import Ignore
    from motor.motor_asyncio import AsyncIOMotorClient

    from depictio.api.v1.configs.logging_init import logger
    from depictio.api.v1.services.screenshot_service import generate_dual_theme_screenshots
    from depictio.models.models.users import TokenBeanie, UserBeanie

    # Check for duplicate active tasks to avoid redundant screenshot generation
    try:
        inspect = celery_app.control.inspect()
        active_tasks = inspect.active()

        if active_tasks:
            for _worker, tasks in active_tasks.items():
                for task in tasks:
                    if (
                        task["name"] == "generate_dashboard_screenshot_dual"
                        and task["args"] == f"('{dashboard_id}', '{user_id}')"
                        and task["id"] != self.request.id
                    ):
                        raise Ignore()
    except Ignore:
        raise
    except Exception as e:
        logger.warning(f"Failed to check for duplicate tasks: {e}, proceeding with screenshot")

    # Validate user owns dashboard before generating screenshot
    from depictio.api.v1.services.screenshot_service import check_dashboard_owner_permission_sync

    if not check_dashboard_owner_permission_sync(dashboard_id, user_id):
        logger.warning(
            f"Screenshot denied: user {user_id} is not owner of dashboard {dashboard_id}"
        )
        return {
            "status": "forbidden",
            "dashboard_id": dashboard_id,
            "message": "User is not dashboard owner",
        }

    async def async_screenshot_task():
        """Async wrapper: initializes MongoDB and runs Playwright screenshot generation."""
        from depictio.api.v1.configs.config import MONGODB_URL

        client = AsyncIOMotorClient(MONGODB_URL)
        try:
            await init_beanie(
                database=client[settings.mongodb.db_name],
                document_models=[TokenBeanie, UserBeanie],
            )
            return await generate_dual_theme_screenshots(dashboard_id, user_id=user_id)
        finally:
            client.close()

    try:
        result = asyncio.run(async_screenshot_task())

        if result["status"] == "success":
            logger.info(f"✅ Screenshots generated for dashboard {dashboard_id}")
            return {
                "status": "success",
                "dashboard_id": dashboard_id,
                "light_screenshot": result.get("light_screenshot"),
                "dark_screenshot": result.get("dark_screenshot"),
            }

        logger.warning(f"Dual-screenshot failed for {dashboard_id}: {result.get('error')}")
        return {
            "status": "failed",
            "dashboard_id": dashboard_id,
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error(f"Dual-screenshot error for {dashboard_id}: {e}")
        return {"status": "error", "dashboard_id": dashboard_id, "error": str(e)}


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

# Background callbacks are registered by flask_dispatcher.py when apps are created
# Management, Viewer, and Editor apps each have their own callback registry


# Auto-discovery of tasks on app start
if __name__ == "__main__":
    celery_app.start()
