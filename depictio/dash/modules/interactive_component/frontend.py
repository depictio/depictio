"""
Interactive Component - Frontend (DEPRECATED - Backward Compatibility Layer)

This module is deprecated and maintained only for backward compatibility.
New code should import from:
- depictio.dash.modules.interactive_component.callbacks for callback registration
- depictio.dash.modules.interactive_component.design_ui for UI creation functions

The module has been split to enable lazy loading of design-mode functionality.

Module Structure:
- callbacks/__init__.py - Lazy loading coordinator
- callbacks/core.py - Core clientside callback (always loaded)
- design_ui.py - Design UI creation (lazy loaded)
"""

import warnings

# Re-export for backward compatibility
from depictio.dash.modules.interactive_component.callbacks import (
    load_design_callbacks,
    register_callbacks_interactive_component,
)
from depictio.dash.modules.interactive_component.design_ui import (
    create_stepper_interactive_button,
    design_interactive,
)

# Warn users about deprecation
warnings.warn(
    "depictio.dash.modules.interactive_component.frontend is deprecated. "
    "Use depictio.dash.modules.interactive_component.callbacks or design_ui instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "register_callbacks_interactive_component",
    "load_design_callbacks",
    "design_interactive",
    "create_stepper_interactive_button",
]
