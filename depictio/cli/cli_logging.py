import logging

from colorlog import ColoredFormatter

# Initialize logger without handlers
logger = logging.getLogger("depictio-cli")
logger.propagate = True  # Allow propagation to root logger


def setup_logging(verbose: bool = False, verbose_level: str = "INFO") -> logging.Logger:
    global logger

    # Clear any existing handlers
    logger.handlers.clear()
    formatter = ColoredFormatter(
        "%(log_color)s%(asctime)s%(reset)s - %(name)s - %(log_color)s%(levelname)s%(reset)s - %(filename)s - %(funcName)s - line %(lineno)d - %(message)s",
        datefmt=None,
        reset=True,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if verbose:
        level_name = logging.getLevelNamesMapping().get(verbose_level, verbose_level)
        logger.setLevel(level_name)
    else:
        logger.setLevel(logging.ERROR)  # Only show critical errors when not in verbose mode

    return logger


# Don't automatically set up logging - will be controlled by CLI
