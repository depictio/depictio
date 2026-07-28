"""Ship ingestion steps to the server while the run is still going.

Before this, steps were accumulated in a list and sent once at ``finish``, so
the monitoring UI showed nothing until a run was over — which is precisely when
progress reporting stops being useful. The point of reporting a step is to
answer "what is it doing right now", and that requires reporting it as it
*starts*, not only when it ends.

Two properties this has to guarantee, in order:

1. **It can never slow down or break an ingestion.** Sends happen on a daemon
   thread fed by an unbounded queue; the ingestion thread only ever enqueues.
   A hung monitoring endpoint costs nothing but a thread parked in a socket
   read. Every failure path swallows its exception.
2. **It gives up permanently when the server says no.** A 404 or 422 means this
   server cannot accept step updates at all, so retrying for the rest of the
   run is pure waste — the reporter latches off and drains silently.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Any, Callable, Optional

from depictio.cli.cli_logging import logger

#: Sentinel that tells the worker thread to finish and exit.
_STOP = object()

# CLI options whose *value* is a secret and must never reach the monitoring ledger.
_SENSITIVE_OPTS = {"--provisioning-key"}


def redacted_command_line() -> str | None:
    """Best-effort reconstruction of the CLI invocation with secrets redacted.

    Renders as ``depictio-cli <args…>`` (argv[0] normalized to the entrypoint
    name) and masks the value of any sensitive option. Never raises.
    """
    try:
        import sys

        out = ["depictio-cli"]
        redact_next = False
        for arg in sys.argv[1:]:
            if redact_next:
                out.append("***")
                redact_next = False
                continue
            key = arg.split("=", 1)[0]
            if key in _SENSITIVE_OPTS:
                out.append(f"{key}=***" if "=" in arg else arg)
                redact_next = "=" not in arg
                continue
            out.append(arg)
        return " ".join(out)
    except Exception:
        return None


def ingestion_data_collections(project_config) -> list[dict]:
    """Per-DC summary (tag / type / format) + the local scan paths the CLI
    resolved, walked from the validated project config. Best-effort; never raises."""
    out: list[dict] = []
    try:
        for wf in getattr(project_config, "workflows", None) or []:
            dl = getattr(wf, "data_location", None)
            locations = [str(x) for x in (getattr(dl, "locations", None) or [])] if dl else []
            for dc in getattr(wf, "data_collections", None) or []:
                cfg = getattr(dc, "config", None)
                scan = getattr(cfg, "scan", None) if cfg else None
                mode = getattr(scan, "mode", None) if scan else None
                params = getattr(scan, "scan_parameters", None) if scan else None
                if mode == "single":
                    pattern = getattr(params, "filename", None)
                elif mode == "recursive":
                    rc = getattr(params, "regex_config", None)
                    pattern = getattr(rc, "pattern", None) if rc else None
                else:
                    pattern = None
                dcsp = getattr(cfg, "dc_specific_properties", None) if cfg else None
                out.append(
                    {
                        "tag": getattr(dc, "data_collection_tag", None) or "",
                        "type": getattr(cfg, "type", None) if cfg else None,
                        "format": getattr(dcsp, "format", None) if dcsp else None,
                        "scan_mode": mode,
                        "scan_pattern": pattern,
                        "locations": locations,
                        "file_count": None,
                    }
                )
    except Exception:
        return out
    return out


class StepReporter:
    """Records run steps locally and mirrors them to the server in the background.

    The local list stays authoritative: it is what gets sent with ``finish``,
    so a run whose live updates were all dropped still reports a complete step
    history at the end. Live reporting is strictly an enhancement on top.
    """

    def __init__(
        self,
        send: Callable[[str, dict, Optional[str]], bool],
        run_id: Optional[str],
        *,
        enabled: bool = True,
    ) -> None:
        self._send = send
        self._run_id = run_id
        self._enabled = bool(enabled and run_id)
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        #: Ordered step records, keyed by name so a step reported at start and
        #: again at finish updates in place rather than appearing twice. The
        #: server upserts by name too, so both sides agree.
        self._steps: dict[str, dict] = {}
        self._started_at: dict[str, datetime] = {}

        if self._enabled:
            self._thread = threading.Thread(
                target=self._worker, name="depictio-step-reporter", daemon=True
            )
            self._thread.start()

    # ── recording ───────────────────────────────────────────────────────────

    def start(self, name: str, detail: str | None = None, **extra: Any) -> None:
        """Mark a step as running. Call this *before* doing the work."""
        self._started_at[name] = datetime.now()
        self._record(name, "running", detail, started_at=self._started_at[name], **extra)

    def finish(self, name: str, status: str, detail: str | None = None, **extra: Any) -> None:
        """Mark a step terminal, stamping its duration if it was started."""
        now = datetime.now()
        started = self._started_at.get(name)
        if started is not None and "duration_ms" not in extra:
            extra["duration_ms"] = (now - started).total_seconds() * 1000.0
        self._record(name, status, detail, started_at=started, finished_at=now, **extra)

    def record(self, name: str, status: str, detail: str | None = None, **extra: Any) -> None:
        """Record a step in one shot, for phases with no meaningful duration."""
        if status == "running":
            self.start(name, detail, **extra)
        else:
            self.finish(name, status, detail, **extra)

    def _record(
        self,
        name: str,
        status: str,
        detail: str | None,
        **extra: Any,
    ) -> None:
        step: dict[str, Any] = {"name": name, "status": status, "detail": detail}
        for key, value in extra.items():
            if value is not None:
                step[key] = value.isoformat() if isinstance(value, datetime) else value

        with self._lock:
            existing = self._steps.get(name)
            if existing:
                existing.update(step)
                step = existing
            else:
                step["index"] = len(self._steps)
                self._steps[name] = step
            snapshot = dict(step)

        if self._enabled:
            # `current_step` is the running one; a terminal status clears it so
            # the UI does not keep a spinner on a finished step.
            current = name if status == "running" else None
            self._queue.put((snapshot, current, status != "running"))

    # ── output ──────────────────────────────────────────────────────────────

    @property
    def steps(self) -> list[dict]:
        """Every step recorded so far, in first-seen order — sent with ``finish``."""
        with self._lock:
            return list(self._steps.values())

    def replay(self, steps: list[dict]) -> None:
        """Adopt steps recorded before this reporter existed and push them.

        A run does real work — reaching the server, checking S3, validating the
        config — before it can open a monitoring record, because opening one
        requires a validated config. Those phases would otherwise be missing
        from the live view and appear only in the final ``finish`` payload.
        """
        for step in steps:
            with self._lock:
                self._steps.setdefault(step["name"], dict(step))
                snapshot = dict(self._steps[step["name"]])
            if self._enabled:
                self._queue.put((snapshot, None, True))

    def close(self, timeout: float = 2.0) -> None:
        """Stop the worker, giving queued updates a bounded chance to flush.

        Bounded on purpose: the full step list goes out with ``finish`` anyway,
        so waiting longer than a couple of seconds would delay the user's
        command to re-send information the next call already carries.
        """
        if not self._enabled or self._thread is None:
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)

    # ── worker ──────────────────────────────────────────────────────────────

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            step, current, _terminal = item
            try:
                if not self._send(self._run_id or "", step, current):
                    # Server cannot take step updates. Stop sending, and drain
                    # whatever is queued so close() does not block on it.
                    self._enabled = False
                    logger.debug("Live step reporting disabled for this run")
                    self._drain()
                    return
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug(f"Step reporting failed (non-fatal): {exc}")

    def _drain(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if item is _STOP:
                return
