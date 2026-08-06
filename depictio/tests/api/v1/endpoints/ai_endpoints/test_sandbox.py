"""The sandbox's only job that the in-process executor cannot do: stop.

These tests spawn real processes. They are slower than the rest of the
suite by design — a deadline that is only asserted against a mock is not
evidence that anything gets killed.
"""

from __future__ import annotations

import time

import polars as pl
import pytest

from depictio.api.v1.endpoints.ai_endpoints.sandbox import (
    AnalysisSandbox,
    InlineSandbox,
)


@pytest.fixture()
def frames() -> dict[str, pl.DataFrame]:
    return {
        "obs": pl.DataFrame({"sample": ["a", "b", "c", "d"], "depth": [10, 20, 30, 40]}),
        "meta": pl.DataFrame({"sample": ["a", "b"], "site": ["x", "y"]}),
    }


# A self-join on a constant key: every verb is inside the allowlist, and
# the cost is entirely in the data, which is exactly the case policy
# cannot price. Selecting the key column keeps the output narrow, so this
# is slow without being a memory hazard on CI.
SLOW_CODE = "df.join(df.select('k'), on='k', how='inner').height"


def _slow_frame() -> pl.DataFrame:
    return pl.DataFrame({"k": [1] * 4000, "v": list(range(4000))})


class TestDeadline:
    """The point of the whole module."""

    def test_step_is_killed_mid_flight_not_relabelled_afterwards(self):
        with AnalysisSandbox(inline_frames={"obs": _slow_frame()}, default_tag="obs") as box:
            # First establish what the query actually costs, uncapped.
            baseline = box.run(SLOW_CODE, deadline_s=120.0)
            assert baseline.status == "success", baseline.output
            cost = baseline.seconds
            assert cost > 0.05, f"query too cheap to be a meaningful deadline test ({cost}s)"

            # Now cap it well under that and time the call.
            t0 = time.perf_counter()
            step = box.run(SLOW_CODE, deadline_s=cost / 4)
            elapsed = time.perf_counter() - t0

        assert step.status == "error"
        assert "TimeoutError" in step.output
        # The old implementation let the work finish and then complained
        # about the clock. Returning faster than the query itself takes is
        # what distinguishes an enforced deadline from an advisory one.
        assert elapsed < cost, f"returned after {elapsed:.3f}s for a {cost:.3f}s query"

    def test_sandbox_survives_a_kill_and_serves_the_next_step(self, frames):
        with AnalysisSandbox(
            inline_frames={"obs": _slow_frame(), "small": frames["obs"]}, default_tag="obs"
        ) as box:
            killed = box.run(SLOW_CODE, deadline_s=0.01)
            assert killed.status == "error"
            assert "TimeoutError" in killed.output

            # The child was respawned, so its frames are loaded again and
            # the next step behaves as if nothing happened.
            after = box.run("df.height", dc_tag="small")
            assert after.status == "success", after.output
            assert after.output == "4"

    def test_close_reaps_the_child(self):
        box = AnalysisSandbox(inline_frames={"obs": pl.DataFrame({"a": [1]})}, default_tag="obs")
        box.start()
        proc = box._proc
        assert proc is not None and proc.is_alive()
        box.close()
        assert not proc.is_alive()

    def test_close_is_idempotent(self):
        box = AnalysisSandbox(inline_frames={"obs": pl.DataFrame({"a": [1]})}, default_tag="obs")
        box.start()
        box.close()
        box.close()  # must not raise


class TestExecution:
    def test_runs_allowlisted_code(self, frames):
        with AnalysisSandbox(inline_frames=frames, default_tag="obs") as box:
            step = box.run("df.filter(pl.col('depth') >= 30).height")
            assert step.status == "success", step.output
            assert step.output == "2"
            assert step.dc_tag == "obs"

    def test_policy_still_applies_inside_the_child(self, frames):
        with AnalysisSandbox(inline_frames=frames, default_tag="obs") as box:
            step = box.run("__import__('os').system('true')")
            assert step.status == "error"
            assert "BlockedByPolicy" in step.output or "SyntaxError" in step.output

    def test_unknown_tag_is_an_error_step_not_a_crash(self, frames):
        with AnalysisSandbox(inline_frames=frames, default_tag="obs") as box:
            step = box.run("df.height", dc_tag="nope")
            assert step.status == "error"
            assert "unknown data collection" in step.output
            # The child is still usable.
            assert box.run("df.height").status == "success"

    def test_cardinalities_are_reported(self, frames):
        with AnalysisSandbox(inline_frames=frames, default_tag="obs") as box:
            step = box.run("df.filter(pl.col('depth') >= 30)")
            assert step.rows_in == 4
            assert step.rows_out == 2


class TestInlineSandbox:
    """The fixture double keeps the same contract, minus the deadline."""

    def test_same_surface(self, frames):
        with InlineSandbox(frames=frames, default_tag="obs") as box:
            step = box.run("df.height")
            assert step.status == "success"
            assert step.dc_tag == "obs"

    def test_unknown_tag(self, frames):
        with InlineSandbox(frames=frames, default_tag="obs") as box:
            assert box.run("df.height", dc_tag="nope").status == "error"
