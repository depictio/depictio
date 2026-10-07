"""--server: which CLI configuration file a command loads."""

import pytest
import typer

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
    assert resolve_server(None, "~/old.yaml") == "~/old.yaml"


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


def test_local_without_a_local_server_says_how_to_start_one(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))

    with pytest.raises(typer.BadParameter, match="depictio local up"):
        resolve_server("local")


def test_the_refusal_names_the_legacy_option_the_command_took():
    with pytest.raises(typer.BadParameter, match="--server or --config, not both"):
        resolve_server("local", "~/old.yaml", legacy_option="--config")


class TestToServer:
    """migrate's --to-server: the same values as --server, its own default."""

    def test_nothing_given_keeps_the_remote_default(self):
        assert DEFAULT_TARGET_CLI_CONFIG == "~/.depictio/CLI_remote.yaml"
        assert resolve_target_server(None) == DEFAULT_TARGET_CLI_CONFIG

    def test_the_target_config_option_stands_in(self):
        assert resolve_target_server(None, "~/remote.yaml") == "~/remote.yaml"

    def test_both_are_refused(self):
        with pytest.raises(typer.BadParameter, match="--to-server or --target-config"):
            resolve_target_server("a.yaml", "b.yaml")

    def test_local_is_the_config_depictio_local_up_writes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
        config = tmp_path / "cli" / "admin_config.yaml"
        config.parent.mkdir()
        config.write_text("{}")

        assert resolve_target_server("local") == str(config)

    def test_local_without_a_local_server_blames_to_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))

        with pytest.raises(typer.BadParameter) as caught:
            resolve_target_server("local")
        assert caught.value.param_hint == "--to-server"
