"""
Figure Component - Scatter Selection Callback

This module handles scatter plot selection events (point click, lasso, rectangle)
and updates the interactive-values-store to enable cross-component filtering.

The callback listens to:
- selectedData: Triggered by lasso/rectangle selection
- clickData: Triggered by point click
- reset button: Clears selection from store

Selection data is added to interactive-values-store with source="scatter_selection"
to distinguish it from regular interactive components (dropdowns, sliders).
"""

from typing import Any

import dash
from dash import ALL, Input, Output, State, ctx

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.shared.selection_utils import (
    build_metadata_lookup,
    create_selection_entry,
    filter_existing_values,
    handle_reset_button,
    initialize_store,
    merge_selection_values,
    should_prevent_update,
)

# Constants for this selection type
BUTTON_TYPE = "reset-selection-graph-button"
SOURCE_TYPE = "scatter_selection"


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
        Input({"type": BUTTON_TYPE, "index": ALL}, "n_clicks"),
        State({"type": "figure-graph", "index": ALL}, "id"),
        State({"type": BUTTON_TYPE, "index": ALL}, "id"),
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
        """Update interactive-values-store with scatter selection data."""
        current_store = initialize_store(current_store)

        # Check if this callback was triggered by a reset button
        reset_result = handle_reset_button(
            ctx.triggered_id, BUTTON_TYPE, SOURCE_TYPE, current_store
        )
        if reset_result is not None:
            return reset_result

        # Debug: log trigger info
        triggered_prop = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None

        logger.info(
            f"Scatter selection callback: {len(figure_ids)} figures, "
            f"selectedData={[bool(s) for s in selected_data_list]}, "
            f"clickData={[bool(c) for c in click_data_list]}, "
            f"trigger={triggered_prop}"
        )

        # Guard: When selectedData or clickData becomes None (figure re-render),
        # ALWAYS prevent update. This is never a user action - it's Plotly clearing
        # state after the figure was re-rendered. Allowing it to propagate creates
        # a circular dependency: store -> figure update -> None selection -> store write -> loop.
        is_clearing_trigger = (
            "selectedData" in triggered_prop or "clickData" in triggered_prop
        ) and not triggered_value
        if is_clearing_trigger:
            logger.info(
                f"Scatter selection: Ignoring clearing trigger ({triggered_prop}), "
                f"preventing circular update"
            )
            raise dash.exceptions.PreventUpdate

        # Build metadata lookup
        metadata_by_index = build_metadata_lookup(metadata_list, metadata_ids)

        # Get existing values (non-scatter-selection sources)
        existing_values = filter_existing_values(current_store, SOURCE_TYPE)

        # Get existing scatter selections (to preserve on re-render)
        existing_scatter_by_index: dict[str, dict[str, Any]] = {}
        for v in current_store.get("interactive_components_values", []):
            if v.get("source") == SOURCE_TYPE:
                existing_scatter_by_index[v.get("index", "")] = v

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

            # Handle re-render case: selectedData exists but customdata is stale/empty
            # When figure re-renders after filtering, Plotly preserves selectedData
            # but customdata may be invalid. Preserve existing selection in this case.
            if not values and selected_data and fig_index in existing_scatter_by_index:
                existing_entry = existing_scatter_by_index[fig_index]
                logger.info(
                    f"  Figure {fig_index[:8]}: Preserving existing selection "
                    f"(re-render with stale customdata)"
                )
                selection_values.append(existing_entry)
                has_any_selection = True
                continue

            # Debug: log extraction details
            logger.info(
                f"  Figure {fig_index[:8]}: selection_enabled={selection_enabled}, "
                f"has_selectedData={bool(selected_data)}, "
                f"extracted_values={values[:5] if values else []}{'...' if len(values) > 5 else ''}"
            )

            if values:
                has_any_selection = True
                selection_values.append(
                    create_selection_entry(
                        component_index=fig_index,
                        values=values,
                        source_type=SOURCE_TYPE,
                        column_name=selection_column,
                        dc_id=metadata.get("dc_id"),
                    )
                )

        # Debug: log final decision
        logger.info(
            f"  Result: has_any_selection={has_any_selection}, "
            f"existing_scatter={len([v for v in current_store.get('interactive_components_values', []) if v.get('source') == SOURCE_TYPE])}"
        )

        # Check if update should be prevented
        if should_prevent_update(has_any_selection, current_store, SOURCE_TYPE):
            raise dash.exceptions.PreventUpdate

        new_store = merge_selection_values(existing_values, selection_values)

        # Final safety: prevent writing identical data to the store
        current_values = sorted(
            current_store.get("interactive_components_values", []),
            key=lambda x: (x.get("index", ""), x.get("source", "")),
        )
        new_values = sorted(
            new_store.get("interactive_components_values", []),
            key=lambda x: (x.get("index", ""), x.get("source", "")),
        )
        if current_values == new_values:
            raise dash.exceptions.PreventUpdate

        return new_store
