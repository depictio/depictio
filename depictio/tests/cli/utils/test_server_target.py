"""--server: which CLI configuration file a command loads."""

import pytest
import typer

from depictio.cli.cli.utils.server_target import DEFAULT_CLI_CONFIG, resolve_server


def test_nothing_given_keeps_the_default_so_the_env_var_still_applies():
    assert resolve_server(None) == DEFAULT_CLI_CONFIG


def test_a_path_is_used_as_is():
    assert resolve_server("/etc/depictio/CLI.yaml") == "/etc/depictio/CLI.yaml"


def test_the_legacy_option_stands_in_for_server():
    assert resolve_server(None, "~/old.yaml") == "~/old.yaml"


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
