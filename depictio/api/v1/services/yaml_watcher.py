"""
YAML Directory Watcher Service.

Provides automatic synchronization from YAML files to MongoDB when files change.
Uses watchdog for cross-platform file system monitoring.
"""

import asyncio
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from depictio.api.v1.configs.logging_init import logger

# Track watcher state
_watcher_threads: dict[str, threading.Thread] = {}
_watcher_running: dict[str, bool] = {}
_watcher_stop_events: dict[str, threading.Event] = {}


class YAMLFileHandler:
    """Handler for YAML file system events."""

    def __init__(
        self,
        on_change_callback: Callable[[str, str], None],
        debounce_seconds: float = 2.0,
    ):
        """
        Initialize the file handler.

        Args:
            on_change_callback: Function to call when a file changes (filepath, event_type)
            debounce_seconds: Time to wait before processing changes (to batch rapid edits)
        """
        self.on_change_callback = on_change_callback
        self.debounce_seconds = debounce_seconds
        self._pending_changes: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_file_changed(self, filepath: str, event_type: str) -> None:
        """
        Handle a file change event with debouncing.

        Args:
            filepath: Path to the changed file
            event_type: Type of event (created, modified, deleted)
        """
        # Only process YAML files
        if not filepath.endswith((".yaml", ".yml")):
            return

        with self._lock:
            self._pending_changes[filepath] = time.time()

    def process_pending_changes(self) -> list[tuple[str, str]]:
        """
        Process any pending changes that have been debounced.

        Returns:
            List of (filepath, event_type) tuples that were processed
        """
        processed = []
        current_time = time.time()

        with self._lock:
            to_remove = []
            for filepath, change_time in self._pending_changes.items():
                if current_time - change_time >= self.debounce_seconds:
                    to_remove.append(filepath)
                    try:
                        self.on_change_callback(filepath, "modified")
                        processed.append((filepath, "modified"))
                    except Exception as e:
                        logger.error(f"Error processing YAML change for {filepath}: {e}")

            for filepath in to_remove:
                del self._pending_changes[filepath]

        return processed


def _simple_watcher_loop(
    watch_dir: Path,
    handler: YAMLFileHandler,
    stop_event: threading.Event,
    poll_interval: float = 1.0,
) -> None:
    """
    Simple polling-based file watcher loop.

    This is a fallback when watchdog isn't available.

    Args:
        watch_dir: Directory to watch
        handler: File handler for changes
        stop_event: Event to signal stop
        poll_interval: Seconds between polls
    """
    # Track file modification times
    file_mtimes: dict[str, float] = {}

    # Initial scan
    for yaml_file in watch_dir.glob("**/*.yaml"):
        file_mtimes[str(yaml_file)] = yaml_file.stat().st_mtime
    for yaml_file in watch_dir.glob("**/*.yml"):
        file_mtimes[str(yaml_file)] = yaml_file.stat().st_mtime

    logger.info(f"YAML watcher started (polling mode) for {watch_dir}")
    logger.info(f"Watching {len(file_mtimes)} YAML files")

    while not stop_event.is_set():
        try:
            # Check for changes
            current_files: dict[str, float] = {}

            for yaml_file in watch_dir.glob("**/*.yaml"):
                current_files[str(yaml_file)] = yaml_file.stat().st_mtime
            for yaml_file in watch_dir.glob("**/*.yml"):
                current_files[str(yaml_file)] = yaml_file.stat().st_mtime

            # Detect changes
            for filepath, mtime in current_files.items():
                if filepath not in file_mtimes:
                    # New file
                    handler.on_file_changed(filepath, "created")
                    logger.debug(f"YAML file created: {filepath}")
                elif mtime > file_mtimes[filepath]:
                    # Modified file
                    handler.on_file_changed(filepath, "modified")
                    logger.debug(f"YAML file modified: {filepath}")

            # Detect deletions
            for filepath in list(file_mtimes.keys()):
                if filepath not in current_files:
                    handler.on_file_changed(filepath, "deleted")
                    logger.debug(f"YAML file deleted: {filepath}")

            # Update tracked files
            file_mtimes = current_files

            # Process pending changes
            handler.process_pending_changes()

        except Exception as e:
            logger.error(f"Error in YAML watcher loop: {e}")

        # Wait for next poll
        stop_event.wait(poll_interval)

    logger.info("YAML watcher stopped")


def _watchdog_watcher_loop(
    watch_dir: Path,
    handler: YAMLFileHandler,
    stop_event: threading.Event,
) -> None:
    """
    Watchdog-based file watcher loop (more efficient).

    Args:
        watch_dir: Directory to watch
        handler: File handler for changes
        stop_event: Event to signal stop
    """
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class WatchdogHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if not event.is_directory:
                    handler.on_file_changed(event.src_path, "modified")

            def on_created(self, event):
                if not event.is_directory:
                    handler.on_file_changed(event.src_path, "created")

            def on_deleted(self, event):
                if not event.is_directory:
                    handler.on_file_changed(event.src_path, "deleted")

        observer = Observer()
        observer.schedule(WatchdogHandler(), str(watch_dir), recursive=True)
        observer.start()

        logger.info(f"YAML watcher started (watchdog mode) for {watch_dir}")

        while not stop_event.is_set():
            handler.process_pending_changes()
            stop_event.wait(1.0)

        observer.stop()
        observer.join()

        logger.info("YAML watcher stopped")

    except ImportError:
        logger.warning("watchdog not available, falling back to polling mode")
        _simple_watcher_loop(watch_dir, handler, stop_event)


def sync_yaml_to_mongodb(filepath: str, event_type: str) -> dict[str, Any]:
    """
    Sync a YAML file change to MongoDB.

    Args:
        filepath: Path to the changed YAML file
        event_type: Type of change (created, modified, deleted)

    Returns:
        Dict with sync result information
    """
    from bson import ObjectId

    from depictio.api.v1.db import dashboards_collection
    from depictio.models.models.dashboards import DashboardData
    from depictio.models.yaml_serialization import import_dashboard_from_file

    result: dict[str, Any] = {
        "filepath": filepath,
        "event_type": event_type,
        "success": False,
        "action": None,
        "dashboard_id": None,
        "error": None,
    }

    try:
        if event_type == "deleted":
            # For deleted files, we don't auto-delete from MongoDB
            # This is a safety measure - YAML deletion shouldn't remove DB data
            result["action"] = "skipped"
            result["success"] = True
            logger.info(f"YAML file deleted, skipping MongoDB deletion: {filepath}")
            return result

        # Read and parse the YAML file
        dashboard_dict = import_dashboard_from_file(filepath)
        dashboard_id = dashboard_dict.get("dashboard_id")

        if not dashboard_id:
            result["error"] = "No dashboard_id in YAML file"
            logger.warning(f"Skipping YAML without dashboard_id: {filepath}")
            return result

        # Check if dashboard exists in MongoDB
        existing = dashboards_collection.find_one({"dashboard_id": ObjectId(dashboard_id)})

        if existing:
            # Update existing dashboard
            # Preserve critical fields from existing record
            dashboard_dict["project_id"] = existing["project_id"]
            dashboard_dict["permissions"] = existing.get("permissions", {})
            dashboard_dict["is_public"] = existing.get("is_public", False)
            dashboard_dict["version"] = existing.get("version", 0) + 1
            dashboard_dict["last_saved_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            dashboard = DashboardData.from_mongo(dashboard_dict)

            dashboards_collection.find_one_and_update(
                {"dashboard_id": ObjectId(dashboard_id)},
                {"$set": dashboard.mongo()},
            )

            result["success"] = True
            result["action"] = "updated"
            result["dashboard_id"] = str(dashboard_id)
            logger.info(f"Auto-synced YAML to MongoDB (updated): {filepath}")
        else:
            # New dashboard - skip auto-creation for safety
            # User should use import endpoint for new dashboards
            result["action"] = "skipped_new"
            result["success"] = True
            result["dashboard_id"] = str(dashboard_id)
            logger.info(f"Skipping new dashboard (use import endpoint): {filepath}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Failed to sync YAML to MongoDB: {filepath} - {e}")

    return result


def start_yaml_watcher() -> bool:
    """
    Start the YAML directory watchers in background threads.

    Starts watchers for:
    - Local dashboards directory (if watch_local_dir=True)
    - Templates directory (if watch_templates_dir=True)

    Returns:
        True if at least one watcher was started, False if all disabled or already running
    """
    global _watcher_threads, _watcher_running, _watcher_stop_events

    from depictio.api.v1.configs.config import settings

    # Check if enabled
    if not settings.dashboard_yaml.enabled:
        logger.info("YAML watcher not started: dashboard_yaml is disabled")
        return False

    started_any = False

    # Determine which directories to watch
    watch_configs = []
    if settings.dashboard_yaml.watch_local_dir:
        watch_configs.append(("local", Path(settings.dashboard_yaml.yaml_dir_path)))
    if settings.dashboard_yaml.watch_templates_dir:
        watch_configs.append(("templates", Path(settings.dashboard_yaml.templates_path)))

    if not watch_configs:
        logger.info("YAML watcher not started: no directories configured to watch")
        return False

    # Start watcher for each configured directory
    for watch_name, watch_dir in watch_configs:
        # Check if already running
        if _watcher_running.get(watch_name, False):
            logger.info(f"YAML watcher already running for {watch_name}")
            continue

        # Ensure directory exists
        watch_dir.mkdir(parents=True, exist_ok=True)

        # Create handler with sync callback
        handler = YAMLFileHandler(
            on_change_callback=sync_yaml_to_mongodb,
            debounce_seconds=settings.dashboard_yaml.watcher_debounce_seconds,
        )

        # Create stop event
        _watcher_stop_events[watch_name] = threading.Event()

        # Start watcher thread
        def run_watcher(name=watch_name, directory=watch_dir, stop_event=_watcher_stop_events[watch_name]):
            _watcher_running[name] = True
            try:
                _watchdog_watcher_loop(directory, handler, stop_event)
            finally:
                _watcher_running[name] = False

        _watcher_threads[watch_name] = threading.Thread(target=run_watcher, daemon=True)
        _watcher_threads[watch_name].start()

        logger.info(f"YAML watcher thread started for {watch_name}: {watch_dir}")
        started_any = True

    return started_any


def stop_yaml_watcher() -> bool:
    """
    Stop all YAML directory watchers.

    Returns:
        True if at least one watcher was stopped, False if none were running
    """
    global _watcher_threads, _watcher_running, _watcher_stop_events

    if not _watcher_running:
        logger.info("YAML watcher not running")
        return False

    stopped_any = False

    # Stop all running watchers
    for watch_name in list(_watcher_running.keys()):
        if not _watcher_running.get(watch_name, False):
            continue

        # Signal stop
        stop_event = _watcher_stop_events.get(watch_name)
        if stop_event:
            stop_event.set()

        # Wait for thread to finish
        thread = _watcher_threads.get(watch_name)
        if thread and thread.is_alive():
            thread.join(timeout=5.0)

        # Clean up
        _watcher_threads.pop(watch_name, None)
        _watcher_stop_events.pop(watch_name, None)
        _watcher_running.pop(watch_name, None)

        logger.info(f"YAML watcher stopped for {watch_name}")
        stopped_any = True

    return stopped_any


def get_watcher_status() -> dict[str, Any]:
    """
    Get the current status of all YAML watchers.

    Returns:
        Dict with watcher status information
    """
    from depictio.api.v1.configs.config import settings

    return {
        "enabled": settings.dashboard_yaml.enabled,
        "watchers": {
            "local": {
                "running": _watcher_running.get("local", False),
                "directory": settings.dashboard_yaml.yaml_dir_path,
                "watch_enabled": settings.dashboard_yaml.watch_local_dir,
            },
            "templates": {
                "running": _watcher_running.get("templates", False),
                "directory": settings.dashboard_yaml.templates_path,
                "watch_enabled": settings.dashboard_yaml.watch_templates_dir,
            },
        },
        "auto_export_on_save": settings.dashboard_yaml.auto_export_on_save,
    }


# Async wrappers for FastAPI endpoints
async def async_start_watcher() -> bool:
    """Async wrapper for start_yaml_watcher."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, start_yaml_watcher)


async def async_stop_watcher() -> bool:
    """Async wrapper for stop_yaml_watcher."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, stop_yaml_watcher)
