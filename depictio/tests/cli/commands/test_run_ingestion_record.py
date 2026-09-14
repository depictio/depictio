"""`depictio-cli run` closes its monitoring record on every way out.

The record used to be closed only at the very end of the command, so every
error exit (sync, scan, process, joins, dashboard import), a Ctrl-C or a SIGTERM
left the run "running" in the admin Ingestion pane forever. Server calls are
mocked; these assert what the record is closed with, and that reporting never
changes the exit code or hides the original error.
"""

from __future__ import annotations

import signal
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from depictio.cli.cli.commands import run as run_module
from depictio.cli.cli.commands.run import register_run_command
from depictio.tests.cli.commands.test_run_attach_flow import _Harness


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "run_a"
    root.mkdir()
    return root


def _invoke(harness, data_root, finish, start=None):
    app = typer.Typer()
    register_run_command(app)
    patches = [
        *harness.patches(),
        # Layered over the harness's own monitoring mocks; stopped in reverse
        # below so each patch restores exactly what it replaced.
        patch.object(
            run_module,
            "api_monitoring_ingestion_start",
            start or MagicMock(return_value="run-1"),
        ),
        patch.object(run_module, "api_monitoring_ingestion_finish", finish),
    ]
    for p in patches:
        p.start()
    try:
        return CliRunner().invoke(
            app,
            [
                "--template",
                "nf-core/ampliseq/2.16.0",
                "--data-root",
                str(data_root),
                "--skip-server-check",
                "--skip-s3-check",
            ],
        )
    finally:
        for p in reversed(patches):
            p.stop()


def _plain_exit_code(exc: BaseException) -> int:
    """Exit code Typer gives a bare command raising ``exc``: the baseline the
    monitoring wrapper must leave untouched."""
    app = typer.Typer()

    @app.command()
    def boom() -> None:
        raise exc

    return CliRunner().invoke(app, []).exit_code


def _closed_with(finish: MagicMock) -> dict:
    finish.assert_called_once()
    return finish.call_args.kwargs


class TestNormalCompletion:
    def test_a_successful_run_is_closed_once_as_success(self, data_root):
        finish = MagicMock()
        result = _invoke(_Harness(data_root, remote_locations=[]), data_root, finish)

        assert result.exit_code == 0, result.output
        assert _closed_with(finish)["status"] == "success"

    def test_nothing_is_reported_when_the_record_never_opened(self, data_root):
        harness = _Harness(data_root, remote_locations=[])
        harness.scan = MagicMock(return_value={"result": "failed"})
        finish = MagicMock()
        result = _invoke(harness, data_root, finish, start=MagicMock(return_value=None))

        assert result.exit_code == 1
        finish.assert_not_called()


class TestErrorExits:
    def test_a_failed_step_closes_the_run_as_failed_naming_the_step(self, data_root):
        harness = _Harness(data_root, remote_locations=[])
        harness.scan = MagicMock(return_value={"result": "failed"})
        finish = MagicMock()
        result = _invoke(harness, data_root, finish)

        assert result.exit_code == 1
        closed = _closed_with(finish)
        assert closed["status"] == "failed"
        assert "scan" in closed["error"]
        assert {"name": "scan", "status": "failed"}.items() <= closed["steps"][-1].items()
        # An error exit does not wait the full default timeout on the server.
        assert closed["timeout"] == run_module._ERROR_REPORT_TIMEOUT
        harness.process.assert_not_called()

    def test_a_deliberate_exit_keeps_its_own_code(self, data_root):
        harness = _Harness(data_root, remote_locations=[])
        harness.sync = MagicMock(return_value={"action": "exists"})
        finish = MagicMock()
        result = _invoke(harness, data_root, finish)

        assert result.exit_code == 2
        closed = _closed_with(finish)
        assert closed["status"] == "failed"
        assert "sync_project" in closed["error"]

    def test_an_unexpected_exception_is_reported_and_still_raised(self, data_root):
        harness = _Harness(data_root, remote_locations=[])
        finish = MagicMock()
        # Separators: step 0, 3, 4 and 5 print; step 6's raises, after the
        # record opened (before step 4) and outside any step's own handler.
        with patch.object(
            run_module,
            "rich_print_section_separator",
            side_effect=[None] * 4 + [RuntimeError("boom")],
        ):
            result = _invoke(harness, data_root, finish)

        assert isinstance(result.exception, RuntimeError)
        assert str(result.exception) == "boom"
        assert _closed_with(finish)["status"] == "failed"


class TestInterruptions:
    def test_ctrl_c_closes_the_run_as_interrupted_during_its_step(self, data_root):
        harness = _Harness(data_root, remote_locations=[])
        harness.process = MagicMock(side_effect=KeyboardInterrupt)
        finish = MagicMock()
        result = _invoke(harness, data_root, finish)

        assert result.exit_code == _plain_exit_code(KeyboardInterrupt())
        closed = _closed_with(finish)
        assert closed["status"] == "interrupted"
        assert "process" in closed["error"]
        assert closed["steps"][-1] == {
            "name": "process",
            "status": "interrupted",
            "detail": "Interrupted",
        }

    def test_sigterm_closes_the_run_and_exits_143(self, data_root):
        harness = _Harness(data_root, remote_locations=[])
        harness.process = MagicMock(
            side_effect=run_module._TerminatedBySignal(128 + signal.SIGTERM)
        )
        finish = MagicMock()
        result = _invoke(harness, data_root, finish)

        assert result.exit_code == 128 + signal.SIGTERM
        closed = _closed_with(finish)
        assert closed["status"] == "interrupted"
        assert "SIGTERM" in closed["error"]

    def test_sigterm_handler_is_scoped_to_the_run(self):
        before = signal.getsignal(signal.SIGTERM)
        restore = run_module._raise_on_sigterm()
        try:
            handler = signal.getsignal(signal.SIGTERM)
            if handler is before:
                pytest.skip("signal handlers can only be installed from the main thread")
            assert callable(handler)
            with pytest.raises(run_module._TerminatedBySignal) as raised:
                handler(signal.SIGTERM, None)
            assert raised.value.code == 128 + signal.SIGTERM
        finally:
            restore()
        assert signal.getsignal(signal.SIGTERM) in (before, signal.SIG_DFL)


class TestReportingNeverMasksTheExit:
    @pytest.mark.parametrize(
        ("break_step", "expected_code", "expected_output"),
        [
            pytest.param(
                {"scan": MagicMock(return_value={"result": "failed"})},
                1,
                "Data scanning failed",
                id="failed-step",
            ),
            # Exit code and output are whatever Typer does with a Ctrl-C.
            pytest.param(
                {"process": MagicMock(side_effect=KeyboardInterrupt)},
                None,
                None,
                id="ctrl-c",
            ),
        ],
    )
    def test_a_failing_report_leaves_the_exit_untouched(
        self, data_root, break_step, expected_code, expected_output
    ):
        harness = _Harness(data_root, remote_locations=[])
        for name, mock in break_step.items():
            setattr(harness, name, mock)
        finish = MagicMock(side_effect=RuntimeError("monitoring is down"))
        result = _invoke(harness, data_root, finish)

        if expected_code is None:
            expected_code = _plain_exit_code(KeyboardInterrupt())
        assert result.exit_code == expected_code
        if expected_output:
            assert expected_output in result.output
        assert "monitoring is down" not in result.output
