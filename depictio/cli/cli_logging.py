import contextlib
import logging
from collections.abc import Iterator

# Same format as the models logger, whose records interleave with these.
from depictio.models.logging import make_formatter

# Initialize logger without handlers
logger = logging.getLogger("depictio-cli")
logger.propagate = True  # Allow propagation to root logger


def setup_logging(verbose: bool = False, verbose_level: str = "INFO") -> logging.Logger:
    global logger

    # Clear any existing handlers
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(make_formatter(handler.stream))
    logger.addHandler(handler)
    if verbose:
        level_name = logging.getLevelNamesMapping().get(verbose_level, verbose_level)
        logger.setLevel(level_name)
    else:
        # A safety net: a failure the user is told about with a ✗ line is logged at
        # DEBUG, so ERROR records are the failures nothing else reports.
        logger.setLevel(logging.ERROR)

    return logger


@contextlib.contextmanager
def multiqc_logging(quiet_level: int = logging.WARNING) -> Iterator[None]:
    """Run MultiQC with its logs kept to what the CLI shows.

    Unless -v asked for logs, MultiQC's loggers drop records below ``quiet_level``: it
    logs at INFO each report it reads ("file_search | Search path: ..."). And
    ``multiqc.parse_logs`` replaces the root logger's handlers with a stderr handler of
    its own. The root logger is put back on the way out, or every record of the CLI,
    which propagates there, would print a second time in MultiQC's format.
    """
    root = logging.getLogger()
    root_handlers, root_level = root.handlers[:], root.level
    multiqc_logger = logging.getLogger("multiqc")
    multiqc_level = multiqc_logger.level
    if not logger.isEnabledFor(logging.INFO):
        multiqc_logger.setLevel(quiet_level)
    try:
        yield
    finally:
        root.handlers[:] = root_handlers
        root.setLevel(root_level)
        multiqc_logger.setLevel(multiqc_level)


# Don't automatically set up logging - will be controlled by CLI
