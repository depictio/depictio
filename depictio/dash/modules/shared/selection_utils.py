"""
Shared utilities for selection callbacks (scatter plot and table row selection).

This module provides common functionality used by both figure and table
selection callbacks to reduce code duplication.
"""

from typing import Any

from depictio.api.v1.configs.logging_init import logger


def initialize_store(current_store: dict[str, Any] | None) -> dict[str, Any]:
    """Initialize or return existing interactive-values-store.

    Args:
        current_store: Current store data or None

    Returns:
        Initialized store dictionary
    """
    if current_store is None:
        return {"interactive_components_values": [], "first_load": False}
    return current_store


def build_metadata_lookup(
    metadata_list: list[dict[str, Any] | None],
    metadata_ids: list[dict[str, str]],
    component_type_filter: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a lookup dictionary mapping component index to metadata.

    Args:
        metadata_list: List of metadata dictionaries
        metadata_ids: List of metadata store IDs
        component_type_filter: Optional filter to include only specific component types

    Returns:
        Dictionary mapping component index to metadata
    """
    metadata_by_index: dict[str, dict[str, Any]] = {}

    for i, meta_id in enumerate(metadata_ids):
        if i < len(metadata_list) and metadata_list[i]:
            index = meta_id.get("index") if isinstance(meta_id, dict) else str(meta_id)

            # Apply component type filter if specified
            if component_type_filter:
                if metadata_list[i].get("component_type") == component_type_filter:
                    metadata_by_index[index] = metadata_list[i]
            else:
                metadata_by_index[index] = metadata_list[i]

    return metadata_by_index


def handle_reset_button(
    triggered_id: dict[str, Any] | str | None,
    button_type: str,
    source_type: str,
    current_store: dict[str, Any],
) -> dict[str, Any] | None:
    """Handle reset button click and clear selection from store.

    Args:
        triggered_id: The triggered component ID from callback context
        button_type: Expected button type (e.g., "reset-selection-graph-button")
        source_type: Selection source to clear (e.g., "scatter_selection")
        current_store: Current store data

    Returns:
        Updated store if reset was triggered, None otherwise
    """
    if not isinstance(triggered_id, dict):
        return None

    if triggered_id.get("type") != button_type:
        return None

    reset_index = triggered_id.get("index")
    logger.info(
        f"Selection reset triggered for component {reset_index[:8] if reset_index else 'None'} "
        f"(source={source_type})"
    )

    # Remove selection entries for this component
    filtered_values = [
        v
        for v in current_store.get("interactive_components_values", [])
        if not (v.get("source") == source_type and v.get("index") == reset_index)
    ]

    return {
        "interactive_components_values": filtered_values,
        "first_load": False,
    }


def filter_existing_values(
    current_store: dict[str, Any],
    source_type: str,
) -> list[dict[str, Any]]:
    """Get existing store values excluding a specific source type.

    Args:
        current_store: Current store data
        source_type: Source type to exclude (e.g., "scatter_selection")

    Returns:
        List of values without the specified source type
    """
    return [
        v
        for v in current_store.get("interactive_components_values", [])
        if v.get("source") != source_type
    ]


def should_prevent_update(
    has_any_selection: bool,
    current_store: dict[str, Any],
    source_type: str,
) -> bool:
    """Check if callback update should be prevented.

    Returns True if there are no new selections AND no previous selections
    to clear, meaning no state change is needed.

    Args:
        has_any_selection: Whether any new selection data exists
        current_store: Current store data
        source_type: Selection source type to check

    Returns:
        True if update should be prevented
    """
    if has_any_selection:
        return False

    # Check if we had previous selections that should now be cleared
    had_previous_selections = any(
        v.get("source") == source_type
        for v in current_store.get("interactive_components_values", [])
    )

    return not had_previous_selections


def create_selection_entry(
    component_index: str,
    values: list[Any],
    source_type: str,
    column_name: str,
    dc_id: str | None,
) -> dict[str, Any]:
    """Create a standardized selection entry for the store.

    Args:
        component_index: Unique component identifier
        values: List of selected values
        source_type: Selection source (e.g., "scatter_selection", "table_selection")
        column_name: Name of the column being filtered
        dc_id: Data collection ID

    Returns:
        Selection entry dictionary
    """
    return {
        "index": component_index,
        "value": values,
        "source": source_type,
        "column_name": column_name,
        "dc_id": dc_id,
    }


def merge_selection_values(
    existing_values: list[dict[str, Any]],
    selection_values: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge existing store values with new selection values.

    Args:
        existing_values: Values from store (excluding current source type)
        selection_values: New selection values to add

    Returns:
        Updated store dictionary
    """
    return {
        "interactive_components_values": existing_values + selection_values,
        "first_load": False,
    }
