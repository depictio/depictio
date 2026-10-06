"""What `depictio -vv local ...` logs: probe failures once per reason, the verbosity
handed to the ingestion, and never a secret value."""

import http.server
import json
import logging
import os
import shlex
import socket
import sys
import threading
import urllib.error
from unittest.mock import MagicMock

import pytest
import yaml

from depictio.cli.cli import local_stack
from depictio.cli.cli.local_stack import LocalStackError, Paths

CLI_LOGGER = local_stack.logger.name


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path)
    p.ensure_dirs()
    return p


@pytest.fixture
def debug(caplog):
    caplog.set_level(logging.DEBUG, logger=CLI_LOGGER)
    return caplog


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def answering():
    """``answering(code, body)``: a server answering every GET so, echoing the
    Authorization header into the body when ``body`` is None."""
    servers = []

    def serve(code: int, body: dict | None = None) -> int:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                payload = body if body is not None else {"detail": self.headers["Authorization"]}
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, *_args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_address[1]

    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()


def _running_proc() -> MagicMock:
    proc = MagicMock(pid=4242)
    proc.poll.return_value = None
    return proc


# --- Secrets ----------------------------------------------------------------------


def test_no_secret_value_reaches_the_debug_log(paths, debug, monkeypatch, answering):
    inherited = {
        "AWS_SECRET_ACCESS_KEY": "inherited-aws-secret",
        "DEPICTIO_CLI_TOKEN": "inherited-cli-token",
        "DEPICTIO_S3_ROOT_PASSWORD": "inherited-s3-password",
    }
    for name, value in inherited.items():
        monkeypatch.setenv(name, value)
    popen = MagicMock(return_value=_running_proc())
    monkeypatch.setattr(local_stack.subprocess, "Popen", popen)
    call = MagicMock(return_value=0)
    monkeypatch.setattr(local_stack.subprocess, "call", call)
    monkeypatch.setattr(local_stack, "wait_until", lambda *a, **k: None)
    ports = {"api": answering(404), "mongo": 1, "redis": 2, "s3": 3}

    secret_values = local_stack.load_secrets(paths)
    assert local_stack.load_secrets(paths) == secret_values
    env = local_stack.server_env(paths, ports, secret_values, "iris", False)
    local_stack.start_services(paths, ports, secret_values, env)
    token, cli_s3_password = "cli-config-admin-token", "cli-config-s3-password"
    paths.cli_config.write_text(
        yaml.safe_dump(
            {
                "api_base_url": "http://127.0.0.1:1",
                "s3_storage": {"service_port": 9, "root_password": cli_s3_password},
                "user": {"token": {"access_token": token}},
            }
        )
    )
    assert local_stack.sync_cli_config(paths, ports)
    # The stand-in API echoes the bearer token back in its 404 body.
    state = local_stack.State(ports=ports, examples="iris", first_run=True)
    assert local_stack.examples_status(paths, state) == {"iris": "loading"}
    local_stack.ingest(paths, "nf-core/rnaseq/latest", paths.home)

    # The secrets were handed to the services, so their absence below means something.
    envs = dict(
        zip(
            local_stack.PROCESS_ORDER,
            (c.kwargs["env"] for c in popen.call_args_list),
            strict=True,
        )
    )
    assert envs["s3"]["AWS_SECRET_ACCESS_KEY"] == secret_values["s3_password"]
    assert envs["api"]["DEPICTIO_S3_ROOT_PASSWORD"] == secret_values["s3_password"]
    assert envs["api"]["DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD"] == secret_values["admin_password"]
    logged = debug.text
    for secret in [
        *secret_values.values(),
        *inherited.values(),
        token,
        cli_s3_password,
        paths.secrets.read_text(),
    ]:
        assert secret not in logged
    # Names are fine, and what makes the environment debuggable.
    for name in ("DEPICTIO_S3_ROOT_PASSWORD", "AWS_SECRET_ACCESS_KEY", "DEPICTIO_CLI_TOKEN"):
        assert name in logged


def test_describe_env_names_what_changes_and_never_a_value(monkeypatch):
    monkeypatch.setenv("KEPT", "kept-value")
    monkeypatch.setenv("DROPPED", "dropped-value")
    monkeypatch.setenv("CHANGED", "old-value")
    env = {k: v for k, v in os.environ.items() if k != "DROPPED"}
    env.update({"CHANGED": "new-value", "ADDED": "added-value"})

    text = local_stack._describe_env(env)

    assert "set: ADDED, CHANGED" in text
    assert "removed: DROPPED" in text
    assert "KEPT" not in text
    assert "value" not in text


# --- Readiness probes ------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (ConnectionRefusedError(61, "Connection refused"), "Connection refused"),
        (TimeoutError("timed out"), "timed out"),
        (
            urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")),
            "Connection refused",
        ),
        (urllib.error.URLError("unknown url type"), "unknown url type"),
        (
            urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None),
            "HTTP 401 Unauthorized",
        ),
        (ValueError("Expecting value"), "ValueError: Expecting value"),
    ],
)
def test_probe_error_says_why_in_a_few_words(exc, reason):
    assert local_stack._probe_error(exc) == reason


def test_a_probe_failure_is_logged_once_per_reason(paths, debug, monkeypatch):
    outcomes = iter(
        [ConnectionRefusedError(61, "Connection refused")] * 3
        + [urllib.error.HTTPError("http://x", 503, "Service Unavailable", {}, None)] * 2
        + [True]
    )

    def check():
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(local_stack.time, "sleep", lambda _s: None)

    local_stack.wait_until(check, "the Depictio API", 60, _running_proc(), paths.logs / "api.log")

    assert [r.getMessage() for r in debug.records if "Waiting for" in r.getMessage()] == [
        "Waiting for the Depictio API: Connection refused",
        "Waiting for the Depictio API: HTTP 503 Service Unavailable",
    ]
    assert any(r.getMessage().startswith("Waited ") for r in debug.records)


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (None, "Connection refused"),
        ((401, {"detail": "Not authenticated"}), "HTTP 401 Unauthorized"),
        (
            (200, {"status": "ok"}),
            "/health answered HTTP 200 with status 'ok', not a healthy Depictio API",
        ),
    ],
    ids=["nothing-listening", "unauthorized", "another-server"],
)
def test_a_timeout_names_the_last_probe_error(paths, answering, answer, reason):
    port = answering(*answer) if answer else _free_port()
    ports = {"api": port, "mongo": 1, "redis": 2, "s3": 3}

    with pytest.raises(LocalStackError) as excinfo:
        local_stack.wait_for_api(paths, ports, _running_proc(), timeout=1)

    assert str(excinfo.value) == (
        f"Timed out after 1s waiting for the Depictio API (last error: {reason}). "
        f"See {paths.logs / 'api.log'}"
    )


def test_api_healthy_logs_why_it_is_not(debug):
    port = _free_port()
    assert not local_stack.api_healthy(port)
    assert f"API health check on port {port} failed: Connection refused" in debug.text


def test_table_status_logs_each_outcome_once_and_not_the_token(debug, monkeypatch, answering):
    monkeypatch.setattr(local_stack, "_last_debug", {})
    url = f"http://127.0.0.1:{answering(404)}"

    for _ in range(3):
        assert local_stack.table_status(url, "bearer-secret", "dc1") == "loading"

    lines = [r.getMessage() for r in debug.records if "dc1" in r.getMessage()]
    assert lines == ["Delta table of dc1: loading (HTTP 404 Not Found)"]
    assert "bearer-secret" not in debug.text


# --- Ingestion ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "flags"),
    [
        (logging.DEBUG, ["-vv"]),
        (logging.INFO, ["-v"]),
        (logging.WARNING, []),
        (logging.ERROR, []),
    ],
    ids=["-vv", "-v", "warning", "default"],
)
def test_ingestion_runs_at_the_cli_log_level(paths, caplog, monkeypatch, level, flags):
    caplog.set_level(level, logger=CLI_LOGGER)
    call = MagicMock(return_value=0)
    monkeypatch.setattr(local_stack.subprocess, "call", call)

    assert local_stack.ingest(paths, "nf-core/rnaseq/latest", paths.home) == 0

    cmd = call.call_args.args[0]
    # Root options, before the subcommand.
    assert cmd[: cmd.index("run")] == [sys.executable, "-m", "depictio.cli", *flags]
    assert (f"Ingesting with: {shlex.join(cmd)}" in caplog.text) == (level == logging.DEBUG)
