"""Dispatch helper that runs Celery tasks via a non-blocking poll loop.

Used by FastAPI preview / render endpoints to offload heavy Polars+Plotly work
to the Celery worker without pinning an API worker thread on `result.get()`.

The frontend contract is unchanged — the endpoint still returns a single
HTTP response with the task's payload. From the React side this is identical
to running the work inline.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from celery.exceptions import TimeoutError as CeleryTimeoutError
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger


async def offload_or_run(
    task: Any,
    args: tuple | list,
    *,
    offload: bool,
    timeout: float | None = None,
    label: str = "",
) -> Any:
    """Run `task` either inline or via Celery, awaiting completion async-safely.

    Inline path simply calls `task.run(*args)` in the current event-loop thread.
    Offload path dispatches via `apply_async` and polls `AsyncResult.ready()`
    with `asyncio.sleep` so the FastAPI event loop stays responsive while the
    worker does the heavy work.
    """
    if not offload:
        return task.run(*args)

    timeout = timeout if timeout is not None else settings.celery.offload_timeout_seconds
    async_result = task.apply_async(args=list(args))
    deadline = time.monotonic() + timeout
    poll = 0.05
    started = time.monotonic()
    try:
        while not async_result.ready():
            if time.monotonic() > deadline:
                try:
                    async_result.revoke(terminate=True)
                except Exception:
                    pass
                logger.warning(
                    f"celery_dispatch: task {task.name} ({label or 'unlabeled'}) "
                    f"timed out after {timeout:.1f}s"
                )
                raise HTTPException(
                    status_code=504,
                    detail=f"Celery task '{task.name}' timed out after {timeout:.1f}s",
                )
            await asyncio.sleep(poll)
            poll = min(poll * 1.5, 0.5)

        if async_result.failed():
            tb = async_result.traceback or str(async_result.result)
            logger.error(f"celery_dispatch: task {task.name} ({label}) failed: {tb}")
            raise HTTPException(
                status_code=500,
                detail=f"Celery task '{task.name}' failed: {async_result.result}",
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            f"celery_dispatch: task {task.name} ({label or 'unlabeled'}) "
            f"completed in {elapsed_ms}ms"
        )
        return async_result.get(timeout=1.0)
    except CeleryTimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail=f"Celery task '{task.name}' result fetch timed out: {e}",
        )
