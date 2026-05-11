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


def _warm_multiqc_components(
    components: list[dict],
    project_id,
    *,
    dedupe: bool = False,
    disk_persist: bool = False,
) -> dict:
    """Warm Redis caches for every MultiQC component in ``components``.

    Shared body for the dashboard-scoped Celery task and the DC-scoped sync
    helper called from the upload endpoints. Each component dict must carry
    ``dc_id`` (or ``data_collection_id``), ``selected_module``,
    ``selected_plot`` and optionally ``selected_dataset``/``s3_locations``.

    ``dedupe=True`` collapses identical (dc_id, module, plot, dataset) tuples
    so several dashboards referencing the same DC don't redundantly rebuild
    the same figure — used by the DC-scoped path which fans across dashboards.

    ``disk_persist=True`` (Phase 2) additionally writes each rendered figure
    dict to ``multiqc_prerender_store`` so the next render survives a Redis
    flush. Disk writes are purely additive on top of Redis caching — failures
    don't stop the loop.
    """
    import hashlib

    from depictio.api.cache import get_cache
    from depictio.api.v1.configs.logging_init import logger

    cache = get_cache()

    # Lazy imports — these modules pull in MultiQC + Plotly which is heavy.
    from depictio.dash.modules.figure_component.multiqc_vis import (
        MULTIQC_CACHE_TTL_SECONDS,
        _generate_figure_cache_key,
        _get_local_path_for_s3,
        create_multiqc_plot,
    )
    from depictio.dash.modules.figure_component.utils import _get_theme_template
    from depictio.dash.modules.multiqc_component.callbacks.core import (
        _normalize_multiqc_paths,
    )
    from depictio.dash.modules.multiqc_component.general_stats import (
        build_general_stats_payload,
    )
    from depictio.dash.modules.multiqc_component.models import _fetch_s3_locations_from_dc

    seen: set[tuple] = set()
    warmed = 0
    skipped = 0
    failed = 0

    for comp in components:
        dc_id = comp.get("dc_id") or comp.get("data_collection_id")
        comp_project_id = comp.get("project_id") or project_id
        s3_locations = comp.get("s3_locations") or []
        if dc_id and comp_project_id:
            try:
                live_locations = _fetch_s3_locations_from_dc(str(dc_id), str(comp_project_id))
                if live_locations:
                    s3_locations = live_locations
            except Exception as e:
                logger.warning(f"prewarm: _fetch_s3_locations_from_dc failed for {dc_id}: {e}")
        if not s3_locations:
            failed += 1
            continue

        # Match the render endpoint's resolver — it falls back to legacy
        # multiqc_* keys when selected_* are absent. Without this fallback,
        # legacy components silently skip the prewarm (warmed=0 for them)
        # and pay full parse cost on first render.
        module = comp.get("selected_module") or comp.get("multiqc_module")
        plot = comp.get("selected_plot") or comp.get("multiqc_plot")
        dataset = comp.get("selected_dataset") or comp.get("multiqc_dataset")
        is_general_stats = (
            module == "general_stats"
            or plot == "general_stats"
            or bool(comp.get("is_general_stats"))
        )

        if dedupe:
            tuple_key = (
                str(dc_id) if dc_id else None,
                module,
                plot,
                dataset,
                "gs" if is_general_stats else "fig",
            )
            if tuple_key in seen:
                skipped += 1
                continue
            seen.add(tuple_key)

        if is_general_stats:
            try:
                normalized = _normalize_multiqc_paths(s3_locations)
                filter_sig = "all"
                all_paths_str = "|".join(sorted(s3_locations))
                cache_key_str = f"{all_paths_str}::{filter_sig}::general_stats_payload"
                cache_key = (
                    f"multiqc:gs_payload:dc={str(dc_id) if dc_id else 'none'}:"
                    f"{hashlib.sha256(cache_key_str.encode()).hexdigest()[:16]}"
                )
                if cache.get(cache_key) is not None:
                    skipped += 1
                    continue
                parquet_paths = [_get_local_path_for_s3(p) for p in normalized]
                payload = build_general_stats_payload(
                    parquet_path=parquet_paths,
                    show_hidden=True,
                    selected_samples=None,
                )
                cache.set(cache_key, payload, ttl=MULTIQC_CACHE_TTL_SECONDS)
                warmed += 1
            except Exception as e:
                logger.warning(f"prewarm: GS build failed for {comp.get('index')}: {e}")
                failed += 1
            continue

        if not module or not plot:
            continue

        # Build the figure for the light theme. ``create_multiqc_plot`` is
        # the slow path: parse + multiqc.get_plot() + Plotly figure
        # construction (~10-20s per figure on big modules). It writes the
        # light-theme dict to its bare cache key.
        try:
            fig = create_multiqc_plot(
                s3_locations=s3_locations,
                module=module,
                plot=plot,
                dataset_id=dataset,
                theme="light",
                dc_id=str(dc_id) if dc_id else None,
            )
            warmed += 1
        except Exception as e:
            logger.warning(
                f"prewarm: figure build failed for {comp.get('index')} "
                f"({module}/{plot}, light): {e}"
            )
            failed += 1
            continue

        if disk_persist and dc_id:
            try:
                from depictio.api.v1.services import multiqc_prerender_store

                light_key = _generate_figure_cache_key(
                    s3_locations, module, plot, dataset, "light", dc_id=str(dc_id)
                )
                multiqc_prerender_store.write_figure(str(dc_id), light_key, fig.to_dict())
            except Exception as e:
                logger.warning(
                    f"prewarm: light disk persist failed for {comp.get('index')} "
                    f"({module}/{plot}): {e}"
                )

        # For the dark theme, swap only the layout template and cache the
        # resulting dict directly. Avoids a second multiqc.get_plot() +
        # get_figure() round-trip (the dominant cost) — figures are
        # structurally identical between themes; only the template differs.
        try:
            fig.update_layout(template=_get_theme_template("dark"))
            dark_dict = fig.to_dict()
            dark_key = _generate_figure_cache_key(
                s3_locations,
                module,
                plot,
                dataset,
                "dark",
                dc_id=str(dc_id) if dc_id else None,
            )
            cache.set(dark_key, dark_dict, ttl=MULTIQC_CACHE_TTL_SECONDS)
            if disk_persist and dc_id:
                try:
                    from depictio.api.v1.services import multiqc_prerender_store

                    multiqc_prerender_store.write_figure(str(dc_id), dark_key, dark_dict)
                except Exception as e:
                    logger.warning(
                        f"prewarm: dark disk persist failed for {comp.get('index')} "
                        f"({module}/{plot}): {e}"
                    )
            warmed += 1
        except Exception as e:
            logger.warning(
                f"prewarm: dark re-template failed for {comp.get('index')} ({module}/{plot}): {e}"
            )
            failed += 1

    return {"warmed": warmed, "skipped": skipped, "failed": failed}


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
    from bson import ObjectId

    from depictio.api.cache import get_cache
    from depictio.api.v1.configs.logging_init import logger
    from depictio.api.v1.db import dashboards_collection

    cache = get_cache()
    # Render endpoints check this lock to decide whether to return 202.
    # Cleared on completion (success or failure) so a future cold-start
    # doesn't wait for the 10 min TTL to expire.
    #
    # ALSO used as task-dedup: ``set_nx`` only succeeds for the first task
    # that races to claim it. Subsequent parallel tasks (queued by
    # dashboard GET + render endpoint + startup prewarm racing) bail out
    # immediately. Without this, N tasks each redo the same parse/build
    # in separate worker processes, adding CPU contention and ~20s of
    # wallclock overhead.
    lock_key = f"multiqc:prewarm_lock:dashboard={dashboard_id}"

    if not cache.set_nx(lock_key, "1", ttl=600):
        logger.info(
            f"prewarm_multiqc_dashboard {dashboard_id}: another worker holds the "
            f"lock; skipping duplicate run"
        )
        return {"status": "skipped_locked", "dashboard_id": dashboard_id}

    try:
        try:
            dashboard = dashboards_collection.find_one(
                {"dashboard_id": ObjectId(str(dashboard_id))}
            )
        except Exception:
            dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
        if not dashboard:
            return {"status": "not_found", "dashboard_id": dashboard_id}

        project_id = dashboard.get("project_id")
        components = [
            m
            for m in (dashboard.get("stored_metadata") or [])
            if m.get("component_type") == "multiqc"
        ]
        if not components:
            return {"status": "no_multiqc", "dashboard_id": dashboard_id}

        counts = _warm_multiqc_components(components, project_id, dedupe=False)

        logger.info(
            f"prewarm_multiqc_dashboard {dashboard_id}: "
            f"warmed={counts['warmed']} skipped={counts['skipped']} failed={counts['failed']}"
        )
        return {"status": "ok", "dashboard_id": dashboard_id, **counts}
    finally:
        try:
            cache.delete(lock_key)
        except Exception as exc:
            logger.warning(f"prewarm_multiqc_dashboard: failed to clear lock {lock_key}: {exc}")


def _collect_dc_components(dc_id: str) -> tuple[list[dict], object | None, int, int]:
    """Find every multiqc component across all dashboards that targets ``dc_id``.

    Returns ``(components, project_id, dashboards_scanned, matched_dashboards)``
    where ``components`` is the flat list of stored_metadata entries (with
    ``project_id`` injected) ready to feed into ``_warm_multiqc_components``.
    Centralises the fan-out so both the legacy sync prewarm and the new
    Phase-2 ``build_multiqc_prerender`` task share one implementation.
    """
    from depictio.api.v1.db import dashboards_collection

    # Server-side filter to "any dashboard with a multiqc component"; the
    # per-component dc_id match runs in Python because stored_metadata.dc_id
    # is an ObjectId in some docs and a string in others (depending on which
    # write path created the dashboard). Comparing via str() handles both.
    cursor = dashboards_collection.find(
        {"stored_metadata.component_type": "multiqc"},
        {"stored_metadata": 1, "project_id": 1},
    )

    dc_id_str = str(dc_id)
    aggregated: list[dict] = []
    project_id = None
    dashboard_count = 0
    matched_dashboards = 0
    for dashboard in cursor:
        dashboard_count += 1
        matched = False
        for comp in dashboard.get("stored_metadata") or []:
            if comp.get("component_type") != "multiqc":
                continue
            comp_dc_id = comp.get("dc_id") or comp.get("data_collection_id")
            if comp_dc_id is None or str(comp_dc_id) != dc_id_str:
                continue
            matched = True
            project_id = project_id or dashboard.get("project_id")
            aggregated.append({**comp, "project_id": dashboard.get("project_id")})
        if matched:
            matched_dashboards += 1

    return aggregated, project_id, dashboard_count, matched_dashboards


def prewarm_multiqc_for_dc(dc_id: str) -> dict:
    """Synchronous DC-scoped prewarm — called from the manage-DC upload
    endpoint right after invalidation, so the user's next dashboard render
    hits a warm cache.

    Walks every dashboard whose stored_metadata references this DC, collapses
    identical (module, plot, dataset) tuples across them (multiple dashboards
    can bind the same figure), and warms the figure cache for each.
    """
    from depictio.api.v1.configs.logging_init import logger

    aggregated, project_id, dashboard_count, matched_dashboards = _collect_dc_components(dc_id)

    if not aggregated:
        logger.info(
            f"prewarm_multiqc_for_dc dc={dc_id}: no components match (scanned "
            f"{dashboard_count} dashboards with multiqc components)"
        )
        return {"status": "no_components", "dc_id": str(dc_id), "warmed": 0}

    counts = _warm_multiqc_components(aggregated, project_id, dedupe=True)
    logger.info(
        f"prewarm_multiqc_for_dc dc={dc_id}: dashboards={matched_dashboards} "
        f"components={len(aggregated)} warmed={counts['warmed']} "
        f"skipped={counts['skipped']} failed={counts['failed']}"
    )
    return {"status": "ok", "dc_id": str(dc_id), **counts}


@celery_app.task(bind=True, name="prewarm_multiqc_dc", soft_time_limit=600, time_limit=900)
def prewarm_multiqc_dc_task(self, dc_id: str) -> dict:
    """Async wrapper around ``prewarm_multiqc_for_dc`` — used by the render
    endpoint's 202 fallback when a request arrives with a fully-cold cache.
    """
    return prewarm_multiqc_for_dc(dc_id)


def _compute_s3_locations_hash(dc_id: str) -> str:
    """Hash the sorted set of s3 locations for every MultiQC report in this DC.

    Used as the staleness signal on the ``multiqc_prerender_collection`` doc:
    an upload/append/replace mutates the report set, the hash flips, the next
    build task notices and rebuilds. Returns empty string when no reports
    exist for the DC (a freshly-invalidated state).
    """
    import hashlib

    from bson import ObjectId

    from depictio.api.v1.db import multiqc_collection

    # The reports collection stores ``data_collection_id`` as a string in some
    # write paths and ObjectId in others (matches the dashboards quirk handled
    # in _collect_dc_components). Query both shapes.
    queries: list[dict] = [{"data_collection_id": str(dc_id)}]
    if ObjectId.is_valid(str(dc_id)):
        queries.append({"data_collection_id": ObjectId(str(dc_id))})

    locations: set[str] = set()
    for q in queries:
        for doc in multiqc_collection.find(q, {"s3_location": 1}):
            loc = doc.get("s3_location")
            if loc:
                locations.add(str(loc))

    if not locations:
        return ""
    joined = "|".join(sorted(locations))
    return hashlib.sha256(joined.encode()).hexdigest()


@celery_app.task(bind=True, name="build_multiqc_prerender", soft_time_limit=900, time_limit=1200)
def build_multiqc_prerender(self, dc_id: str) -> dict:
    """Phase 2: write every dashboard-bound MultiQC figure for ``dc_id`` to disk.

    Triggered from the upload (append/replace) invalidator and from the render
    endpoint's cold-fallback path. ``set_nx`` lock dedups concurrent enqueues
    so racing render requests don't fan out into N workers all rebuilding the
    same figures.

    The doc + s3_locations_hash short-circuits a no-op when nothing has
    changed: if the persisted hash matches the current MultiQC reports and
    status is already ``ready``, we return without doing any work — disk is
    already current.
    """
    from datetime import datetime

    from depictio.api.cache import get_cache
    from depictio.api.v1.configs.logging_init import logger
    from depictio.api.v1.db import multiqc_prerender_collection

    cache = get_cache()
    lock_key = f"multiqc:prerender_build_lock:dc={dc_id}"

    if not cache.set_nx(lock_key, "1", ttl=600):
        logger.info(
            f"build_multiqc_prerender {dc_id}: another worker holds the "
            f"lock; skipping duplicate run"
        )
        return {"status": "skipped_locked", "dc_id": str(dc_id)}

    try:
        current_hash = _compute_s3_locations_hash(dc_id)

        existing = multiqc_prerender_collection.find_one({"dc_id": str(dc_id)})
        if (
            existing
            and existing.get("status") == "ready"
            and existing.get("s3_locations_hash") == current_hash
            and current_hash
        ):
            logger.info(
                f"build_multiqc_prerender {dc_id}: doc already ready for hash "
                f"{current_hash[:8]}…; no-op"
            )
            return {
                "status": "already_ready",
                "dc_id": str(dc_id),
                "figure_count": existing.get("figure_count", 0),
            }

        now = datetime.now()
        multiqc_prerender_collection.update_one(
            {"dc_id": str(dc_id)},
            {
                "$set": {
                    "dc_id": str(dc_id),
                    "status": "building",
                    "s3_locations_hash": current_hash,
                    "last_error": None,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now, "figure_count": 0},
            },
            upsert=True,
        )

        aggregated, project_id, dashboard_count, matched_dashboards = _collect_dc_components(dc_id)
        if not aggregated:
            multiqc_prerender_collection.update_one(
                {"dc_id": str(dc_id)},
                {
                    "$set": {
                        "status": "ready",
                        "figure_count": 0,
                        "updated_at": datetime.now(),
                    }
                },
            )
            logger.info(
                f"build_multiqc_prerender {dc_id}: no dashboard components "
                f"reference this DC (scanned {dashboard_count} dashboards)"
            )
            return {"status": "no_components", "dc_id": str(dc_id), "warmed": 0}

        counts = _warm_multiqc_components(aggregated, project_id, dedupe=True, disk_persist=True)

        # ``warmed`` counts every successful figure write (light + dark
        # separately). Disk file count is roughly warmed/2 — but using
        # ``warmed`` here as the visible build metric is fine; the disk
        # ledger doesn't need to be byte-exact.
        multiqc_prerender_collection.update_one(
            {"dc_id": str(dc_id)},
            {
                "$set": {
                    "status": "ready",
                    "figure_count": counts.get("warmed", 0),
                    "updated_at": datetime.now(),
                }
            },
        )
        logger.info(
            f"build_multiqc_prerender {dc_id}: dashboards={matched_dashboards} "
            f"components={len(aggregated)} warmed={counts['warmed']} "
            f"skipped={counts['skipped']} failed={counts['failed']}"
        )
        return {"status": "ok", "dc_id": str(dc_id), **counts}
    except Exception as exc:
        from depictio.api.v1.configs.logging_init import logger as _logger

        _logger.error(f"build_multiqc_prerender {dc_id}: build failed: {exc}", exc_info=True)
        try:
            multiqc_prerender_collection.update_one(
                {"dc_id": str(dc_id)},
                {
                    "$set": {
                        "status": "failed",
                        "last_error": str(exc)[:1000],
                        "updated_at": datetime.now(),
                    }
                },
            )
        except Exception as doc_exc:
            _logger.warning(
                f"build_multiqc_prerender {dc_id}: failed to mark doc as failed: {doc_exc}"
            )
        return {"status": "failed", "dc_id": str(dc_id), "error": str(exc)}
    finally:
        try:
            cache.delete(lock_key)
        except Exception as exc:
            logger.warning(f"build_multiqc_prerender: failed to clear lock {lock_key}: {exc}")


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
