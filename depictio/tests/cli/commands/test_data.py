"""`depictio data`: the server each command talks to.

Every command takes --server ('local' or a CLI configuration file) and, out of the
help, the --CLI-config-path it replaced. The configuration they resolve to is what
the project validation, the first thing each command does, is handed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands.data import app, link_app

runner = CliRunner()

# Each command, with what it needs besides the server to reach the validation.
COMMANDS = [
    (app, ["scan"]),
    (app, ["process"]),
    (app, ["join"]),
    (link_app, ["list"]),
    (link_app, ["delete", "--link-id", "abc", "--force"]),
]
IDS = ["scan", "process", "join", "link list", "link delete"]


@pytest.fixture
def validate():
    """The validation, failing, so each command stops right after it."""
    mock = MagicMock(return_value=(MagicMock(), {"success": False}))
    with patch("depictio.cli.cli.commands.data.validate_project_config_and_check_S3_storage", mock):
        yield mock


@pytest.mark.parametrize(("cli_app", "command"), COMMANDS, ids=IDS)
def test_server_is_the_configuration_used(cli_app, command, validate):
    runner.invoke(cli_app, [*command, "--server", "/srv/CLI.yaml"])

    assert validate.call_args.kwargs["CLI_config_path"] == "/srv/CLI.yaml"


@pytest.mark.parametrize(("cli_app", "command"), COMMANDS, ids=IDS)
def test_the_former_option_still_names_it(cli_app, command, validate):
    runner.invoke(cli_app, [*command, "--CLI-config-path", "/srv/old.yaml"])

    assert validate.call_args.kwargs["CLI_config_path"] == "/srv/old.yaml"


def test_without_either_the_default_applies(validate):
    runner.invoke(app, ["scan"])

    # Left as the default, so DEPICTIO_CLI_CONFIG_PATH can still stand in for it.
    assert validate.call_args.kwargs["CLI_config_path"] == "~/.depictio/CLI.yaml"


def test_both_together_are_refused(validate):
    result = runner.invoke(app, ["scan", "--server", "a.yaml", "--CLI-config-path", "b.yaml"])

    assert result.exit_code == 2
    validate.assert_not_called()


@pytest.mark.parametrize("command", ["scan", "process", "join", "push-images"])
def test_the_help_shows_server_not_the_former_option(command):
    result = runner.invoke(app, [command, "--help"], terminal_width=200)

    assert "--server" in result.output
    assert "--CLI-config-path" not in result.output
