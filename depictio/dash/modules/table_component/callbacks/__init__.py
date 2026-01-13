"""
Table Component Callbacks - Lazy Loading Pattern

This module implements a lazy loading pattern where:
- Core rendering callbacks are always loaded at app startup (view mode)
- Design/edit mode callbacks will be loaded on-demand when entering edit mode (Phase 2 - future PR)

This follows the same pattern as card and figure components to reduce
initial import time and improve app startup performance.

Phase 1: View mode only - infinite scroll, filtering, sorting, theme support
Phase 2: Edit mode - design UI, parameter selection, save functionality (future)
"""

# Track if design callbacks have been registered
_design_callbacks_loaded = False


def register_callbacks_table_component(app):
    """
    Register core rendering callbacks for table component.

    This function is called at app startup and only registers callbacks
    needed for viewing dashboards (view mode), not for editing/designing tables.

    Args:
        app: Dash application instance
    """
    from .core import register_core_callbacks

    register_core_callbacks(app)


def load_design_callbacks(app):
    """
    Lazy-load design and edit callbacks for table component.

    This function is called when a user enters edit mode (edit page or stepper).
    It loads the design UI creation functions and registers design-related callbacks
    as well as the edit save callback.

    NOTE: This is a placeholder for future PR implementing edit mode restoration.

    Args:
        app: Dash application instance

    Returns:
        bool: True if callbacks were loaded, False if already loaded
    """
    global _design_callbacks_loaded

    if _design_callbacks_loaded:
        return False

    # TODO: Implement in future PR (edit mode restoration)
    # from .design import register_design_callbacks
    # from .edit import register_table_edit_callback
    #
    # register_design_callbacks(app)
    # register_table_edit_callback(app)

    _design_callbacks_loaded = True

    return True


__all__ = ["register_callbacks_table_component", "load_design_callbacks"]
