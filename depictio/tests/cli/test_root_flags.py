"""The root -v/-vv/--log-level flags: the level the CLI and models loggers end at."""

import io
import logging
import os
import re
import sys

import pytest
import typer
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def cli(monkeypatch):
    """The depictio_cli module, with the loggers it configures restored afterwards.

    Importing it sets DEPICTIO_CONTEXT=CLI for the whole process: monkeypatch puts
    the previous value back once the test is over.
    """
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    from depictio.cli import depictio_cli

    saved = [
        (lg, lg.level, list(lg.handlers))
        for lg in map(logging.getLogger, ("depictio-cli", "depictio-models"))
    ]
    yield depictio_cli
    for lg, level, handlers in saved:
        lg.setLevel(level)
        lg.handlers[:] = handlers


@pytest.mark.parametrize(
    ("verbose", "explicit", "expected"),
    [
        (0, None, None),
        (1, None, "INFO"),
        (2, None, "DEBUG"),
        (3, None, "DEBUG"),
        (0, "debug", "DEBUG"),
        (2, "warning", "WARNING"),
    ],
)
def test_log_level(cli, verbose, explicit, expected):
    assert cli._log_level(verbose, explicit) == expected


def test_log_level_rejects_an_unknown_level(cli):
    with pytest.raises(typer.BadParameter, match="bogus"):
        cli._log_level(0, "bogus")


@pytest.mark.parametrize(
    ("args", "level"),
    [
        ([], logging.ERROR),
        (["-v"], logging.INFO),
        (["-vv"], logging.DEBUG),
        (["--log-level", "debug"], logging.DEBUG),
        (["-vl", "DEBUG"], logging.DEBUG),
        (["-v", "-vl", "DEBUG"], logging.DEBUG),
    ],
    ids=["none", "-v", "-vv", "--log-level", "-vl", "-v -vl"],
)
def test_root_flags_set_the_log_level(cli, args, level):
    result = runner.invoke(cli.app, [*args, "version"])

    assert result.exit_code == 0, result.output
    assert logging.getLogger("depictio-cli").level == level
    # The models stay quieter by default: CRITICAL rather than ERROR.
    models = logging.CRITICAL if level == logging.ERROR else level
    assert logging.getLogger("depictio-models").level == models


def test_the_former_level_option_says_it_is_log_level(cli):
    result = runner.invoke(cli.app, ["-vl", "INFO", "version"])

    assert result.exit_code == 0, result.output
    assert "-vl/--verbose-level is now --log-level" in " ".join(result.stderr.split())


def test_the_cli_switches_load_dotenv_off(cli, tmp_path, monkeypatch):
    """MultiQC calls load_dotenv() when imported: a .env found above the installed
    package must not fill the CLI's environment, nor the local server's it starts."""
    from dotenv import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("DEPICTIO_DOTENV_PROBE=leaked\n")
    monkeypatch.delenv("DEPICTIO_DOTENV_PROBE", raising=False)

    assert not load_dotenv(env_file)
    assert "DEPICTIO_DOTENV_PROBE" not in os.environ


def test_an_unknown_log_level_is_a_usage_error(cli):
    result = runner.invoke(cli.app, ["--log-level", "bogus", "version"])

    assert result.exit_code == 2
    assert "unknown level 'bogus'" in result.output


def test_log_lines_are_short_and_plain_when_redirected(cli, monkeypatch):
    from depictio.cli.cli_logging import setup_logging

    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    logger = setup_logging(True, "DEBUG")

    logger.debug("hello")

    # No colour codes: stderr is not a terminal.
    assert re.fullmatch(
        r"\d\d:\d\d:\d\d\.\d{3} DEBUG    test_root_flags: hello\n", stderr.getvalue()
    )


def test_the_api_and_worker_keep_the_detailed_format(cli, monkeypatch):
    from depictio.cli.cli_logging import setup_logging

    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    logger = setup_logging(True, "DEBUG")

    logger.debug("hello")

    line = re.sub(r"\x1b\[[0-9;]*m", "", stderr.getvalue())
    assert re.fullmatch(
        r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} - depictio-cli - DEBUG - test_root_flags\.py"
        r" - test_the_api_and_worker_keep_the_detailed_format - line \d+ - hello\n",
        line,
    )
