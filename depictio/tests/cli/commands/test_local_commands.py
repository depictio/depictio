"""`depictio local up/down/status`, with every process launch faked."""

import sys
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from depictio.cli.cli import local_stack
from depictio.cli.cli.commands import local as local_cmd
from depictio.cli.cli.local_stack import PROCESS_ORDER, LocalStackError, Paths

runner = CliRunner()


def _invoke(*args: str):
    result = runner.invoke(local_cmd.app, list(args))
    # Rich wraps at 80 columns under the runner: compare on normalised whitespace.
    return result, " ".join(result.output.split())


class _Proc:
    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        return None


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """`up` on a temporary home, with the services, checks and browser stubbed."""
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
    for var in ("SSH_CONNECTION", "SSH_TTY"):
        monkeypatch.delenv(var, raising=False)
    fake = MagicMock()
    fake.running_status.return_value = dict.fromkeys(PROCESS_ORDER, False)
    fake.stop_all.return_value = []
    fake.start_services.side_effect = lambda *a, **k: {
        name: _Proc(100_000 + i) for i, name in enumerate(PROCESS_ORDER)
    }
    fake.process_start_time.return_value = 123.0
    fake.viewer_built.return_value = True
    for name in (
        "check_platform_supported",
        "check_server_installed",
        "viewer_built",
        "ensure_binaries",
        "seed_screenshots",
        "running_status",
        "start_services",
        "process_start_time",
        "wait_for_api",
        "check_alive",
        "stop_all",
        "webbrowser",
    ):
        monkeypatch.setattr(local_cmd, name, getattr(fake, name))
    fake.paths = Paths(tmp_path / "local")
    return fake


def test_up_prints_where_things_are_and_what_to_do_next(stack):
    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    assert f"Depictio is ready: {local_stack.load_state(stack.paths)['url']}/dashboards" in out
    assert "Examples: iris, penguins" in out
    assert f"export DEPICTIO_CLI_CONFIG_PATH={stack.paths.cli_config}" in out
    assert "depictio local up --template <template> --data-root <dir>" in out
    assert "depictio local down" in out
    state = local_stack.load_state(stack.paths)
    assert state["start_times"] == dict.fromkeys(PROCESS_ORDER, 123.0)
    assert local_stack.load_ports(stack.paths) == state["ports"]
    stack.webbrowser.open.assert_not_called()


def test_up_rejects_unknown_examples_before_starting_anything(stack):
    result, out = _invoke("up", "--examples", "all", "--no-open")

    assert result.exit_code == 1
    assert "iris, penguins, iris,penguins or none" in out
    stack.start_services.assert_not_called()


def test_ctrl_c_during_startup_stops_what_was_started(stack):
    stack.wait_for_api.side_effect = KeyboardInterrupt

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 130
    assert "Interrupted" in out
    # Once to clear a previous run, once for the services this run started.
    assert stack.stop_all.call_count == 2


def test_a_failed_check_leaves_a_running_server_alone(stack):
    stack.check_server_installed.side_effect = LocalStackError("server not installed")

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 1
    assert "server not installed" in out
    stack.stop_all.assert_not_called()


def test_up_on_a_running_server_names_the_flags_it_ignores(stack):
    stack.running_status.return_value = dict.fromkeys(PROCESS_ORDER, True)
    stack.paths.ensure_dirs()
    local_stack.save_state(
        stack.paths,
        {"pids": {}, "ports": {"api": 18058}, "url": "http://127.0.0.1:18058", "home": "x"},
    )

    result, out = _invoke(
        "up", "--port", "18059", "--examples", "iris", "--screenshots", "--no-open"
    )

    assert result.exit_code == 0, out
    for flag in ("--port", "--examples", "--screenshots"):
        assert f"{flag} is ignored" in out
    stack.start_services.assert_not_called()

    result, out = _invoke("up", "--port", "18058", "--no-open")
    assert "is ignored" not in out


def test_ingestion_runs_the_cli_module_without_remote_overrides(stack, tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "remote-token")
    monkeypatch.setenv("DEPICTIO_CLI_API_BASE_URL", "https://depictio.example.org")
    call = MagicMock(return_value=0)
    monkeypatch.setattr(local_cmd.subprocess, "call", call)

    result, out = _invoke(
        "up", "--template", "nf-core/rnaseq/latest", "--data-root", str(tmp_path), "--no-open"
    )

    assert result.exit_code == 0, out
    cmd, env = call.call_args.args[0], call.call_args.kwargs["env"]
    assert cmd[:4] == [sys.executable, "-m", "depictio.cli", "run"]
    assert cmd[cmd.index("--CLI-config-path") + 1] == str(stack.paths.cli_config)
    assert not [k for k in env if k.startswith("DEPICTIO_CLI_")]


def test_open_over_ssh_prints_a_tunnel_instead(stack, monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 50000 10.0.0.2 22")

    result, out = _invoke("up")

    assert result.exit_code == 0, out
    port = local_stack.load_state(stack.paths)["ports"]["api"]
    assert f"ssh -L {port}:127.0.0.1:{port} <host>" in out
    stack.webbrowser.open.assert_not_called()


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("linux", {}, False),
        ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, True),
        ("linux", {"DISPLAY": ":0", "SSH_TTY": "/dev/pts/0"}, False),
        ("darwin", {}, True),
    ],
)
def test_has_display(monkeypatch, platform, env, expected):
    for var in ("DISPLAY", "WAYLAND_DISPLAY", "SSH_CONNECTION", "SSH_TTY"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(local_cmd.sys, "platform", platform)
    assert local_cmd._has_display() is expected


def test_down_says_when_nothing_is_running(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))

    result, out = _invoke("down")

    assert result.exit_code == 0
    assert "Depictio local is not running." in out


def test_status_reports_api_health(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
    ports = {"api": 18058, "mongo": 17018, "redis": 16379, "s3": 19000}
    local_stack.save_state(
        Paths(tmp_path),
        {"pids": {}, "ports": ports, "url": "http://127.0.0.1:18058", "home": str(tmp_path)},
    )
    monkeypatch.setattr(local_cmd, "running_status", lambda _: dict.fromkeys(PROCESS_ORDER, True))
    monkeypatch.setattr(local_cmd, "api_healthy", lambda port: port == 18058)

    result, out = _invoke("status")

    assert result.exit_code == 0, out
    assert "API at http://127.0.0.1:18058: reachable" in out
    assert "worker: running" in out
    assert "worker (port" not in out
