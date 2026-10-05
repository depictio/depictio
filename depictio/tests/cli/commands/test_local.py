import http.server
import json
import os
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
    _absolutize_path_var,
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


def test_the_server_and_ingestion_reach_127_0_0_1_without_the_proxy(paths, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy:3128")
    monkeypatch.setenv("no_proxy", "localhost,.example.org")
    monkeypatch.delenv("NO_PROXY", raising=False)
    ports = {"api": 1, "mongo": 2, "redis": 3, "s3": 4}
    env = server_env(paths, ports, SECRETS, "none", False)

    assert env["no_proxy"] == env["NO_PROXY"] == "localhost,.example.org,127.0.0.1,localhost"
    assert local_stack._ingestion_env()["NO_PROXY"].endswith("127.0.0.1,localhost")


@pytest.mark.parametrize(
    ("value", "template", "expected"),
    [
        (None, None, "iris,penguins"),
        (None, "nf-core/rnaseq/latest", "none"),
        ("penguins", None, "penguins"),
        ("Iris, penguins,iris", None, "iris,penguins"),
        ("none", "nf-core/rnaseq/latest", "none"),
    ],
)
def test_parse_examples(value, template, expected):
    assert parse_examples(value, template) == expected


@pytest.mark.parametrize("value", ["all", "ampliseq", "iris,none", ""])
def test_parse_examples_rejects_anything_but_the_shipped_examples(value):
    with pytest.raises(LocalStackError, match="iris, penguins, iris,penguins or none"):
        parse_examples(value, None)


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


def test_absolutize_path_var_resolves_existing_relative_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "samplesheet.csv").write_text("sample\n")

    assert _absolutize_path_var("SAMPLESHEET_FILE=samplesheet.csv") == (
        f"SAMPLESHEET_FILE={tmp_path / 'samplesheet.csv'}"
    )
    assert _absolutize_path_var("SKIP_MULTIQC=true") == "SKIP_MULTIQC=true"
    assert _absolutize_path_var("F=/abs/path.csv") == "F=/abs/path.csv"


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
        "start_times",
    }


def test_state_is_none_until_up_records_one(paths):
    assert State.load(paths) is None
    assert local_stack.live_pids(None) == {}


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
    # An API that does not answer yet: keep waiting.
    assert local_stack.table_status(f"http://127.0.0.1:{_free_ports(1)[0]}", "t", "x") == "loading"


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
