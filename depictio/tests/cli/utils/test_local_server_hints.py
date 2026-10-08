"""A local server that runs besides the server a command targets: the hints that name it.

HOME and the local home point under ``tmp_path``: no real configuration or state is read.
A local server "runs" when its state.json records an API pid that is alive: this test's.
"""

import json
import os
from unittest.mock import patch

import httpx
import pytest
import typer
import yaml

from depictio.cli.cli.utils.common import load_depictio_config, report_unreachable
from depictio.cli.cli.utils.server_target import (
    local_is_default_server,
    resolve_server,
    running_local_url,
)

LOCAL_URL = "http://127.0.0.1:63600"
REMOTE_URL = "https://remote.example.org"
WARNING = f"A local server is running too ({LOCAL_URL}): add --server local to use it"
HINT = f"A local server is running at {LOCAL_URL}: add --server local to use it"


def _config(api_base_url: str) -> dict:
    """A loadable CLI configuration whose api_base_url marks which file was read."""
    return {
        "api_base_url": api_base_url,
        "user": {
            "email": "admin@example.com",
            "is_admin": True,
            "id": "507f1f77bcf86cd799439011",
            "token": {
                "user_id": "507f1f77bcf86cd799439011",
                "access_token": "secret-access-token",
                "refresh_token": "secret-refresh-token",
                "token_type": "bearer",
                "token_lifetime": "short-lived",
                "expire_datetime": "2099-12-31T23:59:59",
                "refresh_expire_datetime": "2099-12-31T23:59:59",
                "name": "test_token",
                "created_at": "2025-06-30T18:00:00",
                "logged_in": False,
            },
        },
        "s3_storage": {
            "service_name": "localhost",
            "service_port": 9000,
            "external_host": "localhost",
            "external_port": 9000,
            "external_protocol": "http",
            "root_user": "depictio",
            "root_password": "s3-password",
            "bucket": "depictio-bucket",
        },
    }


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
    for var in ("DEPICTIO_CLI_CONFIG_PATH", "DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def _write(path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@pytest.fixture
def home_config(tmp_path):
    """~/.depictio/CLI.yaml, for a remote server."""
    return _write(tmp_path / "home" / ".depictio" / "CLI.yaml", yaml.safe_dump(_config(REMOTE_URL)))


@pytest.fixture
def local_config(tmp_path):
    """The configuration `depictio local up` writes."""
    return _write(
        tmp_path / "local" / "cli" / "admin_config.yaml", yaml.safe_dump(_config(LOCAL_URL))
    )


@pytest.fixture
def running(tmp_path):
    """state.json of a local server whose API runs: its pid is this process."""
    state = {"ports": {"api": 63600}, "pids": {"api": os.getpid()}}
    return _write(tmp_path / "local" / "state.json", json.dumps(state))


@pytest.fixture
def printed():
    """What load_depictio_config and report_unreachable print: (mode, line) pairs."""
    with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
        yield lambda: [(call.args[1], str(call.args[0])) for call in printer.call_args_list]


class TestRunningLocalUrl:
    def test_a_running_api_gives_its_url(self, running):
        assert running_local_url() == LOCAL_URL

    def test_no_state_is_not_running(self):
        assert running_local_url() is None

    def test_a_state_without_a_live_api_is_not_running(self, tmp_path):
        _write(tmp_path / "local" / "state.json", json.dumps({"ports": {"api": 63600}}))

        assert running_local_url() is None

    def test_an_unreadable_state_is_not_running(self, tmp_path):
        _write(tmp_path / "local" / "state.json", "{not json")

        assert running_local_url() is None

    def test_any_failure_is_not_running(self, running):
        with patch("depictio.cli.cli.local_stack.running_status", side_effect=RuntimeError("boom")):
            assert running_local_url() is None


class TestLocalIsDefaultServer:
    def test_nothing_configured(self):
        assert local_is_default_server()

    def test_a_default_file_is_another_server(self, home_config):
        assert not local_is_default_server()

    def test_a_remote_server_variable_is_another_server(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "remote-token")

        assert not local_is_default_server()

    def test_the_config_path_variable_naming_local(self, home_config, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", "local")

        assert local_is_default_server()


class TestWarningAfterTheServerLine:
    """Only for a server nobody named: one named with --server is the one meant."""

    def test_a_default_target_with_a_local_server_running(self, home_config, running, printed):
        load_depictio_config(resolve_server(None))

        assert printed() == [
            ("info", f"Server: {REMOTE_URL} (configuration ~/.depictio/CLI.yaml)"),
            ("warning", WARNING),
        ]

    def test_once_per_command(self, home_config, running, printed):
        load_depictio_config(resolve_server(None))
        load_depictio_config(resolve_server(None))
        load_depictio_config(resolve_server(None), label="Source server")

        assert [line for mode, line in printed() if mode == "warning"] == [WARNING]

    def test_a_target_from_the_config_path_variable(self, tmp_path, monkeypatch, running, printed):
        env_config = _write(tmp_path / "env.yaml", yaml.safe_dump(_config(REMOTE_URL)))
        monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(env_config))

        load_depictio_config(resolve_server(None))

        assert ("warning", WARNING) in printed()

    def test_a_target_from_the_url_variable(self, home_config, monkeypatch, running, printed):
        monkeypatch.setenv("DEPICTIO_CLI_API_BASE_URL", "https://other.example.org")

        load_depictio_config(resolve_server(None))

        assert ("warning", WARNING) in printed()

    @pytest.mark.parametrize("named", ["file", "default file"])
    def test_not_for_a_server_named_on_purpose(self, home_config, running, printed, named):
        server = str(home_config) if named == "file" else "~/.depictio/CLI.yaml"

        load_depictio_config(resolve_server(server))

        assert [mode for mode, _ in printed()] == ["info"]

    def test_not_when_the_default_is_the_local_server(self, local_config, running, printed):
        load_depictio_config(resolve_server(None))

        assert [mode for mode, _ in printed()] == ["info"]

    def test_not_for_server_local(self, home_config, local_config, running, printed):
        load_depictio_config(resolve_server("local"))

        assert [mode for mode, _ in printed()] == ["info"]

    def test_not_when_the_default_already_reaches_it(self, tmp_path, running, printed):
        """A configuration copied from the local server's: the target is that server."""
        _write(
            tmp_path / "home" / ".depictio" / "CLI.yaml",
            yaml.safe_dump(_config("http://localhost:63600")),
        )

        load_depictio_config(resolve_server(None))

        assert [mode for mode, _ in printed()] == ["info"]

    def test_not_when_the_local_server_is_stopped(self, home_config, tmp_path, printed):
        _write(tmp_path / "local" / "state.json", json.dumps({"ports": {"api": 63600}}))

        load_depictio_config(resolve_server(None))

        assert [mode for mode, _ in printed()] == ["info"]

    def test_not_when_its_state_is_unreadable(self, home_config, tmp_path, printed):
        _write(tmp_path / "local" / "state.json", "{not json")

        config = load_depictio_config(resolve_server(None))

        assert config.api_base_url == REMOTE_URL
        assert [mode for mode, _ in printed()] == ["info"]

    def test_not_when_quiet(self, home_config, running, printed):
        load_depictio_config(resolve_server(None), quiet=True)

        assert printed() == []


class TestHintWhenTheTargetDoesNotAnswer:
    """Named on purpose or not: the target failed, and a running local server may help."""

    @pytest.fixture
    def refused(self):
        return httpx.ConnectError("[Errno 61] Connection refused")

    @pytest.mark.parametrize("named", [False, True])
    def test_another_server_with_the_local_one_running(
        self, home_config, running, printed, refused, named
    ):
        report_unreachable(resolve_server(str(home_config) if named else None), refused)

        lines = printed()
        assert [mode for mode, _ in lines] == ["error", "info", "info"]
        assert lines[1][1].startswith(f"Tried {REMOTE_URL}, read from ")
        assert lines[2] == ("info", HINT)

    def test_not_when_the_local_server_is_the_one_tried(
        self, local_config, running, printed, refused
    ):
        report_unreachable(resolve_server("local"), refused)

        assert HINT not in [line for _, line in printed()]

    def test_not_when_the_local_server_is_stopped(self, home_config, printed, refused):
        report_unreachable(resolve_server(None), refused)

        assert [mode for mode, _ in printed()] == ["error", "info"]

    def test_not_when_its_state_is_unreadable(self, home_config, tmp_path, printed, refused):
        _write(tmp_path / "local" / "state.json", "{not json")

        report_unreachable(resolve_server(None), refused)

        assert [mode for mode, _ in printed()] == ["error", "info"]

    def test_a_missing_target_configuration_gets_no_hint_and_no_error(
        self, tmp_path, running, printed, refused
    ):
        report_unreachable(str(tmp_path / "gone.yaml"), refused)

        assert [mode for mode, _ in printed()] == ["error", "info"]


def test_nothing_configured_still_fails_with_both_ways_out(running, printed):
    """The rule is unchanged: a running local server is not a configuration."""
    with pytest.raises(typer.Exit):
        load_depictio_config(resolve_server(None))

    ((mode, line),) = printed()
    assert mode == "error"
    assert line.startswith("No server configured")


class TestMigrateWithTheLocalServerOnOneSide:
    """migrate's other server is the local one: "add --server local" would name it twice."""

    @pytest.fixture
    def remote_target(self, tmp_path):
        return _write(
            tmp_path / "remote.yaml", yaml.safe_dump(_config("https://other.example.org"))
        )

    @staticmethod
    def _migrate(*args: str, **login) -> tuple[int, str]:
        from typer.testing import CliRunner

        from depictio.cli.cli.commands.migrate import app

        with patch("depictio.cli.cli.commands.migrate.api_login", **login):
            result = CliRunner().invoke(app, ["--project", "p", *args])
        return result.exit_code, " ".join(result.output.split())

    def test_no_warning_on_a_default_source_when_the_target_is_local(
        self, home_config, local_config, running
    ):
        code, out = self._migrate(
            "--to-server", "local", return_value={"success": True, "is_admin": False}
        )

        assert code == 1  # the mocked source login is not an admin
        assert f"Source server: {REMOTE_URL}" in out
        assert f"Target server: {LOCAL_URL}" in out
        assert "add --server local" not in out

    def test_no_hint_on_an_unreachable_source_when_the_target_is_local(
        self, home_config, local_config, running
    ):
        code, out = self._migrate("--to-server", "local", side_effect=httpx.ConnectError("refused"))

        assert code == 1
        assert "Source: cannot reach the server: refused" in out
        assert "add --server local" not in out

    def test_no_hint_on_an_unreachable_target_when_the_source_is_local(
        self, local_config, running, remote_target
    ):
        code, out = self._migrate(
            "--server",
            "local",
            "--to-server",
            str(remote_target),
            side_effect=[{"success": True, "is_admin": True}, httpx.ConnectError("refused")],
        )

        assert code == 1
        assert "Target: cannot reach the server: refused" in out
        assert "add --to-server local" not in out

    def test_the_warning_stays_when_neither_side_is_local(
        self, home_config, local_config, running, remote_target
    ):
        code, out = self._migrate(
            "--to-server", str(remote_target), return_value={"success": True, "is_admin": False}
        )

        assert code == 1
        assert WARNING in out
