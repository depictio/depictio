"""
Card Component - Frontend (DEPRECATED - Backward Compatibility Layer)

This module is deprecated and maintained only for backward compatibility.
New code should import from:
- depictio.dash.modules.card_component.callbacks for callback registration
- depictio.dash.modules.card_component.design_ui for UI creation functions

The module has been split to enable lazy loading of design-mode functionality,
reducing initial app startup time from ~1954ms to ~350ms.

Module Structure:
- callbacks/__init__.py - Lazy loading coordinator
- callbacks/core.py - Core rendering callbacks (always loaded)
- callbacks/design.py - Design/edit mode callbacks (lazy loaded)
- design_ui.py - Design UI creation (lazy loaded)
"""

import warnings

# Re-export for backward compatibility
from depictio.dash.modules.card_component.callbacks import (
    load_design_callbacks,
    register_callbacks_card_component,
)
from depictio.dash.modules.card_component.design_ui import (
    create_stepper_card_button,
    design_card,
)

# Warn users about deprecation
warnings.warn(
    "depictio.dash.modules.card_component.frontend is deprecated. "
    "Use depictio.dash.modules.card_component.callbacks or design_ui instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "register_callbacks_card_component",
    "load_design_callbacks",
    "design_card",
    "create_stepper_card_button",
]
