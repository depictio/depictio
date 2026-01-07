"""
Card Component Callbacks - Lazy Loading Pattern

This module implements a lazy loading pattern where:
- Core rendering callbacks are always loaded at app startup
- Design/edit mode callbacks are loaded on-demand when entering edit mode

This reduces initial import time from ~1954ms to ~350ms.
"""

# Track if design callbacks have been registered
_design_callbacks_loaded = False


def register_callbacks_card_component(app):
    """
    Register core rendering callbacks for card component.

    This function is called at app startup and only registers callbacks
    needed for viewing dashboards, not for editing/designing cards.

    Args:
        app: Dash application instance
    """
    from .core import register_core_callbacks

    register_core_callbacks(app)


def load_design_callbacks(app):
    """
    Lazy-load design and edit callbacks for card component.

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
    from .edit import register_card_edit_callback

    register_design_callbacks(app)
    register_card_edit_callback(app)
    _design_callbacks_loaded = True

    return True
