"""
Table Component - Row Selection Callback

This module handles AG Grid row selection events and updates the
interactive-values-store to enable cross-component filtering.

The callback listens to selectedRows from table-aggrid components.
Selection data is added to interactive-values-store with source="table_selection"
to distinguish it from regular interactive components.
"""

from typing import Any

import dash
from dash import ALL, Input, Output, State

from depictio.api.v1.configs.logging_init import logger


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
        Input({"type": "reset-selection-table-button", "index": ALL}, "n_clicks"),
        State({"type": "table-aggrid", "index": ALL}, "id"),
        State({"type": "reset-selection-table-button", "index": ALL}, "id"),
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
        """Update interactive-values-store with table row selection data.

        This callback merges table selection data into the existing store,
        preserving values from regular interactive components while adding
        selection-based filters.

        Also handles reset button clicks to clear selections for specific components.

        Args:
            selected_rows_list: List of selectedRows from all tables
            reset_clicks_list: List of reset button click counts
            table_ids: List of table component IDs
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
            and triggered_id.get("type") == "reset-selection-table-button"
        ):
            reset_index = triggered_id.get("index")
            logger.info(
                f"Table selection reset triggered for component {reset_index[:8] if reset_index else 'None'}"
            )

            # Remove table_selection entries for this component
            filtered_values = [
                v
                for v in current_store.get("interactive_components_values", [])
                if not (v.get("source") == "table_selection" and v.get("index") == reset_index)
            ]

            return {
                "interactive_components_values": filtered_values,
                "first_load": False,
            }

        logger.info(
            f"Table selection callback triggered: "
            f"{len(table_ids)} tables, "
            f"selectedRows counts={[len(r) if r else 0 for r in selected_rows_list]}"
        )

        # Build metadata lookup by component index
        metadata_by_index: dict[str, dict[str, Any]] = {}
        for i, meta_id in enumerate(metadata_ids):
            if i < len(metadata_list) and metadata_list[i]:
                index = meta_id.get("index") if isinstance(meta_id, dict) else str(meta_id)
                # Only include table components
                if metadata_list[i].get("component_type") == "table":
                    metadata_by_index[index] = metadata_list[i]

        # Initialize store if needed
        if current_store is None:
            current_store = {"interactive_components_values": [], "first_load": False}

        # Get existing values (non-table-selection sources)
        existing_values = [
            v
            for v in current_store.get("interactive_components_values", [])
            if v.get("source") != "table_selection"
        ]

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
                    {
                        "index": table_index,
                        "value": values,
                        "source": "table_selection",
                        "column_name": row_selection_column,
                        "dc_id": metadata.get("dc_id"),
                    }
                )
                logger.debug(f"Table selection: {len(values)} values from table {table_index[:8]}")

        # If no selection data changed and we have no new selections, prevent update
        if not has_any_selection:
            # Check if we had previous selections that should now be cleared
            had_previous_selections = any(
                v.get("source") == "table_selection"
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
