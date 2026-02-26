"""
Map Component Callbacks - Lazy Loading Pattern.

Core rendering and selection callbacks are loaded at app startup.
Design/edit callbacks are loaded on-demand when entering edit mode.
"""

_design_callbacks_loaded = False


def register_callbacks_map_component(app):
    """Register core rendering and selection callbacks for map component.

    Called at app startup for both viewer and editor apps.

    Args:
        app: Dash application instance.
    """
    from .core import register_core_callbacks
    from .selection import register_map_selection_callback
    from .theme import register_theme_callbacks

    register_core_callbacks(app)
    register_map_selection_callback(app)
    register_theme_callbacks(app)


def load_design_callbacks(app):
    """Lazy-load design and edit callbacks for map component.

    Called when a user enters edit mode (editor app).

    Args:
        app: Dash application instance.

    Returns:
        True if callbacks were loaded, False if already loaded.
    """
    global _design_callbacks_loaded

    if _design_callbacks_loaded:
        return False

    from .design import register_design_callbacks
    from .edit import register_map_edit_callback

    register_design_callbacks(app)
    register_map_edit_callback(app)
    _design_callbacks_loaded = True

    return True


__all__ = ["register_callbacks_map_component", "load_design_callbacks"]
