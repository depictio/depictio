"""
Centralized helper utilities for background callback configuration.

This module provides a consistent way to check whether background callbacks
are enabled for DASHBOARD VIEW/EDIT MODE callbacks.

IMPORTANT: This only applies to dashboard view/edit mode (core.py callbacks).
Component design/editing mode (render.py callbacks) ALWAYS uses background callbacks
and is not controlled by this configuration.
"""

import os

# Read the environment variable once at module load
_USE_BACKGROUND_CALLBACKS = os.getenv("DEPICTIO_CELERY_ENABLED", "false").lower() == "true"


def use_background_callbacks() -> bool:
    """
    Check if background callbacks are enabled for dashboard view/edit mode.

    NOTE: This only affects dashboard view/edit mode callbacks (core.py).
    Design mode callbacks (render.py) always use background=True regardless.

    Returns:
        bool: True if DEPICTIO_CELERY_ENABLED=true, False otherwise

    Example:
        >>> from depictio.dash.background_callback_helpers import use_background_callbacks
        >>> # For dashboard view/edit mode callbacks only:
        >>> @app.callback(..., background=use_background_callbacks())
    """
    return _USE_BACKGROUND_CALLBACKS


def should_use_background_for_component(component_type: str) -> bool:
    """
    Determine if a specific component type should use background callbacks.

    Currently applies background callbacks to:
    - card: Initial render and filter patches
    - figure: Initial render and filter patches

    Args:
        component_type: Component type ('card', 'figure', 'table', etc.)

    Returns:
        bool: True if component should use background callbacks when enabled

    Example:
        >>> background_enabled = should_use_background_for_component('card')
        >>> @app.callback(..., background=background_enabled)
    """
    # Components that benefit from background callbacks
    # (long-running data loading operations)
    background_compatible_components = {"card", "figure", "table"}

    if component_type in background_compatible_components:
        return use_background_callbacks()

    return False


def log_background_callback_status(component_type: str, callback_name: str):
    """
    Log the background callback status for a component's callback.

    No-op in production to reduce log verbosity.

    Args:
        component_type: Component type ('card', 'figure', etc.)
        callback_name: Name of the callback being registered
    """
    pass


# Log overall background callback status at module load
# Background callback status determined by DEPICTIO_CELERY_ENABLED environment variable
