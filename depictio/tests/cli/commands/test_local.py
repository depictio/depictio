import http.server
import importlib.metadata
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
from depictio.cli.cli.commands.local import _absolutize_path_var
from depictio.cli.cli.local_stack import (
    LocalStackError,
    Paths,
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
    env = server_env(paths, ports, {"s3_password": "x", "admin_password": "y"}, "none", True)

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
    local_stack.save_state(paths, state)

    assert local_stack.running_status(paths)["api"] is ours
    assert local_stack.stop_all(paths, log=lambda _: None) == (["api"] if ours else [])
    assert signalled == ([os.getpid()] if ours else [])


def test_stop_all_does_not_wait_out_a_child_it_already_stopped(paths):
    # `up` stopping what it started, after Ctrl-C: the exited child is a zombie until reaped.
    proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
    started = local_stack.process_start_time(proc.pid)
    local_stack.save_state(paths, {"pids": {"api": proc.pid}, "start_times": {"api": started}})

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


def _fake_local_server(paths):
    """A stopped local server: data, keys, secrets and the conda-meta records."""
    (paths.home / "mongo" / "WiredTiger").write_text("wt")
    (paths.home / "s3" / "vol").mkdir(parents=True)
    (paths.home / "s3" / "mini.options").write_text(
        "ip=127.0.0.1\nip.bind=127.0.0.1\ns3.port=9123\nwebdav=false\n"
    )
    for name in local_stack.KEY_FILES:
        (paths.home / "keys" / name).write_text(name)
    meta = paths.env / "conda-meta"
    meta.mkdir(parents=True)
    for name, version in (("mongodb", "8.0.23"), ("seaweedfs", "4.47")):
        (meta / f"{name}-{version}-h0_0.json").write_text(
            f'{{"name": "{name}", "version": "{version}"}}'
        )
    local_stack.load_secrets(paths)


def test_export_compose_copies_data_and_pins_the_local_versions(paths, tmp_path, monkeypatch):
    _fake_local_server(paths)
    monkeypatch.setattr(local_stack.sys, "platform", "linux")
    monkeypatch.setattr(local_stack, "release_version", lambda: "9.8.7")
    out = tmp_path / "export"

    local_stack.export_compose(paths, out, log=lambda _: None)

    assert (out / "data" / "mongo" / "WiredTiger").read_text() == "wt"
    assert (out / "data" / "s3" / "vol").is_dir()
    options = (out / "data" / "s3" / "mini.options").read_text().splitlines()
    assert "ip.bind=0.0.0.0" in options and "s3.port=9000" in options
    assert "ip=127.0.0.1" in options and "ip.bind=127.0.0.1" not in options
    # The local server keeps its own options.
    assert "ip.bind=127.0.0.1" in (paths.home / "s3" / "mini.options").read_text()
    assert (out / "data" / "keys" / "private_key.pem").read_text() == "private_key.pem"
    override = (out / "docker-compose.override.yaml").read_text()
    assert "image: mongo:8.0.23" in override
    assert "image: chrislusf/seaweedfs:4.47" in override
    assert "./data/mongo:/data/db" in override
    assert f'user: "{local_stack.os.getuid()}:{local_stack.os.getgid()}"' in override
    env = (out / ".env").read_text()
    secrets = local_stack.load_secrets(paths)
    assert f"DEPICTIO_S3_ROOT_PASSWORD={secrets['s3_password']}" in env
    assert f"DEPICTIO_S3_ROOT_USER={local_stack.S3_USER}" in env
    assert "DEPICTIO_VERSION=9.8.7" in env.splitlines()
    assert oct((out / ".env").stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        ({"depictio": "1.2.3", "depictio-cli": "1.2.3"}, "1.2.3"),
        ({"depictio-cli": "1.2.3"}, "1.2.3"),
        ({"depictio": "1.2.3b1"}, None),
        ({"depictio-cli": "1.2.3-b1"}, None),
        ({}, None),
    ],
)
def test_release_version_names_only_published_releases(monkeypatch, installed, expected):
    def version(dist):
        if dist not in installed:
            raise importlib.metadata.PackageNotFoundError(dist)
        return installed[dist]

    monkeypatch.setattr(importlib.metadata, "version", version)
    assert local_stack.release_version() == expected


def test_export_compose_runs_as_the_image_user_off_linux(paths, tmp_path, monkeypatch):
    _fake_local_server(paths)
    monkeypatch.setattr(local_stack.sys, "platform", "darwin")
    local_stack.export_compose(paths, tmp_path / "export", log=lambda _: None)
    assert "user:" not in (tmp_path / "export" / "docker-compose.override.yaml").read_text()


def test_export_compose_refuses_a_running_server(paths, tmp_path, monkeypatch):
    _fake_local_server(paths)
    monkeypatch.setattr(local_stack, "running_status", lambda _: {"mongo": True})
    with pytest.raises(local_stack.LocalStackError, match="depictio local down"):
        local_stack.export_compose(paths, tmp_path / "export", log=lambda _: None)


def test_export_compose_refuses_a_non_empty_directory(paths, tmp_path):
    _fake_local_server(paths)
    out = tmp_path / "export"
    out.mkdir()
    (out / "keep").write_text("x")
    with pytest.raises(local_stack.LocalStackError, match="not empty"):
        local_stack.export_compose(paths, out, log=lambda _: None)
