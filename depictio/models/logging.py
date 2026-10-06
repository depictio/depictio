import logging
import os
from typing import TextIO

from colorlog import ColoredFormatter

# Initialize logger without handlers
logger = logging.getLogger("depictio-models")
logger.propagate = True  # Prevent propagation to root logger

# The CLI prints one short line per record: time, level, the module that logged, the
# message. The API and the worker keep the date and the code location, which their logs
# need when they are read long after the fact.
CLI_FORMAT = "%(asctime)s.%(msecs)03d %(log_color)s%(levelname)-8s%(reset)s %(module)s: %(message)s"
SERVER_FORMAT = "%(log_color)s%(asctime)s%(reset)s - %(name)s - %(log_color)s%(levelname)s%(reset)s - %(filename)s - %(funcName)s - line %(lineno)d - %(message)s"
LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red,bg_white",
}


def make_formatter(stream: TextIO) -> ColoredFormatter:
    """The formatter for a handler writing to ``stream``, in the CLI or server format."""
    if os.getenv("DEPICTIO_CONTEXT", "server").lower() == "cli":
        # No escape codes when stderr is redirected to a file or a pipe.
        return ColoredFormatter(
            CLI_FORMAT, datefmt="%H:%M:%S", reset=True, log_colors=LOG_COLORS, stream=stream
        )
    return ColoredFormatter(SERVER_FORMAT, datefmt=None, reset=True, log_colors=LOG_COLORS)


def setup_logging(verbose: bool = False, verbose_level: str = "INFO") -> logging.Logger:
    global logger

    # Clear any existing handlers
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(make_formatter(handler.stream))
    logger.addHandler(handler)
    if verbose:
        level_name = logging.getLevelNamesMapping().get(verbose_level, verbose_level)  # type: ignore[attr-defined]
        logger.setLevel(level_name)
    else:
        logger.setLevel(logging.CRITICAL)  # Only show critical errors when not in verbose mode

    return logger


# Don't automatically set up logging - will be controlled by CLI
