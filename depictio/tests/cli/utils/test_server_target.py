"""--server: which CLI configuration file a command loads."""

import os
from unittest.mock import patch

import pytest
import typer
import yaml

from depictio.cli.cli.utils.common import cli_config_file, load_depictio_config
from depictio.cli.cli.utils.server_target import (
    DEFAULT_CLI_CONFIG,
    DEFAULT_TARGET_CLI_CONFIG,
    ConfigFile,
    default_server,
    resolve_server,
    resolve_target_server,
)


def test_nothing_given_keeps_the_default_so_the_env_var_still_applies():
    assert resolve_server(None) == DEFAULT_CLI_CONFIG


def test_a_path_is_used_as_is():
    assert resolve_server("/etc/depictio/CLI.yaml") == "/etc/depictio/CLI.yaml"


def test_the_legacy_option_stands_in_for_server():
    assert resolve_server(None, "/etc/old.yaml") == "/etc/old.yaml"


@pytest.mark.parametrize("flags", [("~/.depictio/CLI.yaml", None), (None, "~/.depictio/CLI.yaml")])
def test_a_named_default_file_is_expanded_so_the_env_var_does_not_replace_it(flags):
    """DEPICTIO_CLI_CONFIG_PATH stands in for the unexpanded default only."""
    resolved = resolve_server(*flags)

    assert resolved == os.path.expanduser("~/.depictio/CLI.yaml")
    assert resolved != DEFAULT_CLI_CONFIG


@pytest.mark.parametrize("value", ["", "  "])
@pytest.mark.parametrize(
    ("resolve", "option"),
    [
        (lambda v: resolve_server(v), "--server"),
        (lambda v: resolve_server(None, v), "--CLI-config-path"),
        (lambda v: resolve_target_server(v), "--to-server"),
    ],
    ids=["--server", "--CLI-config-path", "--to-server"],
)
def test_an_empty_value_is_refused_not_taken_for_the_default(resolve, option, value):
    with pytest.raises(typer.BadParameter, match="is empty") as caught:
        resolve(value)
    assert caught.value.param_hint == option


def test_an_empty_server_with_the_legacy_option_is_still_refused():
    with pytest.raises(typer.BadParameter, match="is empty"):
        resolve_server("", "b.yaml")


@pytest.mark.parametrize(
    ("resolve", "notice"),
    [
        (lambda: resolve_server(None, "~/old.yaml"), "--CLI-config-path is now --server"),
        (
            lambda: resolve_server(None, "~/old.yaml", legacy_option="--config"),
            "--config is now --server",
        ),
        (
            lambda: resolve_target_server(None, "~/remote.yaml"),
            "--target-config is now --to-server",
        ),
    ],
    ids=["--CLI-config-path", "--config", "--target-config"],
)
def test_a_legacy_option_says_what_replaced_it(capsys, resolve, notice):
    resolve()

    assert notice in " ".join(capsys.readouterr().err.split())


def test_server_and_the_legacy_option_together_are_refused():
    with pytest.raises(typer.BadParameter, match="not both"):
        resolve_server("local", "~/old.yaml")


def test_local_is_the_config_depictio_local_up_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
    config = tmp_path / "cli" / "admin_config.yaml"
    config.parent.mkdir()
    config.write_text("{}")

    assert resolve_server("local") == str(config)


@pytest.mark.parametrize("value", ["LOCAL", "Local", " local "])
def test_local_is_recognised_in_any_case(tmp_path, monkeypatch, value):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))

    assert resolve_server(value) == str(tmp_path / "cli" / "admin_config.yaml")


def test_local_without_a_local_server_still_resolves(tmp_path, monkeypatch):
    """Checked when a command reads it: --offline and --dry-run need no local server."""
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))

    assert resolve_server("local") == str(tmp_path / "cli" / "admin_config.yaml")


def test_loading_a_missing_local_configuration_says_how_to_start_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))

    with pytest.raises(typer.Exit):
        load_depictio_config(resolve_server("local"))

    printed = " ".join(capsys.readouterr().out.split())
    assert "No local server configuration at" in printed
    assert "start one with `depictio local up`" in printed


def test_the_refusal_names_the_legacy_option_the_command_took():
    with pytest.raises(typer.BadParameter, match="--server or --config, not both"):
        resolve_server("local", "~/old.yaml", legacy_option="--config")


class TestToServer:
    """migrate's --to-server: the same values as --server, its own default."""

    def test_nothing_given_keeps_the_remote_default(self):
        assert DEFAULT_TARGET_CLI_CONFIG == "~/.depictio/CLI_remote.yaml"
        assert resolve_target_server(None) == DEFAULT_TARGET_CLI_CONFIG

    def test_the_target_config_option_stands_in(self):
        assert resolve_target_server(None, "/etc/remote.yaml") == "/etc/remote.yaml"

    def test_both_are_refused(self):
        with pytest.raises(typer.BadParameter, match="--to-server or --target-config"):
            resolve_target_server("a.yaml", "b.yaml")

    def test_local_is_the_config_depictio_local_up_writes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
        config = tmp_path / "cli" / "admin_config.yaml"
        config.parent.mkdir()
        config.write_text("{}")

        assert resolve_target_server("local") == str(config)

    def test_local_without_a_local_server_blames_to_server(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))

        with pytest.raises(typer.Exit):
            load_depictio_config(resolve_target_server("local"), option="--to-server")

        printed = " ".join(capsys.readouterr().out.split())
        assert "(from --to-server)" in printed
        assert "depictio local up" in printed

    def test_a_missing_default_target_names_to_server(self, tmp_path, monkeypatch, capsys):
        """Not --server: the file is migrate's default target."""
        monkeypatch.setenv("HOME", str(tmp_path))

        with pytest.raises(typer.Exit):
            load_depictio_config(resolve_target_server(None), option="--to-server")

        printed = " ".join(capsys.readouterr().out.split())
        assert "~/.depictio/CLI_remote.yaml (the default for --to-server)" in printed
        assert "pass --to-server" in printed
        assert "--server" not in printed.replace("--to-server", "")


def _valid_config(api_base_url: str) -> dict:
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


class TestDefaultServer:
    """No --server: $DEPICTIO_CLI_CONFIG_PATH, else ~/.depictio/CLI.yaml, else the local server.

    HOME and the local home point under ``tmp_path``: no real configuration is read.
    """

    @pytest.fixture(autouse=True)
    def isolated(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
        for var in ("DEPICTIO_CLI_CONFIG_PATH", "DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN"):
            monkeypatch.delenv(var, raising=False)

    @pytest.fixture
    def home_config(self, tmp_path):
        """~/.depictio/CLI.yaml, as a CLI agents page download saved there."""
        path = tmp_path / "home" / ".depictio" / "CLI.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump(_valid_config("http://home.test")))
        return path

    @pytest.fixture
    def local_config(self, tmp_path):
        """The configuration `depictio local up` writes."""
        path = tmp_path / "local" / "cli" / "admin_config.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump(_valid_config("http://127.0.0.1:8058")))
        return path

    @pytest.fixture
    def printed(self):
        """The status lines load_depictio_config prints, on one line each."""
        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
            yield lambda: [" ".join(str(call.args[0]).split()) for call in printer.call_args_list]

    def test_nothing_configured_falls_back_to_the_local_server(self, tmp_path):
        local = str(tmp_path / "local" / "cli" / "admin_config.yaml")

        assert default_server() == ConfigFile(local, local_fallback=True)
        assert cli_config_file(resolve_server(None)) == local

    def test_the_fallback_does_not_need_a_local_server_to_run(self, local_config):
        """A fixed rule: the configuration decides, not whether the server is up."""
        assert default_server() == ConfigFile(str(local_config), local_fallback=True)

    def test_an_existing_default_file_is_kept(self, home_config, local_config):
        assert default_server() == ConfigFile(str(home_config))

    def test_a_dangling_link_at_the_default_is_kept_to_be_reported(self, tmp_path):
        link = tmp_path / "home" / ".depictio" / "CLI.yaml"
        link.parent.mkdir(parents=True)
        link.symlink_to(tmp_path / "gone.yaml")

        assert default_server() == ConfigFile(str(link))

    @pytest.mark.parametrize("var", ["DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN"])
    def test_a_remote_server_variable_keeps_the_default_file(
        self, tmp_path, monkeypatch, local_config, var
    ):
        """Set, it means a remote server: a missing file is then reported, not replaced."""
        monkeypatch.setenv(var, "https://remote.example.org")

        expected = ConfigFile(str(tmp_path / "home" / ".depictio" / "CLI.yaml"))
        assert default_server() == expected

    def test_the_config_path_variable_wins(self, tmp_path, monkeypatch, local_config):
        monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(tmp_path / "env.yaml"))

        assert default_server() == ConfigFile(str(tmp_path / "env.yaml"), from_env=True)

    @pytest.mark.parametrize(
        "var", ["DEPICTIO_CLI_CONFIG_PATH", "DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN"]
    )
    def test_an_empty_variable_counts_as_unset(self, monkeypatch, var):
        monkeypatch.setenv(var, "")

        assert default_server().local_fallback

    def test_an_explicit_server_file_is_never_replaced(self, tmp_path):
        named = str(tmp_path / "named.yaml")

        assert cli_config_file(resolve_server(named)) == named

    def test_loading_with_nothing_configured_reads_the_local_server(self, local_config, printed):
        config = load_depictio_config(resolve_server(None))

        assert config.api_base_url == "http://127.0.0.1:8058"
        (line,) = printed()
        assert line == (
            "Server: http://127.0.0.1:8058 (local server, as no ~/.depictio/CLI.yaml exists; "
            f"configuration {local_config})"
        )

    def test_an_existing_default_file_is_announced_as_before(self, home_config, printed):
        load_depictio_config(resolve_server(None))

        assert printed() == ["Server: http://home.test (configuration ~/.depictio/CLI.yaml)"]

    def test_with_nothing_configured_at_all_both_ways_out_are_named(self, printed):
        with pytest.raises(typer.Exit) as caught:
            load_depictio_config(resolve_server(None))

        assert caught.value.exit_code == 1
        (message,) = printed()
        assert message == (
            "No server configured: start a local one with `depictio local up`, or point "
            "--server at a CLI configuration file, downloaded from the CLI agents page of a "
            "Depictio instance (saved as ~/.depictio/CLI.yaml, it needs no --server)."
        )

    def test_a_missing_explicit_file_is_still_blamed_on_server(self, tmp_path, printed):
        with pytest.raises(typer.Exit):
            load_depictio_config(resolve_server(str(tmp_path / "typo.yaml")))

        (message,) = printed()
        assert "(from --server)" in message
        assert "No server configured" not in message

    def test_a_remote_server_variable_without_the_file_names_the_file(self, monkeypatch, printed):
        monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "remote-token")

        with pytest.raises(typer.Exit):
            load_depictio_config(resolve_server(None))

        (message,) = printed()
        assert "configuration file not found: ~/.depictio/CLI.yaml (the default)" in message

    def test_to_server_keeps_its_own_default(self, local_config, printed):
        """migrate's target never falls back: it would migrate a server onto itself."""
        assert cli_config_file(resolve_target_server(None)).endswith("CLI_remote.yaml")

        with pytest.raises(typer.Exit):
            load_depictio_config(resolve_target_server(None), option="--to-server")

        (message,) = printed()
        assert "~/.depictio/CLI_remote.yaml (the default for --to-server)" in message
