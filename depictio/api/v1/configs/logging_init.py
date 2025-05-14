"""
Centralized logging initialization to avoid circular imports.
This module initializes both depictio-cli and depictio-models loggers
with the same verbosity settings from the global configuration.
"""

from typing import Optional

# Import the logging setup functions
from depictio.api.v1.configs.custom_logging import setup_logging
from depictio.cli.cli_logging import setup_logging as setup_cli_logging
from depictio.models.logging import setup_logging as setup_models_logging


def initialize_loggers(
    verbose: Optional[bool] = None,
    verbose_level: Optional[str] = None,
) -> None:
    """
    Initialize all loggers with consistent settings.

    Args:
        verbose: Boolean flag indicating whether verbose logging is enabled
        verbose_level: String indicating the verbosity level (DEBUG, INFO, etc.)
    """
    # Initialize loggers with the same settings
    setup_cli_logging(verbose=verbose, verbose_level=verbose_level)
    setup_models_logging(verbose=verbose, verbose_level=verbose_level)
    logger = setup_logging(__name__, level=verbose_level)
    return logger
