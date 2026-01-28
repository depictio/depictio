"""Interactive Component - Background Rendering Callbacks.

Two-stage pattern for Celery background processing:
1. Background callback: Load data and extract options (JSON serializable)
2. Regular callback: Build UI components from extracted data

This ensures all Celery task parameters and returns are JSON serializable.

Key components:
- register_async_rendering_callback: Batch rendering callback for all interactive components
- build_select_component: Creates Select/MultiSelect/SegmentedControl components
- build_slider_component: Creates Slider/RangeSlider components
- build_datepicker_component: Creates DateRangePicker components
"""

from typing import Any, Optional

import dash_mantine_components as dmc
import polars as pl
from bson import ObjectId
from dash import ALL, Input, Output, State, no_update
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite

# Common wrapper style for all interactive components
_WRAPPER_STYLE: dict[str, Any] = {
    "width": "100%",
    "minHeight": "120px",
    "padding": "0.5rem 1rem 0.5rem 0.5rem",
    "boxSizing": "border-box",
    "display": "flex",
    "flexDirection": "column",
    "justifyContent": "flex-start",
    "alignItems": "stretch",
}


def _create_component_title(
    title: Optional[str],
    column_name: str,
    component_type: str,
    icon_name: str,
    title_size: str,
    color: Optional[str],
) -> dmc.Group:
    """Create a styled title with icon for interactive components.

    Args:
        title: Custom title text, or None to auto-generate.
        column_name: Column name for auto-generated title.
        component_type: Component type for auto-generated title.
        icon_name: DashIconify icon name.
        title_size: Size parameter for text and icon.
        color: Optional color for title and icon.

    Returns:
        DMC Group containing icon and title text.
    """
    card_title = title if title else f"{component_type} on {column_name}"

    title_style = {"marginBottom": "0.25rem"}
    if color:
        title_style["color"] = color

    icon_width = int(title_size) if str(title_size).isdigit() else 20
    icon_style = {"color": color} if color else {"opacity": 0.9}

    return dmc.Group(
        [
            DashIconify(icon=icon_name, width=icon_width, style=icon_style),
            dmc.Text(card_title, size=title_size, fw="bold", style={"margin": "0"}),
        ],
        gap="xs",
        align="center",
        style=title_style,
    )


def _wrap_component_with_title(title_element: dmc.Group, component: Any) -> dmc.Stack:
    """Wrap an interactive component with its title in a styled Stack.

    Args:
        title_element: The title Group element.
        component: The interactive DMC component.

    Returns:
        DMC Stack containing title and component.
    """
    return dmc.Stack(
        [title_element, component],
        gap="0",
        style=_WRAPPER_STYLE,
    )


def _build_stored_metadata(
    index: str,
    component_type: str,
    column_name: str,
    trigger_data: dict,
    default_state: dict,
) -> dict:
    """Build stored metadata dict for interactive components.

    Args:
        index: Component index.
        component_type: Interactive component type (e.g., 'Select', 'RangeSlider').
        column_name: Data column name.
        trigger_data: Trigger data containing dc_id, wf_id, column_type.
        default_state: Component-specific default state.

    Returns:
        Stored metadata dict for persistence.
    """
    return {
        "index": str(index),
        "component_type": "interactive",
        "interactive_component_type": component_type,
        "column_name": column_name,
        "column_type": trigger_data.get("column_type", "object"),
        "dc_id": trigger_data.get("dc_id"),
        "wf_id": trigger_data.get("wf_id"),
        "default_state": default_state,
    }


def register_async_rendering_callback(app):
    """
    Register async rendering callback for interactive components.

    Pattern-matching callback that:
    1. Receives trigger from interactive-trigger Store
    2. Loads data asynchronously with load_deltatable_lite
    3. Builds the appropriate interactive component (Select/Slider/DatePicker)
    4. Returns the built component + metadata
    """

    @app.callback(
        # BATCH RENDERING: ALL pattern - process all interactive components in single callback
        Output({"type": "interactive-component-value-container", "index": ALL}, "children"),
        Output({"type": "interactive-metadata", "index": ALL}, "data"),
        Output({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        Input({"type": "interactive-trigger", "index": ALL}, "data"),
        Input(
            "project-metadata-store", "data"
        ),  # Keep as Input - needed for Stage 2 when metadata arrives
        State({"type": "interactive-metadata", "index": ALL}, "data"),
        State({"type": "interactive-trigger", "index": ALL}, "id"),  # Add: Need IDs for indexing
        State("local-store", "data"),  # SECURITY: Access token from centralized store
        prevent_initial_call=False,  # Must be False - trigger store has data at creation time
        background=False,  # DISABLED: Batch processing faster than Celery overhead
    )
    # NOTE: Batch rendering optimization - same as cards (8.4× speedup)
    # Idempotency checks per component prevent duplicate renders
    def render_interactive_options_background_batch(
        trigger_data_list, project_metadata, existing_metadata_list, trigger_ids, local_data
    ):
        """
        BATCH RENDERING: Process ALL interactive components in single callback.

        Similar to card batch rendering - reduces N×700ms Dash overhead to 1×700ms.

        OPTIMIZATION STRATEGY:
        - Extract delta_locations once (shared across all components)
        - Process each component in loop
        - Idempotency checks per component prevent duplicate renders
        - Handle heterogeneous types (Select, Slider, DatePicker) in single callback

        Args:
            trigger_data_list: List of trigger data for all components
            project_metadata: Full project metadata cache (includes delta_locations from MongoDB join)
            existing_metadata_list: List of existing metadata (for idempotency checks)
            trigger_ids: List of trigger IDs for indexing
            local_data: User authentication data from local-store

        Returns:
            tuple: (all_components, all_metadata, all_stored_metadata) - lists for all components
        """
        import time

        batch_start = time.time()

        # Early validation - Wait for project_metadata
        if not project_metadata or not isinstance(project_metadata, dict):
            return (
                [no_update] * len(trigger_data_list),
                [no_update] * len(trigger_data_list),
                [no_update] * len(trigger_data_list),
            )

        # ✅ CACHE OPTIMIZATION: Extract delta_locations once (shared across all components)
        delta_locations = {}
        project_data = project_metadata.get("project", {})
        for wf in project_data.get("workflows", []):
            for dc in wf.get("data_collections", []):
                dc_id = str(dc.get("_id"))
                if dc.get("delta_location"):
                    # Extract dc_type from config for special handling (e.g., MultiQC uses parquet)
                    dc_config = dc.get("config", {})
                    dc_type = dc_config.get("type") if isinstance(dc_config, dict) else None
                    delta_locations[dc_id] = {
                        "delta_location": dc["delta_location"],
                        "size_bytes": -1,
                        "dc_type": dc_type,
                    }

        # SECURITY: Extract access_token once (shared)
        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access_token available in local-store")
            # Return errors for all components
            error_result = ("Auth Error", {}, {})
            return (
                [error_result[0]] * len(trigger_data_list),
                [error_result[1]] * len(trigger_data_list),
                [error_result[2]] * len(trigger_data_list),
            )

        # Initialize result lists
        all_components = []
        all_metadata = []
        all_stored_metadata = []

        # Process each interactive component
        for i, (trigger_data, existing_meta, trigger_id) in enumerate(
            zip(trigger_data_list, existing_metadata_list, trigger_ids)
        ):
            # Idempotency check - Skip if no trigger data
            if not trigger_data or not isinstance(trigger_data, dict):
                all_components.append(no_update)
                all_metadata.append(no_update)
                all_stored_metadata.append(no_update)
                continue

            # Extract component info
            component_type = trigger_data.get("interactive_component_type", "unknown")

            # IDEMPOTENCY CHECK: If already rendered, skip
            if existing_meta and existing_meta.get("options") is not None:
                all_components.append(no_update)
                all_metadata.append(no_update)
                all_stored_metadata.append(no_update)
                continue

            # Extract parameters from trigger store
            wf_id = trigger_data.get("wf_id")
            dc_id = trigger_data.get("dc_id")
            column_name = trigger_data.get("column_name")

            # Validate required parameters
            if not all([wf_id, dc_id, column_name, component_type]):
                logger.error(
                    f"[{i}] Missing parameters: wf_id={wf_id}, dc_id={dc_id}, "
                    f"column={column_name}, type={component_type}"
                )
                all_components.append("Error: Missing parameters")
                all_metadata.append({})
                all_stored_metadata.append({})
                continue

            try:
                # Load Delta table with shared cache
                init_data = delta_locations if delta_locations else None

                # Handle joined data collection IDs
                if isinstance(dc_id, str) and "--" in dc_id:
                    df = load_deltatable_lite(
                        ObjectId(wf_id),
                        dc_id,
                        TOKEN=access_token,
                        init_data=init_data,
                    )
                else:
                    df = load_deltatable_lite(
                        ObjectId(wf_id),
                        ObjectId(dc_id),
                        TOKEN=access_token,
                        init_data=init_data,
                    )

                # Build component based on type
                if component_type in ["Select", "MultiSelect", "SegmentedControl"]:
                    component, metadata, stored_metadata = build_select_component(
                        df, column_name, component_type, trigger_data, delta_locations
                    )
                elif component_type in ["Slider", "RangeSlider"]:
                    component, metadata, stored_metadata = build_slider_component(
                        df, column_name, component_type, trigger_data, delta_locations
                    )
                elif component_type == "DateRangePicker":
                    component, metadata, stored_metadata = build_datepicker_component(
                        df, column_name, trigger_data, delta_locations
                    )
                else:
                    logger.error(f"Unsupported component type: {component_type}")
                    component = f"Error: Unsupported type: {component_type}"
                    metadata = {}
                    stored_metadata = {}

                all_components.append(component)
                all_metadata.append(metadata)
                all_stored_metadata.append(stored_metadata)

            except Exception as e:
                logger.error(f"[{i}] Interactive render error: {e}", exc_info=True)
                all_components.append(f"Error: {str(e)}")
                all_metadata.append({})
                all_stored_metadata.append({})

        (time.time() - batch_start) * 1000

        return all_components, all_metadata, all_stored_metadata


def build_select_component(
    df: pl.DataFrame,
    column_name: str,
    component_type: str,
    trigger_data: dict,
    delta_locations: dict,
) -> tuple[Any, dict, dict]:
    """Build Select/MultiSelect/SegmentedControl component.

    Args:
        df: Polars DataFrame with data.
        column_name: Column to extract options from.
        component_type: Type of select component ('Select', 'MultiSelect', 'SegmentedControl').
        trigger_data: Metadata from trigger store.
        delta_locations: Delta locations dict (for cache optimization).

    Returns:
        Tuple of (wrapped_component, metadata, stored_metadata).
    """
    if column_name not in df.columns:
        logger.error(f"Column '{column_name}' not found in DataFrame")
        return dmc.Text(f"Error: Column '{column_name}' not found", c="red"), {}, {}

    # Extract unique values
    try:
        unique_vals = df[column_name].unique()
        if hasattr(unique_vals, "to_list"):
            unique_vals_list = unique_vals.to_list()
        elif hasattr(unique_vals, "tolist"):
            unique_vals_list = unique_vals.tolist()
        else:
            unique_vals_list = list(unique_vals)

        options = [
            {"label": str(val), "value": str(val)} for val in unique_vals_list if val is not None
        ][:100]
    except Exception as e:
        logger.error(f"Error extracting unique values: {e}")
        return dmc.Text("Error: Could not extract options", c="red"), {}, {}

    index = trigger_data.get("index")
    preserved_value = trigger_data.get("value")
    component_id = {"type": "interactive-component-value", "index": str(index)}

    # Build appropriate DMC component
    if component_type == "Select":
        default_value = (
            preserved_value if preserved_value else (options[0]["value"] if options else None)
        )
        interactive_component = dmc.Select(
            id=component_id,
            data=options,
            value=default_value,
            clearable=True,
            searchable=True,
            w="100%",
        )
    elif component_type == "MultiSelect":
        interactive_component = dmc.MultiSelect(
            id=component_id,
            data=options,
            value=preserved_value or [],
            clearable=True,
            searchable=True,
            w="100%",
        )
    elif component_type == "SegmentedControl":
        default_value = (
            preserved_value if preserved_value else (options[0]["value"] if options else None)
        )
        interactive_component = dmc.SegmentedControl(
            id=component_id, data=[opt["value"] for opt in options], value=default_value, w="100%"
        )
    else:
        return dmc.Text(f"Error: Unknown select type: {component_type}", c="red"), {}, {}

    # Create title and wrap component
    title = trigger_data.get("title")
    icon_name = trigger_data.get("icon_name", "bx:slider-alt")
    title_size = trigger_data.get("title_size", "md")
    color = trigger_data.get("color") or trigger_data.get("custom_color")

    title_element = _create_component_title(
        title, column_name, component_type, icon_name, title_size, color
    )
    wrapped_component = _wrap_component_with_title(title_element, interactive_component)

    metadata = {"options": options, "reference_value": preserved_value}

    default_state = {
        "type": "select",
        "options": [opt["value"] for opt in options],
        "default_value": None,
    }
    stored_metadata = _build_stored_metadata(
        index, component_type, column_name, trigger_data, default_state
    )

    return wrapped_component, metadata, stored_metadata


def _clean_numeric_column(df_pandas, column_name: str):
    """Clean numeric column data for slider components.

    Args:
        df_pandas: Pandas DataFrame.
        column_name: Column to clean.

    Returns:
        Tuple of (cleaned_df, min_value, max_value) or (None, None, None) on error.
    """
    import math

    import numpy as np

    df_pandas = df_pandas[~df_pandas[column_name].isin([None, "None", "nan", "NaN"])]
    df_pandas[column_name] = df_pandas[column_name].replace([np.inf, -np.inf], np.nan)
    df_pandas[column_name] = df_pandas[column_name].astype(float)
    df_pandas[column_name] = df_pandas[column_name].apply(
        lambda x: round(x, 2) if x not in [float("inf"), float("-inf")] else x
    )
    df_pandas = df_pandas.dropna(subset=[column_name])

    if df_pandas.empty:
        return None, None, None

    min_value = float(df_pandas[column_name].min())
    max_value = float(df_pandas[column_name].max())

    # Validate min/max
    if math.isnan(min_value) or math.isinf(min_value):
        min_value = 0.0
    if math.isnan(max_value) or math.isinf(max_value):
        max_value = 100.0
    if min_value >= max_value:
        max_value = min_value + 1.0

    return df_pandas, min_value, max_value


def build_slider_component(
    df: pl.DataFrame,
    column_name: str,
    component_type: str,
    trigger_data: dict,
    delta_locations: dict,
) -> tuple[Any, dict, dict]:
    """Build Slider/RangeSlider component.

    Args:
        df: Polars DataFrame with data.
        column_name: Column to extract min/max from.
        component_type: 'Slider' or 'RangeSlider'.
        trigger_data: Metadata from trigger store.
        delta_locations: Delta locations dict (for cache optimization).

    Returns:
        Tuple of (wrapped_component, metadata, stored_metadata).
    """
    import math

    df_pandas = df.to_pandas()

    if column_name not in df_pandas.columns:
        logger.error(f"Column '{column_name}' not found in DataFrame")
        return dmc.Text(f"Error: Column '{column_name}' not found", c="red"), {}, {}

    df_pandas, min_value, max_value = _clean_numeric_column(df_pandas, column_name)
    if df_pandas is None:
        logger.error(f"No valid numeric data in column '{column_name}'")
        return dmc.Text(f"Error: No valid data in column '{column_name}'", c="red"), {}, {}

    index = trigger_data.get("index")
    preserved_value = trigger_data.get("value")
    color = trigger_data.get("color")
    title_size = trigger_data.get("title_size", "md")

    # Build component kwargs
    kwargs_component = {
        "min": min_value,
        "max": max_value,
        "id": {"type": "interactive-component-value", "index": str(index)},
        "step": 0.01,
        "persistence_type": "local",
        "w": "100%",
        "size": title_size,
        "styles": {
            "root": {"width": "100%", "paddingLeft": "12px", "paddingRight": "12px"},
            "track": {"minWidth": "50px"},
        },
        "marks": [
            {"value": min_value, "label": str(round(min_value, 2))},
            {"value": max_value, "label": str(round(max_value, 2))},
        ],
    }

    if color:
        kwargs_component["color"] = color

    # Handle value based on component type
    if component_type == "RangeSlider":
        kwargs_component["minRange"] = 0.01
        if (
            preserved_value is None
            or not isinstance(preserved_value, list)
            or len(preserved_value) != 2
        ):
            cleaned_value = [min_value, max_value]
        else:
            cleaned_value = [
                max(min_value, min(max_value, float(preserved_value[0]))),
                max(min_value, min(max_value, float(preserved_value[1]))),
            ]
            if cleaned_value[0] > cleaned_value[1]:
                cleaned_value = [cleaned_value[1], cleaned_value[0]]
        kwargs_component["value"] = cleaned_value
        interactive_component = dmc.RangeSlider(**kwargs_component)
    else:
        if preserved_value is None or (
            isinstance(preserved_value, float) and math.isnan(preserved_value)
        ):
            cleaned_value = (min_value + max_value) / 2
        else:
            cleaned_value = max(min_value, min(max_value, float(preserved_value)))
        kwargs_component["value"] = cleaned_value
        interactive_component = dmc.Slider(**kwargs_component)

    # Create title and wrap component
    title = trigger_data.get("title")
    icon_name = trigger_data.get("icon_name", "bx:slider-alt")
    title_size_param = trigger_data.get("title_size", "md")

    title_element = _create_component_title(
        title, column_name, component_type, icon_name, title_size_param, color
    )
    wrapped_component = _wrap_component_with_title(title_element, interactive_component)

    metadata = {"min": min_value, "max": max_value, "reference_value": preserved_value}

    default_state = {
        "type": "range",
        "min_value": min_value,
        "max_value": max_value,
        "default_range": [min_value, max_value],
    }
    stored_metadata = _build_stored_metadata(
        index, component_type, column_name, trigger_data, default_state
    )
    stored_metadata["column_type"] = trigger_data.get("column_type", "float64")

    return wrapped_component, metadata, stored_metadata


def _parse_date_value(val: Any, min_date, max_date):
    """Parse a date value from various formats.

    Args:
        val: Date value (string, datetime, or date).
        min_date: Minimum allowed date.
        max_date: Maximum allowed date.

    Returns:
        Clamped date object.
    """
    from datetime import datetime

    if isinstance(val, str):
        date_obj = datetime.strptime(val, "%Y-%m-%d").date()
    elif hasattr(val, "date"):
        date_obj = val.date()
    else:
        date_obj = val
    return max(min_date, min(max_date, date_obj))


def build_datepicker_component(
    df: pl.DataFrame,
    column_name: str,
    trigger_data: dict,
    delta_locations: dict,
) -> tuple[Any, dict, dict]:
    """Build DateRangePicker component.

    Args:
        df: Polars DataFrame with data.
        column_name: Column to extract date range from.
        trigger_data: Metadata from trigger store.
        delta_locations: Delta locations dict (for cache optimization).

    Returns:
        Tuple of (wrapped_component, metadata, stored_metadata).
    """
    import pandas as pd

    df_pandas = df.to_pandas()

    if column_name not in df_pandas.columns:
        logger.error(f"Column '{column_name}' not found in DataFrame")
        return dmc.Text(f"Error: Column '{column_name}' not found", c="red"), {}, {}

    # Ensure column is datetime type
    if not pd.api.types.is_datetime64_any_dtype(df_pandas[column_name]):
        try:
            df_pandas[column_name] = pd.to_datetime(df_pandas[column_name], errors="coerce")
        except Exception as e:
            logger.error(f"Failed to convert column to datetime: {e}")
            return dmc.Text(f"Error: Column '{column_name}' must be datetime type", c="red"), {}, {}

    df_pandas = df_pandas.dropna(subset=[column_name])

    if df_pandas.empty:
        logger.error(f"No valid datetime values in column '{column_name}'")
        return dmc.Text(f"Error: No valid dates in column '{column_name}'", c="red"), {}, {}

    # Get min and max dates as Python date objects
    min_date_py = df_pandas[column_name].min().date()
    max_date_py = df_pandas[column_name].max().date()

    index = trigger_data.get("index")
    preserved_value = trigger_data.get("value")
    color = trigger_data.get("color")
    title_size = trigger_data.get("title_size", "md")

    # Build component kwargs
    kwargs_component = {
        "type": "range",
        "id": {"type": "interactive-component-value", "index": str(index)},
        "minDate": min_date_py,
        "maxDate": max_date_py,
        "persistence_type": "local",
        "w": "100%",
        "size": title_size,
        "clearable": False,
        "styles": {"root": {"width": "100%"}},
    }

    # Handle value preservation
    if (
        preserved_value is not None
        and isinstance(preserved_value, list)
        and len(preserved_value) == 2
    ):
        try:
            date_value = [
                _parse_date_value(preserved_value[0], min_date_py, max_date_py),
                _parse_date_value(preserved_value[1], min_date_py, max_date_py),
            ]
            kwargs_component["value"] = date_value
        except Exception as e:
            logger.warning(f"Failed to parse date range value: {e}")
            kwargs_component["value"] = [min_date_py, max_date_py]
    else:
        kwargs_component["value"] = [min_date_py, max_date_py]

    # Apply custom color if specified
    if color:
        kwargs_component["styles"] = {
            **kwargs_component.get("styles", {}),
            "input": {"borderColor": color},
            "label": {"color": color},
        }

    interactive_component = dmc.DatePickerInput(**kwargs_component)

    # Create title and wrap component
    title = trigger_data.get("title")
    icon_name = trigger_data.get("icon_name", "bx:calendar")
    title_size_param = trigger_data.get("title_size", "md")

    title_element = _create_component_title(
        title, column_name, "DateRangePicker", icon_name, title_size_param, color
    )
    wrapped_component = _wrap_component_with_title(title_element, interactive_component)

    metadata = {
        "min_date": str(min_date_py),
        "max_date": str(max_date_py),
        "reference_value": preserved_value,
    }

    default_state = {
        "type": "date_range",
        "min_date": str(min_date_py),
        "max_date": str(max_date_py),
        "default_range": [str(min_date_py), str(max_date_py)],
    }
    stored_metadata = _build_stored_metadata(
        index, "DateRangePicker", column_name, trigger_data, default_state
    )
    stored_metadata["column_type"] = trigger_data.get("column_type", "datetime")

    return wrapped_component, metadata, stored_metadata
