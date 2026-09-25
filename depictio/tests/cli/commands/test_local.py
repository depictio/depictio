import socket

import pytest

from depictio.cli.cli import local_stack
from depictio.cli.cli.commands.local import _absolutize_path_var
from depictio.cli.cli.local_stack import Paths, pick_ports, port_is_free, server_env


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path)
    p.ensure_dirs()
    return p


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
    local_stack.stop_all(paths, log=lambda _msg: None)
    assert not paths.state.exists()
