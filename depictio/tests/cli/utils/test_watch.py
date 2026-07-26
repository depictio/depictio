"""Tests for the watcher's scheduling and coalescing logic.

No real Observer and no real clock: time is injected so debounce, settle and
backoff windows are exact rather than slept through, and change notices are fed
in directly so the tests describe the decision logic rather than the plumbing.
"""

import os

import pytest

from depictio.cli.cli.utils.watch import (
    NETWORK_FSTYPES,
    ChangeAccumulator,
    ProjectWatcher,
    WatchConfig,
    project_lock,
    resolve_backend,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_accumulator(clock, **overrides) -> ChangeAccumulator:
    config = WatchConfig(
        debounce_seconds=overrides.pop("debounce_seconds", 30.0),
        settle_seconds=overrides.pop("settle_seconds", 5.0),
        max_delay_seconds=overrides.pop("max_delay_seconds", 300.0),
        **overrides,
    )
    return ChangeAccumulator(config=config, now=clock)


def write(path, content: str = "x") -> str:
    path.write_text(content)
    return str(path)


class TestDebounce:
    def test_no_changes_is_never_ready(self, clock):
        assert make_accumulator(clock).ready() is False

    def test_not_ready_before_the_quiet_period(self, clock, tmp_path):
        accumulator = make_accumulator(clock)
        accumulator.note(write(tmp_path / "a.csv"))

        clock.advance(20.0)
        assert accumulator.ready() is False

    def test_ready_once_quiet(self, clock, tmp_path):
        accumulator = make_accumulator(clock)
        accumulator.note(write(tmp_path / "a.csv"))

        clock.advance(31.0)
        assert accumulator.ready() is True

    def test_a_new_change_restarts_the_quiet_period(self, clock, tmp_path):
        accumulator = make_accumulator(clock)
        accumulator.note(write(tmp_path / "a.csv"))

        clock.advance(25.0)
        accumulator.note(write(tmp_path / "b.csv"))
        clock.advance(25.0)
        # A burst of pipeline writes must produce one cycle, not one per file.
        assert accumulator.ready() is False

        clock.advance(10.0)
        assert accumulator.ready() is True

    def test_max_delay_forces_a_cycle_during_continuous_writes(self, clock, tmp_path):
        accumulator = make_accumulator(clock, max_delay_seconds=100.0)
        target = tmp_path / "stream.csv"

        for index in range(20):
            write(target, "x" * (index + 1))
            accumulator.note(str(target))
            clock.advance(10.0)

        # Debounce alone would defer forever while writes keep arriving.
        assert accumulator.ready() is True


class TestSettling:
    def test_a_growing_file_is_not_ingested(self, clock, tmp_path):
        accumulator = make_accumulator(clock, debounce_seconds=1.0)
        target = tmp_path / "growing.csv"
        accumulator.note(write(target, "partial"))

        clock.advance(10.0)
        write(target, "partial-plus-more")
        # A created event fires at open(), not close(): ingesting here would
        # publish a truncated file.
        assert accumulator.ready() is False

    def test_a_settled_file_becomes_ready(self, clock, tmp_path):
        accumulator = make_accumulator(clock, debounce_seconds=1.0)
        accumulator.note(write(tmp_path / "done.csv"))

        clock.advance(10.0)
        assert accumulator.ready() is True

    def test_drain_returns_only_settled_paths(self, clock, tmp_path):
        accumulator = make_accumulator(clock, debounce_seconds=1.0)
        settled = write(tmp_path / "settled.csv")
        accumulator.note(settled)

        clock.advance(10.0)
        assert accumulator.ready() is True
        assert accumulator.drain() == {settled}

    def test_drain_resets_the_window(self, clock, tmp_path):
        accumulator = make_accumulator(clock, debounce_seconds=1.0)
        accumulator.note(write(tmp_path / "a.csv"))
        clock.advance(10.0)
        accumulator.ready()
        accumulator.drain()

        assert accumulator.ready() is False

    def test_a_vanished_file_still_counts_as_a_change(self, clock, tmp_path):
        accumulator = make_accumulator(clock, debounce_seconds=1.0)
        # Deletions matter to ingestion, but have no stability to establish.
        accumulator.note(str(tmp_path / "never-existed.csv"))

        clock.advance(10.0)
        assert accumulator.ready() is True
        assert accumulator.drain() == set()

    def test_unstable_paths_survive_a_drain(self, clock, tmp_path):
        accumulator = make_accumulator(clock, debounce_seconds=1.0, settle_seconds=100.0)
        accumulator.note(write(tmp_path / "slow.csv"))
        clock.advance(2.0)
        accumulator.drain()

        # Still in flight: it must not be silently forgotten.
        assert accumulator.has_changes is True


class TestBackendResolution:
    def test_explicit_backend_is_respected(self, tmp_path):
        assert resolve_backend("native", [str(tmp_path)]) == "native"
        assert resolve_backend("polling", [str(tmp_path)]) == "polling"

    def test_auto_on_a_local_path_keeps_the_polling_backstop(self, tmp_path, monkeypatch):
        monkeypatch.setattr("depictio.cli.cli.utils.watch.detect_filesystem", lambda _p: "ext4")
        # Not "native": the inotify queue can overflow and drop events silently,
        # so a slow reconciliation walk runs alongside.
        assert resolve_backend("auto", [str(tmp_path)]) == "both"

    @pytest.mark.parametrize("fstype", sorted(NETWORK_FSTYPES))
    def test_auto_forces_polling_on_network_filesystems(self, tmp_path, monkeypatch, fstype):
        monkeypatch.setattr("depictio.cli.cli.utils.watch.detect_filesystem", lambda _p: fstype)
        # inotify does not report writes made from another host — the exact HPC
        # case of a compute node writing while the watcher runs on a login node.
        assert resolve_backend("auto", [str(tmp_path)]) == "polling"

    def test_auto_forces_polling_on_fuse(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "depictio.cli.cli.utils.watch.detect_filesystem", lambda _p: "fuse.sshfs"
        )
        assert resolve_backend("auto", [str(tmp_path)]) == "polling"

    def test_one_network_root_forces_polling_for_all(self, tmp_path, monkeypatch):
        seen = iter(["ext4", "nfs4"])
        monkeypatch.setattr("depictio.cli.cli.utils.watch.detect_filesystem", lambda _p: next(seen))
        # A mixed setup where half the roots emit events is worse than a
        # uniformly polled one: the silence looks identical to "no changes".
        assert resolve_backend("auto", [str(tmp_path), str(tmp_path)]) == "polling"


class TestProjectLock:
    def test_lock_is_exclusive(self, tmp_path):
        lock_file = tmp_path / "project.lock"
        with project_lock(lock_file):
            with pytest.raises(RuntimeError, match="already holds"):
                with project_lock(lock_file):
                    pass

    def test_lock_is_released_on_exit(self, tmp_path):
        lock_file = tmp_path / "project.lock"
        with project_lock(lock_file):
            pass
        with project_lock(lock_file):
            pass

    def test_lock_is_released_on_exception(self, tmp_path):
        lock_file = tmp_path / "project.lock"
        with pytest.raises(ValueError):
            with project_lock(lock_file):
                raise ValueError("boom")
        with project_lock(lock_file):
            pass

    def test_lock_records_the_holding_pid(self, tmp_path):
        lock_file = tmp_path / "project.lock"
        with project_lock(lock_file):
            assert lock_file.read_text() == str(os.getpid())


class TestWatcherLoop:
    def _watcher(self, tmp_path, clock, run_cycle, *, external_writes=False, **overrides):
        """A watcher whose sleep advances the fake clock.

        ``external_writes`` simulates the outside world dropping a new file into
        the data root while the watcher waits — without it the tree never
        changes, nothing ever triggers, and a loop bounded only by ``max_runs``
        would spin forever. An iteration cap turns that into a fast failure
        rather than a hang.
        """
        ticks = {"n": 0}

        def sleep(_seconds: float) -> None:
            ticks["n"] += 1
            if ticks["n"] > 500:
                raise AssertionError("watcher loop did not terminate")
            clock.advance(1.0)
            if external_writes:
                write(tmp_path / f"external-{ticks['n']}.csv")

        config = WatchConfig(backend="polling", **overrides)
        return ProjectWatcher(
            roots=[str(tmp_path)],
            config=config,
            run_cycle=run_cycle,
            sleep=sleep,
            now=clock,
        )

    def test_once_runs_a_single_cycle(self, tmp_path, clock):
        calls = []
        watcher = self._watcher(
            tmp_path, clock, lambda mode, paths: calls.append(mode) or True, once=True
        )

        assert watcher.run() == 0
        assert calls == ["incremental"]

    def test_once_reports_failure_as_a_nonzero_exit(self, tmp_path, clock):
        watcher = self._watcher(tmp_path, clock, lambda mode, paths: False, once=True)
        assert watcher.run() == 1

    def test_full_mode_is_passed_through(self, tmp_path, clock):
        calls = []
        watcher = self._watcher(
            tmp_path, clock, lambda mode, paths: calls.append(mode) or True, once=True, mode="full"
        )
        watcher.run()
        assert calls == ["full"]

    def test_max_runs_stops_the_loop(self, tmp_path, clock):
        write(tmp_path / "seed.csv")
        calls = []

        watcher = self._watcher(
            tmp_path,
            clock,
            lambda mode, paths: calls.append(mode) or True,
            external_writes=True,
            max_runs=2,
            debounce_seconds=0.0,
            poll_interval_seconds=0.0,
            settle_seconds=0.0,
        )
        assert watcher.run() == 0
        assert len(calls) == 2

    def test_a_failing_cycle_backs_off_without_stopping(self, tmp_path, clock):
        write(tmp_path / "seed.csv")
        attempts = []

        watcher = self._watcher(
            tmp_path,
            clock,
            lambda mode, paths: attempts.append(mode) and False,
            external_writes=True,
            max_runs=3,
            debounce_seconds=0.0,
            poll_interval_seconds=0.0,
            settle_seconds=0.0,
            backoff_initial_seconds=1.0,
            backoff_max_seconds=4.0,
        )
        watcher.run()
        # A broken server must not kill the watcher, only slow it down.
        assert len(attempts) == 3

    def test_a_raising_cycle_is_contained(self, tmp_path, clock):
        def cycle(mode, paths):
            raise RuntimeError("network down")

        watcher = self._watcher(tmp_path, clock, cycle, once=True, backoff_initial_seconds=0.0)
        assert watcher.run() == 1

    @staticmethod
    def _ticking_sleep(clock, watcher, *, stop_after: int):
        """A sleep that advances the clock one second and stops after N ticks.

        Counts ticks rather than reading the clock, which starts at an arbitrary
        offset rather than zero.
        """
        ticks = {"n": 0}

        def sleep(_seconds: float) -> None:
            ticks["n"] += 1
            clock.advance(1.0)
            if ticks["n"] >= stop_after:
                watcher.request_stop()

        return sleep

    def test_an_idle_watcher_keeps_reporting(self, tmp_path, clock):
        """A quiet watcher must stay visible to the server.

        The agent record expires on a TTL measured from the last report, so a
        watcher that only reported on state changes was declared wedged and
        then evicted while sitting healthily in its loop.
        """
        reports = []
        watcher = self._watcher(
            tmp_path,
            clock,
            lambda mode, paths: True,
            heartbeat_interval_seconds=10.0,
        )
        watcher.on_status = lambda status, extra: reports.append(status)

        # Nothing ever changes in the data root, so no cycle can run.
        watcher.sleep = self._ticking_sleep(clock, watcher, stop_after=35)
        watcher.run()

        assert reports == ["idle", "idle", "idle"]

    def test_the_heartbeat_repeats_the_current_status(self, tmp_path, clock):
        """A watcher backing off from failures must not beat "idle" over it."""
        write(tmp_path / "seed.csv")
        reports = []
        watcher = self._watcher(
            tmp_path,
            clock,
            lambda mode, paths: False,
            external_writes=True,
            max_runs=1,
            debounce_seconds=0.0,
            poll_interval_seconds=0.0,
            settle_seconds=0.0,
            backoff_initial_seconds=0.0,
            heartbeat_interval_seconds=1.0,
        )
        watcher.on_status = lambda status, extra: reports.append(status)
        watcher.run()

        assert reports[0] == "ingesting"
        assert reports[1] == "error"
        # Every beat after the failed cycle carries the error forward.
        assert set(reports[2:]) <= {"error"}

    def test_no_heartbeat_before_the_interval_elapses(self, tmp_path, clock):
        reports = []
        watcher = self._watcher(
            tmp_path,
            clock,
            lambda mode, paths: True,
            heartbeat_interval_seconds=600.0,
        )
        watcher.on_status = lambda status, extra: reports.append(status)

        watcher.sleep = self._ticking_sleep(clock, watcher, stop_after=5)
        watcher.run()

        assert reports == []

    def test_a_requested_run_starts_a_cycle(self, tmp_path, clock):
        """ "Run now" in the UI must reach a watcher with nothing to react to."""
        calls = []
        watcher = self._watcher(
            tmp_path,
            clock,
            lambda mode, paths: calls.append(paths) or True,
            max_runs=1,
            command_poll_interval_seconds=0.0,
        )
        # Requested once; the server clears the flag, so later polls say no.
        requests = iter([True])
        watcher.on_poll_command = lambda: next(requests, False)
        watcher.run()

        assert calls == [set()]
        assert watcher.trigger_kind == "ui"
        assert watcher.trigger_reason == "requested from the web UI"

    def test_a_requested_run_is_recorded_as_a_ui_trigger(self, tmp_path, clock):
        """The history must distinguish a person pressing a button from a poll."""
        watcher = self._watcher(tmp_path, clock, lambda mode, paths: True, once=True)
        watcher.run()

        assert watcher.trigger_kind == "watch"
        assert watcher.trigger_reason == "single --once pass"

    def test_the_command_poll_is_rate_limited(self, tmp_path, clock):
        """The loop ticks every second; the server must not be asked that often."""
        polls = []
        watcher = self._watcher(
            tmp_path,
            clock,
            lambda mode, paths: True,
            command_poll_interval_seconds=10.0,
        )
        watcher.on_poll_command = lambda: polls.append(clock()) or False
        watcher.sleep = self._ticking_sleep(clock, watcher, stop_after=35)
        watcher.run()

        assert len(polls) == 3

    def test_a_failing_command_poll_is_survivable(self, tmp_path, clock):
        """An unreachable server costs the feature, not the watcher."""
        watcher = self._watcher(
            tmp_path,
            clock,
            lambda mode, paths: True,
            command_poll_interval_seconds=0.0,
        )

        def explode() -> bool:
            raise RuntimeError("connection refused")

        watcher.on_poll_command = explode
        watcher.sleep = self._ticking_sleep(clock, watcher, stop_after=3)

        assert watcher.run() == 0

    def test_stop_request_ends_the_loop(self, tmp_path, clock):
        watcher = self._watcher(tmp_path, clock, lambda mode, paths: True)
        watcher.request_stop()
        assert watcher.run() == 0

    def test_second_stop_request_raises(self, tmp_path, clock):
        watcher = self._watcher(tmp_path, clock, lambda mode, paths: True)
        watcher.request_stop()
        with pytest.raises(KeyboardInterrupt):
            watcher.request_stop()

    def test_priming_prevents_a_spurious_first_cycle(self, tmp_path, clock):
        write(tmp_path / "existing.csv")
        watcher = self._watcher(tmp_path, clock, lambda mode, paths: True)
        watcher.prime()

        # An already-populated data root is not "new data".
        assert watcher.poll_once() is False

    def test_poll_detects_a_new_file(self, tmp_path, clock):
        watcher = self._watcher(tmp_path, clock, lambda mode, paths: True)
        watcher.prime()
        write(tmp_path / "arrived.csv")

        assert watcher.poll_once() is True

    def test_poll_detects_a_removed_file(self, tmp_path, clock):
        target = tmp_path / "leaving.csv"
        write(target)
        watcher = self._watcher(tmp_path, clock, lambda mode, paths: True)
        watcher.prime()
        target.unlink()

        assert watcher.poll_once() is True

    def test_full_every_alternates_cycle_modes(self, tmp_path, clock):
        write(tmp_path / "seed.csv")
        modes = []

        watcher = self._watcher(
            tmp_path,
            clock,
            lambda mode, paths: modes.append(mode) or True,
            external_writes=True,
            max_runs=4,
            full_every=2,
            debounce_seconds=0.0,
            poll_interval_seconds=0.0,
            settle_seconds=0.0,
        )
        watcher.run()
        # Cycle counting starts at 0, so every second cycle thereafter is full.
        assert modes == ["incremental", "incremental", "full", "incremental"]
