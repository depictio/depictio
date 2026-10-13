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
    # An installed wheel, so `up` never builds the viewer of the checkout running the tests.
    fake.viewer_workspace.return_value = None
    fake.viewer_outdated.return_value = None
    fake.api_responds.return_value = True
    fake.api_healthy.return_value = True
    # What the home holds: None for the examples this run seeds, all of them ready.
    fake.home_examples = None

    def examples_status(paths, state, names=None):
        names = local_stack.requested_examples(state) if names is None else names
        held = fake.home_examples
        if held is None:
            held = dict.fromkeys(local_stack.requested_examples(state), "ready")
        return {name: held[name] for name in names if name in held}

    monkeypatch.setattr(local_cmd, "examples_status", examples_status)
    # A ~/.depictio/CLI.yaml exists, so the hints name the local server: whatever the
    # machine running the tests has.
    monkeypatch.setattr(local_cmd, "local_is_default_server", lambda: False)
    # The checks `up` runs itself, then what start_stack calls.
    for name in (
        "check_platform_supported",
        "check_server_installed",
        "viewer_built",
        "viewer_workspace",
        "viewer_outdated",
        "build_viewer",
        "running_status",
        "stop_all",
        "webbrowser",
        "api_responds",
        "api_healthy",
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
    assert "Add data depictio ingest <results dir> --server local" in out
    assert "Use the CLI depictio <command> --server local" in out
    assert "Stop depictio local down" in out
    assert state.start_times == dict.fromkeys(PROCESS_ORDER, 123.0)
    assert state.screenshots is False
    # Started on an empty database, whose examples are now loaded.
    assert not state.first_run
    assert local_stack.load_ports(stack.paths) == state.ports
    stack.webbrowser.open.assert_not_called()
    assert stack.paths.marker.is_file()


def test_the_next_steps_leave_server_out_when_local_is_the_default(stack, monkeypatch):
    """Without a ~/.depictio/CLI.yaml, a command reaches the local server unprompted."""
    monkeypatch.setattr(local_cmd, "local_is_default_server", lambda: True)

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    assert "Add data depictio ingest <results dir> Use the CLI depictio <command> Stop" in out
    assert "--server local" not in out


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
            "depictio ingest 'my results' --server local --template nf-core/rnaseq/latest",
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
            "depictio ingest /data --server local --template t "
            "--project 'My run' --var SAMPLESHEET_FILE=s.csv --var 'LABEL=a b'",
        ),
        (
            ["--var", "X=1"],
            "depictio ingest <results dir> --server local --var X=1",
        ),
    ],
    ids=["template-and-data-root", "every-flag", "incomplete"],
)
def test_up_data_flags_exit_2_with_the_ingest_command(stack, args, command):
    result, out = _invoke("up", *args, "--no-open")

    assert result.exit_code == 2, out
    assert "depictio local up starts the server only: add data with depictio ingest" in out
    assert "Start the server depictio local up " in out
    assert f"Add the data {command}" in out
    # Before anything starts, or the local home is even created.
    stack.check_platform_supported.assert_not_called()
    stack.start_services.assert_not_called()
    assert not stack.paths.home.exists()


def test_up_data_flags_are_hidden_from_the_help():
    up = get_command(local_cmd.app).commands["up"]
    hidden = {param.opts[0] for param in up.params if getattr(param, "hidden", False)}
    assert hidden == {"--template", "--data-root", "--project-name", "--var"}


@pytest.mark.parametrize(
    ("args", "start"),
    [
        (
            ["--port", "18059", "--examples", "iris", "--screenshots", "--template", "t"],
            "depictio local up --examples iris --port 18059 --screenshots --no-open",
        ),
        # 1.12.0b1's `up --template` seeded no example.
        (["--template", "t", "--data-root", "/d"], "depictio local up --examples none --no-open"),
        (["--data-root", "/d"], "depictio local up --no-open Add the data"),
        (
            ["--data-root-allow", "/data", "--template", "t"],
            "depictio local up --examples none --data-root-allow /data --no-open",
        ),
    ],
    ids=["other-flags", "template-means-no-examples", "data-root-only", "data-root-allow"],
)
def test_the_start_command_keeps_the_other_up_flags(stack, args, start):
    result, out = _invoke("up", *args, "--no-open")

    assert result.exit_code == 2, out
    assert f"Start the server {start}" in out


@pytest.mark.parametrize(
    "args",
    [["--examples", "all"], ["--port", "0"], ["--port", "70000"], ["--port", "-5"]],
    ids=["examples", "port-0", "port-70000", "port-negative"],
)
def test_up_rejects_bad_values_as_usage_errors_before_starting_anything(stack, args):
    result, out = _invoke("up", *args, "--no-open")

    assert result.exit_code == 2, out
    assert ("iris, penguins, iris,penguins or none" in out) == (args[0] == "--examples")
    stack.start_services.assert_not_called()
    assert not stack.paths.home.exists()


def test_ctrl_c_during_startup_stops_what_was_started(stack):
    stack.wait_for_api.side_effect = KeyboardInterrupt

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 130
    assert "Interrupted: services started by this run are stopped" in out
    # Once to clear a previous run, once for the services this run started.
    assert stack.stop_all.call_count == 2


def test_ctrl_c_that_beat_the_cleanup_does_not_claim_the_services_stopped(stack, monkeypatch):
    # The interrupt reached `up` before start_stack could stop what it started.
    monkeypatch.setattr(local_cmd, "start_stack", MagicMock(side_effect=KeyboardInterrupt))
    stack.running_status.return_value = {name: name == "mongo" for name in PROCESS_ORDER}

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 130
    assert (
        "Interrupted: services started by this run may still be running "
        "(depictio local down stops them)"
    ) in out
    assert "are stopped" not in out


def test_up_on_an_unsupported_platform_creates_nothing(stack):
    stack.check_platform_supported.side_effect = LocalStackError(
        "depictio local is not supported on Windows. Use WSL2, or the Docker compose stack."
    )

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 1
    assert "Use WSL2" in out
    assert not stack.paths.home.exists()
    stack.start_services.assert_not_called()


def test_a_failed_check_leaves_a_running_server_alone(stack):
    stack.check_server_installed.side_effect = LocalStackError("server not installed")

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 1
    assert "server not installed" in out
    stack.stop_all.assert_not_called()


def test_up_on_a_running_server_names_the_flags_it_ignores(stack):
    stack.running_status.return_value = dict.fromkeys(PROCESS_ORDER, True)
    stack.paths.ensure_dirs()
    State(ports={"api": 18058}, home="x", screenshots=False).save(stack.paths)

    result, out = _invoke("up", "--port", "18059", "--screenshots", "--no-open")

    assert result.exit_code == 0, out
    assert "Depictio is already running at http://127.0.0.1:18058" in out
    for flag in ("--port", "--screenshots"):
        assert f"{flag} is ignored" in out
    stack.start_services.assert_not_called()

    # The values the server runs with.
    result, out = _invoke("up", "--port", "18058", "--no-screenshots", "--no-open")
    assert result.exit_code == 0, out
    assert "is ignored" not in out


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    home = tmp_path / "me"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home.resolve()


def _plain(output: str) -> str:
    """``output`` without the borders of Rich's error panel, whitespace normalised."""
    return " ".join("".join(c for c in output if c not in "│╭╮╰╯─").split())


def test_up_lets_the_web_ui_read_the_home_folder_and_each_allowed_one(stack, tmp_path, user_home):
    data = tmp_path / "data"
    data.mkdir()

    result, out = _invoke("up", "--data-root-allow", str(data), "--no-open")

    assert result.exit_code == 0, out
    roots = [str(user_home), str(data.resolve())]
    env = stack.start_services.call_args.args[3]
    assert env["DEPICTIO_LOCAL_DATA_ROOTS"] == ",".join(roots)
    assert env["DEPICTIO_LOCAL_HOME"] == str(stack.paths.home)
    assert State.load(stack.paths).data_roots == roots


@pytest.mark.parametrize(
    ("allowed", "reason"),
    [("relative", "is not an absolute path"), ("{tmp}/missing", "is not an existing folder")],
    ids=["relative", "missing"],
)
def test_up_refuses_a_data_root_before_creating_anything(
    stack, tmp_path, user_home, allowed, reason
):
    result, _ = _invoke("up", "--data-root-allow", allowed.format(tmp=tmp_path), "--no-open")

    assert result.exit_code == 2, result.output
    assert reason in _plain(result.output)
    stack.start_services.assert_not_called()
    assert not stack.paths.home.exists()


def test_up_refuses_a_data_root_inside_the_local_home(stack, user_home):
    stack.paths.ensure_dirs()

    result, _ = _invoke("up", "--data-root-allow", str(stack.paths.logs), "--no-open")

    assert result.exit_code == 2, result.output
    assert "is inside the local home" in _plain(result.output)
    stack.start_services.assert_not_called()


def test_up_on_a_running_server_says_other_data_roots_need_a_restart(stack, tmp_path, user_home):
    stack.running_status.return_value = dict.fromkeys(PROCESS_ORDER, True)
    stack.paths.ensure_dirs()
    State(ports={"api": 18058}, home="x", data_roots=[str(user_home)]).save(stack.paths)
    data = tmp_path / "data"
    data.mkdir()

    result, out = _invoke("up", "--data-root-allow", str(data), "--no-open")

    assert result.exit_code == 0, out
    assert "The running server lets the web UI read run folders under" in out
    assert "restart it to change that (depictio local down first)" in out
    stack.start_services.assert_not_called()
    # Not restarted, so what it was started with stays recorded.
    assert State.load(stack.paths).data_roots == [str(user_home)]

    # The folders it runs with.
    result, out = _invoke("up", "--no-open")
    assert result.exit_code == 0, out
    assert "lets the web UI read" not in out

    # Started before they were recorded: nothing to compare with.
    State(ports={"api": 18058}, home="x").save(stack.paths)
    result, out = _invoke("up", "--data-root-allow", str(data), "--no-open")
    assert result.exit_code == 0, out
    assert "lets the web UI read" not in out


def test_up_help_says_what_data_root_allow_does():
    up = get_command(local_cmd.app).commands["up"]
    option = next(param for param in up.params if param.opts[0] == "--data-root-allow")
    assert option.help == (
        "Also let the web UI read run folders under PATH. Your home folder is always allowed."
    )
    assert option.multiple and not option.hidden


def test_up_does_not_reuse_a_server_whose_api_hangs(stack):
    stack.running_status.return_value = dict.fromkeys(PROCESS_ORDER, True)
    stack.api_responds.return_value = False
    stack.paths.ensure_dirs()
    State(ports={"api": 18058}, home="x", examples="iris").save(stack.paths)

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 1, out
    assert "Depictio is running but its API at http://127.0.0.1:18058 is not responding" in out
    assert "depictio local down, then depictio local up" in out
    assert "did not finish loading" not in out and "wipe" not in out
    stack.start_services.assert_not_called()
    stack.stop_all.assert_not_called()


def test_up_says_which_process_died_before_restarting(stack):
    stack.running_status.return_value = {name: name != "worker" for name in PROCESS_ORDER}
    stack.paths.ensure_dirs()
    State(ports={"api": 18058}, home="x", pids={"worker": 1}).save(stack.paths)

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    assert "worker is not running: restarting the server" in out
    stack.start_services.assert_called_once()


def test_up_on_a_running_server_writes_a_deleted_cli_config_again(stack, monkeypatch):
    stack.running_status.return_value = dict.fromkeys(PROCESS_ORDER, True)
    stack.paths.ensure_dirs()
    local_stack.load_secrets(stack.paths)
    ports = {"api": 18058, "mongo": 1, "redis": 2, "s3": 3}
    State(ports=ports, home="x").save(stack.paths)
    rebuild, sync = MagicMock(), MagicMock()
    monkeypatch.setattr(local_cmd, "rebuild_cli_config", rebuild)
    monkeypatch.setattr(local_cmd, "sync_cli_config", sync)

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    assert rebuild.call_args.args[:2] == (stack.paths, 18058)
    sync.assert_called_once_with(stack.paths, ports)
    assert f"Wrote {stack.paths.cli_config} again" in out


@pytest.mark.parametrize("given", [True, False], ids=["--examples", "default"])
def test_examples_missing_from_an_existing_home_are_not_waited_for(stack, monkeypatch, given):
    stack.home_examples = {"iris": "absent", "penguins": "ready"}
    wait = MagicMock()
    monkeypatch.setattr(local_cmd, "wait_for_examples", wait)

    result, out = _invoke("up", *(["--examples", "iris"] if given else []), "--no-open")

    assert result.exit_code == 0, out
    wait.assert_not_called()
    # What the home holds, whatever this run asked for.
    assert "Examples penguins" in out
    warning = "This local home has no iris example: examples are added on its first run only"
    assert (warning in out) == given


def test_examples_list_only_what_the_home_has_ready(stack, monkeypatch):
    stack.home_examples = {"iris": "ready", "penguins": "ready"}

    result, out = _invoke("up", "--examples", "iris", "--no-open")

    assert result.exit_code == 0, out
    assert "Examples iris, penguins" in out
    # Asked for something the home has: nothing to warn about.
    assert "first run only" not in out


def test_an_api_that_stops_answering_is_not_blamed_on_the_examples(stack, monkeypatch):
    stack.home_examples = {"iris": "unreachable", "penguins": "ready"}
    monkeypatch.setattr(
        local_cmd, "wait_for_examples", lambda paths, state: {"iris": "unreachable"}
    )

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    assert "did not answer while checking the iris example" in out
    assert "did not finish loading" not in out and "wipe" not in out
    assert "Examples penguins" in out


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


@pytest.mark.parametrize("healthy", [True, False], ids=["api-answers", "api-down"])
def test_open_with_a_stopped_worker_says_the_server_is_partly_running(stack, monkeypatch, healthy):
    monkeypatch.setattr(local_cmd, "_has_display", lambda: True)
    _save_running_state(stack)
    stack.running_status.return_value = {name: name != "worker" for name in PROCESS_ORDER}
    stack.api_healthy.return_value = healthy

    result, out = _invoke("open")

    assert result.exit_code == (0 if healthy else 1), out
    assert "partly running (worker stopped): run depictio local up" in out
    assert stack.webbrowser.open.called == healthy


def test_open_with_a_hung_api_says_so(stack, monkeypatch):
    monkeypatch.setattr(local_cmd, "_has_display", lambda: True)
    _save_running_state(stack)
    stack.api_healthy.return_value = False

    result, out = _invoke("open")

    assert result.exit_code == 1
    assert "The Depictio API at http://127.0.0.1:18058 is not responding" in out
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


@pytest.mark.parametrize(
    ("dead", "healthy", "code"),
    [(None, True, 0), ("worker", True, 1), (None, False, 1)],
    ids=["all-up", "worker-stopped", "api-unreachable"],
)
def test_status_reports_api_health_and_exits_1_unless_all_is_well(
    tmp_path, monkeypatch, dead, healthy, code
):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
    ports = {"api": 18058, "mongo": 17018, "redis": 16379, "s3": 19000}
    State(ports=ports, home=str(tmp_path)).save(Paths(tmp_path))
    running = {name: name != dead for name in PROCESS_ORDER}
    monkeypatch.setattr(local_cmd, "running_status", lambda *_: running)
    monkeypatch.setattr(local_cmd, "api_healthy", lambda port: healthy and port == 18058)

    result, out = _invoke("status")

    assert result.exit_code == code, out
    reachable = "is reachable" if healthy else "is not reachable"
    assert f"API at http://127.0.0.1:18058 {reachable}" in out
    assert "mongo running port 17018" in out
    # The worker listens on no port.
    assert f"worker {'stopped' if dead else 'running'}" in out
    assert "worker running port" not in out


def test_status_of_a_server_never_started_exits_1(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))

    result, out = _invoke("status")

    assert result.exit_code == 1
    assert "Depictio local is not running" in out


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


def test_the_exported_path_is_printed_as_typed(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
    monkeypatch.setattr(local_cmd, "export_compose", MagicMock())
    out_dir = tmp_path / "stack[red]v2[/x]"

    result, out = _invoke("export", "--out", str(out_dir))

    assert result.exit_code == 0, out
    assert f"Exported to {out_dir}" in out
    assert "docker compose up -d" in out


def test_the_export_entry_of_the_help_holds_on_one_line():
    export = get_command(local_cmd.app).commands["export"]
    first_paragraph = export.help.split("\n\n")[0]
    assert "\n" not in first_paragraph
    assert "Formerly `export-compose`" in " ".join(export.help.split())


# --- The local home ------------------------------------------------------------


def test_wipe_on_a_home_never_used_has_nothing_to_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "never-used"))

    result, out = _invoke("wipe", "--yes")

    assert result.exit_code == 0, out
    assert f"Nothing to delete under {tmp_path / 'never-used'}" in out
    assert "Local data deleted" not in out


def test_wipe_refuses_a_folder_that_is_not_a_local_home(tmp_path, monkeypatch):
    project = tmp_path / "project"
    for sub in ("logs", "cache", "src"):
        (project / sub).mkdir(parents=True)
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(project))

    result, out = _invoke("wipe", "--yes")

    assert result.exit_code == 1
    assert "is not a Depictio local home" in out and "nothing deleted" in out
    assert all((project / sub).is_dir() for sub in ("logs", "cache", "src"))


def test_an_empty_depictio_local_home_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", "")

    for command in (["wipe", "--yes"], ["up", "--no-open"], ["down"], ["status"]):
        result, out = _invoke(*command)
        assert result.exit_code == 1, (command, out)
        assert "DEPICTIO_LOCAL_HOME is set but empty" in out
    assert (tmp_path / "logs").is_dir()


@pytest.mark.parametrize("marker", [True, False], ids=["marker", "made-before-the-marker"])
def test_wipe_deletes_a_local_home(tmp_path, monkeypatch, marker):
    paths = Paths(tmp_path / "local")
    local_stack.claim_home(paths)
    paths.ensure_dirs()
    local_stack.save_ports(paths, dict(local_stack.DEFAULT_PORTS))
    if not marker:
        paths.marker.unlink()
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(paths.home))

    result, out = _invoke("wipe", "--yes")

    assert result.exit_code == 0, out
    assert "Local data deleted" in out
    assert not paths.has_data()


def test_declining_the_wipe_prompt_says_so(tmp_path, monkeypatch):
    paths = Paths(tmp_path / "local")
    local_stack.claim_home(paths)
    paths.ensure_dirs()
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(paths.home))

    result = runner.invoke(local_cmd.app, ["wipe"], input="n\n")

    assert result.exit_code == 0
    assert result.output.endswith("Cancelled.\n")
    assert paths.has_data()


def test_up_refuses_a_folder_that_is_not_a_local_home(stack, monkeypatch):
    project = stack.paths.home
    (project / "src").mkdir(parents=True)
    project.chmod(0o755)

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 1
    assert "is not empty and is not a Depictio local home" in out
    stack.start_services.assert_not_called()
    assert project.stat().st_mode & 0o777 == 0o755
    assert not (project / "mongo").exists() and not stack.paths.marker.exists()


def test_up_in_an_unwritable_folder_names_depictio_local_home(stack, tmp_path, monkeypatch):
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o555)
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(parent / "local"))
    try:
        result, out = _invoke("up", "--no-open")
    finally:
        parent.chmod(0o755)

    assert result.exit_code == 1, out
    assert "Cannot set up the local home" in out and "DEPICTIO_LOCAL_HOME" in out
    assert "Traceback" not in out


def test_a_relative_depictio_local_home_is_made_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", "relhome")
    assert local_stack.local_home() == (tmp_path / "relhome").resolve()


def test_a_second_up_on_a_home_being_started_fails_fast(stack):
    local_stack.claim_home(stack.paths)
    held = local_stack.lock_for_startup(stack.paths)
    try:
        result, out = _invoke("up", "--no-open")
    finally:
        held.close()

    assert result.exit_code == 1
    assert "Another `depictio local up` is already starting this home" in out
    stack.start_services.assert_not_called()
    # Released: the next one goes ahead.
    result, out = _invoke("up", "--no-open")
    assert result.exit_code == 0, out


@pytest.mark.parametrize("holder", ["wipe", "export"])
def test_up_while_wipe_or_export_holds_the_home_names_it(stack, holder):
    local_stack.claim_home(stack.paths)
    held = local_stack.lock_for_startup(stack.paths, holder)
    try:
        result, out = _invoke("up", "--no-open")
    finally:
        held.close()

    assert result.exit_code == 1
    assert f"`depictio local {holder}` is using this home" in out
    stack.start_services.assert_not_called()


def test_wipe_while_up_is_starting_fails_fast_and_deletes_nothing(tmp_path, monkeypatch):
    paths = Paths(tmp_path / "local")
    local_stack.claim_home(paths)
    paths.ensure_dirs()
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(paths.home))
    stop_all = MagicMock()
    monkeypatch.setattr(local_cmd, "stop_all", stop_all)
    held = local_stack.lock_for_startup(paths)
    try:
        result, out = _invoke("wipe", "--yes")
    finally:
        held.close()

    assert result.exit_code == 1
    assert (
        f"A `depictio local up` is starting this home ({paths.home}): wait for it, or stop "
        "it, then try again"
    ) in out
    assert all((paths.home / sub).is_dir() for sub in local_stack.DATA_DIRS)
    stop_all.assert_not_called()
    # Released: the wipe goes ahead.
    result, out = _invoke("wipe", "--yes")
    assert result.exit_code == 0, out
    assert not paths.has_data()


# --- Unreadable files ------------------------------------------------------------


@pytest.mark.parametrize("command", ["status", "open"])
def test_an_unreadable_state_is_named_with_the_way_out(tmp_path, monkeypatch, command):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
    Paths(tmp_path).state.write_text("{garbage")

    result, out = _invoke(command)

    assert result.exit_code == 1
    assert f"{tmp_path / 'state.json'} is unreadable" in out
    assert "depictio local down stops the server without it" in out
    assert "Traceback" not in out


def test_down_with_an_unreadable_state_finds_the_processes(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
    Paths(tmp_path).state.write_text("")
    monkeypatch.setattr(local_stack, "find_server_processes", lambda paths: {"mongo": 4242})
    terminated = []
    monkeypatch.setattr(local_stack, "terminate_group", lambda pid, *a, **k: terminated.append(pid))

    result, out = _invoke("down")

    assert result.exit_code == 0, out
    assert "state.json is unreadable: looking for the server's processes instead" in out
    assert "Stopping mongo (pid 4242)" in out
    assert terminated == [4242]
    assert not Paths(tmp_path).state.exists()


def test_up_with_an_unreadable_state_starts_again(stack):
    stack.paths.ensure_dirs()
    stack.paths.state.write_text("[1, 2]")

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    stack.start_services.assert_called_once()


# The viewer bundle: built by `up` from a source checkout, carried by a wheel.


@pytest.fixture
def checkout(stack, tmp_path):
    """`up` run from a source checkout whose viewer bundle is out of date."""
    stack.viewer_workspace.return_value = tmp_path / "repo"
    stack.viewer_outdated.return_value = "depictio/viewer/src/main.tsx changed since the last build"
    return stack


def test_up_builds_an_outdated_viewer_before_starting(checkout):
    order = []
    checkout.build_viewer.side_effect = lambda *a: order.append("build")
    checkout.start_services.side_effect = lambda *a, **k: (
        order.append("start") or {name: _Proc(100_000 + i) for i, name in enumerate(PROCESS_ORDER)}
    )

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    checkout.build_viewer.assert_called_once_with(
        checkout.viewer_workspace.return_value, checkout.paths.logs / "viewer-build.log"
    )
    # The API reads the bundle when it starts: built first.
    assert order == ["build", "start"]
    assert "Building the viewer bundle (depictio/viewer/src/main.tsx changed" in out
    assert "Built the viewer bundle" in out


def test_up_leaves_an_up_to_date_viewer_alone(checkout):
    checkout.viewer_outdated.return_value = None

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    checkout.build_viewer.assert_not_called()
    assert "viewer" not in out.lower()


@pytest.mark.parametrize(
    ("built", "left"),
    [(True, "with the previous bundle"), (False, "without a viewer, so dashboards will not")],
)
def test_a_failed_viewer_build_does_not_stop_the_start(checkout, built, left):
    checkout.build_viewer.side_effect = LocalStackError("pnpm run build failed (exit 2, see x)")
    checkout.viewer_built.return_value = built

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    assert f"pnpm run build failed (exit 2, see x). The server starts {left}" in out
    assert "Depictio is ready" in out


def test_up_does_not_rebuild_the_viewer_under_a_running_server(checkout):
    _invoke("up", "--no-open")
    checkout.build_viewer.reset_mock()
    checkout.running_status.return_value = dict.fromkeys(PROCESS_ORDER, True)

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    checkout.build_viewer.assert_not_called()
    assert (
        "The viewer bundle is out of date (depictio/viewer/src/main.tsx changed since the last "
        "build): depictio local down, then depictio local up, rebuilds it"
    ) in out


def test_a_wheel_without_the_viewer_bundle_says_so(stack):
    stack.viewer_built.return_value = False

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 0, out
    stack.build_viewer.assert_not_called()
    assert "This installation has no viewer bundle, so dashboards will not render" in out
