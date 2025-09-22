"""
Selector module to choose between original draggable.py and minimal version.
Allows easy switching between complex grid layout and simple row layout.
"""

import os

from depictio.api.v1.configs.logging_init import logger


def get_draggable_layout(
    init_layout: dict,
    init_children: list[dict],
    dashboard_id: str,
    local_data: dict,
    cached_project_data: dict | None = None,
    force_minimal: bool = False,
):
    """
    Get the appropriate draggable layout based on configuration.

    Args:
        force_minimal: If True, forces use of minimal layout regardless of env vars
        Other args: Same as design_draggable functions

    Returns:
        Layout component (original or minimal)
    """

    # Check environment variable or force flag
    use_minimal = (
        force_minimal or os.getenv("DEPICTIO_USE_MINIMAL_DRAGGABLE", "false").lower() == "true"
    )

    if use_minimal:
        logger.info("🔧 SELECTOR: Using minimal draggable layout")
        from depictio.dash.layouts.draggable_minimal import design_draggable_minimal

        return design_draggable_minimal(
            init_layout=init_layout,
            init_children=init_children,
            dashboard_id=dashboard_id,
            local_data=local_data,
            cached_project_data=cached_project_data,
        )
    else:
        logger.info("🔧 SELECTOR: Using original draggable layout")
        from depictio.dash.layouts.draggable import design_draggable

        return design_draggable(
            init_layout=init_layout,
            init_children=init_children,
            dashboard_id=dashboard_id,
            local_data=local_data,
            cached_project_data=cached_project_data,
        )


def register_draggable_callbacks(app, use_minimal: bool | None = None):
    """
    Register appropriate callbacks based on layout type.

    Args:
        app: Dash app instance
        use_minimal: If True, registers minimal callbacks. If None, checks env var.
    """

    if use_minimal is None:
        use_minimal = os.getenv("DEPICTIO_USE_MINIMAL_DRAGGABLE", "false").lower() == "true"

    if use_minimal:
        logger.info("🔧 SELECTOR: Registering minimal draggable callbacks")
        from depictio.dash.layouts.draggable_minimal import register_minimal_callbacks

        register_minimal_callbacks(app)
    else:
        logger.info("🔧 SELECTOR: Registering original draggable callbacks")
        from depictio.dash.layouts.draggable import register_callbacks_draggable

        register_callbacks_draggable(app)
