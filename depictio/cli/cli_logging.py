import logging

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
        logger.setLevel(logging.ERROR)  # Only show critical errors when not in verbose mode

    return logger


# Don't automatically set up logging - will be controlled by CLI
