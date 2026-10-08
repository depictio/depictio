"""`depictio watch` runs `ingest` (``run_ingest``) once per cycle.

``run_ingest`` is mocked: these assert what each cycle asks of it, which is all
the watch command decides. The scheduling itself is tested in utils/test_watch.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from depictio.cli.cli.commands import watch as watch_module
from depictio.cli.cli.commands.run import IngestOptions, IngestOutcome
from depictio.cli.cli.commands.watch import _Cycles, register_watch_command

OK = IngestOutcome(success_count=7, total_steps=7)
PARTIAL = IngestOutcome(success_count=6, total_steps=7)


def _fake_run_ingest(*outcomes, project_config=None):
    """A run_ingest that returns (or raises) each of ``outcomes`` in turn, and
    validates ``project_config`` onto the record as the real one does."""
    calls: list[IngestOptions] = []
    pending = list(outcomes)

    def run(opts, record):
        calls.append(opts)
        record.project_config = project_config
        outcome = pending.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return run, calls


@pytest.fixture
def project():
    return SimpleNamespace(id="p1", name="proj", workflows=[])


class TestTheWatchCommand:
    @pytest.fixture
    def invoke(self, tmp_path, project):
        def _invoke(*outcomes, args=()):
            app = typer.Typer()
            register_watch_command(app)
            app.command("noop")(lambda: None)
            run, calls = _fake_run_ingest(*outcomes, project_config=project)
            with patch.object(watch_module, "run_ingest", run):
                result = CliRunner().invoke(
                    app,
                    ["watch", str(tmp_path), "--server", str(tmp_path / "CLI.yaml"), *args],
                )
            return result, calls

        return _invoke

    def test_once_runs_a_single_refreshing_cycle(self, invoke, tmp_path):
        result, calls = invoke(OK, args=["--once"])

        assert result.exit_code == 0, result.output
        (opts,) = calls
        assert opts.data_root == str(tmp_path)
        assert opts.CLI_config_path == str(tmp_path / "CLI.yaml")
        assert opts.update_config is True
        assert opts.skip == {"server-check", "s3-check", "dashboards"}
        assert (opts.sync_changed, opts.sync_files, opts.skip_unchanged) == (True, False, False)
        assert (opts.command, opts.triggered_by, opts.trigger) == ("watch", "watch", "watch")
        assert opts.state_cache is True

    def test_once_exits_with_the_cycle_status(self, invoke):
        result, _ = invoke(PARTIAL, args=["--once"])
        assert result.exit_code == 1

    def test_a_dry_run_syncs_nothing_and_writes_nothing(self, invoke):
        _, (opts,) = invoke(OK, args=["--once", "--dry-run"])
        assert "sync" in opts.skip
        assert opts.scan_dry_run is True
        # Not ingest's own dry run, which stops before the server is reached.
        assert opts.dry_run is False

    def test_a_first_cycle_that_validated_nothing_stops_the_watch(self, tmp_path):
        app = typer.Typer()
        register_watch_command(app)
        app.command("noop")(lambda: None)
        run, _ = _fake_run_ingest(typer.Exit(code=2), project_config=None)
        with patch.object(watch_module, "run_ingest", run):
            result = CliRunner().invoke(app, ["watch", str(tmp_path), "--server", "x.yaml"])

        assert result.exit_code == 2
        assert "nothing to watch" in result.output

    @pytest.mark.parametrize(
        ("option", "value"),
        [("--mode", "sideways"), ("--backend", "telepathy"), ("--write-mode", "append")],
    )
    def test_an_unknown_choice_is_a_usage_error(self, invoke, option, value):
        result, calls = invoke(OK, args=[option, value])
        assert result.exit_code == 2
        assert calls == []


class TestCycles:
    @staticmethod
    def _cycles(*outcomes, dry_run=False, project_config=None):
        run, calls = _fake_run_ingest(*outcomes, project_config=project_config)
        base = IngestOptions(
            skip=frozenset({"server-check", "s3-check", "dashboards"}),
            update_config=True,
            scan_dry_run=dry_run,
        )
        return _Cycles(base), run, calls

    def test_the_project_is_synced_once_then_only_rescanned(self):
        cycles, run, calls = self._cycles(OK, OK)
        with patch.object(watch_module, "run_ingest", run):
            assert cycles("incremental", set()) is True
            assert cycles("incremental", {"/data/a.tsv"}) is True

        assert "sync" not in calls[0].skip
        assert "sync" in calls[1].skip

    def test_only_an_incremental_cycle_after_a_success_skips_unchanged(self):
        cycles, run, calls = self._cycles(OK, OK, PARTIAL, OK)
        with patch.object(watch_module, "run_ingest", run):
            cycles("incremental", set())
            cycles("full", set())
            cycles("incremental", set())
            cycles("incremental", set())

        assert [c.skip_unchanged for c in calls] == [False, False, True, False]
        assert [c.sync_files for c in calls] == [False, True, False, False]
        assert [c.sync_changed for c in calls] == [True, False, True, True]

    def test_a_failed_cycle_does_not_sync_the_project(self):
        cycles, run, calls = self._cycles(PARTIAL, OK)
        with patch.object(watch_module, "run_ingest", run):
            cycles("incremental", set())
            cycles("incremental", set())

        assert "sync" not in calls[1].skip

    def test_a_dry_run_never_vouches_for_skipping(self):
        cycles, run, calls = self._cycles(OK, OK, dry_run=True)
        with patch.object(watch_module, "run_ingest", run):
            cycles("incremental", set())
            cycles("incremental", set())

        assert calls[1].skip_unchanged is False

    def test_a_failed_step_is_a_failed_cycle_not_the_end_of_the_watch(self, project):
        cycles, run, _ = self._cycles(typer.Exit(code=1), project_config=project)
        with patch.object(watch_module, "run_ingest", run):
            assert cycles("incremental", set()) is False

        assert cycles.exit_code == 1
        # Read from the record whatever the outcome: it says where to watch.
        assert cycles.project_config is project

    def test_the_watcher_says_why_a_cycle_ran_and_learns_its_run(self):
        cycles, _, calls = self._cycles(OK)
        watcher = MagicMock(trigger_kind="ui", trigger_reason="requested from the web UI")
        cycles.watcher = watcher

        def run(opts, record):
            calls.append(opts)
            opts.on_run_opened("run-9")
            return OK

        with patch.object(watch_module, "run_ingest", run):
            cycles("incremental", set())

        assert (calls[0].trigger, calls[0].trigger_reason) == ("ui", "requested from the web UI")
        watcher.note_run.assert_called_once_with("run-9")
        assert cycles.last_run_id == "run-9"
