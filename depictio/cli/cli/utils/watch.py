"""Filesystem watcher that re-runs ingestion when a data root changes.

Two trigger sources, deliberately, because neither is sufficient alone:

**Native events** (``watchdog`` → inotify on Linux, FSEvents on macOS) are the
low-latency path, and the only one that reacts in seconds.

**Polling** re-walks the tree and compares :func:`run_signature`. It is the only
path that works at all on NFS, Lustre, GPFS and fuse mounts, where inotify does
not see writes made from another host — which is exactly depictio's common
deployment: the pipeline writes from a compute node, the watcher runs on a login
node. With native events alone that watcher would sit silent forever and never
report an error.

Polling is therefore not merely a fallback for when watchdog is unavailable; on
local disks it also runs *alongside* native events as a slow safety net, because
the inotify queue can overflow (``IN_Q_OVERFLOW``) and silently drop events. One
missed event with no backstop means data that is never ingested. A five-minute
reconciliation walk is a cheap price for turning "usually works" into "works".

Two more things that look like details and are not:

* **File stability.** A ``created`` event fires at ``open()``, not at
  ``close()``. Ingesting immediately captures a half-written CSV, which then
  gets corrected on the next cycle — after the bad rows have already reached
  dashboards. Every path must hold a stable ``(size, mtime)`` across
  ``settle_seconds`` before it counts.
* **Re-entrancy.** Events arriving during an ingestion are coalesced into a
  single follow-up pass, never queued into N passes; and a lock file keeps two
  watchers (or a watcher and a manual ``depictio run``) off the same project.
"""

from __future__ import annotations

import fcntl
import os
import signal
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from depictio.cli.cli.utils.scan_walk import iter_run_files, run_signature
from depictio.cli.cli_logging import logger

WatchMode = Literal["incremental", "full"]
WatchBackend = Literal["auto", "native", "polling", "both"]

#: Filesystems where inotify/FSEvents cannot be trusted: they either do not
#: deliver events for changes made by another host, or do not deliver them at
#: all. Detected from the mount table and forced onto the polling path.
NETWORK_FSTYPES = frozenset(
    {
        "nfs",
        "nfs4",
        "cifs",
        "smbfs",
        "smb3",
        "lustre",
        "gpfs",
        "beegfs",
        "glusterfs",
        "ceph",
        "afs",
        "9p",
    }
)


@dataclass(slots=True)
class WatchConfig:
    """Tuning for one watch session."""

    mode: WatchMode = "incremental"
    backend: WatchBackend = "auto"
    #: Quiet period with no new events before a cycle is triggered. Pipelines
    #: write in bursts of hundreds of files; triggering per event would start an
    #: ingestion per file.
    debounce_seconds: float = 30.0
    #: A path must hold the same (size, mtime) across this window before it is
    #: considered complete.
    settle_seconds: float = 5.0
    #: Ceiling on debouncing, so a continuously-written stream still gets
    #: ingested periodically instead of being deferred forever.
    max_delay_seconds: float = 300.0
    #: Reconciliation walk period. Also the sole trigger in polling mode.
    poll_interval_seconds: float = 300.0
    #: Run a full re-ingest every N incremental cycles. Off by default.
    full_every: int | None = None
    once: bool = False
    max_runs: int | None = None
    #: Failure backoff bounds. A broken server must not be hammered.
    backoff_initial_seconds: float = 30.0
    backoff_max_seconds: float = 900.0
    #: How often to re-report the current status while nothing is happening.
    #: The server expires an agent after DEPICTIO_MONITORING_AGENT_TTL_SECONDS
    #: (300s) and the UI reddens it after 180s, both measured from the last
    #: report — so a watcher that only reported on state changes was declared
    #: wedged, then evicted, while sitting healthily in its poll loop. Several
    #: beats inside both windows, so one dropped beat changes nothing.
    heartbeat_interval_seconds: float = 60.0
    #: How often to ask the server whether someone pressed "Run now" in the UI.
    #: Short, because this one is a person waiting for a button to do something;
    #: the request is cheap (a single conditional update that writes nothing
    #: when no run is pending) and it is only issued while the watcher is
    #: otherwise idle.
    command_poll_interval_seconds: float = 5.0


@dataclass(slots=True)
class _PathObservation:
    size: int
    mtime_ns: int
    first_seen: float


@dataclass(slots=True)
class ChangeAccumulator:
    """Collects change notices and decides when a cycle should run.

    Separated from the observer plumbing so the decision logic — the part with
    the edge cases — is testable without a real filesystem watcher.
    """

    config: WatchConfig
    now: Callable[[], float] = time.monotonic
    _pending: dict[str, _PathObservation] = field(default_factory=dict)
    _stable: set[str] = field(default_factory=set)
    _first_change_at: float | None = None
    _last_change_at: float | None = None

    def note(self, path: str, *, size: int | None = None, mtime_ns: int | None = None) -> None:
        """Record that ``path`` may have changed.

        ``size``/``mtime_ns`` are optional: native events do not carry them, so
        they are read here when absent. A path that has vanished is dropped
        rather than treated as stable.
        """
        timestamp = self.now()
        if size is None or mtime_ns is None:
            try:
                stat_result = os.stat(path)
            except OSError:
                # Deleted between the event and this stat. A deletion is a real
                # change, so it still counts toward triggering a cycle — it just
                # has no stability to establish.
                self._pending.pop(path, None)
                self._stable.discard(path)
                self._mark_changed(timestamp)
                return
            size = stat_result.st_size
            mtime_ns = stat_result.st_mtime_ns

        previous = self._pending.get(path)
        if previous is None or previous.size != size or previous.mtime_ns != mtime_ns:
            # Still moving: restart this path's settle window.
            self._pending[path] = _PathObservation(size, mtime_ns, timestamp)
            self._stable.discard(path)

        self._mark_changed(timestamp)

    def note_change(self) -> None:
        """Record that *something* changed, without a specific path.

        Used by the polling trigger, which compares a whole-tree signature and
        so knows a change happened without attributing it to one file. Settling
        there falls to the debounce window rather than per-path stability, which
        is why the debounce must be at least one poll interval long — a tree
        still being written keeps failing the signature comparison and pushes
        the debounce clock forward on each poll.
        """
        self._mark_changed(self.now())

    def _mark_changed(self, timestamp: float) -> None:
        if self._first_change_at is None:
            self._first_change_at = timestamp
        self._last_change_at = timestamp

    def _promote_stable(self) -> None:
        """Move paths that have held still long enough into the stable set."""
        timestamp = self.now()
        for path, observation in list(self._pending.items()):
            if timestamp - observation.first_seen < self.config.settle_seconds:
                continue
            try:
                stat_result = os.stat(path)
            except OSError:
                self._pending.pop(path, None)
                continue
            if (
                stat_result.st_size == observation.size
                and stat_result.st_mtime_ns == observation.mtime_ns
            ):
                self._stable.add(path)
                self._pending.pop(path, None)
            else:
                # Grew while we waited — restart its window rather than
                # ingesting a partial file.
                observation.size = stat_result.st_size
                observation.mtime_ns = stat_result.st_mtime_ns
                observation.first_seen = timestamp

    @property
    def has_changes(self) -> bool:
        return bool(self._pending or self._stable or self._first_change_at is not None)

    def ready(self) -> bool:
        """Whether a cycle should run now."""
        if self._first_change_at is None:
            return False

        self._promote_stable()
        timestamp = self.now()

        # Past the ceiling: run even if writes are still arriving, otherwise a
        # continuous stream defers ingestion indefinitely.
        if timestamp - self._first_change_at >= self.config.max_delay_seconds:
            return True

        if self._pending:
            # Something is still in flight; do not ingest a partial file.
            return False

        assert self._last_change_at is not None
        return timestamp - self._last_change_at >= self.config.debounce_seconds

    def drain(self) -> set[str]:
        """Take the settled paths and reset, keeping anything still unstable."""
        drained = set(self._stable)
        self._stable.clear()
        if self._pending:
            # Unstable paths survive into the next window and keep the clock
            # running, so they are not silently forgotten.
            self._first_change_at = self.now()
            self._last_change_at = self._first_change_at
        else:
            self._first_change_at = None
            self._last_change_at = None
        return drained


def detect_filesystem(path: str) -> str | None:
    """Best-effort filesystem type for ``path``, or None when undetectable."""
    target = os.path.abspath(path)
    try:
        with open("/proc/mounts", encoding="utf-8") as handle:
            entries = [line.split() for line in handle]
    except OSError:
        # macOS and friends: no /proc. FSEvents is reliable on local volumes and
        # the caller falls back to "both", which keeps the polling safety net.
        return None

    best_mount, best_type = "", None
    for parts in entries:
        if len(parts) < 3:
            continue
        mount_point, fstype = parts[1], parts[2]
        if (target == mount_point or target.startswith(mount_point.rstrip("/") + "/")) and len(
            mount_point
        ) > len(best_mount):
            best_mount, best_type = mount_point, fstype
    return best_type


def resolve_backend(configured: WatchBackend, paths: Iterable[str]) -> WatchBackend:
    """Turn ``auto`` into a concrete backend for these paths.

    Any path on a network filesystem forces polling for the whole session: a
    mixed setup where half the roots emit events and half do not is worse than a
    uniformly polled one, because the silence looks identical to "no changes".
    """
    if configured != "auto":
        return configured

    for path in paths:
        fstype = detect_filesystem(path)
        if fstype and (fstype in NETWORK_FSTYPES or fstype.startswith("fuse")):
            logger.info(
                f"{path} is on {fstype}; native file events are unreliable there "
                "(writes from another host are not delivered). Using polling."
            )
            return "polling"

    # Local disk: native events for latency, polling as a backstop against a
    # dropped/overflowed event queue.
    return "both"


@contextmanager
def project_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive, non-blocking lock for one project's ingestion.

    Guards against two watchers on the same project, and against a manual
    ``depictio run`` racing a watcher cycle. Both would interleave writes to the
    same runs and the same Delta table.

    Raises ``RuntimeError`` when the lock is already held, rather than blocking:
    a watcher that queues behind another watcher would drift arbitrarily far
    behind the filesystem.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "w", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                f"Another depictio process already holds {lock_path}. "
                "Only one watcher or ingestion may run per project at a time."
            ) from exc
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def start_native_observer(roots: list[str], accumulator: ChangeAccumulator):
    """Start a watchdog observer feeding ``accumulator``. Returns None if unavailable.

    Import is deferred and failures are downgraded to a warning: watchdog is an
    optional capability, and a missing or unusable one (inotify watch limit
    exhausted, most often) must degrade to polling rather than abort the watch.
    """
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        logger.warning(
            "watchdog is not installed; falling back to polling only. "
            "Install depictio-cli with its watch extra for low-latency events."
        )
        return None

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event) -> None:
            if event.is_directory:
                return
            accumulator.note(event.src_path)
            # A move reports the destination separately; record it too so the
            # arrival of a renamed-into-place file is not missed.
            destination = getattr(event, "dest_path", None)
            if destination:
                accumulator.note(destination)

    observer = Observer()
    handler = _Handler()
    try:
        for root in roots:
            observer.schedule(handler, root, recursive=True)
        observer.start()
    except OSError as exc:
        # Typically ENOSPC: fs.inotify.max_user_watches exhausted by a deep tree.
        logger.warning(
            f"Could not watch natively ({exc}); falling back to polling only. "
            "On Linux this is usually fs.inotify.max_user_watches being too low."
        )
        return None

    logger.info(f"Watching {len(roots)} location(s) for native filesystem events.")
    return observer


class ProjectWatcher:
    """Runs ingestion cycles in response to filesystem activity.

    The ingestion itself is injected as ``run_cycle`` so this class owns only
    scheduling, coalescing and failure handling.
    """

    def __init__(
        self,
        *,
        roots: list[str],
        config: WatchConfig,
        run_cycle: Callable[[WatchMode, set[str]], bool],
        lock_path: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.roots = roots
        self.config = config
        self.run_cycle = run_cycle
        self.lock_path = lock_path
        self.sleep = sleep
        self.now = now
        self.accumulator = ChangeAccumulator(config=config, now=now)
        self.backend = resolve_backend(config.backend, roots)

        self._stop = False
        self._cycles = 0
        self._consecutive_failures = 0
        self._signatures: dict[str, str] = {}
        #: Optional telemetry sink. Called with (status, extra) on each state
        #: change; a watcher nobody can see is a watcher nobody can debug.
        self.on_status: Callable[[str, dict], None] | None = None
        #: Optional command source. Returns True when a run has been requested
        #: from outside — today, the "Run now" button on the agent card. The
        #: watcher pulls rather than being pushed to, because it typically runs
        #: on a machine the server cannot open a connection to.
        self.on_poll_command: Callable[[], bool] | None = None
        #: Why the cycle now in flight was started, and under which trigger kind
        #: it should be recorded. Read by the ingestion callback, which owns the
        #: monitoring record but not the reason it exists.
        self.trigger_kind: str = "watch"
        self.trigger_reason: str | None = None
        self._last_run_id: str | None = None
        self._last_trigger_at: datetime | None = None
        self._last_command_poll: float = now()
        #: Status last published, so the keepalive beat repeats the truth rather
        #: than asserting "idle" over an error the loop is still backing off from.
        self._status = "idle"
        self._last_report_at: float | None = None

        if self.backend in ("polling", "both") and (
            config.debounce_seconds < config.poll_interval_seconds
        ):
            # Polling has no per-path stability signal, so a tree still being
            # written is only caught by successive polls pushing the debounce
            # clock forward. A debounce shorter than the poll interval defeats
            # that and can ingest mid-write.
            logger.warning(
                f"debounce ({config.debounce_seconds:.0f}s) is shorter than the poll interval "
                f"({config.poll_interval_seconds:.0f}s); a tree still being written may be "
                "ingested before it settles. Raise --watch-debounce to at least the interval."
            )

    # -- lifecycle ---------------------------------------------------------

    def request_stop(self, *_args: object) -> None:
        """Finish the current cycle, then exit. Safe to call from a signal handler."""
        if self._stop:
            logger.warning("Second stop request — exiting immediately.")
            raise KeyboardInterrupt
        logger.info("Stop requested; finishing the current cycle.")
        self._stop = True

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self.request_stop)

    # -- polling -----------------------------------------------------------

    def poll_once(self) -> bool:
        """Walk the roots and record any signature drift. Returns True if changed.

        Only the digest is retained between polls, not the per-file table: a
        watcher over a 100k-file root would otherwise hold that table resident
        for its whole lifetime to answer a question the digest already answers.
        """
        changed = False
        for root in self.roots:
            signature = run_signature(iter_run_files(root))
            previous = self._signatures.get(root)
            self._signatures[root] = signature
            if previous is not None and previous != signature:
                logger.info(f"Poll detected changes under {root}")
                self.accumulator.note_change()
                changed = True
        return changed

    def prime(self) -> None:
        """Record baseline signatures so the first poll does not fire spuriously."""
        for root in self.roots:
            self._signatures[root] = run_signature(iter_run_files(root))

    # -- main loop ---------------------------------------------------------

    def _mode_for_cycle(self) -> WatchMode:
        if self.config.mode == "full":
            return "full"
        if self.config.full_every and self._cycles and self._cycles % self.config.full_every == 0:
            logger.info(f"Cycle {self._cycles}: running a full re-ingest (--full-every).")
            return "full"
        return "incremental"

    def note_run(self, run_id: str | None) -> None:
        """Adopt the monitoring run id the cycle callback just opened.

        The watcher schedules cycles but does not own the monitoring record —
        ``run_cycle`` opens it — so the id has to come back in, otherwise the
        agent card can never link to the run it is executing.
        """
        if run_id:
            self._last_run_id = run_id

    def _report(self, status: str, **extra: object) -> None:
        """Publish a status change, if anyone is listening. Never raises."""
        self._status = status
        self._last_report_at = self.now()
        if self.on_status is None:
            return
        payload = {
            "runs_total": self._cycles,
            "last_run_id": self._last_run_id,
            "last_trigger_at": self._last_trigger_at,
            **extra,
        }
        try:
            self.on_status(status, payload)
        except Exception as exc:  # noqa: BLE001 - telemetry must not break the loop
            logger.debug(f"Status report failed (non-fatal): {exc}")

    def _heartbeat(self) -> None:
        """Re-publish the current status if the last report is going stale.

        Liveness and state changes are different questions, and the server can
        only answer the first from the timestamp of the last report. A quiet
        watcher makes no state changes for hours, so without this it looks
        identical to one whose process died.
        """
        if self._last_report_at is None:
            return
        if self.now() - self._last_report_at < self.config.heartbeat_interval_seconds:
            return
        self._report(self._status)

    def _poll_command(self) -> bool:
        """Whether a run has been requested from outside since the last check.

        Rate-limited to ``command_poll_interval_seconds`` rather than run on
        every loop tick, which turns over once a second. Never raises: an
        unreachable server must cost the watcher nothing but this feature.
        """
        if self.on_poll_command is None:
            return False
        if self.now() - self._last_command_poll < self.config.command_poll_interval_seconds:
            return False
        self._last_command_poll = self.now()
        try:
            return bool(self.on_poll_command())
        except Exception as exc:  # noqa: BLE001 - a remote button must not kill the loop
            logger.debug(f"Command poll failed (non-fatal): {exc}")
            return False

    def _execute(
        self, paths: set[str], *, trigger: str = "watch", reason: str | None = None
    ) -> None:
        mode = self._mode_for_cycle()
        self.trigger_kind = trigger
        self.trigger_reason = reason or (
            f"{len(paths)} settled change(s)" if paths else "scheduled poll"
        )
        self._cycles += 1
        # Wall-clock, not the injected monotonic clock: this one is rendered to
        # a person in the admin UI, not used for interval arithmetic.
        self._last_trigger_at = datetime.now()
        self._report("ingesting", mode=mode, changed_paths=len(paths))
        try:
            succeeded = self.run_cycle(mode, paths)
        except Exception as exc:  # noqa: BLE001 - a watcher must outlive one bad cycle
            logger.error(f"Ingestion cycle failed: {exc}")
            succeeded = False

        if succeeded:
            self._consecutive_failures = 0
            self._report("idle")
            return

        self._consecutive_failures += 1
        self._report("error", failures=self._consecutive_failures)
        delay = min(
            self.config.backoff_max_seconds,
            self.config.backoff_initial_seconds * (2 ** (self._consecutive_failures - 1)),
        )
        logger.warning(
            f"Cycle failed ({self._consecutive_failures} in a row); backing off {delay:.0f}s"
        )
        self.sleep(delay)

    def run(self) -> int:
        """Watch until stopped. Returns a process exit code."""
        if self.config.once:
            self._execute(set(), reason="single --once pass")
            return 0 if self._consecutive_failures == 0 else 1

        observer = None
        if self.backend in ("native", "both"):
            observer = start_native_observer(self.roots, self.accumulator)
            if observer is None:
                # Native events were requested but are unusable. Polling is the
                # only remaining trigger, so switch rather than sit silent.
                self.backend = "polling"

        self.prime()
        last_poll = self.now()
        # The caller registers the agent just before run(); treat that as the
        # first beat so the keepalive clock starts even for a watcher that never
        # reaches a cycle — which is precisely the one that looked dead.
        if self._last_report_at is None:
            self._last_report_at = self.now()

        try:
            while not self._stop:
                if self.backend in ("polling", "both"):
                    if self.now() - last_poll >= self.config.poll_interval_seconds:
                        self.poll_once()
                        last_poll = self.now()

                if self._poll_command():
                    # Take whatever has settled along with it: the cycle rescans
                    # everything regardless, so running the request and the
                    # pending changes as one pass beats running two.
                    logger.info("Run requested from the web UI; starting a cycle.")
                    self._execute(
                        self.accumulator.drain(),
                        trigger="ui",
                        reason="requested from the web UI",
                    )
                elif self.accumulator.ready():
                    paths = self.accumulator.drain()
                    # Events arriving while this runs land in the accumulator and
                    # are coalesced into exactly one follow-up pass by the next
                    # ready() check — no matter how many of them there were.
                    self._execute(paths)

                if self.config.max_runs is not None and self._cycles >= self.config.max_runs:
                    logger.info(f"Reached --watch-max-runs={self.config.max_runs}; stopping.")
                    break

                self._heartbeat()
                self.sleep(1.0)
        finally:
            if observer is not None:
                observer.stop()
                observer.join(timeout=5.0)

        logger.info(f"Watcher stopped after {self._cycles} cycle(s).")
        return 0
