"""Commands and options renamed in 1.12: still accepted, and saying what they are called now."""

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def cli(monkeypatch):
    """The depictio_cli module. Importing it sets DEPICTIO_CONTEXT=CLI for the whole
    process: monkeypatch puts the previous value back once the test is over."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    from depictio.cli import depictio_cli

    return depictio_cli


def _stderr(result) -> str:
    # Rich wraps at 80 columns under the runner: compare on normalised whitespace.
    return " ".join(result.stderr.split())


@pytest.mark.parametrize(
    ("former", "current", "args"),
    [
        ("run", "ingest", ["--template", "x/y", "--data-root", "/nonexistent"]),
        ("images push", "data push-images", ["/nonexistent", "s3://bucket/images/"]),
    ],
)
def test_a_former_command_name_says_its_new_one(cli, former, current, args):
    old = runner.invoke(cli.app, [*former.split(), *args])
    new = runner.invoke(cli.app, [*current.split(), *args])

    # Both stop at the missing directory, before reaching any server.
    assert old.exit_code == new.exit_code == 1, old.output
    assert f"{former} is now {current}: the old name still works" in _stderr(old)
    # On stderr only: a script reading the output sees what the new name prints.
    assert "is now" not in old.stdout
    assert "is now" not in new.stderr


def test_local_export_compose_says_it_is_local_export(cli, tmp_path, monkeypatch):
    from depictio.cli.cli.commands import local as local_cmd

    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
    monkeypatch.setattr(local_cmd, "export_compose", MagicMock())

    result = runner.invoke(cli.app, ["local", "export-compose", "--out", str(tmp_path / "out")])

    assert result.exit_code == 0, result.output
    assert "local export-compose is now local export" in _stderr(result)


def test_a_former_server_option_says_it_is_server(cli, tmp_path):
    missing = str(tmp_path / "CLI.yaml")

    result = runner.invoke(cli.app, ["config", "show", "--CLI-config-path", missing])

    assert "--CLI-config-path is now --server" in _stderr(result)
    # Still honoured: the file it names is the one looked for.
    assert "CLI.yaml" in result.output


def test_server_says_nothing(cli, tmp_path):
    result = runner.invoke(cli.app, ["config", "show", "--server", str(tmp_path / "CLI.yaml")])

    assert "is now" not in result.output
