"""An API module imported inside a CLI command keeps to the CLI's log level."""

import logging

from depictio.cli.cli_logging import setup_logging


def test_initialize_loggers_leaves_the_cli_level_alone(monkeypatch):
    from depictio.api.v1.configs import logging_init

    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    setup_logging(verbose=False)  # what a command without -v sets: ERROR

    api_logger = logging_init.initialize_loggers(verbose=True, verbose_level="DEBUG")

    assert logging.getLogger("depictio-cli").level == logging.ERROR
    assert not api_logger.isEnabledFor(logging.INFO)


def test_on_the_server_it_still_sets_every_logger(monkeypatch):
    from depictio.api.v1.configs import logging_init

    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    setup_logging(verbose=False)

    logging_init.initialize_loggers(verbose=True, verbose_level="DEBUG")

    assert logging.getLogger("depictio-cli").level == logging.DEBUG
