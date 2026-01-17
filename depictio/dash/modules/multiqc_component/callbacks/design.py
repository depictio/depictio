"""
Design mode callbacks for MultiQC component.

Unlike other components (card, figure), MultiQC design mode uses the same UI
and functionality as view mode. The design_multiqc() function in frontend.py
creates a complete interactive UI with module/plot/dataset selectors, and the
core callbacks handle all metadata loading and rendering.

This module exists primarily for structural consistency with other components
in the system, even though MultiQC doesn't require separate design-specific callbacks.
"""

from depictio.api.v1.configs.logging_init import logger


def register_design_callbacks(app):
    """
    Register design mode callbacks for MultiQC component.

    Note: MultiQC design mode leverages the same core callbacks used for view mode.
    The design_multiqc() function in frontend.py creates the complete interactive UI
    (module selector, plot selector, dataset selector), and the core callbacks registered
    via register_core_callbacks() handle all the metadata loading, dropdown population,
    and plot rendering.

    This pattern differs from components like Card or Figure which have distinct design
    UIs with preview functionality. MultiQC's design experience IS its view experience,
    making it a simpler integration.

    Args:
        app: Dash application instance

    Implementation Note:
    - Core callbacks handle metadata loading from WF/DC stores
    - Core callbacks populate module/plot/dataset dropdowns
    - Core callbacks render plots with theme support
    - No additional design-specific callbacks needed
    """
    logger.info("✅ MultiQC design callbacks registered (using core callbacks)")


__all__ = ["register_design_callbacks"]
