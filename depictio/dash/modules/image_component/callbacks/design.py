"""
Image Component - Design Mode Callbacks

Callbacks for the design/stepper interface when creating or editing an image component.
Lazy-loaded only when entering edit mode.
"""

from __future__ import annotations

from typing import Any

import dash
from dash import MATCH, Input, Output, State, ctx

from depictio.dash.modules.image_component.utils import build_image


def register_design_callbacks(app):
    """Register design mode callbacks for image component."""

    @app.callback(
        Output({"type": "component-container", "index": MATCH}, "children"),
        Input({"type": "image-input", "index": MATCH}, "value"),
        Input({"type": "image-dropdown-column", "index": MATCH}, "value"),
        Input({"type": "image-s3-base-folder", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        State({"type": "image-input", "index": MATCH}, "id"),
        prevent_initial_call=False,
    )
    def update_image_preview(
        title: str | None,
        image_column: str | None,
        s3_base_folder: str | None,
        wf_id: str | None,
        dc_id: str | None,
        component_id: dict[str, str],
    ) -> Any:
        """Update the image preview when design form values change."""
        # Early return if no component triggered (switching to non-image component)
        if not ctx.triggered_id:
            raise dash.exceptions.PreventUpdate

        # Validate that image component exists (title is required field)
        if title is None:
            raise dash.exceptions.PreventUpdate

        return build_image(
            index=component_id.get("index", ""),
            title=title or "Image Gallery",
            wf_id=wf_id,
            dc_id=dc_id,
            image_column=image_column,
            s3_base_folder=s3_base_folder,
            thumbnail_size=150,
            columns=4,
            max_images=20,
            build_frame=True,
            stepper=True,
        )
