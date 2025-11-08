"""
Interactive Component - Background Rendering Callbacks

Two-stage pattern for Celery background processing:
1. Background callback: Load data and extract options (JSON serializable)
2. Regular callback: Build UI components from extracted data

This ensures all Celery task parameters and returns are JSON serializable.
"""

import dash_mantine_components as dmc
from bson import ObjectId
from dash import MATCH, Input, Output, State, no_update
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite


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
        # Output to container DIV (not the inner component) to avoid duplicate IDs
        Output({"type": "interactive-component-value-container", "index": MATCH}, "children"),
        Output({"type": "interactive-metadata", "index": MATCH}, "data"),
        Output({"type": "interactive-stored-metadata", "index": MATCH}, "data"),
        Input({"type": "interactive-trigger", "index": MATCH}, "data"),
        Input(
            "project-metadata-store", "data"
        ),  # ✅ MIGRATED: Read directly from project metadata cache
        State({"type": "interactive-metadata", "index": MATCH}, "data"),
        State("local-store", "data"),  # SECURITY: Access token from centralized store
        prevent_initial_call=False,
        background=True,
    )
    def render_interactive_options_background(
        trigger_data, project_metadata, existing_metadata, local_data
    ):
        """
        PATTERN-MATCHING: Async rendering callback for interactive components.

        Similar to render_card_value_background but builds entire interactive component.

        TWO-STAGE RENDERING OPTIMIZATION:
        - Stage 1: Renders immediately with trigger_data (before project_metadata available)
        - Stage 2: Re-renders when project-metadata-store arrives (contains delta_locations)

        Args:
            trigger_data: Data from interactive-trigger store containing all necessary params
            project_metadata: Full project metadata cache (includes delta_locations from MongoDB join)
            existing_metadata: Existing metadata from previous render (for idempotency check)
            local_data: User authentication data from local-store

        Returns:
            tuple: (built_component, metadata_dict, stored_metadata_dict)
        """

        # DEFENSIVE CHECK 1: Skip if trigger_data not ready
        if not trigger_data or not isinstance(trigger_data, dict):
            return no_update, no_update, no_update

        # ✅ CACHE OPTIMIZATION: Extract delta_locations from project-metadata-store
        delta_locations = None
        if project_metadata:
            delta_locations = {}
            project_data = project_metadata.get("project", {})
            for wf in project_data.get("workflows", []):
                for dc in wf.get("data_collections", []):
                    dc_id = str(dc.get("_id"))
                    if dc.get("delta_location"):
                        delta_locations[dc_id] = dc["delta_location"]

        # DEFENSIVE CHECK 2: Skip if already initialized (prevents spurious re-renders)
        if existing_metadata and existing_metadata.get("options") is not None:
            had_delta_locations = existing_metadata.get("delta_locations_available", False)
            has_delta_locations_now = delta_locations is not None and len(delta_locations) > 0

            if not (has_delta_locations_now and not had_delta_locations):
                return no_update, no_update, no_update

        # Extract parameters from trigger store
        wf_id = trigger_data.get("wf_id")
        dc_id = trigger_data.get("dc_id")
        column_name = trigger_data.get("column_name")
        component_type = trigger_data.get("interactive_component_type")

        # SECURITY: Extract access_token from local-store (centralized, not per-component)
        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access_token available in local-store")
            return "Auth Error", {}, {}

        # Validate required parameters
        if not all([wf_id, dc_id, column_name, component_type]):
            logger.error(
                f"Missing required parameters: wf_id={wf_id}, dc_id={dc_id}, "
                f"column_name={column_name}, component_type={component_type}"
            )
            return "Error: Missing parameters", {}, {}

        try:
            # TWO-STAGE OPTIMIZATION: Use delta_locations when available
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
                return build_select_component(
                    df, column_name, component_type, trigger_data, delta_locations
                )
            elif component_type in ["Slider", "RangeSlider"]:
                return build_slider_component(
                    df, column_name, component_type, trigger_data, delta_locations
                )
            elif component_type == "DateRangePicker":
                return build_datepicker_component(df, column_name, trigger_data, delta_locations)
            else:
                logger.error(f"Unsupported component type: {component_type}")
                return f"Error: Unsupported component type: {component_type}", {}, {}

        except Exception as e:
            logger.error(f"Interactive render error: {e}", exc_info=True)
            return f"Error loading component: {str(e)}", {}, {}


def build_select_component(df, column_name, component_type, trigger_data, delta_locations):
    """
    Build Select/MultiSelect/SegmentedControl component.

    Args:
        df: Polars DataFrame with data
        column_name: Column to extract options from
        component_type: Type of select component
        trigger_data: Metadata from trigger store
        delta_locations: Delta locations dict (for Stage 2 optimization)

    Returns:
        tuple: (component, metadata, stored_metadata)
    """
    # Check if column exists
    if column_name not in df.columns:
        logger.error(f"Column '{column_name}' not found in DataFrame")
        return dmc.Text(f"Error: Column '{column_name}' not found", c="red"), {}, {}

    # Get unique values
    try:
        unique_vals = df[column_name].unique()
        # Handle both pandas and polars dataframes
        if hasattr(unique_vals, "to_list"):
            unique_vals_list = unique_vals.to_list()
        elif hasattr(unique_vals, "tolist"):
            unique_vals_list = unique_vals.tolist()
        else:
            unique_vals_list = list(unique_vals)

        # Clean and limit options
        options = [
            {"label": str(val), "value": str(val)} for val in unique_vals_list if val is not None
        ][:100]

    except Exception as e:
        logger.error(f"Error extracting unique values: {e}")
        return dmc.Text("Error: Could not extract options", c="red"), {}, {}

    # Build component
    index = trigger_data.get("index")
    preserved_value = trigger_data.get("value")

    # Select appropriate DMC component
    if component_type == "Select":
        interactive_component = dmc.Select(
            id={"type": "interactive-component-value", "index": str(index)},
            data=options,
            value=preserved_value
            if preserved_value
            else (options[0]["value"] if options else None),
            clearable=True,
            searchable=True,
            w="100%",
        )
    elif component_type == "MultiSelect":
        interactive_component = dmc.MultiSelect(
            id={"type": "interactive-component-value", "index": str(index)},
            data=options,
            value=preserved_value if preserved_value else [],
            clearable=True,
            searchable=True,
            w="100%",
        )
    elif component_type == "SegmentedControl":
        interactive_component = dmc.SegmentedControl(
            id={"type": "interactive-component-value", "index": str(index)},
            data=[opt["value"] for opt in options],
            value=preserved_value
            if preserved_value
            else (options[0]["value"] if options else None),
            w="100%",
        )
    else:
        return dmc.Text(f"Error: Unknown select type: {component_type}", c="red"), {}, {}

    # Extract title parameters from trigger_data
    title = trigger_data.get("title")
    icon_name = trigger_data.get("icon_name", "bx:slider-alt")
    title_size = trigger_data.get("title_size", "md")
    color = trigger_data.get("color") or trigger_data.get("custom_color")

    # Generate title text
    if not title:
        card_title = f"{component_type} on {column_name}"
    else:
        card_title = title

    logger.info(
        f"📝 SELECT COMPONENT TITLE: '{card_title}' (icon={icon_name}, size={title_size}, color={color})"
    )

    # Create title with icon and color support
    title_style = {"marginBottom": "0.25rem"}
    if color:
        title_style["color"] = color

    icon_props = {
        "icon": icon_name,
        "width": int(title_size) if str(title_size).isdigit() else 20,
    }
    if color:
        icon_props["style"] = {"color": color}
    else:
        icon_props["style"] = {"opacity": 0.9}

    card_title_h5 = dmc.Group(
        [
            DashIconify(**icon_props),
            dmc.Text(card_title, size=title_size, fw="bold", style={"margin": "0"}),
        ],
        gap="xs",
        align="center",
        style=title_style,
    )

    # Wrap component with title in Stack
    wrapped_component = dmc.Stack(
        [card_title_h5, interactive_component],
        gap="0",
        style={
            "width": "100%",
            "minHeight": "120px",
            "padding": "0.5rem 1rem 0.5rem 0.5rem",
            "boxSizing": "border-box",
            "display": "flex",
            "flexDirection": "column",
            "justifyContent": "flex-start",
            "alignItems": "stretch",
        },
    )

    # Build metadata for reference (lightweight, for interactive-metadata store)
    metadata = {
        "options": options,
        "reference_value": preserved_value,
        "delta_locations_available": delta_locations is not None,
    }

    # Build stored_metadata with ALL fields required for filtering
    stored_metadata = {
        "index": str(index),
        "interactive_component_type": component_type,
        "column_name": column_name,
        "column_type": trigger_data.get("column_type", "object"),  # Get from trigger
        "dc_id": trigger_data.get("dc_id"),
        "wf_id": trigger_data.get("wf_id"),
        "default_state": {
            "type": "select",
            "options": [opt["value"] for opt in options],
            "default_value": None,
        },
    }

    return wrapped_component, metadata, stored_metadata


def build_slider_component(df, column_name, component_type, trigger_data, delta_locations):
    """
    Build Slider/RangeSlider component.

    Args:
        df: Polars DataFrame with data
        column_name: Column to extract min/max from
        component_type: "Slider" or "RangeSlider"
        trigger_data: Metadata from trigger store
        delta_locations: Delta locations dict (for Stage 2 optimization)

    Returns:
        tuple: (component, metadata, stored_metadata)
    """
    import math

    import numpy as np

    # Convert to pandas for processing
    df_pandas = df.to_pandas()

    # Check if column exists
    if column_name not in df_pandas.columns:
        logger.error(f"Column '{column_name}' not found in DataFrame")
        return dmc.Text(f"Error: Column '{column_name}' not found", c="red"), {}, {}

    # Clean data: drop NaN, None, and invalid values
    df_pandas = df_pandas[~df_pandas[column_name].isin([None, "None", "nan", "NaN"])]
    df_pandas[column_name] = df_pandas[column_name].replace([np.inf, -np.inf], np.nan)
    df_pandas[column_name] = df_pandas[column_name].astype(float)

    # Round to 2 decimal places
    df_pandas[column_name] = df_pandas[column_name].apply(
        lambda x: round(x, 2) if x not in [float("inf"), float("-inf")] else x
    )
    df_pandas = df_pandas.dropna(subset=[column_name])

    if df_pandas.empty:
        logger.error(f"No valid numeric data in column '{column_name}'")
        return dmc.Text(f"Error: No valid data in column '{column_name}'", c="red"), {}, {}

    # Get min/max values
    min_value = float(df_pandas[column_name].min())
    max_value = float(df_pandas[column_name].max())

    # Validate min/max
    if math.isnan(min_value) or math.isinf(min_value):
        min_value = 0.0

    if math.isnan(max_value) or math.isinf(max_value):
        max_value = 100.0

    # Ensure min < max
    if min_value >= max_value:
        max_value = min_value + 1.0

    # Extract parameters from trigger store
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
            "root": {
                "width": "100%",
                "paddingLeft": "12px",
                "paddingRight": "12px",
            },
            "track": {
                "minWidth": "50px",
            },
        },
    }

    # Handle value for component type
    if component_type == "RangeSlider":
        # RangeSlider needs [min, max] value
        kwargs_component["minRange"] = 0.01

        if (
            preserved_value is None
            or not isinstance(preserved_value, list)
            or len(preserved_value) != 2
        ):
            # Default to full range
            cleaned_value = [min_value, max_value]
        else:
            # Clean and clamp values
            cleaned_value = [
                max(min_value, min(max_value, float(preserved_value[0]))),
                max(min_value, min(max_value, float(preserved_value[1]))),
            ]
            # Ensure order
            if cleaned_value[0] > cleaned_value[1]:
                cleaned_value = [cleaned_value[1], cleaned_value[0]]

        kwargs_component["value"] = cleaned_value

    else:  # Slider
        # Slider needs single value
        if preserved_value is None or (
            isinstance(preserved_value, float) and math.isnan(preserved_value)
        ):
            # Default to middle of range
            cleaned_value = (min_value + max_value) / 2
        else:
            # Clamp to range
            cleaned_value = max(min_value, min(max_value, float(preserved_value)))

        kwargs_component["value"] = cleaned_value

    # Apply custom color if specified
    if color:
        kwargs_component["color"] = color

    # Generate marks (simple 2-mark approach for now)
    kwargs_component["marks"] = [
        {"value": min_value, "label": str(round(min_value, 2))},
        {"value": max_value, "label": str(round(max_value, 2))},
    ]

    # Build component
    if component_type == "RangeSlider":
        interactive_component = dmc.RangeSlider(**kwargs_component)
    else:
        interactive_component = dmc.Slider(**kwargs_component)

    # Extract title parameters from trigger_data
    title = trigger_data.get("title")
    icon_name = trigger_data.get("icon_name", "bx:slider-alt")
    title_size_param = trigger_data.get("title_size", "md")

    # Generate title text
    if not title:
        card_title = f"{component_type} on {column_name}"
    else:
        card_title = title

    logger.info(
        f"📝 SLIDER COMPONENT TITLE: '{card_title}' (icon={icon_name}, size={title_size_param}, color={color})"
    )

    # Create title with icon and color support
    title_style = {"marginBottom": "0.25rem"}
    if color:
        title_style["color"] = color

    icon_props = {
        "icon": icon_name,
        "width": int(title_size_param) if str(title_size_param).isdigit() else 20,
    }
    if color:
        icon_props["style"] = {"color": color}
    else:
        icon_props["style"] = {"opacity": 0.9}

    card_title_h5 = dmc.Group(
        [
            DashIconify(**icon_props),
            dmc.Text(card_title, size=title_size_param, fw="bold", style={"margin": "0"}),
        ],
        gap="xs",
        align="center",
        style=title_style,
    )

    # Wrap component with title in Stack
    wrapped_component = dmc.Stack(
        [card_title_h5, interactive_component],
        gap="0",
        style={
            "width": "100%",
            "minHeight": "120px",
            "padding": "0.5rem 1rem 0.5rem 0.5rem",
            "boxSizing": "border-box",
            "display": "flex",
            "flexDirection": "column",
            "justifyContent": "flex-start",
            "alignItems": "stretch",
        },
    )

    # Build metadata for reference (lightweight, for interactive-metadata store)
    metadata = {
        "min": min_value,
        "max": max_value,
        "reference_value": preserved_value,
        "delta_locations_available": delta_locations is not None,
    }

    # Build stored_metadata with ALL fields required for filtering
    stored_metadata = {
        "index": str(index),
        "interactive_component_type": component_type,
        "column_name": column_name,
        "column_type": trigger_data.get("column_type", "float64"),  # Get from trigger
        "dc_id": trigger_data.get("dc_id"),
        "wf_id": trigger_data.get("wf_id"),
        "default_state": {
            "type": "range",
            "min_value": min_value,
            "max_value": max_value,
            "default_range": [min_value, max_value],
        },
    }

    return wrapped_component, metadata, stored_metadata


def build_datepicker_component(df, column_name, trigger_data, delta_locations):
    """
    Build DateRangePicker component.

    Args:
        df: Polars DataFrame with data
        column_name: Column to extract date range from
        trigger_data: Metadata from trigger store
        delta_locations: Delta locations dict (for Stage 2 optimization)

    Returns:
        tuple: (component, metadata, stored_metadata)
    """
    from datetime import datetime

    import pandas as pd

    # Convert to pandas for processing
    df_pandas = df.to_pandas()

    # Check if column exists
    if column_name not in df_pandas.columns:
        logger.error(f"Column '{column_name}' not found in DataFrame")
        return dmc.Text(f"Error: Column '{column_name}' not found", c="red"), {}, {}

    # Ensure column is datetime type
    if not pd.api.types.is_datetime64_any_dtype(df_pandas[column_name]):
        try:
            df_pandas[column_name] = pd.to_datetime(df_pandas[column_name], errors="coerce")
        except Exception as e:
            logger.error(f"Failed to convert column to datetime: {e}")
            return (
                dmc.Text(f"Error: Column '{column_name}' must be datetime type", c="red"),
                {},
                {},
            )

    # Drop NaN values
    df_pandas = df_pandas.dropna(subset=[column_name])

    if df_pandas.empty:
        logger.error(f"No valid datetime values in column '{column_name}'")
        return dmc.Text(f"Error: No valid dates in column '{column_name}'", c="red"), {}, {}

    # Get min and max dates
    min_date = df_pandas[column_name].min()
    max_date = df_pandas[column_name].max()

    # Convert to Python date objects (DMC requires date, not datetime)
    min_date_py = min_date.date()
    max_date_py = max_date.date()

    # Extract parameters from trigger store
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
        "styles": {
            "root": {
                "width": "100%",
            },
        },
    }

    # Handle value preservation
    if (
        preserved_value is not None
        and isinstance(preserved_value, list)
        and len(preserved_value) == 2
    ):
        try:
            # Convert string dates to date objects if needed
            date_value = []
            for val in preserved_value:
                if isinstance(val, str):
                    date_obj = datetime.strptime(val, "%Y-%m-%d").date()
                elif hasattr(val, "date"):
                    date_obj = val.date()
                else:
                    date_obj = val
                date_value.append(date_obj)

            # Ensure dates are within bounds
            date_value[0] = max(min_date_py, min(max_date_py, date_value[0]))
            date_value[1] = max(min_date_py, min(max_date_py, date_value[1]))

            kwargs_component["value"] = date_value
        except Exception as e:
            logger.warning(f"Failed to parse date range value: {e}")
            kwargs_component["value"] = [min_date_py, max_date_py]
    else:
        # Default to full range
        kwargs_component["value"] = [min_date_py, max_date_py]

    # Apply custom color if specified
    if color:
        existing_styles = kwargs_component.get("styles", {})
        color_styles = {
            "input": {"borderColor": color},
            "label": {"color": color},
        }
        kwargs_component["styles"] = {**existing_styles, **color_styles}

    # Build component
    interactive_component = dmc.DatePickerInput(**kwargs_component)

    # Extract title parameters from trigger_data
    title = trigger_data.get("title")
    icon_name = trigger_data.get("icon_name", "bx:calendar")
    title_size_param = trigger_data.get("title_size", "md")

    # Generate title text
    if not title:
        card_title = f"DateRangePicker on {column_name}"
    else:
        card_title = title

    logger.info(
        f"📝 DATEPICKER COMPONENT TITLE: '{card_title}' (icon={icon_name}, size={title_size_param}, color={color})"
    )

    # Create title with icon and color support
    title_style = {"marginBottom": "0.25rem"}
    if color:
        title_style["color"] = color

    icon_props = {
        "icon": icon_name,
        "width": int(title_size_param) if str(title_size_param).isdigit() else 20,
    }
    if color:
        icon_props["style"] = {"color": color}
    else:
        icon_props["style"] = {"opacity": 0.9}

    card_title_h5 = dmc.Group(
        [
            DashIconify(**icon_props),
            dmc.Text(card_title, size=title_size_param, fw="bold", style={"margin": "0"}),
        ],
        gap="xs",
        align="center",
        style=title_style,
    )

    # Wrap component with title in Stack
    wrapped_component = dmc.Stack(
        [card_title_h5, interactive_component],
        gap="0",
        style={
            "width": "100%",
            "minHeight": "120px",
            "padding": "0.5rem 1rem 0.5rem 0.5rem",
            "boxSizing": "border-box",
            "display": "flex",
            "flexDirection": "column",
            "justifyContent": "flex-start",
            "alignItems": "stretch",
        },
    )

    # Build metadata for reference (lightweight, for interactive-metadata store)
    metadata = {
        "min_date": str(min_date_py),
        "max_date": str(max_date_py),
        "reference_value": preserved_value,
        "delta_locations_available": delta_locations is not None,
    }

    # Build stored_metadata with ALL fields required for filtering
    stored_metadata = {
        "index": str(index),
        "interactive_component_type": "DateRangePicker",
        "column_name": column_name,
        "column_type": trigger_data.get("column_type", "datetime"),  # Get from trigger
        "dc_id": trigger_data.get("dc_id"),
        "wf_id": trigger_data.get("wf_id"),
        "default_state": {
            "type": "date_range",
            "min_date": str(min_date_py),
            "max_date": str(max_date_py),
            "default_range": [str(min_date_py), str(max_date_py)],
        },
    }

    return wrapped_component, metadata, stored_metadata
