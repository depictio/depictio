"""
Interactive Component Utilities.

This module provides utility functions for building and configuring interactive
filter components in dashboards. It supports various component types including:
- RangeSlider: Numeric range filtering with linear and logarithmic scales
- Select/MultiSelect: Categorical selection filtering
- SegmentedControl: Button-based categorical filtering
- DateRangePicker: Date range filtering

Key features:
- Smart mark generation for sliders (linear and logarithmic)
- Default state management for filter reset functionality
- Data loading and filtering with cached column specifications
- Component frame building with proper styling
"""

import math
from datetime import datetime

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import polars as pl
from bson import ObjectId
from dash import dcc, html
from dash_iconify import DashIconify

# PERFORMANCE OPTIMIZATION: Use centralized config
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite


def build_interactive_frame(index, children=None, show_border=False):
    """
    Build interactive component frame with border always visible for draggable delimitation.

    Note: Border is now always shown regardless of show_border parameter for better UX.
    """
    if not children:
        return dmc.Paper(
            children=[
                dmc.Center(
                    dmc.Text(
                        "Configure your interactive component using the edit menu",
                        size="sm",
                        fs="italic",
                        ta="center",
                    ),
                    id={
                        "type": "input-body",
                        "index": index,
                    },
                    p="xl",
                    style={
                        "minHeight": "150px",
                        "height": "100%",
                        "width": "100%",
                        "display": "flex",
                        "alignItems": "center",
                        "justifyContent": "center",
                    },
                )
            ],
            id={
                "type": "interactive-component",
                "index": index,
            },
            w="100%",
            h="100%",
            p=0,
            radius="md",
            withBorder=show_border,
        )
    else:
        return dmc.Paper(
            children=[
                html.Div(
                    children=children,
                    id={
                        "type": "input-body",
                        "index": index,
                    },
                    style={
                        "width": "100%",
                        "height": "100%",
                        "display": "flex",
                        "flexDirection": "column",
                        "justifyContent": "center",  # Center vertically only
                        "padding": "8px",
                    },
                )
            ],
            id={
                "type": "interactive-component",
                "index": index,
            },
            w="100%",
            h="100%",
            p=0,
            radius="md",
            style={
                "width": "100%",
                "height": "100%",
                "display": "flex",
                "flexDirection": "column",
            },
            withBorder=show_border,
        )


def format_mark_label(value):
    """
    Formats the label for the RangeSlider marks without using scientific notation.

    Args:
        value (float or int): The numeric value of the mark.

    Returns:
        str or None: Formatted label as a string, or None if formatting fails.
    """
    try:
        if not isinstance(value, int | float):
            raise TypeError(f"Value {value} is not a number.")

        # Always use consistent float formatting for sliders
        # handle scientific notation if the value is too large
        if value > 1e5:
            label = f"{value:.2e}"
        else:
            # Use float formatting with up to 2 decimal places, but show at least 1 decimal
            if value == int(value):
                # For integer values, show one decimal place for consistency
                label = f"{value:.1f}"
            else:
                # For decimal values, show up to 2 decimal places, removing trailing zeros
                label = f"{value:.2f}".rstrip("0").rstrip(".")
                # Ensure at least one decimal place if it's not a whole number
                if "." not in label and value != int(value):
                    label = f"{value:.1f}"
        return label
    except Exception as e:
        logger.error(f"Error formatting mark label for value '{value}': {e}")
        return None


def generate_equally_spaced_marks(min_val, max_val, marks_count=2, use_log_scale=False):
    """
    Generate equally spaced marks for sliders.
    Always includes min and max values.

    Args:
        min_val (float): Minimum value
        max_val (float): Maximum value
        marks_count (int): Number of marks to generate (minimum 2 for min/max only)
        use_log_scale (bool): Whether to use logarithmic spacing

    Returns:
        dict: Dictionary of mark positions and their labels
    """
    try:
        # Ensure minimum of 2 marks (min and max only)
        marks_count = max(2, marks_count)

        marks = {}

        if use_log_scale:
            # For log scale, create marks at equal intervals in log space
            log_min = min_val  # Already log-transformed
            log_max = max_val  # Already log-transformed

            if marks_count == 1:
                # Special case: only one mark, use the middle
                original_value = 10**log_min
                marks[log_min] = format_mark_label(original_value)
            elif marks_count == 2:
                # Special case: exactly min and max
                original_min = 10**log_min
                original_max = 10**log_max
                marks[log_min] = format_mark_label(original_min)
                marks[log_max] = format_mark_label(original_max)
            else:
                # General case: equal intervals with exact min/max
                original_min = 10**log_min
                original_max = 10**log_max
                marks[log_min] = format_mark_label(original_min)  # Ensure exact min
                marks[log_max] = format_mark_label(original_max)  # Ensure exact max

                # Add intermediate marks if needed
                if marks_count > 2:
                    log_step = (log_max - log_min) / (marks_count - 1)
                    for i in range(1, marks_count - 1):  # Skip first and last (already added)
                        log_pos = log_min + (i * log_step)
                        # Round to avoid floating point precision issues
                        log_pos = round(log_pos, 6)
                        # Convert back to original scale for display
                        original_value = 10**log_pos
                        marks[log_pos] = format_mark_label(original_value)

        else:
            # For linear scale, create marks at equal intervals
            if marks_count == 1:
                # Special case: only one mark, use the middle
                marks[min_val] = format_mark_label(min_val)
            elif marks_count == 2:
                # Special case: exactly min and max
                marks[min_val] = format_mark_label(min_val)
                marks[max_val] = format_mark_label(max_val)
            else:
                # General case: equal intervals
                step = (max_val - min_val) / (marks_count - 1)
                for i in range(marks_count):
                    original_pos = min_val + (i * step)
                    pos = round(original_pos, 6)

                    # Add tiny offset to avoid DCC RangeSlider boundary issues
                    # This affects marks at exact boundaries (min, max) and integer values
                    if i == 0:  # Min mark
                        pos = pos + 1e-10
                    elif abs(pos - round(pos)) < 1e-9:  # Integer or very close to integer
                        pos = pos + 1e-10

                    marks[pos] = format_mark_label(original_pos)  # Use original value for label

        return marks

    except Exception as e:
        logger.error(f"Failed to generate equally spaced marks: {e}")
        # Fallback to min/max marks
        return {min_val: format_mark_label(min_val), max_val: format_mark_label(max_val)}


def generate_log_marks(min_val, max_val, data_min, data_max, tolerance=0.5):
    """
    Generates a dictionary of marks for a log-scaled slider at each order of magnitude.
    Enhanced implementation following Dash "Non-Linear Slider" concepts.

    Args:
        min_val (float): The minimum value of the slider in log-transformed space.
        max_val (float): The maximum value of the slider in log-transformed space.
        data_min (float): The minimum value in the original data space.
        data_max (float): The maximum value in the original data space.
        tolerance (float): Tolerance for avoiding marks too close to min/max.

    Returns:
        dict: A dictionary where keys are positions on the slider and values are formatted labels.
    """
    try:
        # Calculate the exponent range with improved logic
        min_exp = math.floor(min_val)
        max_exp = math.ceil(max_val)

        # Check if this is a small range that needs special handling
        range_span = max_exp - min_exp
        is_small_range = range_span <= 1

        marks = {}

        # Always add the min and max value marks first
        min_log_pos = np.log10(data_min)
        max_log_pos = np.log10(data_max)

        marks[min_log_pos] = format_mark_label(data_min)
        marks[max_log_pos] = format_mark_label(data_max)

        for exp in range(min_exp, max_exp + 1):
            # Calculate the original value at this exponent
            original_value = 10**exp

            # Position on the slider (log-transformed space)
            pos = math.log10(original_value)

            # Skip if outside data range
            if original_value < data_min or original_value > data_max:
                continue

            # Check if this mark is too close to boundaries
            too_close_min = abs(original_value - data_min) / data_min < tolerance
            too_close_max = abs(original_value - data_max) / data_max < tolerance

            # Skip if too close to boundaries (unless it's exactly the boundary or small range)
            if not is_small_range and (
                (too_close_min and original_value != data_min)
                or (too_close_max and original_value != data_max)
            ):
                continue

            # Ensure that pos is within the slider's range
            if min_val <= pos <= max_val:
                label = format_mark_label(original_value)
                if label:
                    # Use float position instead of int for better precision
                    marks[pos] = label
                else:
                    logger.warning(f"Label for value {original_value} is None. Skipping.")

        # Add intermediate marks for better granularity if we have few marks
        if len(marks) < 4:  # Need at least 4 marks for good coverage
            # Add marks at 2x and 5x intervals within each order of magnitude
            for exp in range(min_exp, max_exp + 1):
                for multiplier in [2, 5]:
                    intermediate_value = multiplier * (10**exp)
                    if data_min <= intermediate_value <= data_max:
                        pos = math.log10(intermediate_value)
                        if min_val <= pos <= max_val and pos not in marks:
                            label = format_mark_label(intermediate_value)
                            if label:
                                marks[pos] = label

        # If still too few marks for small ranges, add more intermediate points
        if len(marks) < 3 and is_small_range:
            # Add more granular marks for small ranges
            for exp in range(min_exp, max_exp + 1):
                for multiplier in [1.5, 3, 7]:  # Additional multipliers
                    intermediate_value = multiplier * (10**exp)
                    if data_min <= intermediate_value <= data_max:
                        pos = math.log10(intermediate_value)
                        if min_val <= pos <= max_val and pos not in marks:
                            label = format_mark_label(intermediate_value)
                            if label:
                                marks[pos] = label

        return marks

    except Exception as e:
        logger.error(f"Error generating log marks: {e}")
        return {}


def get_default_state(interactive_component_type, column_name, cols_json, unique_values=None):
    """
    Generate default state for interactive components based on their type and column data.

    Args:
        interactive_component_type (str): Type of interactive component (RangeSlider, Select, etc.)
        column_name (str): Name of the column
        cols_json (dict): Column specifications with statistical data
        unique_values (list, optional): Unique values for select-type components

    Returns:
        dict: Default state information for the component
    """

    if interactive_component_type == "RangeSlider":
        # For range sliders, default state is [min_value, max_value]
        if cols_json and column_name in cols_json:
            column_specs = cols_json[column_name].get("specs", {})
            min_val = column_specs.get("min")
            max_val = column_specs.get("max")

            if min_val is not None and max_val is not None:
                default_range = [min_val, max_val]
                return {
                    "type": "range",
                    "min_value": min_val,
                    "max_value": max_val,
                    "default_range": default_range,
                }

        # Fallback if no column specs available
        logger.warning(f"No min/max specs found for {column_name}, using fallback range")
        return {
            "type": "range",
            "min_value": 0,
            "max_value": 100,
            "default_range": [0, 100],
        }

    elif interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        # For select-type components, default state is usually "All" or first option
        default_options = unique_values if unique_values else []
        default_value = None  # None means "All" / no selection

        return {
            "type": "select",
            "options": default_options,
            "default_value": default_value,
        }

    elif interactive_component_type == "Switch":
        # For switches, default is typically False
        return {
            "type": "boolean",
            "default_value": False,
        }

    elif interactive_component_type == "DateRangePicker":
        # For date range pickers, default state is [min_date, max_date]
        if cols_json and column_name in cols_json:
            column_specs = cols_json[column_name].get("specs") or {}
            min_date = column_specs.get("min")
            max_date = column_specs.get("max")

            if min_date is not None and max_date is not None:
                # Convert to date strings if they're datetime objects
                if hasattr(min_date, "date"):
                    min_date = str(min_date.date() if callable(min_date.date) else min_date)
                if hasattr(max_date, "date"):
                    max_date = str(max_date.date() if callable(max_date.date) else max_date)

                default_range = [min_date, max_date]
                return {
                    "type": "date_range",
                    "min_date": min_date,
                    "max_date": max_date,
                    "default_range": default_range,
                }

        # Fallback if no column specs available
        logger.warning(f"No min/max date specs found for {column_name}")
        return {
            "type": "date_range",
            "min_date": None,
            "max_date": None,
            "default_range": [None, None],
        }

    else:
        # Generic fallback for unknown component types
        logger.warning(f"Unknown interactive component type: {interactive_component_type}")
        return {
            "type": "unknown",
            "default_value": None,
        }


def get_valid_min_max(df, column_name, cols_json):
    """
    Retrieves valid min and max values for a given column.

    Args:
        df (pd.DataFrame): The DataFrame containing the data.
        column_name (str): The name of the column to process.
        cols_json (dict): Dictionary containing column specifications.

    Returns:
        tuple: (min_value, max_value) rounded to 2 decimal places.
    """
    # Initialize min_value and max_value from cols_json
    min_value = cols_json.get(column_name, {}).get("specs", {}).get("min", None)
    max_value = cols_json.get(column_name, {}).get("specs", {}).get("max", None)

    # Helper function to validate and round values
    def validate_and_round(value, value_type="Min"):
        """
        Validates that the value is a finite number and rounds it.

        Args:
            value (float or int): The value to validate and round.
            value_type (str): A label indicating whether it's min or max.

        Returns:
            float: Rounded value if valid, else None.
        """
        try:
            if value is not None:
                value = float(value)
                if math.isinf(value):
                    raise ValueError(f"{value_type} value is infinite.")
                if math.isnan(value):
                    raise ValueError(f"{value_type} value is NaN.")
                return round(value, 2)
            else:
                raise ValueError(f"{value_type} value is None.")
        except (TypeError, ValueError) as e:
            logger.warning(f"{value_type} value from specs is invalid: {e}")
            return None

    # Validate and round min_value
    min_value = validate_and_round(min_value, "Min")

    # Validate and round max_value
    max_value = validate_and_round(max_value, "Max")

    # If min_value is invalid, compute it from the DataFrame
    if min_value is None:
        computed_min = df[column_name].replace([np.inf, -np.inf], np.nan).dropna().min()
        if pd.notnull(computed_min):
            min_value = round(float(computed_min), 2)
        else:
            # Define a default min_value if DataFrame min is not available
            min_value = 0.0
            logger.warning(
                f"DataFrame min is not available. Setting Min value to default: {min_value}"
            )

    # If max_value is invalid, compute it from the DataFrame
    if max_value is None:
        computed_max = df[column_name].replace([np.inf, -np.inf], np.nan).dropna().max()
        if pd.notnull(computed_max):
            max_value = round(float(computed_max), 2)
        else:
            # Define a default max_value if DataFrame max is not available
            max_value = 1.0
            logger.warning(
                f"DataFrame max is not available. Setting Max value to default: {max_value}"
            )

    # Final validation to ensure min_value <= max_value
    if min_value > max_value:
        logger.error(
            f"Min value ({min_value}) is greater than Max value ({max_value}). Swapping values."
        )
        min_value, max_value = max_value, min_value

    return min_value, max_value


def is_highly_skewed(series, threshold=1.0):
    """
    Determines if the distribution of the series is highly skewed.

    Args:
        series (pd.Series): The data series to analyze.
        threshold (float): The skewness threshold to determine high skewness.

    Returns:
        bool: True if skewness is greater than the threshold, else False.
    """
    skewness = series.skew()
    return abs(skewness) > threshold


def apply_log_transformation(series, shift=1e-6):
    """
    Applies a logarithmic transformation to the series after shifting to handle non-positive values.

    Args:
        series (pd.Series): The data series to transform.
        shift (float): A small constant to shift the data if minimum value is <= 0.

    Returns:
        pd.Series: The log-transformed series.
        float: The shift applied to the data (0 if no shift was needed).
    """
    min_val = series.min()
    if min_val < 0:
        shift_amount = abs(min_val) + shift
        transformed_series = np.log10(series + shift_amount)
        return transformed_series, shift_amount
    else:
        transformed_series = np.log10(series)
        return transformed_series, 0.0


# -----------------------------------------------------------------------------
# Component Builder Helper Functions
# -----------------------------------------------------------------------------


def _build_select_component(
    df,
    column_name,
    index,
    value,
    value_div_type,
    interactive_component_type,
    func_name,
    color,
):
    """
    Build a Select, MultiSelect, or SegmentedControl component.

    Creates categorical selection components with proper value handling,
    option generation, and styling.

    Args:
        df: Polars DataFrame containing the data.
        column_name: Name of the column to use for options.
        index: Unique component identifier.
        value: Initial/current value for the component.
        value_div_type: Type suffix for component ID.
        interactive_component_type: One of "Select", "MultiSelect", "SegmentedControl".
        func_name: DMC component constructor function.
        color: Custom color for styling (optional).

    Returns:
        The constructed DMC component (Select, MultiSelect, SegmentedControl, or Text for errors).
    """

    # Check if column exists before processing
    if column_name not in df.columns:
        logger.error(f"SCHEMA MISMATCH: Column '{column_name}' not found in DataFrame")
        logger.error(f"Available columns: {df.columns}")
        # Return empty component to prevent crash
        return dmc.Text(f"Error: Column '{column_name}' not found", c="red")

    data = sorted(df[column_name].drop_nulls().unique())

    # If DataFrame is empty but we have a preserved value, include those values in options
    if df.height == 0 and value:
        if interactive_component_type == "MultiSelect" and isinstance(value, list):
            for val in value:
                if val not in data:
                    data.append(val)
            data = sorted(data)
        elif interactive_component_type in ["Select", "SegmentedControl"] and value not in data:
            data.append(value)
            data = sorted(data)

    # Prepare kwargs for all component types
    component_kwargs = {
        "data": data,
        "id": {"type": value_div_type, "index": str(index)},
        "w": "100%",
        "size": "md",
        "styles": {
            "root": {
                "width": "100%",
                "minWidth": "50px",
            },
        },
    }

    # Process and validate value based on component type
    processed_value = _process_select_value(value, data, index, interactive_component_type)
    if processed_value is not None:
        component_kwargs["value"] = processed_value
    elif interactive_component_type == "SegmentedControl":
        # For SegmentedControl, explicitly set value to None for no selection
        component_kwargs["value"] = None

    # Apply custom color styling
    if color:
        existing_styles = component_kwargs.get("styles", {})
        color_styles = {
            "input": {"borderColor": color},
            "dropdown": {"borderColor": color},
            "label": {"color": color},
        }
        component_kwargs["styles"] = {**existing_styles, **color_styles}

    interactive_component = func_name(**component_kwargs)

    # Add MultiSelect-specific properties
    if interactive_component_type == "MultiSelect":
        multiselect_kwargs = {
            "searchable": True,
            "clearable": True,
            "limit": 100,
            "persistence_type": "local",
        }
        component_kwargs.update(multiselect_kwargs)
        interactive_component = func_name(**component_kwargs)

    return interactive_component


def _process_select_value(value, data: list, index: str, interactive_component_type: str):
    """
    Process and validate a value for Select-type components.

    Handles value type conversion, validation against available options,
    and proper handling for different component types.

    Args:
        value: The initial value to process.
        data: List of available options.
        index: Component index for logging.
        interactive_component_type: Type of component (Select, MultiSelect, SegmentedControl).

    Returns:
        The processed value, or None if no valid value.
    """
    if value is None:
        return None

    if interactive_component_type == "Select":
        return _process_single_select_value(value, data, index, "Select")

    elif interactive_component_type == "SegmentedControl":
        return _process_single_select_value(value, data, index, "SegmentedControl")

    elif interactive_component_type == "MultiSelect":
        return _process_multiselect_value(value, data, index)

    return None


def _process_single_select_value(value, data: list, index: str, component_type: str):
    """
    Process value for single-selection components (Select, SegmentedControl).

    Args:
        value: The value to process.
        data: List of available options.
        index: Component index for logging.
        component_type: Either "Select" or "SegmentedControl".

    Returns:
        The validated string value, or None if invalid.
    """
    # Convert value to string if needed
    if not isinstance(value, str):
        if isinstance(value, (list, tuple)):
            logger.warning(
                f"{component_type} component {index}: Ignoring array value {value} from slider"
            )
            return None
        else:
            value = str(value) if value is not None else None

    if value and value in data:
        return value
    elif value:
        logger.warning(
            f"{component_type} component {index}: Value '{value}' no longer available in options {data}"
        )
    return None


def _process_multiselect_value(value, data: list, index: str) -> list | None:
    """
    Process value for MultiSelect component.

    Args:
        value: The value to process.
        data: List of available options.
        index: Component index for logging.

    Returns:
        The processed list value.
    """
    # Ensure value is a list
    if not isinstance(value, list):
        if isinstance(value, (tuple, set)):
            value = list(value)
        else:
            value = [str(value)]

    # Convert all values to strings
    value = [str(v) for v in value if v is not None]
    return value


def _build_slider_component(
    df,
    column_name,
    index,
    value,
    value_div_type,
    interactive_component_type,
    func_name,
    scale,
    cols_json,
    marks_number,
    title_size,
    color,
    store_data,
):
    """
    Build a Slider or RangeSlider component.

    Creates numeric slider components with proper value handling, scale transformation,
    and mark generation.

    Args:
        df: Polars DataFrame containing the data.
        column_name: Name of the column to use for range.
        index: Unique component identifier.
        value: Initial/current value for the component.
        value_div_type: Type suffix for component ID.
        interactive_component_type: One of "Slider" or "RangeSlider".
        func_name: DMC component constructor function.
        scale: Scale type ("linear" or "log10").
        cols_json: Column specifications with min/max data.
        marks_number: Number of marks to display on slider.
        title_size: Size for title and slider.
        color: Custom color for styling (optional).
        store_data: Dictionary to update with scale information.

    Returns:
        The constructed DMC Slider or RangeSlider component.
    """

    # Convert Polars DataFrame to Pandas for processing
    df_pandas = df.to_pandas()

    # Check if column exists before processing
    if column_name not in df_pandas.columns:
        logger.error(f"SCHEMA MISMATCH: Column '{column_name}' not found in DataFrame")
        logger.error(f"Available columns: {list(df_pandas.columns)}")
        return []

    # Clean data
    df_pandas = _clean_numeric_column(df_pandas, column_name)

    # Determine scale type
    use_log_scale = scale is not None and scale == "log10"

    # Apply log transformation if needed
    if use_log_scale:
        transformed_series, _ = apply_log_transformation(df_pandas[column_name])
        df_pandas[f"{column_name}_log10"] = transformed_series

    # Get valid min and max
    series_name = f"{column_name}_log10" if use_log_scale else column_name
    min_value, max_value = get_valid_min_max(df_pandas, series_name, cols_json)
    min_value, max_value = _validate_slider_range(min_value, max_value)

    # Build component kwargs
    kwargs_component = _build_slider_kwargs(
        min_value, max_value, index, value_div_type, title_size, interactive_component_type
    )

    # Set component value
    if interactive_component_type == "RangeSlider":
        _set_range_slider_value(kwargs_component, value, min_value, max_value)
    else:
        _set_slider_value(kwargs_component, value, min_value, max_value)

    # Apply custom color
    if color:
        kwargs_component["color"] = color

    # Generate marks
    _add_slider_marks(
        kwargs_component, min_value, max_value, marks_number, use_log_scale, df_pandas, column_name
    )

    interactive_component = func_name(**kwargs_component)

    # Store scale information
    store_data["scale"] = "log10" if use_log_scale else "linear"
    if use_log_scale:
        if interactive_component_type == "RangeSlider":
            real_value = [10**val for val in value] if isinstance(value, list) else value
        else:
            real_value = 10**value if value is not None else value
        store_data["original_value"] = real_value
    else:
        store_data["original_value"] = value

    return interactive_component


def _clean_numeric_column(df_pandas: pd.DataFrame, column_name: str) -> pd.DataFrame:
    """
    Clean a numeric column by removing invalid values.

    Args:
        df_pandas: Pandas DataFrame to clean.
        column_name: Name of the column to clean.

    Returns:
        Cleaned DataFrame.
    """
    df_pandas = df_pandas[~df_pandas[column_name].isin([None, "None", "nan", "NaN"])]
    df_pandas[column_name] = df_pandas[column_name].replace([np.inf, -np.inf], np.nan)
    df_pandas[column_name] = df_pandas[column_name].astype(float)
    df_pandas[column_name] = df_pandas[column_name].apply(
        lambda x: round(x, 2) if x not in [float("inf"), float("-inf")] else x
    )
    df_pandas = df_pandas.dropna(subset=[column_name])
    return df_pandas


def _validate_slider_range(min_value: float, max_value: float) -> tuple[float, float]:
    """
    Validate and correct slider min/max range.

    Args:
        min_value: Minimum value.
        max_value: Maximum value.

    Returns:
        Validated (min_value, max_value) tuple.
    """
    if min_value is None or math.isnan(min_value) or math.isinf(min_value):
        min_value = 0.0
        logger.warning("Invalid min_value detected, setting to 0.0")

    if max_value is None or math.isnan(max_value) or math.isinf(max_value):
        max_value = 100.0
        logger.warning("Invalid max_value detected, setting to 100.0")

    if min_value >= max_value:
        max_value = min_value + 1.0
        logger.warning(f"min_value >= max_value, adjusted max_value to {max_value}")

    return min_value, max_value


def _build_slider_kwargs(
    min_value: float,
    max_value: float,
    index: str,
    value_div_type: str,
    title_size: str,
    interactive_component_type: str,
) -> dict:
    """
    Build base kwargs for slider components.

    Args:
        min_value: Minimum slider value.
        max_value: Maximum slider value.
        index: Component index.
        value_div_type: Type suffix for component ID.
        title_size: Size for slider.
        interactive_component_type: "Slider" or "RangeSlider".

    Returns:
        Dictionary of kwargs for the slider component.
    """
    kwargs_component = {
        "min": float(min_value),
        "max": float(max_value),
        "id": {"type": value_div_type, "index": str(index)},
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

    if interactive_component_type == "RangeSlider":
        kwargs_component["minRange"] = 0.01

    return kwargs_component


def _set_range_slider_value(
    kwargs_component: dict, value, min_value: float, max_value: float
) -> None:
    """
    Set and validate value for RangeSlider component.

    Args:
        kwargs_component: Dictionary to update with value.
        value: Initial value to process.
        min_value: Minimum allowed value.
        max_value: Maximum allowed value.
    """
    try:
        if (
            value is None
            or value == "null"
            or value == "None"
            or not isinstance(value, list)
            or len(value) != 2
            or any(v is None or v == "null" or v == "None" for v in value)
        ):
            cleaned_value = [min_value, max_value]
        else:
            cleaned_value = []
            for i, v in enumerate(value):
                try:
                    if v is None or v == "None":
                        clean_val = min_value if i == 0 else max_value
                    else:
                        decimal_val = float(v)
                        if not (math.isnan(decimal_val) or math.isinf(decimal_val)):
                            clean_val = max(min_value, min(max_value, decimal_val))
                        else:
                            clean_val = min_value if i == 0 else max_value
                    cleaned_value.append(clean_val)
                except (ValueError, TypeError):
                    fallback_val = min_value if i == 0 else max_value
                    cleaned_value.append(fallback_val)

            if cleaned_value[0] > cleaned_value[1]:
                cleaned_value = [cleaned_value[1], cleaned_value[0]]

        kwargs_component["value"] = cleaned_value

    except Exception as e:
        logger.error(f"DMC RangeSlider: Exception: {e}")


def _set_slider_value(kwargs_component: dict, value, min_value: float, max_value: float) -> None:
    """
    Set and validate value for Slider component.

    Args:
        kwargs_component: Dictionary to update with value.
        value: Initial value to process.
        min_value: Minimum allowed value.
        max_value: Maximum allowed value.
    """
    try:
        if (
            value is None
            or value == "null"
            or value == "None"
            or (isinstance(value, float) and math.isnan(value))
        ):
            cleaned_value = (min_value + max_value) / 2
        else:
            cleaned_value = float(value)
            cleaned_value = max(min_value, min(max_value, cleaned_value))

        kwargs_component["value"] = cleaned_value
    except (ValueError, TypeError):
        pass


def _add_slider_marks(
    kwargs_component: dict,
    min_value: float,
    max_value: float,
    marks_number: int,
    use_log_scale: bool,
    df_pandas: pd.DataFrame,
    column_name: str,
) -> None:
    """
    Generate and add marks to slider kwargs.

    Args:
        kwargs_component: Dictionary to update with marks.
        min_value: Minimum slider value.
        max_value: Maximum slider value.
        marks_number: Number of marks to generate.
        use_log_scale: Whether using logarithmic scale.
        df_pandas: DataFrame for log scale calculations.
        column_name: Column name for log scale calculations.
    """
    effective_marks_number = marks_number if marks_number and marks_number > 0 else 2

    if use_log_scale:
        marks_dict = generate_log_marks(
            min_value, max_value, df_pandas[column_name].min(), df_pandas[column_name].max()
        )
    else:
        marks_dict = generate_equally_spaced_marks(
            min_value, max_value, marks_count=effective_marks_number, use_log_scale=False
        )

    if marks_dict:
        dmc_marks = []
        for mark_value, label in marks_dict.items():
            try:
                mark_val = float(mark_value)
                tolerance = 1e-9
                if (min_value - tolerance) <= mark_val <= (max_value + tolerance):
                    dmc_marks.append(
                        {
                            "value": mark_val,
                            "label": dmc.Text(str(label), size="xs"),
                        }
                    )
                else:
                    pass
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping invalid mark: {mark_value} -> {label}, error: {e}")

        if dmc_marks:
            kwargs_component["marks"] = dmc_marks
        else:
            logger.warning("No valid DMC marks created")
    else:
        logger.warning("No marks generated from mark generation function")


def _build_date_range_picker_component(
    df,
    column_name,
    index,
    value,
    value_div_type,
    func_name,
    title_size,
    color,
    store_data,
):
    """
    Build a DateRangePicker component.

    Creates a date range picker component with proper date handling and validation.

    Args:
        df: Polars DataFrame containing the data.
        column_name: Name of the datetime column.
        index: Unique component identifier.
        value: Initial/current value for the component.
        value_div_type: Type suffix for component ID.
        func_name: DMC component constructor function.
        title_size: Size for the component.
        color: Custom color for styling (optional).
        store_data: Dictionary to update with date range information.

    Returns:
        The constructed DMC DatePickerInput component.
    """

    # Convert Polars DataFrame to Pandas for processing
    df_pandas = df.to_pandas()

    # Check if column exists before processing
    if column_name not in df_pandas.columns:
        logger.error(f"SCHEMA MISMATCH: Column '{column_name}' not found in DataFrame")
        logger.error(f"Available columns: {list(df_pandas.columns)}")
        return dmc.Text(f"Error: Column '{column_name}' not found", c="red")

    # Ensure column is datetime type
    if not pd.api.types.is_datetime64_any_dtype(df_pandas[column_name]):
        logger.error(
            f"Column '{column_name}' is not a datetime type: {df_pandas[column_name].dtype}"
        )
        return dmc.Text(f"Error: Column '{column_name}' must be datetime type", c="red")

    # Get min and max dates from the column
    df_pandas[column_name] = pd.to_datetime(df_pandas[column_name], errors="coerce")
    df_pandas = df_pandas.dropna(subset=[column_name])

    if df_pandas.empty:
        logger.error(f"No valid datetime values found in column '{column_name}'")
        return dmc.Text(f"Error: No valid dates in column '{column_name}'", c="red")

    min_date = df_pandas[column_name].min()
    max_date = df_pandas[column_name].max()

    # Convert to Python date objects (DMC requires date, not datetime)
    min_date_py = min_date.date()
    max_date_py = max_date.date()

    # Prepare kwargs for DMC DatePickerInput
    kwargs_component = {
        "type": "range",
        "id": {"type": value_div_type, "index": str(index)},
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

    # Handle value persistence
    if value is not None and isinstance(value, list) and len(value) == 2:
        try:
            if isinstance(value[0], str):
                value[0] = datetime.strptime(value[0], "%Y-%m-%d").date()
            if isinstance(value[1], str):
                value[1] = datetime.strptime(value[1], "%Y-%m-%d").date()

            value[0] = max(min_date_py, min(max_date_py, value[0]))
            value[1] = max(min_date_py, min(max_date_py, value[1]))

            kwargs_component["value"] = value
        except Exception as e:
            logger.warning(f"Failed to parse date range value {value}: {e}")
            kwargs_component["value"] = [min_date_py, max_date_py]
    else:
        kwargs_component["value"] = [min_date_py, max_date_py]

    # Apply custom color if specified
    if color:
        existing_styles = kwargs_component.get("styles", {})
        color_styles = {
            "input": {"borderColor": color},
            "label": {"color": color},
        }
        kwargs_component["styles"] = {**existing_styles, **color_styles}

    interactive_component = func_name(**kwargs_component)

    # Store date range information
    store_data["min_date"] = str(min_date_py)
    store_data["max_date"] = str(max_date_py)
    store_data["default_state"] = {
        "type": "date_range",
        "min_date": str(min_date_py),
        "max_date": str(max_date_py),
        "default_range": [str(min_date_py), str(max_date_py)],
    }

    return interactive_component


def _build_boolean_component(
    index,
    value,
    value_div_type,
    interactive_component_type,
    func_name,
    color,
):
    """
    Build a Checkbox or Switch component.

    Creates boolean input components with proper value handling.

    Args:
        index: Unique component identifier.
        value: Initial/current value for the component.
        value_div_type: Type suffix for component ID.
        interactive_component_type: One of "Checkbox" or "Switch".
        func_name: DMC component constructor function.
        color: Custom color for styling (optional).

    Returns:
        The constructed DMC Checkbox or Switch component.
    """

    kwargs = {"persistence_type": "local"}

    if value is None:
        value = False

    # Convert value to boolean if needed
    if isinstance(value, str):
        value = value.lower() in ["true", "1", "yes", "on"]
    elif not isinstance(value, bool):
        value = bool(value)

    kwargs["checked"] = value

    if color:
        kwargs["color"] = color

    return func_name(
        id={"type": value_div_type, "index": str(index)},
        **kwargs,
    )


def _build_fallback_component(
    index,
    value_div_type,
    interactive_component_type,
    column_type,
    column_name,
):
    """
    Build a fallback component for unsupported types.

    Creates an error message component when the requested component type
    is not supported for the given column type.

    Args:
        index: Unique component identifier.
        value_div_type: Type suffix for component ID.
        interactive_component_type: Requested component type.
        column_type: Data type of the column.
        column_name: Name of the column.

    Returns:
        A DMC Text component displaying an error message.
    """
    logger.warning(f"Unsupported interactive component type: {interactive_component_type}")
    logger.warning(f"Column type: {column_type}")
    logger.warning(f"Column name: {column_name}")
    # Get available component types for the column type
    column_config = agg_functions.get(column_type, {}) if column_type else {}
    input_methods = (
        column_config.get("input_methods", {}) if isinstance(column_config, dict) else {}
    )
    available_types = list(input_methods.keys()) if isinstance(input_methods, dict) else []
    logger.warning(f"Available component types: {available_types}")

    return dmc.Text(
        f"Unsupported component type: {interactive_component_type} for {column_type} data",
        id={"type": value_div_type, "index": str(index)},
        c="red",
    )


def _build_frame_mode_component(
    index,
    wf_id,
    dc_id,
    column_name,
    column_type,
    interactive_component_type,
    scale,
    title,
    icon_name,
    marks_number,
    title_size,
    color,
    value,
    parent_index,
    stepper,
    value_div_type,
):
    """
    Build a frame mode component with placeholder and trigger stores.

    Creates a placeholder component with loader that will be populated
    by callback later. This avoids the "Loading..." -> component transition.

    Args:
        index: Unique component identifier.
        wf_id: Workflow ID for data loading.
        dc_id: Data collection ID for data loading.
        column_name: Name of the column to filter.
        column_type: Data type of the column.
        interactive_component_type: Type of filter component.
        scale: Scale type ("linear" or "log10").
        title: Display title for the filter.
        icon_name: Icon name for the component.
        marks_number: Number of marks for sliders.
        title_size: Size for title text.
        color: Custom color for styling.
        value: Initial/current value.
        parent_index: Parent component index if nested.
        stepper: Whether in stepper (creation) mode.
        value_div_type: Type suffix for component ID.

    Returns:
        dmc.Paper: Frame with placeholder component and trigger stores.
    """

    component_with_loader = html.Div(
        id={"type": f"{value_div_type}-container", "index": str(index)},
        children=[
            dmc.Center(
                dmc.Loader(type="dots", size="lg"),
                style={"minHeight": "120px"},
            )
        ],
        style={"padding": "10px"},
    )

    trigger_store = dcc.Store(
        id={"type": "interactive-trigger", "index": str(index)},
        data={
            "index": str(index),
            "wf_id": str(wf_id) if wf_id else None,
            "dc_id": str(dc_id) if dc_id else None,
            "column_name": column_name,
            "column_type": column_type,
            "interactive_component_type": interactive_component_type,
            "scale": scale,
            "title": title,
            "icon_name": icon_name,
            "marks_number": marks_number,
            "title_size": title_size,
            "color": color,
            "value": value,
            "parent_index": parent_index,
            "stepper": stepper,
        },
    )

    metadata_store = dcc.Store(id={"type": "interactive-metadata", "index": str(index)}, data={})

    options_data_store = dcc.Store(
        id={"type": "interactive-options-data", "index": str(index)},
        data={},
        storage_type="memory",
    )

    interactive_stored_metadata = dcc.Store(
        id={"type": "interactive-stored-metadata", "index": str(index)},
        data={
            "index": str(index),
            "interactive_component_type": interactive_component_type,
            "column_name": column_name,
            "default_state": {},
        },
        storage_type="memory",
    )

    return build_interactive_frame(
        index=index,
        children=[
            component_with_loader,
            trigger_store,
            metadata_store,
            options_data_store,
            interactive_stored_metadata,
        ],
    )


def _load_data_for_component(
    df,
    wf_id,
    dc_id,
    interactive_component_type,
    TOKEN,
    init_data,
    index,
):
    """
    Load data for the interactive component.

    Handles loading unfiltered data for categorical components and general
    data loading for other component types.

    Args:
        df: Pre-loaded DataFrame or None.
        wf_id: Workflow ID for data loading.
        dc_id: Data collection ID for data loading.
        interactive_component_type: Type of filter component.
        TOKEN: Authentication token for API calls.
        init_data: Pre-loaded initialization data.
        index: Component index for logging.

    Returns:
        pl.DataFrame: Loaded data for the component.
    """
    # For categorical components, always load unfiltered data for options
    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        if not wf_id or not dc_id:
            logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
            return pl.DataFrame({})

        if isinstance(dc_id, str) and "--" in dc_id:
            return load_deltatable_lite(
                ObjectId(wf_id),
                dc_id,
                TOKEN=TOKEN,
                load_for_options=True,
                init_data=init_data,
            )
        else:
            return load_deltatable_lite(
                ObjectId(wf_id),
                ObjectId(dc_id),
                TOKEN=TOKEN,
                load_for_options=True,
                init_data=init_data,
            )

    elif df is None:
        if not wf_id or not dc_id:
            logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
            return pl.DataFrame({})

        if isinstance(dc_id, str) and "--" in dc_id:
            return load_deltatable_lite(
                ObjectId(wf_id),
                dc_id,
                TOKEN=TOKEN,
                init_data=init_data,
            )
        else:
            return load_deltatable_lite(
                ObjectId(wf_id),
                ObjectId(dc_id),
                TOKEN=TOKEN,
                init_data=init_data,
            )

    else:
        return df


def _build_component_title(
    title,
    interactive_component_type,
    column_name,
    store_data,
    icon_name,
    title_size,
    color,
):
    """
    Build the title section for an interactive component.

    Creates a title with icon and proper styling.

    Args:
        title: Custom title or None.
        interactive_component_type: Type of component.
        column_name: Name of the column.
        store_data: Store data dictionary to check for scale.
        icon_name: Icon name to display.
        title_size: Size for title text.
        color: Custom color for styling.

    Returns:
        dmc.Group: Title component with icon and text.
    """
    if not title:
        card_title = f"{interactive_component_type} on {column_name}"
    else:
        card_title = f"{title}"

    # Add scale information for sliders
    if (
        interactive_component_type in ["Slider", "RangeSlider"]
        and store_data.get("scale") == "log10"
    ):
        card_title += " (Log10 Scale)"

    title_style = {
        "marginBottom": "0.25rem",
    }
    icon_color = color if color else None

    if color:
        title_style["color"] = color
    else:
        pass
    icon_props = {
        "icon": icon_name,
        "width": int(title_size) if title_size.isdigit() else 20,
    }
    if icon_color:
        icon_props["style"] = {"color": icon_color}
    else:
        icon_props["style"] = {"opacity": 0.9}

    # Map title_size to valid DMC Text size literal
    valid_sizes = {"xs", "sm", "md", "lg", "xl"}
    text_size: str | None = title_size if title_size in valid_sizes else None

    return dmc.Group(
        [
            DashIconify(**icon_props),
            dmc.Text(card_title, size=text_size, fw="bold", style={"margin": "0"}),
        ],
        gap="xs",
        align="center",
        style=title_style,
    )


def _extract_unique_values(df, column_name, interactive_component_type):
    """
    Extract unique values from DataFrame for select-type components.

    Args:
        df: DataFrame to extract values from.
        column_name: Name of the column.
        interactive_component_type: Type of component.

    Returns:
        List of unique string values, or None if extraction fails.
    """
    if interactive_component_type not in ["Select", "MultiSelect", "SegmentedControl"]:
        return None

    if df is None:
        return None

    try:
        unique_vals = df[column_name].unique()
        if hasattr(unique_vals, "to_list") and callable(getattr(unique_vals, "to_list", None)):
            unique_vals_list = unique_vals.to_list()
        elif hasattr(unique_vals, "tolist") and callable(getattr(unique_vals, "tolist", None)):
            unique_vals_list = unique_vals.tolist()
        else:
            unique_vals_list = list(unique_vals)

        unique_values = [str(val) for val in unique_vals_list if val is not None][:100]
        return unique_values
    except Exception as e:
        logger.warning(f"Failed to extract unique values for {column_name}: {e}")
        return []


# -----------------------------------------------------------------------------
# Main Build Function
# -----------------------------------------------------------------------------


def build_interactive(**kwargs):
    """
    Build an interactive filter component for the dashboard.

    Creates various types of interactive filter components (Select, MultiSelect,
    RangeSlider, DateRangePicker, SegmentedControl, etc.) based on the specified
    parameters and data column characteristics.

    Supported interactive_component_type values:
    - Select: Single selection dropdown
    - MultiSelect: Multiple selection dropdown
    - SegmentedControl: Radio-button style selector
    - RangeSlider: Numeric range slider
    - DateRangePicker: Date range picker
    - Slider: Single value slider
    - TextInput: Free text input

    Args:
        **kwargs: Keyword arguments including:
            index (str): Unique component identifier.
            title (str): Display title for the filter.
            wf_id (str): Workflow ID for data loading.
            dc_id (str): Data collection ID for data loading.
            column_name (str): Name of the column to filter.
            column_type (str): Data type of the column.
            interactive_component_type (str): Type of filter component.
            value: Initial/current value for the component.
            df: Pre-loaded DataFrame (optional).
            build_frame (bool): Whether to wrap in frame container.
            access_token (str): Authentication token for API calls.
            stepper (bool): Whether in stepper (creation) mode.
            parent_index (str): Parent component index if nested.
            scale (str): "linear" or "log" for numeric components.
            color (str): Custom color for component styling.

    Returns:
        dmc.Paper: The complete interactive filter component wrapped in a container.
    """
    # Extract all kwargs
    index = kwargs.get("index")
    title = kwargs.get("title")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    column_name = kwargs.get("column_name")
    column_type = kwargs.get("column_type")
    interactive_component_type = kwargs.get("interactive_component_type")
    value = kwargs.get("value", None)
    df = kwargs.get("df", None)
    build_frame = kwargs.get("build_frame", False)
    TOKEN = kwargs.get("access_token")
    stepper = kwargs.get("stepper", False)
    parent_index = kwargs.get("parent_index", None)
    scale = kwargs.get("scale", "linear")
    color = kwargs.get("color") or kwargs.get("custom_color") or None

    init_data = kwargs.get("init_data", None)

    # Extract cols_json from init_data if available
    cols_json = None
    if init_data and "column_specs" in init_data and str(dc_id) in init_data["column_specs"]:
        cols_json = init_data["column_specs"][str(dc_id)]
    else:
        pass
    # Default icon mapping
    DEFAULT_ICONS = {
        "Select": "mdi:form-select",
        "MultiSelect": "mdi:form-select",
        "SegmentedControl": "mdi:toggle-switch",
        "Slider": "bx:slider-alt",
        "RangeSlider": "bx:slider-alt",
        "DateRangePicker": "mdi:calendar-range",
        "Checkbox": "mdi:checkbox-marked",
        "Switch": "mdi:toggle-switch",
    }

    default_icon = DEFAULT_ICONS.get(interactive_component_type, "bx:slider-alt")
    icon_name = kwargs.get("icon_name") or default_icon

    marks_number = kwargs.get("marks_number", 2)
    title_size = kwargs.get("title_size", "md")
    cols_json = kwargs.get("cols_json")

    # Determine value div type based on stepper mode
    value_div_type = "interactive-component-value-tmp" if stepper else "interactive-component-value"

    # Build frame mode: create placeholder component with loader
    if build_frame:
        return _build_frame_mode_component(
            index=index,
            wf_id=wf_id,
            dc_id=dc_id,
            column_name=column_name,
            column_type=column_type,
            interactive_component_type=interactive_component_type,
            scale=scale,
            title=title,
            icon_name=icon_name,
            marks_number=marks_number,
            title_size=title_size,
            color=color,
            value=value,
            parent_index=parent_index,
            stepper=stepper,
            value_div_type=value_div_type,
        )

    # Validate required parameters are not None
    if interactive_component_type is None:
        raise ValueError("interactive_component_type cannot be None")
    if column_type is None:
        raise ValueError("column_type cannot be None")
    if column_type not in agg_functions:
        raise ValueError(f"Unknown column_type: {column_type}")

    # Validate component type for column type
    column_config = agg_functions[column_type]
    input_methods = column_config["input_methods"]
    if interactive_component_type not in input_methods:
        available_options = list(input_methods.keys())
        logger.error(
            f"INVALID COMBINATION: {interactive_component_type} not available for {column_type} columns"
        )
        logger.error(f"Available options: {available_options}")
        raise ValueError(
            f"Interactive component type '{interactive_component_type}' is not available for column type '{column_type}'. Available options: {available_options}"
        )

    func_name = input_methods[interactive_component_type]["component"]

    # Determine store index
    if stepper:
        store_index = index
        data_index = index.replace("-tmp", "") if index else "unknown"
    else:
        store_index = index.replace("-tmp", "") if index else "unknown"
        data_index = store_index

    store_data = {
        "component_type": "interactive",
        "interactive_component_type": interactive_component_type,
        "index": str(data_index),
        "title": title,
        "wf_id": wf_id,
        "dc_id": dc_id,
        "column_name": column_name,
        "column_type": column_type,
        "value": value,
        "corrected_value": value,
        "parent_index": parent_index,
        "scale": scale,
        "marks_number": marks_number,
        "title_size": title_size,
        "custom_color": color,
        "icon_name": icon_name,
    }

    # Load data
    df = _load_data_for_component(
        df, wf_id, dc_id, interactive_component_type, TOKEN, init_data, index
    )

    # Build the appropriate component type
    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        interactive_component = _build_select_component(
            df=df,
            column_name=column_name,
            index=index,
            value=value,
            value_div_type=value_div_type,
            interactive_component_type=interactive_component_type,
            func_name=func_name,
            color=color,
        )

    elif interactive_component_type in ["Slider", "RangeSlider"]:
        interactive_component = _build_slider_component(
            df=df,
            column_name=column_name,
            index=index,
            value=value,
            value_div_type=value_div_type,
            interactive_component_type=interactive_component_type,
            func_name=func_name,
            scale=scale,
            cols_json=cols_json,
            marks_number=marks_number,
            title_size=title_size,
            color=color,
            store_data=store_data,
        )

    elif interactive_component_type == "DateRangePicker":
        interactive_component = _build_date_range_picker_component(
            df=df,
            column_name=column_name,
            index=index,
            value=value,
            value_div_type=value_div_type,
            func_name=func_name,
            title_size=title_size,
            color=color,
            store_data=store_data,
        )

    elif interactive_component_type in ["Checkbox", "Switch"]:
        interactive_component = _build_boolean_component(
            index=index,
            value=value,
            value_div_type=value_div_type,
            interactive_component_type=interactive_component_type,
            func_name=func_name,
            color=color,
        )

    else:
        interactive_component = _build_fallback_component(
            index=index,
            value_div_type=value_div_type,
            interactive_component_type=interactive_component_type,
            column_type=column_type,
            column_name=column_name,
        )

    # Build title
    card_title_h5 = _build_component_title(
        title=title,
        interactive_component_type=interactive_component_type,
        column_name=column_name,
        store_data=store_data,
        icon_name=icon_name,
        title_size=title_size,
        color=color,
    )

    if interactive_component_type in ["Slider", "RangeSlider"]:
        pass
    else:
        pass
    # Extract unique values and generate default state
    unique_values = _extract_unique_values(df, column_name, interactive_component_type)

    if "default_state" not in store_data:
        default_state = get_default_state(
            interactive_component_type, column_name, cols_json, unique_values
        )
        store_data["default_state"] = default_state
    else:
        pass
    store_component = dcc.Store(
        id={"type": "interactive-stored-metadata", "index": str(store_index)},
        data=store_data,
        storage_type="memory",
    )

    # Create wrapper with proper sizing
    new_interactive_component = dmc.Stack(
        [card_title_h5, interactive_component, store_component],
        gap=0,
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

    if not build_frame:
        return new_interactive_component
    else:
        interactive_component = build_interactive_frame(
            index=index, children=new_interactive_component
        )

        if not stepper:
            return interactive_component
        else:
            return interactive_component


# List of all the possible aggregation methods for each data type and their corresponding input methods
# TODO: reference in the documentation


agg_functions = {
    "int64": {
        "title": "Integer",
        "input_methods": {
            "Slider": {
                "component": dmc.Slider,
                "description": "Single value slider: will return data equal to the selected value",
            },
            "RangeSlider": {
                "component": dmc.RangeSlider,
                "description": "Two values slider: will return data between the two selected values",
            },
        },
    },
    "float64": {
        "title": "Floating Point",
        "input_methods": {
            "Slider": {
                "component": dmc.Slider,
                "description": "Single value slider: will return data equal to the selected value",
            },
            "RangeSlider": {
                "component": dmc.RangeSlider,
                "description": "Two values slider: will return data between the two selected values",
            },
        },
    },
    "bool": {
        "title": "Boolean",
        "description": "Boolean values",
        "input_methods": {
            "Checkbox": {
                "component": dmc.Checkbox,
                "description": "Checkbox: True or False",
            },
            "Switch": {
                "component": dmc.Switch,
                "description": "Switch",
            },
        },
    },
    "datetime": {
        "title": "Datetime",
        "description": "Date and time values",
        "input_methods": {
            "DateRangePicker": {
                "component": dmc.DatePickerInput,
                "description": "Date range picker: will return data between the two selected dates",
            },
        },
    },
    "timedelta": {
        "title": "Timedelta",
        "description": "Differences between two datetimes",
    },
    "category": {
        "title": "Category",
        "description": "Finite list of text values",
        "input_methods": {
            "Select": {
                "component": dmc.Select,
                "description": "Select: will return corresponding data to the selected value",
            },
            "MultiSelect": {
                "component": dmc.MultiSelect,
                "description": "MultiSelect: will return corresponding data to the selected values",
            },
            "SegmentedControl": {
                "component": dmc.SegmentedControl,
                "description": "SegmentedControl: will return corresponding data to the selected value (best for ≤5 options)",
            },
        },
    },
    "object": {
        "title": "Object",
        "input_methods": {
            # "TextInput": {
            #     "component": dmc.TextInput,
            #     "description": "Text input: will return corresponding data to the exact text or regular expression - DISABLED: causes auto-refresh on every character",
            # },
            "Select": {
                "component": dmc.Select,
                "description": "Select: will return corresponding data to the selected value",
            },
            "MultiSelect": {
                "component": dmc.MultiSelect,
                "description": "MultiSelect: will return corresponding data to the selected values",
            },
            "SegmentedControl": {
                "component": dmc.SegmentedControl,
                "description": "SegmentedControl: will return corresponding data to the selected value",
            },
        },
        "description": "Text or mixed numeric or non-numeric values",
    },
}


# Async wrapper for background callbacks - now calls sync version
async def build_interactive_async(**kwargs):
    """
    Async wrapper for build_interactive function - async functionality disabled, calls sync version.
    """

    # Call the synchronous build_interactive function
    # In the future, this could run in a thread pool if needed for true parallelism
    result = build_interactive(**kwargs)

    return result
