import http.server
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import types
from unittest.mock import MagicMock

import pytest
import yaml

from depictio.cli.cli import local_stack
from depictio.cli.cli.local_stack import (
    DATA_DIRS,
    LocalStackError,
    Paths,
    State,
    parse_examples,
    pick_ports,
    port_is_free,
    server_env,
)

SECRETS = {"s3_password": "x", "admin_password": "y"}


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path)
    p.ensure_dirs()
    return p


def _free_ports(n: int) -> list[int]:
    socks = [socket.socket(socket.AF_INET, socket.SOCK_STREAM) for _ in range(n)]
    for sock in socks:
        sock.bind(("127.0.0.1", 0))
    ports = [sock.getsockname()[1] for sock in socks]
    for sock in socks:
        sock.close()
    return ports


def test_server_env_points_every_service_at_localhost(paths):
    ports = {"api": 18058, "mongo": 17018, "redis": 16379, "s3": 19000}
    env = server_env(
        paths, ports, {"s3_password": "m" * 24, "admin_password": "a" * 24}, "iris", False
    )

    for key in (
        "DEPICTIO_MONGODB_SERVICE_NAME",
        "DEPICTIO_S3_SERVICE_NAME",
        "DEPICTIO_CACHE_REDIS_HOST",
        "DEPICTIO_CELERY_BROKER_HOST",
        "DEPICTIO_FASTAPI_SERVICE_NAME",
        "DEPICTIO_VIEWER_SERVICE_NAME",
    ):
        assert env[key] == "127.0.0.1"
    assert env["DEPICTIO_MONGODB_SERVICE_PORT"] == "17018"
    assert env["DEPICTIO_S3_EXTERNAL_PORT"] == "19000"
    assert env["DEPICTIO_VIEWER_SERVICE_PORT"] == "18058"
    assert env["DEPICTIO_AUTH_SINGLE_USER_MODE"] == "true"
    assert env["DEPICTIO_PERFORMANCE_SCREENSHOTS_ENABLED"] == "false"
    assert env["DEPICTIO_SEED_PROJECTS"] == "iris"
    assert env["DEPICTIO_PERFORMANCE_SCREENSHOTS_DIR"].startswith(str(paths.home))


def test_server_env_drops_inherited_depictio_variables(paths, monkeypatch):
    monkeypatch.setenv("DEPICTIO_MONGODB_SERVICE_NAME", "mongo")
    monkeypatch.setenv("DEPICTIO_SEED_PROJECTS", "penguins")
    ports = {"api": 1, "mongo": 2, "redis": 3, "s3": 4}
    env = server_env(paths, ports, SECRETS, "none", True)

    assert env["DEPICTIO_MONGODB_SERVICE_NAME"] == "127.0.0.1"
    assert "DEPICTIO_SEED_PROJECTS" not in env
    assert env["DEPICTIO_DISABLE_EXAMPLE_DASHBOARDS"] == "true"


def test_server_env_keeps_the_telemetry_opt_out(paths, monkeypatch):
    monkeypatch.setenv("DEPICTIO_TELEMETRY_ENABLED", "false")
    monkeypatch.setenv("DEPICTIO_TELEMETRY_DEPLOYMENT_KIND", "docker")
    ports = {"api": 1, "mongo": 2, "redis": 3, "s3": 4}
    env = server_env(paths, ports, SECRETS, "none", False)

    assert env["DEPICTIO_TELEMETRY_ENABLED"] == "false"
    assert env["DEPICTIO_TELEMETRY_DEPLOYMENT_KIND"] == "local"


def test_the_server_reaches_127_0_0_1_without_the_proxy(paths, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy:3128")
    monkeypatch.setenv("no_proxy", "localhost,.example.org")
    monkeypatch.delenv("NO_PROXY", raising=False)
    ports = {"api": 1, "mongo": 2, "redis": 3, "s3": 4}
    env = server_env(paths, ports, SECRETS, "none", False)

    assert env["no_proxy"] == env["NO_PROXY"] == "localhost,.example.org,127.0.0.1"


def test_no_proxy_keeps_the_entries_of_both_spellings(paths, monkeypatch):
    monkeypatch.setenv("no_proxy", "localhost,.example.org")
    monkeypatch.setenv("NO_PROXY", ".corp.internal, localhost")
    ports = {"api": 1, "mongo": 2, "redis": 3, "s3": 4}
    env = server_env(paths, ports, SECRETS, "none", False)

    expected = "localhost,.example.org,.corp.internal,127.0.0.1"
    assert env["no_proxy"] == env["NO_PROXY"] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "iris,penguins"),
        ("penguins", "penguins"),
        ("Iris, penguins,iris", "iris,penguins"),
        ("none", "none"),
    ],
)
def test_parse_examples(value, expected):
    assert parse_examples(value) == expected


@pytest.mark.parametrize("value", ["all", "ampliseq", "iris,none", ""])
def test_parse_examples_rejects_anything_but_the_shipped_examples(value):
    with pytest.raises(LocalStackError, match="iris, penguins, iris,penguins or none"):
        parse_examples(value)


def test_pick_ports_reuses_the_previous_run_ports():
    saved = dict(zip(local_stack.DEFAULT_PORTS, _free_ports(4), strict=True))
    assert pick_ports(None, saved) == saved
    explicit = _free_ports(1)[0]
    assert pick_ports(explicit, saved)["api"] == explicit


def test_pick_ports_moves_off_a_saved_port_taken_since():
    saved = dict(zip(local_stack.DEFAULT_PORTS, _free_ports(4), strict=True))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", saved["api"]))
        busy.listen()
        ports = pick_ports(None, saved)

    assert ports["api"] != saved["api"]
    assert {k: v for k, v in ports.items() if k != "api"} == {
        k: v for k, v in saved.items() if k != "api"
    }


def test_ports_survive_down_and_ignore_unknown_entries(paths):
    local_stack.save_ports(paths, {"api": 18058, "mongo": 17018, "redis": 16379, "s3": 19000})
    local_stack.stop_all(paths, log=lambda _: None)
    paths.ports.write_text(json.dumps({**json.loads(paths.ports.read_text()), "x": 1}))
    assert local_stack.load_ports(paths) == {
        "api": 18058,
        "mongo": 17018,
        "redis": 16379,
        "s3": 19000,
    }


def test_pick_ports_skips_a_busy_preferred_port(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        monkeypatch.setitem(local_stack.DEFAULT_PORTS, "mongo", taken)

        ports = pick_ports(None)

    assert ports["mongo"] != taken
    assert len(set(ports.values())) == len(ports)


def test_seaweedfs_gets_a_free_port_for_every_internal_listener(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        monkeypatch.setitem(local_stack.SEAWEEDFS_PORTS, "volume.port", taken)

        flags = local_stack.seaweedfs_port_flags({9333})

    ports = {flag.split("=")[0]: int(flag.split("=")[1]) for flag in flags}
    assert set(ports) == {f"-{name}" for name in local_stack.SEAWEEDFS_PORTS}
    assert ports["-volume.port"] != taken
    assert ports["-master.port"] != 9333
    assert len(set(ports.values())) == len(ports)


def test_pick_ports_rejects_a_busy_explicit_api_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        assert not port_is_free(busy.getsockname()[1])
        with pytest.raises(local_stack.LocalStackError):
            pick_ports(busy.getsockname()[1])


def test_load_secrets_is_stable_and_private(paths):
    first = local_stack.load_secrets(paths)
    assert local_stack.load_secrets(paths) == first
    assert paths.secrets.stat().st_mode & 0o777 == 0o600


def test_stop_all_without_state_is_a_no_op(paths):
    assert local_stack.stop_all(paths, log=lambda _msg: None) == []
    assert not paths.state.exists()


def test_ensure_dirs_makes_the_home_keys_and_cli_owner_only(tmp_path):
    home = tmp_path / "local"
    (home / "keys").mkdir(parents=True)
    (home / "keys").chmod(0o755)
    Paths(home).ensure_dirs()
    for directory in (home, home / "keys", home / "cli"):
        assert directory.stat().st_mode & 0o777 == 0o700


def test_wipe_deletes_every_data_dir_and_keeps_the_binaries(paths):
    (paths.env / "bin").mkdir(parents=True)
    local_stack.load_secrets(paths)
    local_stack.save_ports(paths, dict(local_stack.DEFAULT_PORTS))
    State(ports=dict(local_stack.DEFAULT_PORTS)).save(paths)

    local_stack.reset(paths)

    assert not [sub for sub in DATA_DIRS if (paths.home / sub).exists()]
    assert not [f for f in (paths.state, paths.secrets, paths.ports) if f.exists()]
    assert (paths.env / "bin").is_dir()


# --- state.json -------------------------------------------------------------------


def test_state_reads_an_older_file_and_writes_the_same_keys(paths):
    # As written before start times and examples were recorded.
    ports = {"api": 18058, "mongo": 17018, "redis": 16379, "s3": 19000}
    paths.state.write_text(
        json.dumps({"pids": {"api": 12}, "ports": ports, "url": "http://127.0.0.1:18058"})
    )

    state = State.load(paths)

    assert state == State(ports=ports, home=str(paths.home), pids={"api": 12})
    assert state.url == "http://127.0.0.1:18058"
    state.save(paths)
    assert set(json.loads(paths.state.read_text())) == {
        "pids",
        "ports",
        "url",
        "home",
        "examples",
        "first_run",
        "screenshots",
        "start_times",
    }


def test_state_is_none_until_up_records_one(paths):
    assert State.load(paths) is None
    assert local_stack.live_pids(None) == {}


def test_running_status_does_not_read_a_state_it_is_given(paths, monkeypatch):
    monkeypatch.setattr(State, "load", MagicMock(side_effect=AssertionError))
    # This test's own PID, without a start time: alive, so running.
    status = local_stack.running_status(paths, State(pids={"api": os.getpid()}))
    assert status == {name: name == "api" for name in local_stack.PROCESS_ORDER}


# --- Recorded PIDs ----------------------------------------------------------


@pytest.mark.parametrize(
    ("recorded", "ours"),
    [(1.0, False), (1_000_000.5, True), (None, True)],
    ids=["reused-pid", "same-process", "no-start-time-recorded"],
)
def test_only_a_pid_with_its_recorded_start_time_is_signalled(paths, monkeypatch, recorded, ours):
    signalled = []
    monkeypatch.setattr(local_stack, "process_start_time", lambda pid: 1_000_000.0)
    monkeypatch.setattr(local_stack, "terminate_group", lambda pid, *a, **k: signalled.append(pid))
    # This test's own PID: certainly alive, and never actually signalled (stubbed above).
    state = {"pids": {"api": os.getpid()}}
    if recorded is not None:
        state["start_times"] = {"api": recorded}
    paths.state.write_text(json.dumps(state))

    assert local_stack.running_status(paths)["api"] is ours
    assert local_stack.stop_all(paths, log=lambda _: None) == (["api"] if ours else [])
    assert signalled == ([os.getpid()] if ours else [])


def test_stop_all_does_not_wait_out_a_child_it_already_stopped(paths):
    # `up` stopping what it started, after Ctrl-C: the exited child is a zombie until reaped.
    proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
    started = local_stack.process_start_time(proc.pid)
    State(pids={"api": proc.pid}, start_times={"api": started}).save(paths)

    begin = time.monotonic()
    assert local_stack.stop_all(paths, log=lambda _: None) == ["api"]

    assert time.monotonic() - begin < 5
    assert not local_stack.pid_alive(proc.pid)


def test_process_start_time_reads_a_live_process():
    pytest.importorskip("psutil")
    started = local_stack.process_start_time(os.getpid())
    assert started is not None and started <= time.time()


def _running(pid: int) -> bool:
    """Alive and not a zombie (an orphan's reaper may take a moment)."""
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(out.stdout.strip()) and not out.stdout.strip().startswith("Z")


def test_stop_child_also_kills_what_the_leader_forked(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    # Both the shell and its child ignore SIGTERM, so only the group SIGKILL ends them.
    proc = subprocess.Popen(
        ["sh", "-c", f"trap '' TERM; sleep 60 & echo $! > '{pidfile}'; wait"],
        start_new_session=True,
    )
    deadline = time.monotonic() + 10
    while not (pidfile.exists() and pidfile.read_text().strip()):
        assert time.monotonic() < deadline, "the test process never started its child"
        time.sleep(0.05)
    grandchild = int(pidfile.read_text())

    local_stack._stop_child(proc, timeout=0.5)

    assert proc.poll() is not None
    deadline = time.monotonic() + 10
    while _running(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _running(grandchild)


def test_check_alive_names_the_log_of_a_dead_service(paths):
    alive, dead = MagicMock(), MagicMock()
    alive.poll.return_value = None
    dead.poll.return_value = 1
    local_stack.check_alive(paths, {"api": alive})
    with pytest.raises(LocalStackError, match="worker process exited.*worker.log"):
        local_stack.check_alive(paths, {"api": alive, "worker": dead})


# --- API readiness and the CLI configuration ---------------------------------


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        found = self.path == "/health"
        self.send_response(200 if found else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "healthy"} if found else {}).encode())

    def log_message(self, *_args):
        pass


@pytest.fixture
def api_port():
    """A stand-in for the API, answering /health only."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_api_healthy_bypasses_proxies(api_port, monkeypatch):
    for var in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    assert local_stack.api_healthy(api_port)
    assert not local_stack.api_healthy(_free_ports(1)[0])


def _write_cli_config(paths, api: int, s3: int) -> None:
    config = {
        "api_base_url": f"http://127.0.0.1:{api}",
        "s3_storage": {
            "service_name": "127.0.0.1",
            "service_port": s3,
            "external_host": "127.0.0.1",
            "external_port": s3,
            "root_password": "s3-secret",
        },
        "user": {"email": local_stack.ADMIN_EMAIL, "token": {"access_token": "tok"}},
    }
    paths.cli_config.write_text(yaml.dump(config))
    paths.cli_config.chmod(0o644)


def test_a_restart_on_new_ports_rewrites_the_cli_config(paths, api_port):
    # Left by a previous run on other ports: the API does not rewrite it.
    _write_cli_config(paths, api=8058, s3=9000)
    ports = {"api": api_port, "mongo": 1, "redis": 2, "s3": 19123}
    proc = MagicMock()
    proc.poll.return_value = None

    local_stack.wait_for_api(paths, ports, proc, timeout=10)

    config = yaml.safe_load(paths.cli_config.read_text())
    assert config["api_base_url"] == f"http://127.0.0.1:{api_port}"
    assert config["s3_storage"]["service_port"] == config["s3_storage"]["external_port"] == 19123
    assert config["s3_storage"]["root_password"] == "s3-secret"
    assert config["user"]["token"]["access_token"] == "tok"
    assert paths.cli_config.stat().st_mode & 0o777 == 0o600
    assert not local_stack.sync_cli_config(paths, ports)


# --- Native binaries ------------------------------------------------------------


def test_a_failed_download_is_an_actionable_error(paths, monkeypatch):
    async def solve(**_kwargs):
        raise RuntimeError("connection refused")

    rattler = types.SimpleNamespace(
        Platform=types.SimpleNamespace(current=lambda: "linux-64"),
        VirtualPackage=types.SimpleNamespace(detect=lambda: []),
        solve=solve,
        install=None,
    )
    monkeypatch.setitem(sys.modules, "rattler", rattler)
    with pytest.raises(
        LocalStackError, match="conda-forge: connection refused. Check your network"
    ):
        local_stack.ensure_binaries(paths, log=lambda _: None)


def test_port_is_free_sees_a_wildcard_listener():
    # macOS lets a 127.0.0.1 bind succeed next to a 0.0.0.0 listener (Docker-published ports).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("0.0.0.0", 0))
        busy.listen()
        assert not port_is_free(busy.getsockname()[1])


@pytest.mark.parametrize(
    ("platform", "pool"),
    [("linux", "--pool=prefork"), ("darwin", "--pool=threads")],
)
def test_worker_pool_forks_only_on_linux(monkeypatch, platform, pool):
    monkeypatch.setattr(local_stack.sys, "platform", platform)
    args = local_stack.worker_pool_args()
    assert pool in args
    assert ("--max-tasks-per-child=50" in args) == (platform == "linux")


def test_windows_is_rejected_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(local_stack.sys, "platform", "win32")
    with pytest.raises(local_stack.LocalStackError, match="WSL2"):
        local_stack.check_platform_supported()


def test_the_lock_without_fcntl_is_a_clear_error(paths, monkeypatch):
    # As on Windows: None in sys.modules makes the import fail.
    monkeypatch.setitem(sys.modules, "fcntl", None)
    with pytest.raises(LocalStackError, match="POSIX file locks.*WSL2"):
        local_stack.lock_for_startup(paths)
    assert not (paths.home / local_stack.UP_LOCK).exists()


@pytest.mark.parametrize(
    ("holder", "command", "message"),
    [
        ("up", "up", "Another `depictio local up` is already starting this home"),
        ("up", "wipe", "A `depictio local up` is starting this home"),
        ("up", "export", "wait for it, or stop it, then try again"),
        ("wipe", "up", "`depictio local wipe` is using this home"),
        ("export", "wipe", "`depictio local export` is using this home"),
    ],
)
def test_the_lock_names_the_command_holding_it(paths, holder, command, message):
    held = local_stack.lock_for_startup(paths, holder)
    try:
        with pytest.raises(LocalStackError) as err:
            local_stack.lock_for_startup(paths, command)
    finally:
        held.close()

    assert message in str(err.value)
    assert str(paths.home) in str(err.value)
    # Released: the next command goes ahead.
    local_stack.lock_for_startup(paths, command).close()


def test_a_lock_held_by_an_earlier_up_is_named_as_up(paths):
    # Before wipe and export took the lock, up wrote nothing in it.
    import fcntl

    with open(paths.home / local_stack.UP_LOCK, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(LocalStackError, match="A `depictio local up` is starting"):
            local_stack.lock_for_startup(paths, "wipe")


def test_example_tables_match_the_seeded_static_ids():
    from depictio.api.v1.db_init_reference_datasets import STATIC_IDS

    for name, dc_ids in local_stack.EXAMPLE_TABLES.items():
        assert set(dc_ids) == set(STATIC_IDS[name]["data_collections"].values())


def _state_with_token(paths, examples: str, first_run: bool = False) -> State:
    paths.cli_config.write_text(yaml.safe_dump({"user": {"token": {"access_token": "t"}}}))
    return State(ports={"api": 8058}, examples=examples, first_run=first_run)


class _Specs(http.server.BaseHTTPRequestHandler):
    """The deltatables specs endpoint, whose 404s tell a missing collection from one loading."""

    DETAILS = {
        "loading": "No DeltaTable found for data collection loading",
        "absent": "Data collection not found or access denied.",
    }

    def do_GET(self):  # noqa: N802 - http.server API
        detail = self.DETAILS.get(self.path.rsplit("/", 1)[-1])
        self.send_response(404 if detail else 200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"detail": detail} if detail else {}).encode())

    def log_message(self, *_args):
        pass


def test_table_status_tells_a_missing_collection_from_one_loading():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Specs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        statuses = {
            dc: local_stack.table_status(url, "t", dc) for dc in ("ok", "loading", "absent")
        }
    finally:
        server.shutdown()
        server.server_close()

    assert statuses == {"ok": "ready", "loading": "loading", "absent": "absent"}
    # An API that does not answer: not an example still loading.
    port = _free_ports(1)[0]
    assert local_stack.table_status(f"http://127.0.0.1:{port}", "t", "x") == "unreachable"


def test_wait_for_examples_returns_once_every_table_exists(paths, monkeypatch):
    calls = []

    def table_status(url, token, dc_id):
        calls.append(dc_id)
        return "ready" if len(calls) > 3 else "loading"

    monkeypatch.setattr(local_stack, "table_status", table_status)
    state = _state_with_token(paths, "iris,penguins")
    status = local_stack.wait_for_examples(paths, state, timeout=5, interval=0)
    assert status == {"iris": "ready", "penguins": "ready"}


def test_wait_for_examples_reports_the_examples_still_loading(paths, monkeypatch):
    monkeypatch.setattr(local_stack, "table_status", lambda url, token, dc_id: "loading")
    state = _state_with_token(paths, "iris,penguins")
    status = local_stack.wait_for_examples(paths, state, timeout=0.05, interval=0.01)
    assert status == {"iris": "loading", "penguins": "loading"}


def test_an_example_the_home_was_created_without_is_not_waited_for(paths, monkeypatch):
    iris = local_stack.EXAMPLE_TABLES["iris"]
    monkeypatch.setattr(
        local_stack,
        "table_status",
        lambda url, token, dc_id: "ready" if dc_id in iris else "absent",
    )
    sleep = MagicMock()
    monkeypatch.setattr(local_stack.time, "sleep", sleep)
    state = _state_with_token(paths, "iris,penguins")

    assert local_stack.wait_for_examples(paths, state) == {"iris": "ready", "penguins": "absent"}
    sleep.assert_not_called()


def test_on_a_first_run_an_example_not_created_yet_is_waited_for(paths, monkeypatch):
    # The penguins project is only created once iris is processed.
    rounds = []

    def table_status(url, token, dc_id):
        if dc_id == local_stack.EXAMPLE_TABLES["iris"][0]:
            rounds.append(dc_id)
            return "ready"
        return "ready" if len(rounds) > 2 else "absent"

    monkeypatch.setattr(local_stack, "table_status", table_status)
    state = _state_with_token(paths, "iris,penguins", first_run=True)
    status = local_stack.wait_for_examples(paths, state, timeout=5, interval=0)
    assert status == {"iris": "ready", "penguins": "ready"}


def test_no_examples_means_nothing_to_wait_for(paths, monkeypatch):
    monkeypatch.setattr(local_stack, "table_status", MagicMock(side_effect=AssertionError))
    assert local_stack.examples_status(paths, State(examples="none")) == {}
    # A state.json from before `examples` was recorded.
    assert local_stack.examples_status(paths, State()) == {}


def test_wait_for_examples_waits_out_an_api_busy_for_a_moment(paths, monkeypatch):
    answers = iter(["unreachable", "unreachable", "ready"])
    monkeypatch.setattr(local_stack, "table_status", lambda url, token, dc_id: next(answers))
    state = _state_with_token(paths, "iris")
    assert local_stack.wait_for_examples(paths, state, timeout=5, interval=0) == {"iris": "ready"}


def test_only_the_requested_examples_are_still_to_come_on_a_first_run(paths, monkeypatch):
    monkeypatch.setattr(local_stack, "table_status", lambda url, token, dc_id: "absent")
    state = _state_with_token(paths, "iris", first_run=True)
    status = local_stack.examples_status(paths, state, list(local_stack.EXAMPLES))
    assert status == {"iris": "loading", "penguins": "absent"}


def test_loaded_examples_clear_first_run_unless_the_server_changed(paths):
    state = State(ports={"api": 1}, examples="iris", first_run=True, pids={"api": 10})
    state.save(paths)
    local_stack.mark_examples_loaded(paths, state)
    assert State.load(paths).first_run is False

    # Restarted meanwhile by another `up`: its own first_run stays.
    State(ports={"api": 1}, first_run=True, pids={"api": 11}).save(paths)
    local_stack.mark_examples_loaded(paths, State(first_run=True, pids={"api": 10}))
    assert State.load(paths).first_run is True


# --- The environment of the services ---------------------------------------------


def test_no_aws_setting_of_the_shell_reaches_the_services(paths, monkeypatch, caplog):
    for var in ("AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_ENDPOINT_URL_S3", "AWS_ACCESS_KEY_ID"):
        monkeypatch.setenv(var, "from-the-shell")
    monkeypatch.setenv("GITHUB_TOKEN", "kept")
    caplog.set_level("DEBUG", logger=local_stack.logger.name)
    local_stack._last_debug.clear()
    ports = {"api": 1, "mongo": 2, "redis": 3, "s3": 4}

    env = server_env(paths, ports, SECRETS, "none", False)

    assert not [k for k in env if k.startswith("AWS_")]
    assert env["GITHUB_TOKEN"] == "kept"
    assert not [k for k in local_stack.inherited_env() if k.startswith("AWS_")]
    # Named, never shown.
    assert "AWS_SESSION_TOKEN" in caplog.text and "from-the-shell" not in caplog.text


def test_every_service_starts_without_the_shell_aws_settings(paths, monkeypatch):
    monkeypatch.setenv("AWS_SESSION_TOKEN", "from-the-shell")
    monkeypatch.setenv("AWS_PROFILE", "nonexistent")
    spawned, recorded = {}, []

    def spawn(paths, name, cmd, env=None):
        spawned[name] = env
        return MagicMock(pid=1000 + len(spawned))

    monkeypatch.setattr(local_stack, "spawn", spawn)
    monkeypatch.setattr(local_stack, "wait_until", lambda *a, **k: None)
    monkeypatch.setattr(local_stack, "seaweedfs_port_flags", lambda taken: [])
    ports = {"api": 1, "mongo": 2, "redis": 3, "s3": 4}
    env = server_env(paths, ports, SECRETS, "none", False)

    local_stack._start_services(
        paths, ports, SECRETS, env, {}, record=lambda name, proc: recorded.append(name)
    )

    assert recorded == local_stack.PROCESS_ORDER
    for name, service_env in spawned.items():
        assert "AWS_SESSION_TOKEN" not in service_env, name
        assert "AWS_PROFILE" not in service_env, name
    # SeaweedFS takes its own credentials from these two.
    assert spawned["s3"]["AWS_ACCESS_KEY_ID"] == local_stack.S3_USER
    assert spawned["s3"]["AWS_SECRET_ACCESS_KEY"] == SECRETS["s3_password"]


def test_backups_land_in_the_local_home(paths):
    ports = {"api": 1, "mongo": 2, "redis": 3, "s3": 4}
    env = server_env(paths, ports, SECRETS, "none", False)
    # BackupConfig writes to <base_dir>/backups, which `wipe` deletes.
    assert env["DEPICTIO_BACKUP_BASE_DIR"] == str(paths.home)
    assert "backups" in DATA_DIRS


# --- Files `up` writes, and what it makes of broken ones ---------------------------


def test_state_ports_and_secrets_are_replaced_whole_and_keep_their_mode(paths):
    local_stack.load_secrets(paths)
    assert paths.secrets.stat().st_mode & 0o777 == 0o600
    local_stack.save_ports(paths, {"api": 1})
    paths.ports.chmod(0o640)
    local_stack.save_ports(paths, {"api": 2})
    assert paths.ports.stat().st_mode & 0o777 == 0o640
    State(ports={"api": 3}).save(paths)
    State(ports={"api": 4}).save(paths)
    assert State.load(paths).ports == {"api": 4}
    # No temporary file left behind.
    assert not list(paths.home.glob(".*.tmp"))


@pytest.mark.parametrize(
    "content", ["{garbage", "", "[1, 2]", '{"pids": [1]}', '{"pids": {"api": "x"}}']
)
def test_an_unreadable_state_names_the_file_and_the_way_out(paths, content):
    paths.state.write_text(content)
    with pytest.raises(local_stack.StateUnreadable, match="state.json is unreadable") as err:
        State.load(paths)
    assert "depictio local down stops the server without it" in str(err.value)


@pytest.mark.parametrize("content", ["{garbage", "[1, 2]"])
def test_unreadable_ports_name_the_file(paths, content):
    paths.ports.write_text(content)
    with pytest.raises(LocalStackError, match="ports.json is unreadable.*Delete it"):
        local_stack.load_ports(paths)


@pytest.mark.parametrize("content", ["{garbage", '{"s3_password": "x"}', "[]"])
def test_unreadable_secrets_name_the_file_and_never_their_content(paths, content):
    paths.secrets.write_text(content)
    with pytest.raises(LocalStackError, match="secrets.json is unreadable") as err:
        local_stack.load_secrets(paths)
    assert '"x"' not in str(err.value)


def test_export_does_not_make_up_new_passwords(paths):
    with pytest.raises(LocalStackError, match="secrets.json is missing"):
        local_stack.load_secrets(paths, create=False)
    assert not paths.secrets.exists()


def test_an_unparsable_cli_config_names_the_file_without_quoting_it(paths):
    paths.cli_config.write_text("api_base_url: [unclosed\naccess_token: s3cr3t\n")
    with pytest.raises(LocalStackError, match="admin_config.yaml is unreadable") as err:
        local_stack.read_cli_config(paths)
    assert "s3cr3t" not in str(err.value)


# --- The local home ------------------------------------------------------------


def test_a_new_or_empty_folder_becomes_a_local_home(tmp_path):
    for home in (tmp_path / "new", tmp_path / "empty"):
        if home.name == "empty":
            home.mkdir()
        local_stack.claim_home(Paths(home))
        assert local_stack.is_local_home(home)


def test_a_folder_with_other_content_is_not_claimed(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "state.json").write_text("{}")
    with pytest.raises(LocalStackError, match="not a Depictio local home"):
        local_stack.claim_home(Paths(tmp_path))
    assert not (tmp_path / local_stack.HOME_MARKER).exists()


def test_a_home_made_before_the_marker_is_still_one(tmp_path):
    # Stopped (ports.json and the data directories), or wiped (the binaries only).
    stopped, wiped = tmp_path / "stopped", tmp_path / "wiped"
    for sub in ("keys", "cli", "mongo", "logs"):
        (stopped / sub).mkdir(parents=True)
    (stopped / "ports.json").write_text("{}")
    (wiped / "env").mkdir(parents=True)
    (wiped / "env" / ".depictio-specs.json").write_text('{"specs": [], "platform": "x"}')
    assert local_stack.is_local_home(stopped)
    assert local_stack.is_local_home(wiped)
    # A few of its data directories alone do not make one.
    (stopped / "ports.json").unlink()
    assert not local_stack.is_local_home(stopped)
    # All of them do: a first run that failed before writing anything else.
    for sub in DATA_DIRS:
        if sub != "backups":
            (stopped / sub).mkdir(exist_ok=True)
    assert local_stack.is_local_home(stopped)


# --- Startup: PIDs on disk at once, signals, the CLI configuration -------------------


@pytest.fixture
def fake_start(paths, monkeypatch):
    """start_stack with every slow or external step stubbed; services are fakes."""
    fake = MagicMock()
    fake.process_start_time.return_value = 1.0
    for name in ("ensure_binaries", "seed_screenshots", "wait_for_api", "check_alive"):
        monkeypatch.setattr(local_stack, name, getattr(fake, name))
    monkeypatch.setattr(local_stack, "process_start_time", fake.process_start_time)
    monkeypatch.setattr(local_stack, "pick_ports", lambda port, saved: dict(DEFAULT_PORTS_TEST))
    return fake


DEFAULT_PORTS_TEST = {"api": 63998, "mongo": 63997, "redis": 63996, "s3": 63995}


def test_each_pid_is_on_disk_as_soon_as_its_process_starts(paths, fake_start, monkeypatch):
    seen = []

    def start_services(paths, ports, secret_values, env, record=None):
        procs = {}
        for i, name in enumerate(local_stack.PROCESS_ORDER):
            procs[name] = MagicMock(pid=5000 + i)
            record(name, procs[name])
            seen.append(dict(State.load(paths).pids))
        return procs

    monkeypatch.setattr(local_stack, "start_services", start_services)
    local_stack.start_stack(paths, None, "none", False, log=lambda _: None)

    assert seen[0] == {"mongo": 5000}
    assert seen[-1] == {name: 5000 + i for i, name in enumerate(local_stack.PROCESS_ORDER)}


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP], ids=["SIGTERM", "SIGHUP"])
def test_a_signal_during_startup_stops_what_was_started(paths, fake_start, monkeypatch, signum):
    stopped = []
    before = signal.getsignal(signum)

    def start_services(paths, ports, secret_values, env, record=None):
        record("mongo", MagicMock(pid=4321))
        os.kill(os.getpid(), signum)
        time.sleep(5)  # interrupted by the handler
        raise AssertionError("the signal did not interrupt the startup")

    monkeypatch.setattr(local_stack, "start_services", start_services)
    monkeypatch.setattr(local_stack, "live_pids", lambda state: dict(state.pids) if state else {})
    monkeypatch.setattr(local_stack, "terminate_group", lambda pid, *a, **k: stopped.append(pid))

    with pytest.raises(local_stack.Interrupted) as err:
        local_stack.start_stack(paths, None, "none", False, log=lambda _: None)

    assert err.value.signum == signum
    assert stopped == [4321]
    assert not paths.state.exists()
    assert signal.getsignal(signum) == before


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP], ids=["SIGTERM", "SIGHUP"])
def test_a_signal_inside_spawn_still_stops_that_service(paths, fake_start, monkeypatch, signum):
    started: list[subprocess.Popen] = []

    def spawn(paths, name, cmd, env=None):
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        started.append(proc)
        # Before spawn returns, as on a loaded machine: nothing has the pid yet.
        os.kill(os.getpid(), signum)
        return proc

    monkeypatch.setattr(local_stack, "spawn", spawn)
    try:
        with pytest.raises(local_stack.Interrupted) as err:
            local_stack.start_stack(paths, None, "none", False, log=lambda _: None)

        assert err.value.signum == signum
        assert len(started) == 1
        assert started[0].wait(timeout=10) is not None
    finally:
        for proc in started:
            proc.kill()


@pytest.mark.parametrize(
    "first",
    [KeyboardInterrupt(), LocalStackError("Timed out")],
    ids=["ctrl-c", "error"],
)
@pytest.mark.parametrize(
    "second", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP], ids=["ctrl-c", "SIGTERM", "SIGHUP"]
)
def test_a_signal_while_stopping_does_not_cut_the_stop_short(
    paths, fake_start, monkeypatch, first, second
):
    stopped = []
    handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, second)}

    def start_services(paths, ports, secret_values, env, record=None):
        for i, name in enumerate(("mongo", "redis", "s3")):
            record(name, MagicMock(pid=4000 + i))
        raise first

    def terminate_group(pid, *args, **kwargs):
        stopped.append(pid)
        if len(stopped) == 1:
            # Pressed again, or the terminal closed, while the first service stops.
            os.kill(os.getpid(), second)
            time.sleep(0.2)

    monkeypatch.setattr(local_stack, "start_services", start_services)
    monkeypatch.setattr(local_stack, "live_pids", lambda state: dict(state.pids) if state else {})
    monkeypatch.setattr(local_stack, "terminate_group", terminate_group)

    # BaseException: an interrupt escaping the cleanup must fail this test, not end the run.
    with pytest.raises(BaseException) as err:
        local_stack.start_stack(paths, None, "none", False, log=lambda _: None)

    assert err.value is first
    assert stopped == [4002, 4001, 4000]
    assert not paths.state.exists()
    assert {signum: signal.getsignal(signum) for signum in handlers} == handlers


def test_start_services_stops_every_service_it_started_despite_a_second_ctrl_c(paths, monkeypatch):
    started = iter(MagicMock(pid=4000 + i) for i in range(3))
    stopped = []
    before = signal.getsignal(signal.SIGINT)
    first = KeyboardInterrupt()

    def wait_until(*args, **kwargs):
        raise first  # Ctrl-C while MongoDB starts

    def stop_child(proc, timeout=20):
        stopped.append(proc.pid)
        if len(stopped) == 1:
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(0.2)

    monkeypatch.setattr(local_stack, "spawn", lambda *a, **k: next(started))
    monkeypatch.setattr(local_stack, "seaweedfs_port_flags", lambda taken: [])
    monkeypatch.setattr(local_stack, "wait_until", wait_until)
    monkeypatch.setattr(local_stack, "_stop_child", stop_child)
    ports = {"api": 1, "mongo": 2, "redis": 3, "s3": 4}

    with pytest.raises(KeyboardInterrupt) as err:
        local_stack.start_services(paths, ports, SECRETS, {})

    assert err.value is first
    assert stopped == [4002, 4001, 4000]
    assert signal.getsignal(signal.SIGINT) == before


def test_a_cli_config_deleted_after_the_first_run_is_written_again(paths, fake_start, monkeypatch):
    (paths.home / "mongo" / "WiredTiger").write_text("data")
    monkeypatch.setattr(
        local_stack,
        "start_services",
        lambda *a, **k: {name: MagicMock(pid=1) for name in local_stack.PROCESS_ORDER},
    )
    logged = []

    state = local_stack.start_stack(paths, None, "none", False, log=logged.append)

    assert not state.first_run
    assert fake_start.wait_for_api.call_args.kwargs["rebuild_from"] == local_stack.load_secrets(
        paths
    )
    # warn defaults to log: a token that could not be revoked is printed, not raised.
    assert fake_start.wait_for_api.call_args.kwargs["warn"] == logged.append
    assert any("admin_config.yaml is missing" in line for line in logged)


def test_an_unparsable_cli_config_fails_before_anything_starts(paths, fake_start, monkeypatch):
    (paths.home / "mongo" / "WiredTiger").write_text("data")
    paths.cli_config.write_text("{unclosed")
    start_services = MagicMock()
    monkeypatch.setattr(local_stack, "start_services", start_services)

    with pytest.raises(LocalStackError, match="admin_config.yaml is unreadable"):
        local_stack.start_stack(paths, None, "none", False, log=lambda _: None)
    start_services.assert_not_called()


class _Auth(http.server.BaseHTTPRequestHandler):
    """/auth/login, /auth/me/tokens, /auth/generate_agent_config, /auth/list_tokens and
    DELETE /auth/me/tokens/{id}, as the API answers them.

    ``tokens``: the admin's other long-lived tokens; the one POST /me/tokens creates
    (id "new") is listed with them. ``failing``: ids whose DELETE answers 500.
    """

    AUTH = "/depictio/api/v1/auth"
    calls: list = []
    tokens: list = []
    failing: set = set()
    created: dict = {}

    def _answer(self, status: int, payload) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_POST(self):  # noqa: N802 - http.server API
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        type(self).calls.append(("POST", self.path, self.headers.get("Authorization"), body))
        if self.path == f"{self.AUTH}/me/tokens":
            name = json.loads(body)["name"]
            type(self).created = {"_id": "new", "name": name, "token_lifetime": "long-lived"}
        answers = {
            f"{self.AUTH}/login": {"access_token": "session"},
            f"{self.AUTH}/me/tokens": {**self.created, "access_token": "long", "user_id": "u1"},
            f"{self.AUTH}/generate_agent_config": {
                "api_base_url": "http://127.0.0.1:1",
                "user": {"email": local_stack.ADMIN_EMAIL, "token": {"access_token": "long"}},
                "s3_storage": {"service_port": 2, "external_port": 2},
            },
        }
        self._answer(200 if self.path in answers else 404, answers.get(self.path, {}))

    def do_GET(self):  # noqa: N802 - http.server API
        type(self).calls.append(("GET", self.path, self.headers.get("Authorization"), ""))
        if self.path == f"{self.AUTH}/list_tokens?token_lifetime=long-lived":
            self._answer(200, [*self.tokens, self.created])
        else:
            self._answer(404, {})

    def do_DELETE(self):  # noqa: N802 - http.server API
        type(self).calls.append(("DELETE", self.path, self.headers.get("Authorization"), ""))
        token_id = self.path.rsplit("/", 1)[-1]
        if token_id in self.failing:
            self._answer(500, {"detail": "boom"})
        else:
            self._answer(200, {"success": True, "message": "Token deleted successfully"})

    def log_message(self, *_args):
        pass


def _rebuild_against_fake_api(paths, tokens=(), failing=()):
    """rebuild_cli_config against _Auth; the warnings it printed."""
    _Auth.calls, _Auth.tokens, _Auth.failing, _Auth.created = [], list(tokens), set(failing), {}
    server = http.server.HTTPServer(("127.0.0.1", 0), _Auth)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    warnings = []
    try:
        local_stack.rebuild_cli_config(
            paths, server.server_address[1], SECRETS, warn=warnings.append
        )
    finally:
        server.shutdown()
        server.server_close()
    return warnings


def _deleted() -> list[str]:
    return [path.rsplit("/", 1)[-1] for method, path, *_ in _Auth.calls if method == "DELETE"]


def test_rebuild_cli_config_writes_it_owner_only_through_the_api(paths):
    warnings = _rebuild_against_fake_api(paths)

    config = yaml.safe_load(paths.cli_config.read_text())
    assert config["user"]["token"]["access_token"] == "long"
    assert paths.cli_config.stat().st_mode & 0o777 == 0o600
    login, token, generate, listing = _Auth.calls
    assert "username=admin%40example.com" in login[3]
    assert token[2] == generate[2] == listing[2] == "Bearer session"
    assert json.loads(generate[3])["access_token"] == "long"
    assert _deleted() == [] and warnings == []


def test_rebuild_cli_config_revokes_only_the_tokens_of_earlier_rebuilds(paths):
    tokens = [
        {"_id": "first-run", "name": "default_token"},
        {"_id": "old1", "name": "depictio-local-20260101120000"},
        {"_id": "old2", "name": "depictio-local-20260102120000"},
        # Made by hand on the CLI agents page.
        {"_id": "laptop", "name": "laptop"},
        {"_id": "lookalike", "name": "depictio-local-laptop"},
    ]

    warnings = _rebuild_against_fake_api(paths, tokens)

    assert _deleted() == ["old1", "old2"]
    assert local_stack.REBUILT_TOKEN_NAME.fullmatch(_Auth.created["name"])
    assert warnings == []


def test_a_token_that_cannot_be_revoked_is_a_warning(paths):
    tokens = [
        {"_id": "old1", "name": "depictio-local-20260101120000"},
        {"_id": "old2", "name": "depictio-local-20260102120000"},
    ]

    warnings = _rebuild_against_fake_api(paths, tokens, failing={"old1"})

    assert paths.cli_config.exists()
    assert _deleted() == ["old1", "old2"]
    assert len(warnings) == 1
    assert warnings[0].startswith("1 earlier depictio-local token could not be revoked")
    assert "/cli-agents" in warnings[0]


def test_a_token_list_that_fails_is_a_warning(paths, monkeypatch):
    monkeypatch.setattr(_Auth, "do_GET", lambda self: self._answer(500, {"detail": "boom"}))

    warnings = _rebuild_against_fake_api(paths)

    assert paths.cli_config.exists()
    assert _deleted() == []
    assert len(warnings) == 1 and warnings[0].startswith("Could not list the earlier")


def test_rebuild_cli_config_failing_names_the_file(paths):
    with pytest.raises(LocalStackError, match="admin_config.yaml is missing and the API could not"):
        local_stack.rebuild_cli_config(paths, _free_ports(1)[0], SECRETS)


@pytest.mark.parametrize("endpoint", ["login", "me/tokens", "generate_agent_config"])
def test_an_api_answer_that_is_not_an_object_is_an_error(paths, monkeypatch, endpoint):
    answer_post = _Auth.do_POST

    def do_post(self):
        if self.path == f"{self.AUTH}/{endpoint}":
            self.rfile.read(int(self.headers["Content-Length"]))
            self._answer(200, ["not", "an", "object"])
        else:
            answer_post(self)

    monkeypatch.setattr(_Auth, "do_POST", do_post)

    with pytest.raises(LocalStackError) as err:
        _rebuild_against_fake_api(paths)

    assert "admin_config.yaml is missing and the API could not write it again" in str(err.value)
    assert f"/auth/{endpoint} did not answer a JSON object" in str(err.value)
    assert not paths.cli_config.exists()


def test_a_service_that_exits_is_named_at_the_start_of_the_sentence(paths):
    proc = MagicMock()
    proc.poll.return_value = 1
    proc.returncode = 1
    with pytest.raises(LocalStackError, match=r"^The Depictio API exited during startup"):
        local_stack.wait_until(lambda: False, "the Depictio API", 5, proc, paths.logs / "api.log")


# --- Finding the services without state.json ---------------------------------------


def test_find_server_processes_finds_our_services_only(paths):
    pytest.importorskip("psutil")
    (paths.env / "bin").mkdir(parents=True)
    fake_mongod = paths.env / "bin" / "mongod"
    fake_mongod.symlink_to(shutil.which("sleep"))
    ours = subprocess.Popen([str(fake_mongod), "60"], cwd=paths.home, start_new_session=True)
    # Same folder, but not one of the services; and a service outside the home.
    other = subprocess.Popen(["sleep", "60"], cwd=paths.home, start_new_session=True)
    elsewhere = subprocess.Popen([str(fake_mongod), "60"], cwd="/", start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        found = {}
        while "mongo" not in found and time.monotonic() < deadline:
            found = local_stack.find_server_processes(paths)
            time.sleep(0.1)
        assert found == {"mongo": ours.pid}
    finally:
        for proc in (ours, other, elsewhere):
            proc.kill()
            proc.wait()
