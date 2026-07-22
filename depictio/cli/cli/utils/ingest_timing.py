"""Per-phase ingestion timing — a machine-readable breakdown of where a data
collection's ingest wall-clock goes (parse / collect / write / upload) plus the
process peak RSS.

Motivation: the ``depictio run`` subprocess is a black box to the benchmark
harness — it only sees the total wall. This module lets the ingestion code stamp
per-phase durations that are flushed as a single line

    DEPICTIO_INGEST_TIMINGS={"dc_tag": ..., "phase_ms": {...}, "peak_rss_mb": ...}

on stdout, which ``benchmark/runner.py`` greps out of the captured subprocess
output. It is entirely opt-in and zero-overhead when no timer is active: the
:func:`timed` / :func:`record` helpers no-op unless a surrounding
:func:`ingest_run` has installed a timer for the current context.

The active timer is held in a :class:`contextvars.ContextVar`, so it is correct
for the current sequential ingestion and for future per-worker isolation as long
as each worker opens its own :func:`ingest_run` (context is not shared across
threads unless explicitly copied).
"""

from __future__ import annotations

import contextvars
import json
import platform
import sys
import time
from contextlib import contextmanager
from typing import Any

from depictio.cli.cli_logging import logger

_MARKER = "DEPICTIO_INGEST_TIMINGS="

_active: contextvars.ContextVar["IngestTimer | None"] = contextvars.ContextVar(
    "depictio_ingest_timer", default=None
)


class IngestTimer:
    """Accumulates per-phase seconds and free-form counters for one DC ingest."""

    def __init__(self, dc_tag: str, dc_type: str):
        self.dc_tag = dc_tag
        self.dc_type = dc_type
        self.phase_seconds: dict[str, float] = {}
        self.meta: dict[str, Any] = {}

    def add(self, phase: str, seconds: float) -> None:
        self.phase_seconds[phase] = self.phase_seconds.get(phase, 0.0) + seconds

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dc_tag": self.dc_tag,
            "dc_type": self.dc_type,
            "phase_ms": {k: round(v * 1000.0, 1) for k, v in self.phase_seconds.items()},
            "peak_rss_mb": _peak_rss_mb(),
        }
        payload.update(self.meta)
        return payload


def _peak_rss_mb() -> float | None:
    """Process peak resident set size in MB, or ``None`` if unavailable.

    ``resource`` is POSIX-only, hence the local import. ``ru_maxrss`` is bytes on
    macOS but kilobytes on Linux — normalise both.
    """
    try:
        import resource
    except ImportError:  # pragma: no cover - depictio CLI targets POSIX
        return None
    ru_maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024.0**2 if platform.system() == "Darwin" else 1024.0
    return round(ru_maxrss / divisor, 1)


@contextmanager
def timed(phase: str):
    """Time the wrapped block into ``phase`` on the active timer (else no-op)."""
    timer = _active.get()
    if timer is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        timer.add(phase, time.perf_counter() - start)


def record(key: str, value: Any) -> None:
    """Attach a counter (rows, files, delta bytes…) to the active timer, if any."""
    timer = _active.get()
    if timer is not None:
        timer.meta[key] = value


@contextmanager
def ingest_run(dc_tag: str, dc_type: str, *, emit: bool = True):
    """Install a timer for the current context; flush the marker line on exit.

    Nested calls are supported (the inner run swaps the active timer and restores
    the outer one on exit); each run emits its own marker line.
    """
    timer = IngestTimer(dc_tag, dc_type)
    token = _active.set(timer)
    try:
        yield timer
    finally:
        _active.reset(token)
        if emit:
            try:
                sys.stdout.write(_MARKER + json.dumps(timer.as_payload()) + "\n")
                sys.stdout.flush()
            except Exception as exc:  # never let telemetry break an ingest
                logger.debug(f"Failed to emit ingest timings for {dc_tag}: {exc}")


def parse_timing_markers(text: str) -> list[dict[str, Any]]:
    """Extract all ``DEPICTIO_INGEST_TIMINGS=`` payloads from captured stdout.

    Used by the benchmark runner to recover the per-phase breakdown from a
    ``depictio run`` subprocess. Malformed lines are skipped.
    """
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        idx = line.find(_MARKER)
        if idx == -1:
            continue
        try:
            out.append(json.loads(line[idx + len(_MARKER) :]))
        except json.JSONDecodeError:
            continue
    return out
