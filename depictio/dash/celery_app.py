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


@celery_app.task(
    bind=True, name="generate_dashboard_screenshot", soft_time_limit=600, time_limit=900
)
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


@celery_app.task(
    bind=True, name="generate_dashboard_screenshot_dual", soft_time_limit=600, time_limit=900
)
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


@celery_app.task(bind=True, name="prewarm_multiqc_dashboard", soft_time_limit=300, time_limit=600)
def prewarm_multiqc_dashboard(self, dashboard_id: str) -> dict:
    """Pre-render every MultiQC figure + general-stats payload in a dashboard so
    subsequent user requests hit the warm Redis cache.

    Triggered fire-and-forget by the GET /dashboards/get/{id} endpoint.
    Idempotent: each rendered figure is checked against Redis and skipped if
    already cached. Both light and dark themes are warmed for figures because
    the React viewer follows the user's system preference. General-stats
    payloads are theme-agnostic so they're warmed once.
    """
    import hashlib
    import json

    from bson import ObjectId

    from depictio.api.cache import get_cache
    from depictio.api.v1.configs.logging_init import logger
    from depictio.api.v1.db import dashboards_collection

    try:
        dashboard = dashboards_collection.find_one({"dashboard_id": ObjectId(str(dashboard_id))})
    except Exception:
        dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard:
        return {"status": "not_found", "dashboard_id": dashboard_id}

    project_id = dashboard.get("project_id")
    components = [
        m for m in (dashboard.get("stored_metadata") or []) if m.get("component_type") == "multiqc"
    ]
    if not components:
        return {"status": "no_multiqc", "dashboard_id": dashboard_id}

    cache = get_cache()

    # Lazy imports — these modules pull in MultiQC + Plotly which is heavy.
    from depictio.dash.modules.figure_component.multiqc_vis import (
        _get_local_path_for_s3,
        create_multiqc_plot,
        generate_figure_cache_key,
    )
    from depictio.dash.modules.multiqc_component.callbacks.core import (
        _normalize_multiqc_paths,
    )
    from depictio.dash.modules.multiqc_component.general_stats import (
        build_general_stats_payload,
    )
    from depictio.dash.modules.multiqc_component.models import _fetch_s3_locations_from_dc

    warmed = 0
    skipped = 0
    failed = 0

    for comp in components:
        s3_locations = comp.get("s3_locations") or []
        dc_id = comp.get("dc_id") or comp.get("data_collection_id")
        if not s3_locations and dc_id and project_id:
            try:
                s3_locations = _fetch_s3_locations_from_dc(str(dc_id), str(project_id))
            except Exception as e:
                logger.warning(f"prewarm: _fetch_s3_locations_from_dc failed for {dc_id}: {e}")
        if not s3_locations:
            failed += 1
            continue

        module = comp.get("selected_module")
        plot = comp.get("selected_plot")
        dataset = comp.get("selected_dataset")
        is_general_stats = module == "general_stats" or plot == "general_stats"

        if is_general_stats:
            try:
                normalized = _normalize_multiqc_paths(s3_locations)
                raw_path = normalized[0] if normalized else s3_locations[0]
                filter_sig = "all"
                cache_key_str = f"{raw_path}::{filter_sig}::general_stats_payload"
                cache_key = (
                    f"multiqc:gs_payload:{hashlib.sha256(cache_key_str.encode()).hexdigest()[:16]}"
                )
                if cache.get(cache_key) is not None:
                    skipped += 1
                    continue
                parquet_path = _get_local_path_for_s3(raw_path)
                payload = build_general_stats_payload(
                    parquet_path=parquet_path,
                    show_hidden=True,
                    selected_samples=None,
                )
                cache.set(cache_key, payload, ttl=7200)
                warmed += 1
            except Exception as e:
                logger.warning(f"prewarm: GS build failed for {comp.get('index')}: {e}")
                failed += 1
            continue

        if not module or not plot:
            continue

        # Regular figure — warm both light and dark, store JSON-safe form
        # under the filter-aware key (filter_sig=None for the baseline).
        for theme in ("light", "dark"):
            try:
                key = generate_figure_cache_key(
                    s3_locations, module, plot, dataset, theme, filter_sig=None
                )
                if cache.get(key) is not None:
                    skipped += 1
                    continue
                fig = create_multiqc_plot(
                    s3_locations=s3_locations,
                    module=module,
                    plot=plot,
                    dataset_id=dataset,
                    theme=theme,
                )
                fig_dict = json.loads(fig.to_json()) if hasattr(fig, "to_json") else fig
                if isinstance(fig_dict, dict) and "layout" in fig_dict:
                    fig_dict["layout"].setdefault("uirevision", "persistent")
                cache.set(key, fig_dict, ttl=7200)
                warmed += 1
            except Exception as e:
                logger.warning(
                    f"prewarm: figure build failed for {comp.get('index')} "
                    f"({module}/{plot}, {theme}): {e}"
                )
                failed += 1

    logger.info(
        f"prewarm_multiqc_dashboard {dashboard_id}: "
        f"warmed={warmed} skipped={skipped} failed={failed}"
    )
    return {
        "status": "ok",
        "dashboard_id": dashboard_id,
        "warmed": warmed,
        "skipped": skipped,
        "failed": failed,
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

# Background callbacks are registered by flask_dispatcher.py when apps are created
# Management, Viewer, and Editor apps each have their own callback registry


# Auto-discovery of tasks on app start
if __name__ == "__main__":
    celery_app.start()
