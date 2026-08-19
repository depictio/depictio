"""Logging handler that persists recent app logs into the capped app_logs collection.

Attached in both the API process and the Celery worker (tagged by ``source``).
Writes records at/above ``settings.monitoring.app_log_min_level``. Defensive:
write failures are swallowed, and records originating from the database driver
are skipped to avoid feedback loops.
"""

from __future__ import annotations

import logging
import threading

from depictio.api.v1.configs.config import settings
from depictio.models.models.monitoring import AppLogRecord

# Loggers whose records we never persist, to avoid recursion (the handler itself
# talks to MongoDB through pymongo) and noise.
_SKIP_LOGGER_PREFIXES = ("pymongo", "depictio.api.v1.monitoring.store")

_local = threading.local()


class AppLogMongoHandler(logging.Handler):
    """Persist log records into the capped ``app_logs`` collection."""

    def __init__(self, source: str) -> None:
        super().__init__()
        self.source = source

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_SKIP_LOGGER_PREFIXES):
            return
        # Re-entrancy guard: if persisting a record itself logs, don't recurse.
        if getattr(_local, "in_emit", False):
            return
        _local.in_emit = True
        try:
            from depictio.api.v1.monitoring import store

            store.insert_app_log(
                AppLogRecord(
                    level=record.levelname,
                    logger=record.name,
                    source=self.source,  # type: ignore[arg-type]
                    message=self.format(record),
                    pathname=record.pathname,
                    lineno=record.lineno,
                )
            )
        except Exception:
            # Never let log persistence raise into the application.
            pass
        finally:
            _local.in_emit = False


def install_app_log_handler(source: str) -> None:
    """Attach the Mongo log handler to the root depictio logger. Idempotent."""
    if not settings.monitoring.enabled:
        return
    root = logging.getLogger("depictio")
    if any(isinstance(h, AppLogMongoHandler) for h in root.handlers):
        return
    handler = AppLogMongoHandler(source=source)
    handler.setLevel(getattr(logging, settings.monitoring.app_log_min_level, logging.WARNING))
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)


def get_app_log_capture_level() -> str:
    """Return the Mongo log handler's current capture floor in this process."""
    root = logging.getLogger("depictio")
    for h in root.handlers:
        if isinstance(h, AppLogMongoHandler):
            return logging.getLevelName(h.level)
    return settings.monitoring.app_log_min_level


def set_app_log_capture_level(level: str) -> str:
    """Dynamically change what the Mongo log handler persists, in this process.

    Sets the handler level to ``level`` and *lowers* the ``depictio`` logger's own
    level if needed so records at the new floor actually reach the handler (a
    logger never raises its level here, to avoid muting other handlers like the
    console). Returns the normalized level name. Raises ValueError on a bad level.
    """
    name = (level or "").upper()
    numeric = logging.getLevelName(name)
    if not isinstance(numeric, int):
        raise ValueError(f"Invalid log level: {level!r}")
    root = logging.getLogger("depictio")
    if root.level == logging.NOTSET or numeric < root.level:
        root.setLevel(numeric)
    for h in root.handlers:
        if isinstance(h, AppLogMongoHandler):
            h.setLevel(numeric)
    return name
