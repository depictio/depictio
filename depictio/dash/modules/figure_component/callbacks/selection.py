"""
Figure Component - Scatter Selection Callback

This module handles scatter plot selection events (point click, lasso, rectangle)
and updates the interactive-values-store to enable cross-component filtering.

The callback listens to:
- selectedData: Triggered by lasso/rectangle selection
- clickData: Triggered by point click

Selection data is added to interactive-values-store with source="scatter_selection"
to distinguish it from regular interactive components (dropdowns, sliders).
"""

from typing import Any

import dash
from dash import ALL, Input, Output, State

from depictio.api.v1.configs.logging_init import logger


def extract_scatter_selection_values(
    selected_data: dict[str, Any] | None,
    click_data: dict[str, Any] | None,
    selection_column_index: int,
) -> list[Any]:
    """Extract values from scatter selection customdata.

    Handles both lasso/rectangle (selectedData) and point click (clickData).
    Uses customdata array index to extract the selection column value.

    Args:
        selected_data: Data from selectedData property (lasso/rectangle selection)
        click_data: Data from clickData property (point click)
        selection_column_index: Index of selection column in customdata array

    Returns:
        List of unique values extracted from selection

    Example:
        selectedData structure:
        {
            "points": [
                {"pointIndex": 0, "customdata": ["sample1", "cluster_a"]},
                {"pointIndex": 1, "customdata": ["sample2", "cluster_b"]},
            ]
        }

        With selection_column_index=0, returns ["sample1", "sample2"]
    """
    values: set[Any] = set()

    # Priority: selectedData (lasso/rect) over clickData (single point)
    data_to_process = selected_data if selected_data else click_data

    if not data_to_process:
        return []

    points = data_to_process.get("points", [])

    for point in points:
        customdata = point.get("customdata")
        if customdata is None:
            continue

        # Handle both single value and array customdata
        if isinstance(customdata, list):
            if selection_column_index < len(customdata):
                value = customdata[selection_column_index]
                if value is not None:
                    values.add(value)
        else:
            # Single value customdata
            if selection_column_index == 0:
                values.add(customdata)

    return list(values)


def register_scatter_selection_callback(app):
    """Register callback to capture scatter plot selections.

    This callback listens to selectedData (lasso/rectangle) and clickData (point click)
    from all figure-graph components and updates the interactive-values-store.

    The store is extended with selection entries that have source="scatter_selection"
    to distinguish them from regular interactive components.

    Also handles reset button clicks to clear selections.

    Args:
        app: Dash application instance
    """

    logger.info("Registering scatter selection callback")

    @app.callback(
        Output("interactive-values-store", "data", allow_duplicate=True),
        Input({"type": "figure-graph", "index": ALL}, "selectedData"),
        Input({"type": "figure-graph", "index": ALL}, "clickData"),
        Input({"type": "reset-selection-graph-button", "index": ALL}, "n_clicks"),
        State({"type": "figure-graph", "index": ALL}, "id"),
        State({"type": "reset-selection-graph-button", "index": ALL}, "id"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "id"),
        State("interactive-values-store", "data"),
        prevent_initial_call=True,
    )
    def update_store_from_scatter_selection(
        selected_data_list: list[dict[str, Any] | None],
        click_data_list: list[dict[str, Any] | None],
        reset_clicks_list: list[int | None],
        figure_ids: list[dict[str, str]],
        reset_button_ids: list[dict[str, str]],
        metadata_list: list[dict[str, Any] | None],
        metadata_ids: list[dict[str, str]],
        current_store: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Update interactive-values-store with scatter selection data.

        This callback merges scatter selection data into the existing store,
        preserving values from regular interactive components while adding
        selection-based filters.

        Also handles reset button clicks to clear selections for specific components.

        Args:
            selected_data_list: List of selectedData from all figures (lasso/rect)
            click_data_list: List of clickData from all figures (point click)
            reset_clicks_list: List of reset button click counts
            figure_ids: List of figure component IDs
            reset_button_ids: List of reset button IDs
            metadata_list: List of stored metadata for all components
            metadata_ids: List of metadata store IDs
            current_store: Current interactive-values-store data

        Returns:
            Updated store data with selection filters
        """
        from dash import ctx

        # Initialize store if needed
        if current_store is None:
            current_store = {"interactive_components_values": [], "first_load": False}

        # Check if this callback was triggered by a reset button
        triggered_id = ctx.triggered_id
        if (
            isinstance(triggered_id, dict)
            and triggered_id.get("type") == "reset-selection-graph-button"
        ):
            reset_index = triggered_id.get("index")
            logger.info(
                f"Scatter selection reset triggered for component {reset_index[:8] if reset_index else 'None'}"
            )

            # Remove scatter_selection entries for this component
            filtered_values = [
                v
                for v in current_store.get("interactive_components_values", [])
                if not (v.get("source") == "scatter_selection" and v.get("index") == reset_index)
            ]

            return {
                "interactive_components_values": filtered_values,
                "first_load": False,
            }

        logger.info(
            f"Scatter selection callback triggered: "
            f"{len(figure_ids)} figures, "
            f"selectedData={[bool(s) for s in selected_data_list]}, "
            f"clickData={[bool(c) for c in click_data_list]}"
        )

        # Build metadata lookup by component index
        metadata_by_index: dict[str, dict[str, Any]] = {}
        for i, meta_id in enumerate(metadata_ids):
            if i < len(metadata_list) and metadata_list[i]:
                index = meta_id.get("index") if isinstance(meta_id, dict) else str(meta_id)
                metadata_by_index[index] = metadata_list[i]
                # Debug: log what metadata we found
                meta = metadata_list[i]
                logger.debug(
                    f"  Metadata for index {index[:8] if index else 'None'}: "
                    f"component_type={meta.get('component_type')}, "
                    f"selection_enabled={meta.get('selection_enabled')}, "
                    f"selection_column={meta.get('selection_column')}"
                )

        # Initialize store if needed
        if current_store is None:
            current_store = {"interactive_components_values": [], "first_load": False}

        # Get existing values (non-selection sources)
        existing_values = [
            v
            for v in current_store.get("interactive_components_values", [])
            if v.get("source") != "scatter_selection"
        ]

        # Process each figure for selection data
        selection_values: list[dict[str, Any]] = []
        has_any_selection = False

        for i, fig_id in enumerate(figure_ids):
            fig_index = fig_id.get("index") if isinstance(fig_id, dict) else str(fig_id)

            # Get metadata for this figure
            metadata = metadata_by_index.get(fig_index, {})

            # Check if selection is enabled for this figure
            selection_enabled = metadata.get("selection_enabled", False)
            selection_column = metadata.get("selection_column")

            # Debug: log selection check for figures with selection data
            has_selection_data = (i < len(selected_data_list) and selected_data_list[i]) or (
                i < len(click_data_list) and click_data_list[i]
            )
            if has_selection_data:
                if not metadata:
                    logger.warning(
                        f"  Figure {fig_index[:8] if fig_index else 'None'}: "
                        f"has selection data but NO METADATA FOUND! "
                        f"Available metadata indices: {list(metadata_by_index.keys())[:5]}..."
                    )
                else:
                    logger.info(
                        f"  Figure {fig_index[:8] if fig_index else 'None'}: "
                        f"has selection data, selection_enabled={selection_enabled}, "
                        f"selection_column={selection_column}, "
                        f"component_type={metadata.get('component_type')}"
                    )

            if not selection_enabled or not selection_column:
                continue

            # Get selection data
            selected_data = selected_data_list[i] if i < len(selected_data_list) else None
            click_data = click_data_list[i] if i < len(click_data_list) else None

            # Get selection_column_index from metadata (defaults to 0)
            selection_column_index = metadata.get("selection_column_index", 0)

            # Extract values from selection
            values = extract_scatter_selection_values(
                selected_data, click_data, selection_column_index
            )

            if values:
                has_any_selection = True
                selection_values.append(
                    {
                        "index": fig_index,
                        "value": values,
                        "source": "scatter_selection",
                        "column_name": selection_column,
                        "dc_id": metadata.get("dc_id"),
                    }
                )
                logger.debug(f"Scatter selection: {len(values)} values from figure {fig_index[:8]}")

        # If no selection data changed and we have no new selections, prevent update
        if not has_any_selection:
            # Check if we had previous selections that should now be cleared
            had_previous_selections = any(
                v.get("source") == "scatter_selection"
                for v in current_store.get("interactive_components_values", [])
            )
            if not had_previous_selections:
                raise dash.exceptions.PreventUpdate

        # Merge existing values with new selection values
        merged_values = existing_values + selection_values

        return {
            "interactive_components_values": merged_values,
            "first_load": False,
        }
