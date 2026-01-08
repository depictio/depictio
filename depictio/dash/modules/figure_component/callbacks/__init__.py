"""
Figure Component Callbacks - Compatibility Layer

This module provides backward compatibility by re-exporting callbacks from frontend.py.
The callbacks were moved to frontend.py during refactoring, but this maintains the old import paths.
"""

from depictio.dash.modules.figure_component.frontend import (
    register_callbacks_figure_component,
)


# For lazy loading pattern compatibility
def load_design_callbacks(app):
    """
    Lazy-load design callbacks for figure component.

    Note: Figure component callbacks are registered all at once in register_callbacks_figure_component.
    This function exists for compatibility with the lazy loading pattern.
    """
    # Figure component doesn't use lazy loading currently
    # All callbacks are registered in register_callbacks_figure_component
    return False


__all__ = ["register_callbacks_figure_component", "load_design_callbacks"]
