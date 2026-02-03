"""
Table Component - Row Selection Callback

This module handles AG Grid row selection events and updates the
interactive-values-store to enable cross-component filtering.

The callback listens to:
- selectedRows: Triggered by row selection in AG Grid
- reset button: Clears selection from store

Selection data is added to interactive-values-store with source="table_selection"
to distinguish it from regular interactive components.
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
BUTTON_TYPE = "reset-selection-table-button"
SOURCE_TYPE = "table_selection"


def extract_row_selection_values(
    selected_rows: list[dict[str, Any]] | None,
    selection_column: str,
) -> list[Any]:
    """Extract column values from selected AG Grid rows.

    Args:
        selected_rows: List of selected row data dictionaries
        selection_column: Name of column to extract values from

    Returns:
        List of unique values from the selection column

    Example:
        selected_rows:
        [
            {"ID": 1, "sample_id": "S1", "name": "Sample 1"},
            {"ID": 2, "sample_id": "S2", "name": "Sample 2"},
        ]

        With selection_column="sample_id", returns ["S1", "S2"]
    """
    if not selected_rows:
        return []

    values: set[Any] = set()

    for row in selected_rows:
        if not isinstance(row, dict):
            continue

        value = row.get(selection_column)
        if value is not None:
            values.add(value)

    return list(values)


def register_table_selection_callback(app):
    """Register callback to capture AG Grid row selections.

    This callback listens to selectedRows from all table-aggrid components
    and updates the interactive-values-store.

    The store is extended with selection entries that have source="table_selection"
    to distinguish them from regular interactive components.

    Also handles reset button clicks to clear selections.

    Args:
        app: Dash application instance
    """

    logger.info("Registering table selection callback")

    @app.callback(
        Output("interactive-values-store", "data", allow_duplicate=True),
        Input({"type": "table-aggrid", "index": ALL}, "selectedRows"),
        Input({"type": BUTTON_TYPE, "index": ALL}, "n_clicks"),
        State({"type": "table-aggrid", "index": ALL}, "id"),
        State({"type": BUTTON_TYPE, "index": ALL}, "id"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "id"),
        State("interactive-values-store", "data"),
        prevent_initial_call=True,
    )
    def update_store_from_table_selection(
        selected_rows_list: list[list[dict[str, Any]] | None],
        reset_clicks_list: list[int | None],
        table_ids: list[dict[str, str]],
        reset_button_ids: list[dict[str, str]],
        metadata_list: list[dict[str, Any] | None],
        metadata_ids: list[dict[str, str]],
        current_store: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Update interactive-values-store with table row selection data."""
        current_store = initialize_store(current_store)

        # Check if this callback was triggered by a reset button
        reset_result = handle_reset_button(
            ctx.triggered_id, BUTTON_TYPE, SOURCE_TYPE, current_store
        )
        if reset_result is not None:
            return reset_result

        logger.info(
            f"Table selection callback: {len(table_ids)} tables, "
            f"selectedRows counts={[len(r) if r else 0 for r in selected_rows_list]}"
        )

        # Build metadata lookup (filter to table components only)
        metadata_by_index = build_metadata_lookup(
            metadata_list, metadata_ids, component_type_filter="table"
        )

        # Get existing values (non-table-selection sources)
        existing_values = filter_existing_values(current_store, SOURCE_TYPE)

        # Process each table for selection data
        selection_values: list[dict[str, Any]] = []
        has_any_selection = False

        for i, table_id in enumerate(table_ids):
            table_index = table_id.get("index") if isinstance(table_id, dict) else str(table_id)

            # Get metadata for this table
            metadata = metadata_by_index.get(table_index, {})

            # Check if row selection is enabled for this table
            row_selection_enabled = metadata.get("row_selection_enabled", False)
            row_selection_column = metadata.get("row_selection_column")

            if not row_selection_enabled or not row_selection_column:
                continue

            # Get selected rows
            selected_rows = selected_rows_list[i] if i < len(selected_rows_list) else None

            # Extract values from selected rows
            values = extract_row_selection_values(selected_rows, row_selection_column)

            if values:
                has_any_selection = True
                selection_values.append(
                    create_selection_entry(
                        component_index=table_index,
                        values=values,
                        source_type=SOURCE_TYPE,
                        column_name=row_selection_column,
                        dc_id=metadata.get("dc_id"),
                    )
                )
                logger.debug(f"Table selection: {len(values)} values from table {table_index[:8]}")

        # Check if update should be prevented
        if should_prevent_update(has_any_selection, current_store, SOURCE_TYPE):
            raise dash.exceptions.PreventUpdate

        return merge_selection_values(existing_values, selection_values)
