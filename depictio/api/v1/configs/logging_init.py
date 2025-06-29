"""
Centralized logging initialization to avoid circular imports.
This module initializes both depictio-cli and depictio-models loggers
with the same verbosity settings from the global configuration.
"""

import logging
from typing import Optional

# Import the logging setup functions
from depictio.api.v1.configs.custom_logging import format_pydantic, setup_logging
from depictio.api.v1.configs.settings_models import Settings
from depictio.cli.cli.utils.rich_utils import add_rich_display_to_polars
from depictio.cli.cli_logging import setup_logging as setup_cli_logging
from depictio.models.logging import setup_logging as setup_models_logging

# Re-export format_pydantic for use by other modules
__all__ = ["logger", "initialize_loggers", "format_pydantic"]

settings = Settings()

# Create a logger for this module
logger = setup_logging(__name__, level=settings.logging.verbosity_level)


def initialize_loggers(
    verbose: Optional[bool] = True,
    verbose_level: Optional[str] = None,
) -> logging.Logger:
    """
    Initialize all loggers with consistent settings.

    Args:
        verbose: Boolean flag indicating whether verbose logging is enabled
        verbose_level: String indicating the verbosity level (DEBUG, INFO, etc.)
            If None, uses the level from settings.

    Returns:
        The configured logger instance
    """
    # Use settings verbosity level if none provided
    if verbose_level is None:
        verbose_level = settings.logging.verbosity_level

    # Ensure verbose is not None
    if verbose is None:
        verbose = True

    # Initialize loggers with the same settings
    setup_cli_logging(verbose=verbose, verbose_level=verbose_level)
    setup_models_logging(verbose=verbose, verbose_level=verbose_level)

    # Add rich display support for Polars DataFrames
    add_rich_display_to_polars()

    # Update this module's logger with the new level
    global logger
    logger = setup_logging(__name__, level=verbose_level)

    return logger
