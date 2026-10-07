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


# What `data scan` and `data process` exit with: a pipeline runs them one step at a
# time, and a step that went wrong must not look like one that worked.


@pytest.mark.parametrize("command", ["scan", "process"])
def test_a_project_configuration_that_fails_validation_exits_1(command, validate):
    assert runner.invoke(app, [command]).exit_code == 1


def _remote(status_code: int, hash_: str = "same") -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.json.return_value = {"hash": hash_}
    return response


@pytest.fixture
def validated():
    """A validation that passes, with a project whose local hash is 'same'."""
    project = MagicMock(hash="same")
    mock = MagicMock(return_value=(MagicMock(), {"success": True, "project_config": project}))
    with patch("depictio.cli.cli.commands.data.validate_project_config_and_check_S3_storage", mock):
        yield mock


@pytest.mark.parametrize("command", ["scan", "process"])
@pytest.mark.parametrize(
    "remote", [_remote(404), _remote(200, hash_="other")], ids=["not on server", "out of sync"]
)
def test_a_project_the_server_does_not_match_exits_1(command, remote, validated):
    with (
        patch("depictio.cli.cli.commands.data.api_get_project_from_name", return_value=remote),
        patch("depictio.cli.cli.commands.data.api_get_project_from_id", return_value=remote),
        patch("depictio.cli.cli.commands.data.process_project_helper") as helper,
    ):
        result = runner.invoke(app, [command])

    assert result.exit_code == 1, result.output
    helper.assert_not_called()


@pytest.mark.parametrize(("outcome", "exit_code"), [("success", 0), ("partial", 1)])
def test_process_exits_1_when_a_data_collection_failed(outcome, exit_code, validated):
    with (
        patch("depictio.cli.cli.commands.data.api_get_project_from_id", return_value=_remote(200)),
        patch(
            "depictio.cli.cli.commands.data.process_project_helper",
            return_value={"result": outcome},
        ),
    ):
        result = runner.invoke(app, ["process"])

    assert result.exit_code == exit_code, result.output
