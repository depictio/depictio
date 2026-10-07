"""`depictio local up/open/down/status/export`, with every process launch faked."""

import logging
from unittest.mock import MagicMock

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from depictio.cli.cli import local_stack
from depictio.cli.cli.commands import local as local_cmd
from depictio.cli.cli.local_stack import PROCESS_ORDER, LocalStackError, Paths, State

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
    # The checks `up` runs itself, then what start_stack calls.
    for name in (
        "check_platform_supported",
        "check_server_installed",
        "viewer_built",
        "running_status",
        "stop_all",
        "webbrowser",
    ):
        monkeypatch.setattr(local_cmd, name, getattr(fake, name))
    for name in (
        "ensure_binaries",
        "seed_screenshots",
        "start_services",
        "process_start_time",
        "wait_for_api",
        "check_alive",
        "stop_all",
    ):
        monkeypatch.setattr(local_stack, name, getattr(fake, name))
    fake.paths = Paths(tmp_path / "local")
    return fake


def test_up_prints_where_things_are_and_what_to_do_next(stack):
    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    state = State.load(stack.paths)
    assert f"Depictio is ready: {state.url}/dashboards" in out
    assert "Examples iris, penguins" in out
    assert "Add data depictio ingest --server local --template <template> --data-root <dir>" in out
    assert "Use the CLI depictio <command> --server local" in out
    assert "Stop depictio local down" in out
    assert state.start_times == dict.fromkeys(PROCESS_ORDER, 123.0)
    assert state.first_run
    assert local_stack.load_ports(stack.paths) == state.ports
    stack.webbrowser.open.assert_not_called()


@pytest.mark.parametrize(
    ("args", "seed"),
    [
        ([], "iris,penguins"),
        (["--examples", "penguins"], "penguins"),
        (["--examples", "none"], "none"),
    ],
    ids=["default", "penguins", "none"],
)
def test_up_seeds_both_examples_unless_told_otherwise(stack, args, seed):
    result, out = _invoke("up", *args, "--no-open")

    assert result.exit_code == 0, out
    assert State.load(stack.paths).examples == seed
    env = stack.start_services.call_args.args[3]
    assert env.get("DEPICTIO_SEED_PROJECTS") == (None if seed == "none" else seed)
    assert ("Examples" in out) == (seed != "none")


@pytest.mark.parametrize(
    ("args", "command"),
    [
        (
            ["--template", "nf-core/rnaseq/latest", "--data-root", "my results"],
            "depictio ingest --server local --template nf-core/rnaseq/latest "
            "--data-root 'my results'",
        ),
        (
            # Every flag, with --examples, which `up` still takes, ignored.
            [
                "--examples",
                "iris",
                "--template",
                "t",
                "--data-root",
                "/data",
                "--project-name",
                "My run",
                "--var",
                "SAMPLESHEET_FILE=s.csv",
                "--var",
                "LABEL=a b",
            ],
            "depictio ingest --server local --template t --data-root /data "
            "--project-name 'My run' --var SAMPLESHEET_FILE=s.csv --var 'LABEL=a b'",
        ),
        (
            ["--var", "X=1"],
            "depictio ingest --server local --template <template> --data-root <dir> --var X=1",
        ),
    ],
    ids=["template-and-data-root", "every-flag", "incomplete"],
)
def test_up_data_flags_exit_2_with_the_ingest_command(stack, args, command):
    result, out = _invoke("up", *args, "--no-open")

    assert result.exit_code == 2, out
    assert "depictio local up starts the server only: add data with depictio ingest" in out
    assert "Start the server depictio local up" in out
    assert f"Add the data {command}" in out
    # Before anything starts, or the local home is even created.
    stack.check_platform_supported.assert_not_called()
    stack.start_services.assert_not_called()
    assert not stack.paths.home.exists()


def test_up_data_flags_are_hidden_from_the_help():
    up = get_command(local_cmd.app).commands["up"]
    hidden = {param.opts[0] for param in up.params if getattr(param, "hidden", False)}
    assert hidden == {"--template", "--data-root", "--project-name", "--var"}


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
    State(ports={"api": 18058}, home="x").save(stack.paths)

    result, out = _invoke(
        "up", "--port", "18059", "--examples", "iris", "--screenshots", "--no-open"
    )

    assert result.exit_code == 0, out
    for flag in ("--port", "--examples", "--screenshots"):
        assert f"{flag} is ignored" in out
    stack.start_services.assert_not_called()

    result, out = _invoke("up", "--port", "18058", "--no-open")
    assert "is ignored" not in out


@pytest.mark.parametrize("given", [True, False], ids=["--examples", "default"])
def test_examples_missing_from_an_existing_home_are_not_waited_for(stack, monkeypatch, given):
    monkeypatch.setattr(local_cmd, "examples_status", lambda paths, state: {"iris": "absent"})
    wait = MagicMock()
    monkeypatch.setattr(local_cmd, "wait_for_examples", wait)

    result, out = _invoke("up", *(["--examples", "iris"] if given else []), "--no-open")

    assert result.exit_code == 0, out
    wait.assert_not_called()
    assert "Examples iris" not in out
    warning = "This local home has no iris example: examples are added on its first run only"
    assert (warning in out) == given


def test_open_over_ssh_prints_a_tunnel_instead(stack, monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 50000 10.0.0.2 22")

    result, out = _invoke("up")

    assert result.exit_code == 0, out
    port = State.load(stack.paths).ports["api"]
    assert f"ssh -L {port}:127.0.0.1:{port} <host>" in out
    stack.webbrowser.open.assert_not_called()


def _save_running_state(stack, running: bool = True) -> State:
    stack.paths.ensure_dirs()
    state = State(ports={"api": 18058}, home=str(stack.paths.home))
    state.save(stack.paths)
    stack.running_status.return_value = dict.fromkeys(PROCESS_ORDER, running)
    return state


def test_open_opens_the_dashboards_of_the_running_server(stack, monkeypatch):
    monkeypatch.setattr(local_cmd, "_has_display", lambda: True)
    _save_running_state(stack)

    result, out = _invoke("open")

    assert result.exit_code == 0, out
    assert "Opening http://127.0.0.1:18058/dashboards" in out
    stack.webbrowser.open.assert_called_once_with("http://127.0.0.1:18058/dashboards")


def test_open_without_a_display_prints_the_url(stack, monkeypatch):
    monkeypatch.setattr(local_cmd, "_has_display", lambda: False)
    _save_running_state(stack)

    result, out = _invoke("open")

    assert result.exit_code == 0, out
    assert "ssh -L 18058:127.0.0.1:18058 <host>, then open http://127.0.0.1:18058/dashboards" in out
    stack.webbrowser.open.assert_not_called()


@pytest.mark.parametrize("recorded", [False, True], ids=["never-started", "stopped"])
def test_open_without_a_running_server_says_how_to_start_one(stack, monkeypatch, recorded):
    monkeypatch.setattr(local_cmd, "_has_display", lambda: True)
    if recorded:
        _save_running_state(stack, running=False)

    result, out = _invoke("open")

    assert result.exit_code == 1
    assert "Depictio local is not running. Start it with: depictio local up" in out
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
    State(ports=ports, home=str(tmp_path)).save(Paths(tmp_path))
    monkeypatch.setattr(local_cmd, "running_status", lambda *_: dict.fromkeys(PROCESS_ORDER, True))
    monkeypatch.setattr(local_cmd, "api_healthy", lambda port: port == 18058)

    result, out = _invoke("status")

    assert result.exit_code == 0, out
    assert "API at http://127.0.0.1:18058: reachable" in out
    assert "mongo running port 17018" in out
    # The worker listens on no port.
    assert "worker running" in out
    assert "worker running port" not in out


def test_a_failure_after_the_checks_stops_what_up_started(stack):
    stack.check_alive.side_effect = LocalStackError("The worker process exited during startup.")

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 1
    assert "The worker process exited during startup." in out
    # Once to clear a previous run, once for the services this run started.
    assert stack.stop_all.call_count == 2


# export-compose: the 1.12.0b1 name, still accepted.
@pytest.mark.parametrize("command", ["export", "export-compose"])
def test_export_prints_the_command_to_run_next(tmp_path, monkeypatch, command):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
    export = MagicMock()
    monkeypatch.setattr(local_cmd, "export_compose", export)
    out_dir = tmp_path / "my export"

    result, out = _invoke(command, "--out", str(out_dir))

    assert result.exit_code == 0, out
    assert export.call_args.args[1] == out_dir
    assert f"cd '{out_dir}' && docker compose up -d" in out


def test_the_help_lists_open_and_export_but_not_the_old_name():
    group = get_command(local_cmd.app)
    listed = [name for name in group.list_commands(None) if not group.commands[name].hidden]

    assert listed == ["up", "open", "down", "status", "wipe", "export"]
    assert group.commands["export-compose"].hidden


@pytest.mark.parametrize(
    ("tty", "level", "expected"),
    [
        (True, logging.ERROR, True),
        (False, logging.ERROR, False),
        (True, logging.INFO, False),
        (True, logging.DEBUG, False),
    ],
    ids=["terminal", "piped", "-v", "-vv"],
)
def test_spinners_draw_only_on_a_terminal_without_logs(monkeypatch, tty, level, expected):
    """-v/-vv logs go to stderr through a plain handler and would tear a spinner."""
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(local_cmd.sys.stdout, "isatty", lambda: tty)
    monkeypatch.setattr(logging.getLogger("depictio-cli"), "level", level)

    assert local_cmd._can_animate() is expected


def test_a_wait_that_cannot_spin_says_what_it_waits_for(capsys):
    with local_cmd._spinner("Loading the examples", announce=True):
        pass
    with local_cmd._spinner("Starting the local server"):
        pass

    out = capsys.readouterr().out
    assert "Loading the examples" in out
    assert "Starting the local server" not in out
