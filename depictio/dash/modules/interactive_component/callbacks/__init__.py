"""
Interactive Component Callbacks - Lazy Loading Pattern

This module implements a lazy loading pattern where:
- Core clientside callback is always loaded at app startup
- Design/edit mode UI functions are loaded on-demand when entering edit mode

This reduces initial import time and improves app startup performance.
"""

# Track if design callbacks have been registered
_design_callbacks_loaded = False


def register_callbacks_interactive_component(app):
    """
    Register core callbacks for interactive component.

    This function is called at app startup and registers:
    - Clientside filter reset callback
    - Serverside async rendering callback (skeleton → populated component)
    - Serverside interactivity store update callback (values aggregation)

    Args:
        app: Dash application instance
    """
    from .core import register_core_callbacks
    from .core_async import register_async_rendering_callback
    from .core_interactivity import register_store_update_callback

    register_core_callbacks(app)
    register_async_rendering_callback(app)
    register_store_update_callback(app)


def load_design_callbacks(app):
    """
    Lazy-load design callbacks for interactive component.

    Currently, interactive component has no server-side design callbacks,
    only UI creation functions. This function is kept for consistency
    and future extensibility.

    Args:
        app: Dash application instance

    Returns:
        bool: True if callbacks were loaded, False if already loaded
    """
    global _design_callbacks_loaded

    if _design_callbacks_loaded:
        return False

    # No design callbacks to register for interactive component yet
    # (all design callbacks are currently commented out in original code)

    _design_callbacks_loaded = True

    return True
