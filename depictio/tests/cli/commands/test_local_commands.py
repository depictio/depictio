"""`depictio local up/down/status/export-compose`, with every process launch faked."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
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
    assert "Examples: iris, penguins" in out
    assert f"export DEPICTIO_CLI_CONFIG_PATH={stack.paths.cli_config}" in out
    assert "depictio local up --data-root <dir> [--template <template>]" in out
    assert "depictio local down" in out
    assert state.start_times == dict.fromkeys(PROCESS_ORDER, 123.0)
    assert state.first_run
    assert local_stack.load_ports(stack.paths) == state.ports
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
    assert "Examples: iris" not in out
    warning = "This local home has no iris example: examples are added on its first run only"
    assert (warning in out) == given


def test_ingestion_runs_the_cli_module_without_remote_overrides(stack, tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "remote-token")
    monkeypatch.setenv("DEPICTIO_CLI_API_BASE_URL", "https://depictio.example.org")
    call = MagicMock(return_value=0)
    monkeypatch.setattr(local_stack.subprocess, "call", call)

    result, out = _invoke(
        "up", "--template", "nf-core/rnaseq/latest", "--data-root", str(tmp_path), "--no-open"
    )

    assert result.exit_code == 0, out
    cmd, env = call.call_args.args[0], call.call_args.kwargs["env"]
    assert cmd[:4] == [sys.executable, "-m", "depictio.cli", "run"]
    assert cmd[cmd.index("--CLI-config-path") + 1] == str(stack.paths.cli_config)
    assert not [k for k in env if k.startswith("DEPICTIO_CLI_")]


def _fake_run(monkeypatch, code: int, result: dict | None):
    """Stand in for the `depictio run` child: exit ``code`` after writing ``result``."""

    def call(cmd, env):
        if result is not None:
            Path(cmd[cmd.index("--result-json") + 1]).write_text(json.dumps(result))
        return code

    fake = MagicMock(side_effect=call)
    monkeypatch.setattr(local_stack.subprocess, "call", fake)
    return fake


_INGESTED = {
    "status": "success",
    "project": {"name": "nf-core/rnaseq/3.26.0 - results", "id": "p1", "url": None},
    "dashboards": [{"title": "RNA-seq", "id": "d1", "url": None}],
    "template_id": "nf-core/rnaseq/3.26.0",
}


def test_data_root_alone_lets_run_pick_the_template_and_opens_the_dashboard(
    stack, tmp_path, monkeypatch
):
    call = _fake_run(monkeypatch, 0, _INGESTED)
    monkeypatch.setattr(local_cmd, "_has_display", lambda: True)

    result, out = _invoke("up", "--data-root", str(tmp_path))

    assert result.exit_code == 0, out
    cmd = call.call_args.args[0]
    assert "--template" not in cmd
    assert "--update-config" not in cmd
    url = State.load(stack.paths).url
    assert f"Depictio is ready: {url}/dashboard/d1" in out
    assert f"Ingested: {tmp_path.resolve()} (nf-core/rnaseq/3.26.0)" in out
    stack.webbrowser.open.assert_called_once_with(f"{url}/dashboard/d1")
    # Own data to look at: the examples are not seeded next to it.
    assert State.load(stack.paths).examples == "none"


def test_a_template_path_reaches_run_absolute(stack, tmp_path, monkeypatch):
    call = _fake_run(monkeypatch, 0, _INGESTED)
    template = tmp_path / "template.yaml"
    template.write_text("template: {}\n")
    monkeypatch.chdir(tmp_path)

    result, out = _invoke(
        "up", "--template", "template.yaml", "--data-root", str(tmp_path), "--no-open"
    )

    assert result.exit_code == 0, out
    cmd = call.call_args.args[0]
    assert cmd[cmd.index("--template") + 1] == str(template.resolve())


def _exists(locations: list[str]) -> dict:
    return {
        **_INGESTED,
        "status": "exists",
        "project": {**_INGESTED["project"], "locations": locations},
    }


def test_ingesting_the_same_directory_again_shows_the_existing_project(
    stack, tmp_path, monkeypatch
):
    _fake_run(monkeypatch, 2, _exists([str(tmp_path)]))

    result, out = _invoke("up", "--data-root", str(tmp_path), "--no-open")

    assert result.exit_code == 0, out
    assert "is already ingested, as nf-core/rnaseq/3.26.0 - results: showing it" in out
    assert "--refresh" in out
    assert f"Depictio is ready: {State.load(stack.paths).url}/dashboard/d1" in out


def test_another_run_under_a_taken_project_name_is_not_called_ingested(
    stack, tmp_path, monkeypatch
):
    _fake_run(monkeypatch, 2, _exists(["/data/an_earlier_run"]))

    result, out = _invoke("up", "--data-root", str(tmp_path), "--no-open")

    assert result.exit_code == 1
    assert "already exists, for another directory: pass --project-name" in out
    assert "is already ingested" not in out


def test_refresh_reingests_and_resets_the_dashboards(stack, tmp_path, monkeypatch):
    call = _fake_run(monkeypatch, 0, _INGESTED)

    result, out = _invoke("up", "--data-root", str(tmp_path), "--refresh", "--no-open")

    assert result.exit_code == 0, out
    cmd = call.call_args.args[0]
    assert "--update-config" in cmd and "--overwrite" in cmd


def test_a_failed_ingestion_still_fails(stack, tmp_path, monkeypatch):
    # Exit 2 without an "exists" result is not the already-ingested case.
    _fake_run(monkeypatch, 2, None)

    result, out = _invoke("up", "--data-root", str(tmp_path), "--no-open")

    assert result.exit_code == 1
    assert "Ingestion failed" in out


def test_without_dashboards_the_project_page_opens(stack, tmp_path, monkeypatch):
    _fake_run(monkeypatch, 0, {**_INGESTED, "dashboards": []})

    result, out = _invoke("up", "--data-root", str(tmp_path), "--no-open")

    assert result.exit_code == 0, out
    assert f"Depictio is ready: {State.load(stack.paths).url}/projects/p1" in out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--template", "nf-core/rnaseq/latest"], "--template needs --data-root"),
        (["--refresh"], "--refresh needs --data-root"),
    ],
)
def test_flags_that_need_a_data_root(stack, args, message):
    result, out = _invoke("up", *args, "--no-open")

    assert result.exit_code == 1
    assert message in out
    stack.start_services.assert_not_called()


def test_compose_flags_reach_run(stack, tmp_path, monkeypatch):
    call = _fake_run(monkeypatch, 0, _INGESTED)

    result, out = _invoke(
        "up",
        "--data-root",
        str(tmp_path),
        "--compose",
        "--include-unknown",
        "--include",
        "stats/*.tsv",
        "--no-open",
    )

    assert result.exit_code == 0, out
    cmd = call.call_args.args[0]
    assert "--compose" in cmd and "--include-unknown" in cmd
    assert cmd[cmd.index("--include") + 1] == "stats/*.tsv"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--compose"], "need --data-root"),
        (["--include", "x.tsv"], "need --data-root"),
        (["--template", "t.yaml", "--data-root", ".", "--compose"], "drop --template"),
    ],
)
def test_compose_flags_that_cannot_apply(stack, args, message):
    result, out = _invoke("up", *args, "--no-open")

    assert result.exit_code == 1
    assert message in out
    stack.start_services.assert_not_called()


def test_open_over_ssh_prints_a_tunnel_instead(stack, monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 50000 10.0.0.2 22")

    result, out = _invoke("up")

    assert result.exit_code == 0, out
    port = State.load(stack.paths).ports["api"]
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
    State(ports=ports, home=str(tmp_path)).save(Paths(tmp_path))
    monkeypatch.setattr(local_cmd, "running_status", lambda _: dict.fromkeys(PROCESS_ORDER, True))
    monkeypatch.setattr(local_cmd, "api_healthy", lambda port: port == 18058)

    result, out = _invoke("status")

    assert result.exit_code == 0, out
    assert "API at http://127.0.0.1:18058: reachable" in out
    assert "worker: running" in out
    assert "worker (port" not in out


def test_a_failure_after_the_checks_stops_what_up_started(stack):
    stack.check_alive.side_effect = LocalStackError("The worker process exited during startup.")

    result, out = _invoke("up", "--no-open")

    assert result.exit_code == 1
    assert "The worker process exited during startup." in out
    # Once to clear a previous run, once for the services this run started.
    assert stack.stop_all.call_count == 2


def test_export_compose_prints_the_command_to_run_next(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
    export = MagicMock()
    monkeypatch.setattr(local_cmd, "export_compose", export)
    out_dir = tmp_path / "my export"

    result, out = _invoke("export-compose", "--out", str(out_dir))

    assert result.exit_code == 0, out
    assert export.call_args.args[1] == out_dir
    assert f"cd '{out_dir}' && docker compose up -d" in out
