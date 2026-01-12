"""
Figure Component Callbacks - Lazy Loading Pattern

This module implements a lazy loading pattern where:
- Core rendering callbacks are always loaded at app startup (view mode)
- Design/edit mode callbacks are loaded on-demand when entering edit mode (Phase 2)

This follows the same pattern as card and interactive components to reduce
initial import time and improve app startup performance.

Phase 1: View mode only - basic rendering, filtering, theme support
Phase 2: Edit mode - design UI, parameter selection, save functionality (future)
"""

# Track if design callbacks have been registered
_design_callbacks_loaded = False


def register_callbacks_figure_component(app):
    """
    Register core rendering callbacks for figure component.

    This function is called at app startup and only registers callbacks
    needed for viewing dashboards (view mode), not for editing/designing figures.

    Args:
        app: Dash application instance
    """
    from .core import register_core_callbacks

    register_core_callbacks(app)


def load_design_callbacks(app):
    """
    Lazy-load design and edit callbacks for figure component.

    This function is called when a user enters edit mode (edit page or stepper).
    It loads the design UI creation functions and registers design-related callbacks
    as well as the edit save callback.

    Args:
        app: Dash application instance

    Returns:
        bool: True if callbacks were loaded, False if already loaded
    """
    global _design_callbacks_loaded

    if _design_callbacks_loaded:
        return False

    from .design import register_design_callbacks
    from .edit import register_figure_edit_callback
    from .render import register_render_callbacks
    from .ui import register_ui_callbacks

    register_design_callbacks(app)
    register_figure_edit_callback(app)
    register_ui_callbacks(app)
    register_render_callbacks(app)
    _design_callbacks_loaded = True

    return True


__all__ = ["register_callbacks_figure_component", "load_design_callbacks"]
