"""
Dashboard YAML synchronization service.

Handles initial sync of dashboards from MongoDB to YAML files on startup.
"""

import os
from pathlib import Path

from depictio.api.v1.configs.logging_init import logger

WORKER_ID = os.getpid()


def _log(level: str, message: str) -> None:
    """Log a message with worker ID prefix."""
    getattr(logger, level)(f"Worker {WORKER_ID}: {message}")


def initialize_yaml_directory() -> None:
    """Create the YAML dashboards directories if they don't exist."""
    from depictio.api.v1.configs.config import settings

    for name, path in [
        ("Local dashboards", settings.dashboard_yaml.yaml_dir_path),
        ("Templates", settings.dashboard_yaml.templates_path),
    ]:
        directory = Path(path)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            _log("info", f"{name} directory initialized at {directory}")
        except OSError as e:
            _log("error", f"Failed to create {name.lower()} directory {directory}: {e}")


def run_initial_yaml_sync() -> None:
    """
    Export all existing dashboards from MongoDB to YAML files.

    This is run once on startup by the worker that performs initialization.
    """
    from depictio.api.v1.db import dashboards_collection, projects_collection
    from depictio.models.models.dashboards import DashboardData
    from depictio.models.yaml_serialization import export_dashboard_to_yaml_dir

    _log("info", "Running initial MongoDB to YAML sync...")

    try:
        dashboards = list(dashboards_collection.find({}))
        exported_count = 0
        failed_count = 0

        for dash_data in dashboards:
            try:
                proj_id = dash_data.get("project_id")
                project = projects_collection.find_one({"_id": proj_id})
                project_name = project.get("name", "unknown") if project else "unknown"

                dashboard = DashboardData.from_mongo(dash_data)
                export_dashboard_to_yaml_dir(
                    dashboard_data=dashboard.model_dump(),
                    project_name=project_name,
                )
                exported_count += 1

            except Exception as e:
                dashboard_id = dash_data.get("dashboard_id")
                _log("error", f"Failed to export dashboard {dashboard_id}: {e}")
                failed_count += 1

        _log(
            "info",
            f"Initial sync complete - exported {exported_count} dashboards, {failed_count} failed",
        )

    except Exception as e:
        _log("error", f"Initial YAML sync failed: {e}")


def start_yaml_sync_services() -> None:
    """
    Start YAML-related services: initial sync and file watcher.

    This should be called only by the worker that performs initialization.
    """
    from depictio.api.v1.services.yaml_watcher import start_yaml_watcher

    _log("info", "Starting YAML sync services...")

    run_initial_yaml_sync()
    _log("info", "Initial YAML sync complete")

    if start_yaml_watcher():
        _log("info", "YAML watcher started successfully")
    else:
        _log("warning", "YAML watcher not started")


def stop_yaml_sync_services() -> None:
    """
    Stop YAML-related services.

    This should be called during shutdown by the worker that started the services.
    """
    from depictio.api.v1.services.yaml_watcher import stop_yaml_watcher

    if stop_yaml_watcher():
        _log("info", "YAML watcher stopped successfully")
    else:
        _log("info", "YAML watcher was not running")
