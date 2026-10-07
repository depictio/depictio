"""--server: which CLI configuration file a command loads."""

import os

import pytest
import typer

from depictio.cli.cli.utils.common import load_depictio_config
from depictio.cli.cli.utils.server_target import (
    DEFAULT_CLI_CONFIG,
    DEFAULT_TARGET_CLI_CONFIG,
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
