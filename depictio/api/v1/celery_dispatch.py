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


def should_offload_render(
    *,
    force: bool,
    code_mode: bool = False,
    size_bytes: int | None = None,
    threshold_bytes: int | None = None,
) -> bool:
    """Decide whether a render runs on Celery (heavy) or inline (cheap).

    Blanket offload is a poor default for interactive renders: the broker +
    result-backend round-trip and the poll-loop latency floor in
    ``offload_or_run`` add tens-to-hundreds of ms to renders that build inline
    in a few ms, and funnel every cheap figure through the same small worker
    pool as slow code/MultiQC builds. So offload only when the work is actually
    heavy:

    - ``force``: explicit per-deployment override (``offload_rendering``) for
      operators who want every render off the API process regardless of size.
    - ``code_mode``: arbitrary user code of unknown cost — isolate it in a
      worker process instead of running it on the API event loop.
    - ``size_bytes >= threshold_bytes``: large source frames, where
      cross-process parallelism and not pinning an API worker outweigh the
      round-trip.

    Everything else runs inline. The thresholds are coarse proxies pending the
    #4 render benchmark, which should calibrate the crossover empirically.
    """
    if force:
        return True
    if code_mode:
        return True
    if (
        threshold_bytes is not None
        and threshold_bytes > 0
        and size_bytes is not None
        and size_bytes >= threshold_bytes
    ):
        return True
    return False


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
