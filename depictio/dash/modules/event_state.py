"""
Centralized event system for dashboard state management.

This module handles:
- Event state initialization and updates
- Component dependency tracking
- Data filtering based on event state
- Pending changes management
"""

import time
from datetime import datetime, timedelta

import polars as pl

from depictio.api.v1.configs.logging_init import logger

# This module contains event state functions imported and used by dashboard_content.py
# The create_initial_event_state function is implemented directly in dashboard_content.py


def should_component_update(component_type, event_state, trigger_id):
    """
    Determine if a component should update based on its dependencies and what changed.

    Args:
        component_type: Type of component ('metric', 'chart', 'interactive')
        event_state: Current state of all dashboard controls
        trigger_id: The ID that triggered the callback

    Returns:
        bool: True if component should update
    """
    logger.info(f"🔍 SHOULD_UPDATE: {component_type} - trigger_id={trigger_id}")
    logger.info(f"🔍 SHOULD_UPDATE: event_state={event_state}")

    if not event_state:
        logger.info(
            f"🔄 COMPONENT UPDATE: {component_type} updating - no event state (initial render)"
        )
        return True  # Initial render

    # All components depend on all controls for now (simplified dependency management)
    # Check if any control has changed
    for control_key, control_state in event_state.items():
        if control_key.startswith("control-") and control_state.get("changed", False):
            logger.info(
                f"🔄 COMPONENT UPDATE: {component_type} updating due to {control_key} change"
            )
            return True

    # Check if this is initial load (trigger_id is None) - always render
    if trigger_id is None:
        logger.info(f"🔄 COMPONENT UPDATE: {component_type} updating - initial page load")
        return True  # Initial page load

    # Check if this is an initial component trigger (not event-driven)
    if trigger_id and not any(
        control in str(trigger_id)
        for control in ["data-filter-range", "data-filter-dropdown", "dashboard-event-store"]
    ):
        logger.info(f"🔄 COMPONENT UPDATE: {component_type} updating - component initialization")
        return True  # Component initialization

    logger.info(f"⏭️ COMPONENT SKIP: {component_type} skipping - no relevant changes")
    return False


def update_event_state(current_state, control_id, new_value):
    """
    Update the event state when a control changes.
    Now supports dynamic control IDs with metadata preservation.

    Args:
        current_state: Current event state
        control_id: ID of the control that changed (format: "control-N")
        new_value: New value of the control

    Returns:
        dict: Updated event state
    """
    if not current_state:
        current_state = {}  # Return empty state if none provided

    # Reset all changed flags while preserving metadata
    updated_state = {}
    for key, state in current_state.items():
        updated_state[key] = {
            "value": state["value"],
            "timestamp": state["timestamp"],
            "changed": False,
            # Preserve metadata fields
            "field": state.get("field", "unknown"),
            "control_type": state.get("control_type", "unknown"),
        }

    # Update the changed control
    if control_id in updated_state:
        old_value = updated_state[control_id]["value"]
        if old_value != new_value:
            updated_state[control_id].update(
                {
                    "value": new_value,
                    "timestamp": time.time(),
                    "changed": True,
                }
            )
            field = updated_state[control_id].get("field", "unknown")
            logger.info(
                f"🎛️ EVENT UPDATE: {control_id} ({field}) changed from {old_value} → {new_value}"
            )
    else:
        # If control doesn't exist, create it (dynamic addition)
        logger.warning(
            f"⚠️ EVENT UPDATE: Control {control_id} not found in state, creating new entry"
        )
        updated_state[control_id] = {
            "value": new_value,
            "timestamp": time.time(),
            "changed": True,
            "field": "dynamic",
            "control_type": "unknown",
        }

    return updated_state


def get_current_config_from_events(event_state):
    """
    Generate a DATA_CONFIG based on current event state - always use base config for generation.
    Filtering happens post-generation.

    Args:
        event_state: Current dashboard event state

    Returns:
        dict: Base configuration for data generation (filtering applied separately)
    """
    from depictio.dash.layouts.dashboard_content import DATA_CONFIG

    # Always return base config - filtering happens in apply_data_filters()
    return DATA_CONFIG


def apply_data_filters(df, event_state, component_id="unknown"):
    """
    Apply data filters based on current event state to the DataFrame.
    Now works with dynamic control configurations.

    Args:
        df: polars DataFrame to filter
        event_state: Current dashboard event state
        component_id: ID of component requesting filtering (for debugging)

    Returns:
        pl.DataFrame: Filtered DataFrame
    """
    if not event_state:
        return df

    logger.info(f"🔍 FILTER DEBUG [{component_id}]: Processing {len(event_state)} controls")

    filtered_df = df

    # Apply filters dynamically based on control configurations
    for control_key, control_state in event_state.items():
        if not control_key.startswith("control-"):
            continue

        field = control_state.get("field")
        control_type = control_state.get("control_type")
        value = control_state.get("value")

        logger.info(
            f"🔍 FILTER DEBUG [{component_id}]: {control_key} - field={field}, type={control_type}, value={value}"
        )

        # Debug the condition check
        is_range_slider = control_type == "range_slider"
        has_value = bool(value)
        is_list_of_two = isinstance(value, list) and len(value) == 2
        logger.info(
            f"🔍 CONDITION DEBUG [{component_id}]: {control_key} - is_range_slider={is_range_slider}, has_value={has_value}, is_list_of_two={is_list_of_two}"
        )

        if control_type == "range_slider" and value and isinstance(value, list) and len(value) == 2:
            # Apply range filter
            min_val, max_val = value
            column_name = field  # Map field to column name
            logger.info(
                f"🔍 FILTER DEBUG [{component_id}]: Range slider condition met - min={min_val}, max={max_val}"
            )

            if column_name in filtered_df.columns:
                filtered_df = filtered_df.filter(
                    (pl.col(column_name) >= min_val) & (pl.col(column_name) <= max_val)
                )
                logger.info(
                    f"🔍 DATA FILTER [{component_id}]: {field} range [{min_val:,} - {max_val:,}] → {len(filtered_df):,} rows"
                )
            else:
                logger.info(
                    f"🔍 FILTER DEBUG [{component_id}]: Column {column_name} not found in DataFrame"
                )

        elif control_type == "multi_select" and value:
            # Apply category filter
            if "all" not in value:
                column_name = field  # Map field to column name
                if column_name in filtered_df.columns:
                    before_filter = len(filtered_df)
                    filtered_df = filtered_df.filter(pl.col(column_name).is_in(value))
                    logger.info(
                        f"🔍 DATA FILTER [{component_id}]: {field} {value} → {before_filter:,} → {len(filtered_df):,} rows"
                    )

        elif control_type == "dropdown" and value and value != "all":
            # Apply date range or other dropdown filters
            if field == "date_range":
                if value == "last_7_days":
                    cutoff_date = datetime.now() - timedelta(days=7)
                    filtered_df = filtered_df.filter(pl.col("date") >= cutoff_date)
                    logger.info(
                        f"🔍 DATA FILTER [{component_id}]: Last 7 days → {len(filtered_df):,} rows"
                    )
                elif value == "last_30_days":
                    cutoff_date = datetime.now() - timedelta(days=30)
                    filtered_df = filtered_df.filter(pl.col("date") >= cutoff_date)
                    logger.info(
                        f"🔍 DATA FILTER [{component_id}]: Last 30 days → {len(filtered_df):,} rows"
                    )
                elif value == "last_90_days":
                    cutoff_date = datetime.now() - timedelta(days=90)
                    filtered_df = filtered_df.filter(pl.col("date") >= cutoff_date)
                    logger.info(
                        f"🔍 DATA FILTER [{component_id}]: Last 90 days → {len(filtered_df):,} rows"
                    )
        else:
            logger.info(
                f"🔍 FILTER DEBUG [{component_id}]: Control {control_key} not processed - type={control_type}, value={value}, value_len={len(value) if value else 'None'}"
            )

    total_filters_applied = len(df) - len(filtered_df)
    if total_filters_applied > 0:
        logger.info(
            f"📊 FILTERED DATA [{component_id}]: {len(df):,} → {len(filtered_df):,} rows ({total_filters_applied:,} filtered out)"
        )

    return filtered_df
