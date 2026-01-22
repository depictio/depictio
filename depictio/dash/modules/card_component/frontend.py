"""
Card Component - Frontend (DEPRECATED - Backward Compatibility Layer).

This module is deprecated and maintained only for backward compatibility.
New code should import directly from the appropriate submodules:

- For callback registration:
    from depictio.dash.modules.card_component.callbacks import (
        register_callbacks_card_component,
        load_design_callbacks,
    )

- For UI creation functions:
    from depictio.dash.modules.card_component.design_ui import (
        design_card,
        create_stepper_card_button,
    )

The module was split to enable lazy loading of design-mode functionality,
reducing initial app startup time significantly (from ~1954ms to ~350ms).

Module Structure:
    callbacks/__init__.py - Lazy loading coordinator
    callbacks/core.py - Core rendering callbacks (always loaded)
    callbacks/design.py - Design/edit mode callbacks (lazy loaded)
    design_ui.py - Design UI creation (lazy loaded)

Deprecated:
    This module will be removed in a future version. Update imports to use
    the new module structure.
"""

import warnings

from depictio.dash.modules.card_component.callbacks import (
    load_design_callbacks,
    register_callbacks_card_component,
)
from depictio.dash.modules.card_component.design_ui import (
    create_stepper_card_button,
    design_card,
)

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
