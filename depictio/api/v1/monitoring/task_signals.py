"""Celery signal handlers that persist task lifecycle into the monitoring ledger.

Connected at import time (imported from ``depictio/api/celery_app.py`` so the
worker registers them on startup). Each task transition upserts the
``task_events`` row keyed by ``task_id``; a logging handler captures per-task log
lines and flushes them into the row on completion.

Every handler is defensive: a monitoring failure must never disrupt the task
itself, so all bodies are wrapped and swallow exceptions.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_revoked,
)

logger = logging.getLogger(__name__)

# Per-task captured log lines, keyed by task_id. Populated by
# ``_TaskLogCaptureHandler`` while a task runs, flushed on postrun. A prefork
# worker child runs one task at a time in its main thread, so current_task is
# reliable; the lock guards against any auxiliary threads a task may spawn.
_log_buffers: dict[str, list[str]] = {}
_buffers_lock = threading.Lock()
_MAX_LINES_PER_TASK = 500


def _safe(fn):
    """Decorator: never let a signal handler raise into Celery internals."""

    def wrapper(*args: Any, **kwargs: Any):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(f"monitoring task signal {fn.__name__} failed: {exc}")

    wrapper.__name__ = getattr(fn, "__name__", "wrapper")
    return wrapper


def _current_task_id() -> str | None:
    """Return the id of the task running in this process, if any."""
    try:
        from celery import current_task

        if current_task is not None and getattr(current_task, "request", None) is not None:
            return current_task.request.id
    except Exception:
        return None
    return None


class _TaskLogCaptureHandler(logging.Handler):
    """Buffers log records emitted while a Celery task is running, per task_id."""

    def emit(self, record: logging.LogRecord) -> None:
        task_id = _current_task_id()
        if not task_id:
            return
        try:
            line = self.format(record)
        except Exception:
            return
        with _buffers_lock:
            buf = _log_buffers.setdefault(task_id, [])
            if len(buf) < _MAX_LINES_PER_TASK:
                buf.append(line)


def _drain_logs(task_id: str) -> list[str]:
    with _buffers_lock:
        return _log_buffers.pop(task_id, [])


def _extract_refs(kwargs: dict | None, args: tuple | None) -> dict[str, Any]:
    """Best-effort pull of dashboard_id / dc_id from task kwargs."""
    refs: dict[str, Any] = {}
    if isinstance(kwargs, dict):
        for key in ("dashboard_id", "dc_id"):
            val = kwargs.get(key)
            if val is not None:
                refs[key] = str(val)
    return refs


@task_prerun.connect
@_safe
def _on_prerun(task_id=None, task=None, args=None, kwargs=None, **_extra):
    from depictio.api.v1.monitoring import store

    request = getattr(task, "request", None)
    fields: dict[str, Any] = {
        "task_name": getattr(task, "name", "") or "",
        "status": "started",
        "args_repr": (repr({"args": args, "kwargs": kwargs}))[:500],
        "started_at": datetime.now(),
        "worker": getattr(request, "hostname", None),
        "queue": getattr(request, "delivery_info", {}).get("routing_key")
        if getattr(request, "delivery_info", None)
        else None,
    }
    fields.update(_extract_refs(kwargs, args))
    store.upsert_task_event(task_id, **fields)

    from depictio.api.v1.monitoring.publish import publish_task_event
    from depictio.models.models.monitoring import derive_task_kind

    task_name = fields["task_name"]
    publish_task_event(task_id, task_name, derive_task_kind(task_name), "started")


@task_postrun.connect
@_safe
def _on_postrun(task_id=None, task=None, retval=None, state=None, **_extra):
    from depictio.api.v1.monitoring import store

    lines = _drain_logs(task_id)
    if lines:
        store.append_task_logs(task_id, lines)

    # task_failure already recorded the error path; don't clobber it back to a
    # generic status. Only stamp the terminal status + duration here.
    status = "success" if state == "SUCCESS" else (state or "success").lower()
    existing = store.get_task_event(task_id)
    duration_ms = None
    started_iso = existing.get("started_at") if existing else None
    if started_iso:
        try:
            started = datetime.fromisoformat(started_iso)
            duration_ms = (datetime.now() - started).total_seconds() * 1000.0
        except (ValueError, TypeError):
            duration_ms = None

    fields: dict[str, Any] = {
        "finished_at": datetime.now(),
        "duration_ms": duration_ms,
    }
    # Preserve a failure status if task_failure beat us here.
    if existing and existing.get("status") == "failure":
        fields["status"] = "failure"
    else:
        fields["status"] = "success" if status not in ("failure", "retry") else status
    try:
        fields["result_summary"] = repr(retval)[:500] if retval is not None else None
    except Exception:
        fields["result_summary"] = None
    store.upsert_task_event(task_id, **fields)

    from depictio.api.v1.monitoring.publish import publish_task_event

    task_name = (existing or {}).get("task_name", "") or getattr(task, "name", "") or ""
    kind = (existing or {}).get("kind", "other")
    publish_task_event(task_id, task_name, kind, fields["status"])


@task_failure.connect
@_safe
def _on_failure(task_id=None, exception=None, traceback=None, einfo=None, **_extra):
    from depictio.api.v1.monitoring import store

    tb = None
    if einfo is not None:
        tb = str(getattr(einfo, "traceback", "")) or None
    store.upsert_task_event(
        task_id,
        status="failure",
        error=(repr(exception))[:500] if exception is not None else None,
        traceback=tb,
        finished_at=datetime.now(),
    )


@task_retry.connect
@_safe
def _on_retry(request=None, reason=None, **_extra):
    from depictio.api.v1.monitoring import store

    task_id = getattr(request, "id", None)
    if not task_id:
        return
    store.upsert_task_event(
        task_id,
        status="retry",
        error=(repr(reason))[:500] if reason is not None else None,
    )


@task_revoked.connect
@_safe
def _on_revoked(request=None, **_extra):
    from depictio.api.v1.monitoring import store

    task_id = getattr(request, "id", None)
    if not task_id:
        return
    store.upsert_task_event(task_id, status="revoked", finished_at=datetime.now())


def install_task_log_capture() -> None:
    """Attach the per-task log capture handler to the root depictio logger.

    Idempotent. Safe to call in both API and worker processes — in the API
    process there is never a current task, so the handler is a fast no-op.
    """
    root = logging.getLogger("depictio")
    if any(isinstance(h, _TaskLogCaptureHandler) for h in root.handlers):
        return
    handler = _TaskLogCaptureHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


# Connect handlers + log capture as a side effect of import.
install_task_log_capture()
