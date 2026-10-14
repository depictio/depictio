"""Out-of-process execution for analyze code, with a deadline that bites.

`execute_polars` runs an AST-allowlisted expression, which bounds *what*
the model can do but not *how long* it may take. A cross join, a `unique`
over a wide frame or a pathological `pivot` are all inside the allowlist
and all unbounded. The previous approach compared elapsed time after the
fact and logged a warning, which interrupted nothing.

Threads cannot fix this: Python cannot kill a thread, and Polars releases
the GIL for the duration of a query, so the event loop is not even in a
position to notice. A deadline that can be enforced needs a process that
can be killed.

The design point that keeps this affordable is that **the child is told
how to load its data, not handed the data**. A `FrameSpec` is a few
strings; a DataFrame is potentially gigabytes that would have to be
serialised on every respawn. The child calls `load_deltatable_lite`
itself, which also means a kill costs a Redis-warm reload rather than a
trip back to object storage.

Nothing crosses the pipe except code strings in and step dicts out.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
from dataclasses import dataclass, field
from multiprocessing.connection import Connection
from typing import Any

import polars as pl

from depictio.api.v1.endpoints.ai_endpoints.executor import execute_polars
from depictio.api.v1.endpoints.ai_endpoints.schemas import ExecutionStep

logger = logging.getLogger(__name__)

# How long the child gets to import depictio and materialise its frames.
# Generous: a cold spawn re-imports the whole settings stack, and a large
# delta table may genuinely take a while on a cold cache.
START_TIMEOUT_S = 120.0

# Per-step wall clock. The three-bound analysis budget sits above this and
# governs the run as a whole; this one only stops a single runaway step.
DEFAULT_STEP_DEADLINE_S = 30.0


@dataclass(frozen=True)
class FrameSpec:
    """How the child should materialise one data collection.

    `init_data` must be filled in by the parent (via
    `context.init_data_for_dc`). Without it `load_deltatable_lite` falls
    back to fetching the delta location over HTTP from the API that is
    currently serving this request, which deadlocks and then times out.
    """

    tag: str
    workflow_id: str
    data_collection_id: str
    init_data: dict[str, dict]
    filters: list[dict[str, Any]] | None = None


@dataclass
class _Job:
    code: str
    default_tag: str


def _materialise(specs: list[FrameSpec]) -> dict[str, pl.DataFrame]:
    """Load every spec into a frame. Runs in the child."""
    from bson import ObjectId

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    frames: dict[str, pl.DataFrame] = {}
    for spec in specs:
        frames[spec.tag] = load_deltatable_lite(
            workflow_id=ObjectId(spec.workflow_id),
            data_collection_id=ObjectId(spec.data_collection_id),
            metadata=spec.filters or None,
            init_data=spec.init_data,
        )
    return frames


def _child_main(conn: Connection, specs: list[FrameSpec], inline: dict[str, pl.DataFrame]) -> None:
    """Child entry point. Module-level so the spawn context can pickle it."""
    try:
        frames = dict(inline)
        frames.update(_materialise(specs))
    except Exception as e:  # noqa: BLE001 — report, never traceback into the void
        conn.send({"ready": False, "error": f"{type(e).__name__}: {e}"})
        conn.close()
        return

    conn.send({"ready": True, "rows": {tag: f.height for tag, f in frames.items()}})

    while True:
        try:
            job = conn.recv()
        except EOFError:
            break
        if job is None:
            break
        frame = frames.get(job.default_tag)
        if frame is None:
            conn.send(
                ExecutionStep(
                    code=job.code,
                    status="error",
                    output=f"unknown data collection '{job.default_tag}'",
                ).model_dump()
            )
            continue
        step = execute_polars(job.code, frame, scope=frames)
        step.dc_tag = job.default_tag
        conn.send(step.model_dump())

    conn.close()


class AnalysisSandbox:
    """A killable child process holding the frames for one analysis run.

    Use as a context manager, or call `close()` from a `finally`: an
    abandoned child outlives the request that spawned it and keeps a
    whole DataFrame resident.
    """

    def __init__(
        self,
        specs: list[FrameSpec] | None = None,
        *,
        default_tag: str = "",
        inline_frames: dict[str, pl.DataFrame] | None = None,
    ) -> None:
        self._specs = specs or []
        self._inline = inline_frames or {}
        self.default_tag = default_tag or (
            self._specs[0].tag if self._specs else next(iter(self._inline), "")
        )
        self._proc: mp.process.BaseProcess | None = None
        self._conn: Connection | None = None
        self.rows: dict[str, int] = {}

    # ---------- lifecycle ----------

    def start(self) -> None:
        """Spawn the child and block until its frames are loaded."""
        # "spawn" rather than the platform default: forking a uvicorn
        # worker would clone its event loop and thread state into a child
        # that has no use for either.
        ctx = mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe()
        proc = ctx.Process(
            target=_child_main,
            args=(child_conn, self._specs, self._inline),
            daemon=True,
        )
        proc.start()
        child_conn.close()  # only the child holds the write end now

        if not parent_conn.poll(START_TIMEOUT_S):
            proc.kill()
            proc.join()
            parent_conn.close()
            raise RuntimeError(f"analysis sandbox did not start within {START_TIMEOUT_S}s")

        hello = parent_conn.recv()
        if not hello.get("ready"):
            proc.join()
            parent_conn.close()
            raise RuntimeError(f"analysis sandbox failed to load data: {hello.get('error')}")

        self._proc = proc
        self._conn = parent_conn
        self.rows = hello.get("rows", {})

    def close(self) -> None:
        """Kill the child. Safe to call twice, and never raises."""
        if self._conn is not None:
            try:
                self._conn.send(None)
            except (BrokenPipeError, OSError):
                pass
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None
        if self._proc is not None:
            self._proc.kill()
            self._proc.join(timeout=5)
            self._proc = None

    def __enter__(self) -> AnalysisSandbox:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------- execution ----------

    def run(
        self,
        code: str,
        *,
        dc_tag: str = "",
        deadline_s: float = DEFAULT_STEP_DEADLINE_S,
    ) -> ExecutionStep:
        """Execute `code`, killing the child if it overruns `deadline_s`.

        A timeout is reported as a normal error step, not raised: the
        analysis loop should be able to see that a step was too expensive
        and try something cheaper, which it cannot do if the request has
        already failed.
        """
        if self._conn is None or self._proc is None:
            self.start()
        assert self._conn is not None  # narrowed by start()

        tag = dc_tag or self.default_tag
        try:
            self._conn.send(_Job(code=code, default_tag=tag))
        except (BrokenPipeError, OSError):
            self.close()
            return ExecutionStep(
                code=code,
                dc_tag=tag,
                status="error",
                output="the analysis sandbox died; the next step will start a fresh one",
            )

        if not self._conn.poll(deadline_s):
            logger.warning("analysis sandbox exceeded %.2fs; killing", deadline_s)
            # Reap now, respawn lazily. Returning the timeout immediately
            # is the whole point; if the analysis stops here, we never pay
            # for a replacement child at all. When it does continue, the
            # reload is served from the cache the dead child populated.
            self.close()
            return ExecutionStep(
                code=code,
                dc_tag=tag,
                status="error",
                output=(
                    f"TimeoutError: exceeded the {deadline_s:.0f}s step budget and was "
                    "cancelled. Narrow the data first (filter or aggregate) and retry."
                ),
                seconds=deadline_s,
            )

        try:
            payload = self._conn.recv()
        except EOFError:
            self.close()
            return ExecutionStep(
                code=code,
                dc_tag=tag,
                status="error",
                output="the analysis sandbox exited unexpectedly",
            )
        return ExecutionStep.model_validate(payload)


@dataclass
class InlineSandbox:
    """In-process stand-in for `AnalysisSandbox`, for tests and fixtures.

    Same surface, no process and therefore no enforceable deadline. Never
    use it to run model-authored code against real data.
    """

    frames: dict[str, pl.DataFrame] = field(default_factory=dict)
    default_tag: str = ""

    def start(self) -> None:
        if not self.default_tag:
            self.default_tag = next(iter(self.frames), "")

    def close(self) -> None:
        return None

    def __enter__(self) -> InlineSandbox:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def run(self, code: str, *, dc_tag: str = "", deadline_s: float = 0.0) -> ExecutionStep:
        tag = dc_tag or self.default_tag
        frame = self.frames.get(tag)
        if frame is None:
            return ExecutionStep(
                code=code, dc_tag=tag, status="error", output=f"unknown data collection '{tag}'"
            )
        step = execute_polars(code, frame, scope=self.frames)
        step.dc_tag = tag
        return step
