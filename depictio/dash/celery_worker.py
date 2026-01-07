"""
Celery worker entry point for Dash background callbacks.

This module is imported by Celery workers to register background callback tasks
without starting the full Flask/Gunicorn web server.

Architecture:
- Main web process: flask_dispatcher.py → creates apps → registers callbacks
- Worker process: celery_worker.py → imports apps → discovers registered tasks

This solves the "unregistered task" error by ensuring workers can discover
background callbacks from Viewer and Editor apps (Management has no background tasks).

Multi-App Background Callback Distribution:
- Management app: No background tasks (auth, dashboards/projects management)
- Viewer app: Lite version with background=True for heavy data loading (MB-GB dataframes)
- Editor app: Full version with all background callbacks (editing + component builder)

Usage:
    celery -A depictio.dash.celery_worker:celery_app worker --loglevel=info
"""

from depictio.api.v1.configs.logging_init import logger

# Import the Celery app instance
from depictio.dash.celery_app import celery_app

logger.info("=" * 80)
logger.info("🔧 CELERY WORKER: Initializing task discovery...")
logger.info("=" * 80)

# Import flask_dispatcher to trigger app creation and callback registration
# This imports celery_app (circular but safe because celery_app is already loaded above)
# and creates the three Dash apps with background callbacks registered
logger.info("🔧 CELERY WORKER: Importing flask_dispatcher for task discovery...")

try:
    from depictio.dash.flask_dispatcher import app_editor, app_management, app_viewer

    logger.info("✅ CELERY WORKER: Flask dispatcher imported successfully")
    logger.info("   - Management app (no background tasks): %s", app_management)
    logger.info("   - Viewer app (lite, with background tasks): %s", app_viewer)
    logger.info("   - Editor app (full, with background tasks): %s", app_editor)

    # The apps are created with background_callback_manager, which automatically
    # registers background callbacks as Celery tasks when callbacks are wired up
    # in flask_dispatcher.py (lines 403-424)

    # Count registered tasks (for debugging)
    registered_tasks = [task for task in celery_app.tasks.keys() if not task.startswith("celery.")]
    background_callback_tasks = [
        task for task in registered_tasks if "background_callback_" in task
    ]

    logger.info("=" * 80)
    logger.info("✅ CELERY WORKER: Task registration complete")
    logger.info("=" * 80)
    logger.info(f"   Total tasks registered: {len(registered_tasks)}")
    logger.info(f"   Background callback tasks: {len(background_callback_tasks)}")
    logger.info("   Background tasks from: Viewer app (data loading) + Editor app (full)")
    logger.info("=" * 80)

    if background_callback_tasks:
        logger.info("   Sample background callback tasks:")
        for task in background_callback_tasks[:3]:
            logger.info(f"      - {task[:80]}...")
    else:
        logger.warning("⚠️  No background callback tasks found! Check callback registration.")

except Exception as e:
    logger.error("=" * 80)
    logger.error(f"❌ CELERY WORKER: Failed to import flask_dispatcher: {e}")
    logger.error("=" * 80)
    raise

# Export celery_app for worker command
__all__ = ["celery_app"]
