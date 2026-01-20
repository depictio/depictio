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
            p="0",
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
            p="0",
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
    logger.debug(f"Formatting mark label for value '{value}'")
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
        logger.debug(f"Formatted label: {label}")
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

        logger.info(
            f"Generated {len(marks)} equally spaced marks ({'log' if use_log_scale else 'linear'})"
        )
        logger.info(f"Equally spaced marks: {marks}")
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
        logger.debug(f"Generating log marks with min_val={min_val}, max_val={max_val}")
        logger.debug(f"Data min: {data_min}, Data max: {data_max}")

        # Calculate the exponent range with improved logic
        min_exp = math.floor(min_val)
        max_exp = math.ceil(max_val)
        logger.debug(f"Exponent range: {min_exp} to {max_exp}")

        # Check if this is a small range that needs special handling
        range_span = max_exp - min_exp
        is_small_range = range_span <= 1
        logger.debug(f"Range span: {range_span}, is_small_range: {is_small_range}")

        marks = {}

        # Always add the min and max value marks first
        min_log_pos = np.log10(data_min)
        max_log_pos = np.log10(data_max)

        marks[min_log_pos] = format_mark_label(data_min)
        marks[max_log_pos] = format_mark_label(data_max)
        logger.debug(f"Added required min mark: {min_log_pos} -> {data_min}")
        logger.debug(f"Added required max mark: {max_log_pos} -> {data_max}")

        for exp in range(min_exp, max_exp + 1):
            logger.debug(f"Processing exponent: {exp}")

            # Calculate the original value at this exponent
            original_value = 10**exp
            logger.debug(f"Original value at 10^{exp}: {original_value}")

            # Position on the slider (log-transformed space)
            pos = math.log10(original_value)
            logger.debug(f"Position on slider: {pos}")

            # Skip if outside data range
            if original_value < data_min or original_value > data_max:
                logger.debug(f"Skipping {original_value} as it's outside data range")
                continue

            # Check if this mark is too close to boundaries
            too_close_min = abs(original_value - data_min) / data_min < tolerance
            too_close_max = abs(original_value - data_max) / data_max < tolerance

            logger.debug(f"Too close to data_min: {too_close_min}")
            logger.debug(f"Too close to data_max: {too_close_max}")

            # Skip if too close to boundaries (unless it's exactly the boundary or small range)
            if not is_small_range and (
                (too_close_min and original_value != data_min)
                or (too_close_max and original_value != data_max)
            ):
                logger.debug(f"Skipping {original_value} as it's too close to data boundaries")
                continue

            # Ensure that pos is within the slider's range
            if min_val <= pos <= max_val:
                label = format_mark_label(original_value)
                if label:
                    # Use float position instead of int for better precision
                    marks[pos] = label
                    logger.info(f"Added logarithmic mark: pos={pos}, label={label}")
                else:
                    logger.warning(f"Label for value {original_value} is None. Skipping.")

        # Add intermediate marks for better granularity if we have few marks
        if len(marks) < 4:  # Need at least 4 marks for good coverage
            logger.debug("Adding intermediate marks for better granularity")
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
                                logger.info(
                                    f"Added intermediate logarithmic mark: pos={pos}, label={label}"
                                )

        # If still too few marks for small ranges, add more intermediate points
        if len(marks) < 3 and is_small_range:
            logger.debug("Adding extra marks for very small log range")
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
                                logger.info(
                                    f"Added extra logarithmic mark for small range: pos={pos}, label={label}"
                                )

        logger.info(f"Final generated log marks: {marks}")
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
    logger.debug(
        f"Generating default state for {interactive_component_type} on column {column_name}"
    )

    if interactive_component_type == "RangeSlider":
        # For range sliders, default state is [min_value, max_value]
        if cols_json and column_name in cols_json:
            column_specs = cols_json[column_name].get("specs", {})
            min_val = column_specs.get("min")
            max_val = column_specs.get("max")

            if min_val is not None and max_val is not None:
                default_range = [min_val, max_val]
                logger.debug(f"Range slider default state: {default_range}")
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

        logger.debug(
            f"Select component default state: {default_value} (options: {len(default_options)})"
        )
        return {
            "type": "select",
            "options": default_options,
            "default_value": default_value,
        }

    elif interactive_component_type == "Switch":
        # For switches, default is typically False
        logger.debug("Switch default state: False")
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
                logger.debug(f"Date range picker default state: {default_range}")
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

    logger.info(f"Initial Min value: {min_value} (Type: {type(min_value)})")
    logger.info(f"Initial Max value: {max_value} (Type: {type(max_value)})")

    # If min_value is invalid, compute it from the DataFrame
    if min_value is None:
        computed_min = df[column_name].replace([np.inf, -np.inf], np.nan).dropna().min()
        if pd.notnull(computed_min):
            min_value = round(float(computed_min), 2)
            logger.info(f"Min value set from DataFrame: {min_value}")
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
            logger.info(f"Max value set from DataFrame: {max_value}")
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

    logger.info(f"Final Min value: {min_value} (Type: {type(min_value)})")
    logger.info(f"Final Max value: {max_value} (Type: {type(max_value)})")

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
    logger.info(f"Skewness of '{series.name}': {skewness}")
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
    logger.info(f"Minimum value of '{series.name}': {min_val}")
    if min_val < 0:
        shift_amount = abs(min_val) + shift
        logger.info(f"Shifting data by {shift_amount} to handle non-positive values.")
        transformed_series = np.log10(series + shift_amount)
        return transformed_series, shift_amount
    else:
        transformed_series = np.log10(series)
        return transformed_series, 0.0


def build_interactive(**kwargs):
    # DUPLICATION TRACKING: Log interactive component builds
    logger.info(
        f"🔍 BUILD INTERACTIVE CALLED - Index: {kwargs.get('index', 'UNKNOWN')}, Stepper: {kwargs.get('stepper', False)}"
    )
    logger.info(
        f"🔍 BUILD INTERACTIVE KWARGS: wf_id={kwargs.get('wf_id')}, dc_id={kwargs.get('dc_id')}, column={kwargs.get('column_name')}, type={kwargs.get('interactive_component_type')}"
    )

    index = kwargs.get("index")
    title = kwargs.get("title")  # Example of default parameter
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
    scale = kwargs.get("scale", "linear")  # Default to linear scale
    # Check both "color" (from frontend) and "custom_color" (from saved metadata) for DMC compliance
    color = kwargs.get("color") or kwargs.get("custom_color") or None

    # DASHBOARD OPTIMIZATION: Extract init_data for API call elimination
    init_data = kwargs.get("init_data", None)

    # REFACTORING: cols_json no longer stored in component metadata
    # Callbacks access it directly from dashboard-init-data store via State input
    # For build-time usage (like getting min/max for sliders), extract from init_data
    cols_json = None
    if init_data and "column_specs" in init_data and str(dc_id) in init_data["column_specs"]:
        cols_json = init_data["column_specs"][str(dc_id)]
        logger.info(
            f"📡 INTERACTIVE OPTIMIZATION: init_data available with {len(init_data.get('column_specs', {}))} column_specs"
        )
    else:
        logger.debug("⚠️  init_data not available (edit mode or stepper mode)")

    # Default icon mapping by component type for better UX
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

    # Get default icon based on component type, fallback to slider icon
    default_icon = DEFAULT_ICONS.get(interactive_component_type, "bx:slider-alt")
    icon_name = kwargs.get("icon_name") or default_icon

    marks_number = kwargs.get("marks_number", 2)  # Default to 2 marks (min/max only)
    title_size = kwargs.get("title_size", "md")  # Default title size
    cols_json = kwargs.get("cols_json")

    # Determine value div type based on stepper mode
    if stepper:
        value_div_type = "interactive-component-value-tmp"
    else:
        value_div_type = "interactive-component-value"

    # COMPONENT-AT-BUILD-TIME APPROACH: Create actual component immediately (like cards)
    # Component exists in DOM with disabled state, callback enables and populates it
    # This eliminates race conditions with dash.ALL callbacks
    if build_frame:
        logger.info(f"📦 BUILD_FRAME MODE: Creating disabled component for interactive {index}")

        # Show only a loader until callback renders final component
        # This avoids the "Loading..." -> component transition (eliminates visual flicker)
        # The callback will replace this entire container with the final component
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

        # Create trigger store with ALL metadata needed for callback
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
                # SECURITY: access_token removed - accessed from local-store in callbacks
                "title": title,
                "icon_name": icon_name,
                "marks_number": marks_number,
                "title_size": title_size,
                "color": color,
                "value": value,
                "parent_index": parent_index,
                "stepper": stepper,
                # REFACTORING: cols_json removed from component stores
                # Callbacks access dashboard-init-data store directly via State input
            },
        )

        # Create metadata store for reference values (like cards)
        metadata_store = dcc.Store(
            id={"type": "interactive-metadata", "index": str(index)}, data={}
        )

        # Create options data store for background callback (JSON-serializable data)
        options_data_store = dcc.Store(
            id={"type": "interactive-options-data", "index": str(index)},
            data={},
            storage_type="memory",
        )

        # Create interactive-stored-metadata Store (separate from stored-metadata-component to avoid conflicts)
        # This Store is used by the card filtering system and filter reset callback
        interactive_stored_metadata = dcc.Store(
            id={"type": "interactive-stored-metadata", "index": str(index)},
            data={
                "index": str(index),
                "interactive_component_type": interactive_component_type,
                "column_name": column_name,
                "default_state": {},  # Will be populated by async callback
            },
            storage_type="memory",
        )

        # Build frame with component and stores
        frame_with_component = build_interactive_frame(
            index=index,
            children=[
                component_with_loader,
                trigger_store,
                metadata_store,
                options_data_store,
                interactive_stored_metadata,
            ],
        )

        return frame_with_component

    # Log optimization info
    if init_data:
        logger.info(
            f"📡 INTERACTIVE OPTIMIZATION: Using init_data with {len(init_data)} DC entries"
        )

    # logger.info(f"Interactive - kwargs: {kwargs}")
    logger.info(
        f"BUILD_INTERACTIVE: column_type={column_type}, interactive_component_type={interactive_component_type}"
    )
    logger.info(
        f"BUILD_INTERACTIVE: Available input_methods for {column_type}: {list(agg_functions[column_type].get('input_methods', {}).keys())}"
    )

    if stepper:
        value_div_type = "interactive-component-value-tmp"
    else:
        value_div_type = "interactive-component-value"

    # Check if the interactive_component_type is valid for this column_type
    if interactive_component_type not in agg_functions[column_type]["input_methods"]:
        logger.error(
            f"INVALID COMBINATION: {interactive_component_type} not available for {column_type} columns"
        )
        logger.error(
            f"Available options: {list(agg_functions[column_type]['input_methods'].keys())}"
        )
        raise ValueError(
            f"Interactive component type '{interactive_component_type}' is not available for column type '{column_type}'. Available options: {list(agg_functions[column_type]['input_methods'].keys())}"
        )

    func_name = agg_functions[column_type]["input_methods"][interactive_component_type]["component"]

    # Common Store Component
    # For stepper mode, use the temporary index to avoid conflicts with existing components
    # For normal mode, use the original index (remove -tmp suffix if present)
    if stepper:
        store_index = index  # Use the temporary index with -tmp suffix
        data_index = index.replace("-tmp", "") if index else "unknown"  # Clean index for data
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
        # REFACTORING: dc_config and cols_json removed - available via init_data centrally
        # Access via: init_data["dc_configs"][dc_id] and init_data["column_specs"][dc_id]
        "column_name": column_name,
        "column_type": column_type,
        "value": value,
        "corrected_value": value,
        "parent_index": parent_index,
        "scale": scale,  # Save scale configuration for sliders
        "marks_number": marks_number,  # Save marks number configuration for sliders
        "title_size": title_size,  # Save title size configuration
        "custom_color": color,  # Save custom color configuration for DMC theme compliance
        "icon_name": icon_name,  # Save icon configuration
    }

    logger.debug(f"Interactive component {index}: store_data: {store_data}")
    logger.info(
        f"Interactive component {index}: column_type={column_type}, interactive_component_type={interactive_component_type}"
    )
    logger.info(
        f"Interactive component {index}: available agg_functions keys: {list(agg_functions.keys())}"
    )

    # Load the delta table & get the specs
    # CRITICAL: Always load unfiltered data for interactive component options
    # Even if we have a pre-loaded filtered df, we need unfiltered data for options
    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        logger.info(
            f"Interactive component {index}: Loading unfiltered data for options (type: {interactive_component_type})"
        )
        if not wf_id or not dc_id:
            logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
            df_for_options = pl.DataFrame({})  # Empty DataFrame with no columns
        else:
            # Always load unfiltered data for categorical component options
            # Handle joined data collection IDs - don't convert to ObjectId
            if isinstance(dc_id, str) and "--" in dc_id:
                # For joined data collections, pass the DC ID as string
                df_for_options = load_deltatable_lite(
                    ObjectId(wf_id),
                    dc_id,
                    TOKEN=TOKEN,
                    load_for_options=True,
                    init_data=init_data,  # OPTIMIZATION: Use init_data from dashboard
                )
            else:
                # Regular data collection - convert to ObjectId
                df_for_options = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id),
                    TOKEN=TOKEN,
                    load_for_options=True,
                    init_data=init_data,  # OPTIMIZATION: Use init_data from dashboard
                )

        # Use the unfiltered data for generating options
        df = df_for_options
    elif df is None:
        logger.info(
            f"Interactive component {index}: Loading delta table for {wf_id}:{dc_id} (no pre-loaded df)"
        )
        # Validate that we have valid IDs before calling load_deltatable_lite
        if not wf_id or not dc_id:
            logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
            df = pl.DataFrame({})  # Return empty DataFrame if IDs are missing
        else:
            # Handle joined data collection IDs - don't convert to ObjectId
            if isinstance(dc_id, str) and "--" in dc_id:
                # For joined data collections, pass the DC ID as string
                df = load_deltatable_lite(
                    ObjectId(wf_id),
                    dc_id,
                    TOKEN=TOKEN,
                    init_data=init_data,  # OPTIMIZATION: Use init_data from dashboard
                )
            else:
                # Regular data collection - convert to ObjectId
                df = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id),
                    TOKEN=TOKEN,
                    init_data=init_data,  # OPTIMIZATION: Use init_data from dashboard
                )
    else:
        logger.debug(
            f"Interactive component {index}: Using pre-loaded DataFrame (shape: {df.shape})"
        )

    # Handling different aggregation values

    ## Categorical data

    # If the aggregation value is Select, MultiSelect or SegmentedControl
    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        # LOG SCHEMA DEBUG INFO FOR SELECT COMPONENTS
        logger.info("🔍 SELECT COMPONENT SCHEMA DEBUG:")
        logger.info(f"  - Component type: {interactive_component_type}")
        logger.info(f"  - Component expects column: '{column_name}'")
        logger.info(f"  - DataFrame shape: {df.shape}")
        logger.info(f"  - Available columns: {df.columns}")
        logger.info(f"  - Column '{column_name}' present: {column_name in df.columns}")

        # Check if column exists before processing
        if column_name not in df.columns:
            logger.error(f"❌ SCHEMA MISMATCH: Column '{column_name}' not found in DataFrame")
            logger.error(f"Available columns: {df.columns}")
            # Return empty component to prevent crash
            return dmc.Text(f"Error: Column '{column_name}' not found", c="red")

        data = sorted(df[column_name].drop_nulls().unique())

        # CRITICAL: If DataFrame is empty but we have a preserved value, include those values in options
        # This ensures the component can display the preserved selection even when filtered data is empty
        if df.height == 0 and value:
            if interactive_component_type == "MultiSelect" and isinstance(value, list):
                # For MultiSelect, extend data with all preserved values
                for val in value:
                    if val not in data:
                        data.append(val)
                data = sorted(data)
                logger.debug(
                    f"MultiSelect {index}: Added preserved values {value} to empty options, final data: {data}"
                )
            elif interactive_component_type in ["Select", "SegmentedControl"] and value not in data:
                # For Select/SegmentedControl, add the single preserved value
                data.append(value)
                data = sorted(data)
                logger.debug(
                    f"{interactive_component_type} {index}: Added preserved value '{value}' to empty options, final data: {data}"
                )

        # Prepare kwargs for all component types to preserve value
        component_kwargs = {
            "data": data,
            "id": {"type": value_div_type, "index": str(index)},
            # UI/UX improvements for better space utilization
            "w": "100%",  # Fill container width
            "size": "md",  # Medium size for better readability
            "styles": {
                "root": {
                    "width": "100%",
                    "minWidth": "50px",
                },  # Ultra-compact minimum width for tight layouts
            },
        }

        # CRITICAL: Preserve value for ALL interactive component types, but handle SegmentedControl specially
        if value is not None:
            # For Select: only set value if it's still valid (in data options)
            if interactive_component_type == "Select":
                # Convert value to string if it's not already (handles numeric values from sliders)
                if not isinstance(value, str):
                    if isinstance(value, (list, tuple)):
                        # If value is from a RangeSlider, don't set any value
                        logger.warning(
                            f"Select component {index}: Ignoring array value {value} from slider"
                        )
                        value = None
                    else:
                        # Convert numeric value to string
                        value = str(value) if value is not None else None
                        logger.debug(
                            f"Select component {index}: Converted value to string: '{value}'"
                        )

                if value and value in data:
                    component_kwargs["value"] = value
                    logger.debug(
                        f"Select component {index}: Preserved value '{value}' (available in options)"
                    )
                elif value:
                    logger.warning(
                        f"Select component {index}: Value '{value}' no longer available in options {data}"
                    )
            # For SegmentedControl: only set value if it's valid and not empty
            elif interactive_component_type == "SegmentedControl":
                # Convert value to string if it's not already (handles numeric values from sliders)
                if not isinstance(value, str):
                    if isinstance(value, (list, tuple)):
                        # If value is from a RangeSlider, don't set any value
                        logger.warning(
                            f"SegmentedControl component {index}: Ignoring array value {value} from slider"
                        )
                        value = None
                    else:
                        # Convert numeric value to string
                        value = str(value) if value is not None else None
                        logger.debug(
                            f"SegmentedControl component {index}: Converted value to string: '{value}'"
                        )

                if value and value in data:
                    component_kwargs["value"] = value
                    logger.debug(
                        f"SegmentedControl component {index}: Preserved value '{value}' (available in options)"
                    )
                elif value:
                    logger.warning(
                        f"SegmentedControl component {index}: Value '{value}' no longer available in options {data}, defaulting to no selection"
                    )
                    # Don't set value - let it default to None (no selection)
            # For MultiSelect: preserve value even if partially invalid
            elif interactive_component_type == "MultiSelect":
                # Ensure value is a list for MultiSelect
                if value is not None and not isinstance(value, list):
                    if isinstance(value, (tuple, set)):
                        value = list(value)
                        logger.debug(
                            f"MultiSelect component {index}: Converted {type(value).__name__} to list"
                        )
                    else:
                        # Single value - wrap in list
                        value = [str(value)]
                        logger.debug(
                            f"MultiSelect component {index}: Wrapped single value in list: {value}"
                        )

                # Convert all values in list to strings
                if isinstance(value, list):
                    value = [str(v) for v in value if v is not None]
                    logger.debug(
                        f"MultiSelect component {index}: Converted values to strings: {value}"
                    )

                component_kwargs["value"] = value
                logger.debug(f"MultiSelect component {index}: Preserved value '{value}'")
        else:
            # Explicit handling for no initial value
            if interactive_component_type == "SegmentedControl":
                # For SegmentedControl, explicitly set value to None for no selection
                component_kwargs["value"] = None
                logger.debug(
                    f"SegmentedControl component {index}: No initial selection (value=None)"
                )

        # Apply custom color to DMC components if specified
        if color and interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
            # Merge color styles with existing base styles
            existing_styles = component_kwargs.get("styles", {})
            color_styles = {
                "input": {"borderColor": color},
                "dropdown": {"borderColor": color},
                "label": {"color": color},
            }
            # Merge dictionaries - color_styles will override existing_styles for conflicting keys
            component_kwargs["styles"] = {**existing_styles, **color_styles}

        # WARNING: This is a temporary solution to avoid modifying dashboard data - the -tmp suffix is added to the id and removed once clicked on the btn-done D
        interactive_component = func_name(**component_kwargs)

        # If the aggregation value is MultiSelect, make the component searchable and clearable
        if interactive_component_type == "MultiSelect":
            # Add MultiSelect-specific styling properties
            multiselect_kwargs = {
                "searchable": True,
                "clearable": True,
                "limit": 100,  # Limit to 100 options displayed at once for performance
                # "clearSearchOnChange": False,
                "persistence_type": "local",
                # "dropdownPosition": "bottom",
                # "zIndex": 1000,
                # "position": "relative",
            }
            # Merge with existing component_kwargs that already includes the preserved value
            component_kwargs.update(multiselect_kwargs)
            # Recreate the component with additional MultiSelect properties
            interactive_component = func_name(**component_kwargs)

    # # If the aggregation value is TextInput - DISABLED: causes auto-refresh on every character
    # elif interactive_component_type == "TextInput":
    #     logger.debug("TextInput")
    #     logger.debug(f"Value: {value}")
    #     logger.debug(f"Value type: {type(value)}")
    #     kwargs = {"persistence_type": "local"}
    #     if not value:
    #         value = ""
    #     logger.debug(f"Value: {value}")
    #     logger.debug(f"Value type: {type(value)}")
    #     kwargs.update({"value": value})

    #     # Apply custom color to TextInput if specified
    #     if color:
    #         kwargs["styles"] = {"input": {"borderColor": color}, "label": {"color": color}}

    #     interactive_component = func_name(
    #         placeholder="Your selected value",
    #         id={"type": value_div_type, "index": str(index)},
    #         **kwargs,
    #     )

    ## Numerical data

    # # If the aggregation value is Slider or RangeSlider
    # elif interactive_component_type in ["Slider", "RangeSlider"]:
    #     logger.info(f"Column name: {column_name}")

    #     df = df.to_pandas()
    #     logger.info(f"df['{column_name}']: {df[column_name]}")
    #     # Drop NaN, None
    #     df = df[~df[column_name].isin([None, "None", "nan", "NaN"])]

    #     df[column_name] = df[column_name].replace([np.inf, -np.inf], np.nan)

    #     df[column_name] = df[column_name].astype(float)

    #     # Round the values to 2 decimal places when possible (not for inf, -inf)
    #     df[column_name] = df[column_name].apply(lambda x: round(x, 2) if x not in [float("inf"), float("-inf")] else x)

    #     df = df.dropna(subset=[column_name])
    #     logger.info(f"df['{column_name}']: {df[column_name]}")

    #     # Detect skewness
    #     skewed = is_highly_skewed(df[column_name])

    #     slider_series = df[column_name]

    #     # Apply log transformation if skewed
    #     if skewed:
    #         logger.info(f"Data is highly skewed. Applying log transformation.")
    #         transformed_series, shift = apply_log_transformation(df[column_name])
    #         # Replace the original column with transformed data
    #         df[f"{column_name}_log10"] = transformed_series
    #         slider_series = df[f"{column_name}_log10"]
    #         original_scale = True
    #     else:
    #         logger.info(f"Data is not highly skewed. Using linear scale.")
    #     #     shift = 0.0
    #     # slider_series = df[column_name]
    #     #     original_scale = False

    #     # Get valid min and max
    #     min_value, max_value = get_valid_min_max(df, f"{column_name}_log10" if skewed else column_name, cols_json)
    #     logger.info(f"Min value: {min_value}")
    #     logger.info(f"Max value: {max_value}")

    #     # Prepare kwargs for the slider
    #     kwargs_component = {
    #         "min": min_value,
    #         "max": max_value,
    #         "id": {"type": value_div_type, "index": str(index)},
    #         "persistence_type": "local",
    #     }
    #     logger.info(f"kwargs: {kwargs_component}")

    #     # # Set the value prop appropriately

    #     # Construct marks
    #     if skewed:
    #         # Use fixed logarithmic intervals
    #         marks = generate_log_marks(min_value, max_value, df[column_name].min(), df[column_name].max())

    #     else:
    #         # log_marks = generate_log_marks(min_value, max_value)

    #         if slider_series.nunique() < 30:
    #             logger.info(f"Case where nunique < 30")
    #             unique_values = slider_series.unique()
    #             # Filter out None and non-numeric values
    #             unique_values = [elem for elem in unique_values if isinstance(elem, (int, float)) and not math.isinf(elem)]
    #             # Construct marks with formatted labels, filtering out None labels
    #             marks = {
    #                 int(elem) if math.isclose(elem, int(elem), abs_tol=1e-9) else elem: format_mark_label(elem) for elem in unique_values if format_mark_label(elem) is not None
    #             }
    #         else:
    #             logger.info(f"Case where nunique >= 30")

    #             quantiles_nb = 6  # Adjust the number of quantiles as needed
    #             quantiles_values = [i / quantiles_nb for i in range(1, quantiles_nb)]
    #             logger.info(f"Quantiles values: {quantiles_values}")

    #             # Compute quantiles in the slider_series
    #             quantiles = slider_series.quantile(quantiles_values)
    #             logger.info(f"Quantiles: {quantiles}")
    #             logger.info(f"Min value: {min_value}")
    #             logger.info(f"Max value: {max_value}")

    #             # Combine min, quantiles, and max
    #             mark_elements = [min_value] + list(quantiles) + [max_value]
    #             # Filter out None and non-numeric values
    #             mark_elements = [elem for elem in mark_elements if isinstance(elem, (int, float)) and not math.isinf(elem)]
    #             # Construct marks with formatted labels
    #             marks = {
    #                 int(elem) if math.isclose(elem, int(elem), abs_tol=1e-9) else elem: format_mark_label(elem) for elem in mark_elements if format_mark_label(elem) is not None
    #             }
    #         logger.info(f"Marks: {marks}")

    #         # Optionally enforce inclusion of min and max marks with default labels
    #         if min_value not in marks:
    #             marks[min_value] = "Min" if not original_scale else format_mark_label(min_value)
    #             logger.warning(f"Min value {min_value} was not in marks. Assigned default label.")

    #         if max_value not in marks:
    #             marks[max_value] = "Max" if not original_scale else format_mark_label(max_value)
    #             logger.warning(f"Max value {max_value} was not in marks. Assigned default label.")

    #     if interactive_component_type == "RangeSlider":
    #         if not value:
    #             value = [min_value, max_value]
    #         # else:
    #         #     if skewed:
    #         #         value = [math.log10(val) for val in value]
    #         #     else:
    #         #         value = [val for val in value]
    #         # logger.info(f"VALUE - value: {value}")
    #         kwargs_component.update({"value": value})
    #     elif interactive_component_type == "Slider":
    #         if not value:
    #             value = min_value
    #         # else:
    #         #     if skewed:
    #         #         value = math.log10(value)
    #         #     else:
    #         #         value = value
    #         kwargs_component.update({"value": value})

    #     # if skewed:
    #     #     # card_title += " (Log10 Scale)"
    #     #     store_data["scale"] = "log10"
    #     #     real_value = [10**val for val in value] if interactive_component_type == "RangeSlider" else 10**value
    #     #     store_data["value"] = real_value
    #     #     logger.info(f"Interactive - real_value: {real_value}")

    #     # else:
    #     #     store_data["scale"] = "linear"

    #     kwargs_component.update({"marks": marks})
    #     interactive_component = func_name(**kwargs_component)

    ## Numerical data

    # If the aggregation value is Slider or RangeSlider
    elif interactive_component_type in ["Slider", "RangeSlider"]:
        logger.info(f"Column name: {column_name}")
        logger.info(f"Scale type: {scale}")

        # Convert Polars DataFrame to Pandas for processing
        df_pandas = df.to_pandas()
        # logger.info(f"df['{column_name}']: {df_pandas[column_name]}")

        # LOG SCHEMA DEBUG INFO
        logger.info("🔍 INTERACTIVE COMPONENT SCHEMA DEBUG:")
        logger.info(f"  - Component expects column: '{column_name}'")
        logger.info(f"  - DataFrame shape: {df_pandas.shape}")
        logger.info(f"  - Available columns: {list(df_pandas.columns)}")
        logger.info(f"  - Column '{column_name}' present: {column_name in df_pandas.columns}")

        # Check if column exists before processing
        if column_name not in df_pandas.columns:
            logger.error(f"❌ SCHEMA MISMATCH: Column '{column_name}' not found in DataFrame")
            logger.error(f"Available columns: {list(df_pandas.columns)}")
            # Return empty options to prevent crash
            return []

        # Drop NaN, None, and invalid values
        df_pandas = df_pandas[~df_pandas[column_name].isin([None, "None", "nan", "NaN"])]
        df_pandas[column_name] = df_pandas[column_name].replace([np.inf, -np.inf], np.nan)
        df_pandas[column_name] = df_pandas[column_name].astype(float)

        # Round the values to 2 decimal places when possible (not for inf, -inf)
        df_pandas[column_name] = df_pandas[column_name].apply(
            lambda x: round(x, 2) if x not in [float("inf"), float("-inf")] else x
        )
        df_pandas = df_pandas.dropna(subset=[column_name])
        # logger.info(f"Cleaned df['{column_name}']: {df_pandas[column_name]}")

        # Always default to linear scale, only use log10 if explicitly selected
        use_log_scale = False
        if scale is not None and scale == "log10":
            use_log_scale = True
            logger.info("User explicitly selected log10 scale")
        else:
            # Always default to linear scale (including when scale is None, "linear", or any other value)
            logger.info(f"Using linear scale (scale parameter: {scale})")

        # Apply log transformation if using log scale
        if use_log_scale:
            logger.info("Applying log transformation")
            transformed_series, _ = apply_log_transformation(df_pandas[column_name])
            # Replace the original column with transformed data
            df_pandas[f"{column_name}_log10"] = transformed_series
        else:
            logger.info("Using linear scale")

        # Get valid min and max
        series_name = f"{column_name}_log10" if use_log_scale else column_name
        min_value, max_value = get_valid_min_max(df_pandas, series_name, cols_json)
        logger.info(f"Min value: {min_value}, Max value: {max_value}")

        # Ensure min_value and max_value are valid numbers (DMC sliders can't handle null)
        if min_value is None or math.isnan(min_value) or math.isinf(min_value):
            min_value = 0.0
            logger.warning("Invalid min_value detected, setting to 0.0")

        if max_value is None or math.isnan(max_value) or math.isinf(max_value):
            max_value = 100.0
            logger.warning("Invalid max_value detected, setting to 100.0")

        # Ensure min < max
        if min_value >= max_value:
            max_value = min_value + 1.0
            logger.warning(f"min_value >= max_value, adjusted max_value to {max_value}")

        # Prepare kwargs for DMC slider components - simplified like working prototype
        kwargs_component = {
            "min": float(min_value),
            "max": float(max_value),
            "id": {"type": value_div_type, "index": str(index)},
            # Keep it simple - no step, precision, or label parameters initially
            "step": 0.01,  # Default step for DMC sliders
            "persistence_type": "local",
            # UI/UX improvements for better space utilization
            "w": "100%",  # Fill container width
            "size": title_size,  # Use title_size for slider component size
            "styles": {
                "root": {
                    "width": "100%",
                    "paddingLeft": "12px",  # Increased padding to prevent thumb overflow on left
                    "paddingRight": "12px",  # Increased padding to prevent thumb overflow on right
                },
                "track": {
                    "minWidth": "50px",  # Ultra-compact minimum width for tight layouts
                },
            },
        }

        # Add minRange only for RangeSlider (not supported by regular Slider)
        if interactive_component_type == "RangeSlider":
            kwargs_component["minRange"] = 0.01  # Default min range for DMC RangeSlider

        logger.info(f"DMC Slider: Using range {min_value}-{max_value}")

        # Set component values for DMC sliders
        if interactive_component_type == "RangeSlider":
            # For DMC RangeSlider, use simple value handling
            try:
                # Check if we have a valid value first
                if (
                    value is None
                    or value == "null"
                    or value == "None"
                    or not isinstance(value, list)
                    or len(value) != 2
                    or any(v is None or v == "null" or v == "None" for v in value)
                ):
                    # Use range defaults
                    cleaned_value = [min_value, max_value]
                    logger.info(
                        f"DMC RangeSlider: Using default value [{min_value}, {max_value}] (original: {value})"
                    )
                else:
                    # Clean and validate values
                    cleaned_value = []
                    for i, v in enumerate(value):
                        try:
                            if v is None or v == "None":
                                clean_val = min_value if i == 0 else max_value
                            else:
                                # Convert to float and clamp to valid range
                                decimal_val = float(v)
                                if not (math.isnan(decimal_val) or math.isinf(decimal_val)):
                                    clean_val = max(min_value, min(max_value, decimal_val))
                                else:
                                    clean_val = min_value if i == 0 else max_value
                            cleaned_value.append(clean_val)
                        except (ValueError, TypeError):
                            fallback_val = min_value if i == 0 else max_value
                            cleaned_value.append(fallback_val)

                    # Ensure order
                    if cleaned_value[0] > cleaned_value[1]:
                        cleaned_value = [cleaned_value[1], cleaned_value[0]]

                # For DMC RangeSlider, use value property
                kwargs_component["value"] = cleaned_value
                logger.info(f"DMC RangeSlider: Set value: {cleaned_value}")

            except Exception as e:
                logger.error(f"DMC RangeSlider: Exception: {e}")
        elif interactive_component_type == "Slider":
            # For DMC Slider, ensure value is a single valid number
            try:
                if (
                    value is None
                    or value == "null"
                    or value == "None"
                    or (isinstance(value, float) and math.isnan(value))
                ):
                    # For null values, use middle of range as default
                    cleaned_value = (min_value + max_value) / 2
                    logger.info(
                        f"DMC Slider: Using middle of range as default: {cleaned_value} (original: {value})"
                    )
                else:
                    cleaned_value = float(value)
                    # Ensure value is in range
                    cleaned_value = max(min_value, min(max_value, cleaned_value))
                    logger.info(f"DMC Slider: Cleaned value from {value} to {cleaned_value}")

                # For DMC Slider, use value property
                kwargs_component["value"] = cleaned_value
            except (ValueError, TypeError) as e:
                logger.info(f"DMC Slider: Conversion failed ({e})")

        # Apply custom color styling for DMC sliders
        if color:
            kwargs_component["color"] = color
            logger.info(f"DMC Slider: Applied custom color: {color}")

        # Generate marks based on scale type and marks_number parameter
        # For DMC sliders, always generate default marks if none specified
        effective_marks_number = marks_number if marks_number and marks_number > 0 else 2

        logger.info(
            f"Generating {effective_marks_number} marks for DMC slider (requested: {marks_number})"
        )
        # Generate marks based on scale type
        if use_log_scale:
            # For log scale, use the specialized log marks function for better power-of-10 marks
            marks_dict = generate_log_marks(
                min_value, max_value, df_pandas[column_name].min(), df_pandas[column_name].max()
            )
            logger.info("Using specialized log marks function for better power-of-10 display")
        else:
            # Use equally spaced function for linear scale
            marks_dict = generate_equally_spaced_marks(
                min_value, max_value, marks_count=effective_marks_number, use_log_scale=False
            )

        # Convert DCC-style dict to DMC-style list of dicts
        if marks_dict:
            dmc_marks = []
            for value, label in marks_dict.items():
                try:
                    mark_value = float(value)
                    # Ensure mark value is within range with small tolerance for floating point precision
                    tolerance = 1e-9
                    if (min_value - tolerance) <= mark_value <= (max_value + tolerance):
                        dmc_marks.append({"value": mark_value, "label": str(label)})
                        logger.debug(f"Added DMC mark: {mark_value} -> {label}")
                    else:
                        logger.debug(f"Mark {mark_value} outside range [{min_value}, {max_value}]")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Skipping invalid mark: {value} -> {label}, error: {e}")

            if dmc_marks:
                kwargs_component["marks"] = dmc_marks
                logger.info(f"DMC marks created: {len(dmc_marks)} marks")
            else:
                logger.warning("No valid DMC marks created")
        else:
            logger.warning("No marks generated from mark generation function")

        logger.info("DMC Slider: Final kwargs before component creation:")
        logger.info(
            f"  min: {kwargs_component.get('min')} (type: {type(kwargs_component.get('min'))})"
        )
        logger.info(
            f"  max: {kwargs_component.get('max')} (type: {type(kwargs_component.get('max'))})"
        )
        logger.info(
            f"  value: {kwargs_component.get('value')} (type: {type(kwargs_component.get('value'))})"
        )
        logger.info(f"  marks: {len(kwargs_component.get('marks', []))} marks")
        if kwargs_component.get("marks"):
            logger.info(f"  marks detail: {kwargs_component.get('marks')}")

        interactive_component = func_name(**kwargs_component)

        # Store scale information for later use
        store_data["scale"] = "log10" if use_log_scale else "linear"
        if use_log_scale:
            # Convert displayed values back to original scale for storage
            if interactive_component_type == "RangeSlider":
                real_value = [10**val for val in value] if isinstance(value, list) else value
            else:
                real_value = 10**value if value is not None else value
            store_data["original_value"] = real_value
            logger.info(f"Log scale - stored original value: {real_value}")
        else:
            store_data["original_value"] = value

    # If the aggregation value is DateRangePicker (datetime data types)
    elif interactive_component_type == "DateRangePicker":
        logger.info(f"Column name: {column_name}")
        logger.info("Building DateRangePicker component")

        # Convert Polars DataFrame to Pandas for processing
        df_pandas = df.to_pandas()

        # LOG SCHEMA DEBUG INFO
        logger.info("🔍 DATE RANGE PICKER SCHEMA DEBUG:")
        logger.info(f"  - Component expects column: '{column_name}'")
        logger.info(f"  - DataFrame shape: {df_pandas.shape}")
        logger.info(f"  - Available columns: {list(df_pandas.columns)}")
        logger.info(f"  - Column '{column_name}' present: {column_name in df_pandas.columns}")

        # Check if column exists before processing
        if column_name not in df_pandas.columns:
            logger.error(f"❌ SCHEMA MISMATCH: Column '{column_name}' not found in DataFrame")
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

        logger.info(f"Date range: {min_date_py} to {max_date_py}")

        # Prepare kwargs for DMC DatePickerInput
        kwargs_component = {
            "type": "range",
            "id": {"type": value_div_type, "index": str(index)},
            "minDate": min_date_py,
            "maxDate": max_date_py,
            "persistence_type": "local",
            # UI/UX improvements
            "w": "100%",
            "size": title_size,
            "clearable": False,  # Don't allow clearing the date range
            "styles": {
                "root": {
                    "width": "100%",
                },
            },
        }

        # Handle value persistence
        if value is not None and isinstance(value, list) and len(value) == 2:
            try:
                # Convert string dates to date objects if needed
                if isinstance(value[0], str):
                    value[0] = datetime.strptime(value[0], "%Y-%m-%d").date()
                if isinstance(value[1], str):
                    value[1] = datetime.strptime(value[1], "%Y-%m-%d").date()

                # Ensure dates are within bounds
                value[0] = max(min_date_py, min(max_date_py, value[0]))
                value[1] = max(min_date_py, min(max_date_py, value[1]))

                kwargs_component["value"] = value
                logger.info(f"Preserved date range value: {value}")
            except Exception as e:
                logger.warning(f"Failed to parse date range value {value}: {e}")
                kwargs_component["value"] = [min_date_py, max_date_py]
        else:
            # Default to full range
            kwargs_component["value"] = [min_date_py, max_date_py]
            logger.info(f"Using default date range: [{min_date_py}, {max_date_py}]")

        # Apply custom color if specified
        if color:
            # Merge color styles with existing styles
            existing_styles = kwargs_component.get("styles", {})
            color_styles = {
                "input": {"borderColor": color},
                "label": {"color": color},
            }
            kwargs_component["styles"] = {**existing_styles, **color_styles}
            logger.info(f"Applied custom color: {color}")

        interactive_component = func_name(**kwargs_component)

        # Store date range information for later use
        store_data["min_date"] = str(min_date_py)
        store_data["max_date"] = str(max_date_py)

        # Update default_state with actual min/max dates for proper reset functionality
        store_data["default_state"] = {
            "type": "date_range",
            "min_date": str(min_date_py),
            "max_date": str(max_date_py),
            "default_range": [str(min_date_py), str(max_date_py)],
        }
        logger.info(f"Updated default_state for DateRangePicker: {store_data['default_state']}")

    # If the aggregation value is Checkbox or Switch (boolean data types)
    elif interactive_component_type in ["Checkbox", "Switch"]:
        logger.debug(f"Boolean component: {interactive_component_type}")
        logger.debug(f"Value: {value}")
        logger.debug(f"Value type: {type(value)}")
        kwargs = {"persistence_type": "local"}
        if value is None:
            value = False
        # Convert value to boolean if it's not already
        if isinstance(value, str):
            value = value.lower() in ["true", "1", "yes", "on"]
        elif not isinstance(value, bool):
            value = bool(value)
        kwargs.update({"checked": value})

        # Apply custom color to boolean components if specified
        if color:
            kwargs["color"] = color

        interactive_component = func_name(
            id={"type": value_div_type, "index": str(index)},
            **kwargs,
        )

    # Fallback for any other component types
    else:
        logger.warning(f"Unsupported interactive component type: {interactive_component_type}")
        logger.warning(f"Column type: {column_type}")
        logger.warning(f"Column name: {column_name}")
        logger.warning(
            f"Available component types: {list(agg_functions.get(column_type, {}).get('input_methods', {}).keys())}"
        )
        # Create a fallback text component
        interactive_component = dmc.Text(
            f"Unsupported component type: {interactive_component_type} for {column_type} data",
            id={"type": value_div_type, "index": str(index)},
            c="red",
        )

    # If no title is provided, use the aggregation value on the selected column
    if not title:
        card_title = f"{interactive_component_type} on {column_name}"
    else:
        card_title = f"{title}"

    # Add scale information to title for sliders
    if (
        interactive_component_type in ["Slider", "RangeSlider"]
        and store_data.get("scale") == "log10"
    ):
        card_title += " (Log10 Scale)"

    logger.info(f"Interactive - original value: {value}")
    # Log the actual value used in the component
    if interactive_component_type in ["Slider", "RangeSlider"]:
        # The component value was already logged in the slider section
        logger.info(
            f"Interactive - component type: {interactive_component_type} (component value logged above)"
        )
    else:
        logger.info(f"Interactive - component value: {value}")

    # Apply custom color if specified, otherwise let Mantine handle theming
    title_style = {
        "marginBottom": "0.25rem",  # Reduced from 0.5rem for tighter spacing
    }
    icon_color = color if color else None  # Use custom color for icon if specified

    if color:
        title_style["color"] = color
        logger.info(f"Applied custom color: {color}")
    else:
        logger.debug("Using Mantine's native theming for title")

    # Create title with icon - apply color via CSS style to prevent browser freeze
    icon_props = {
        "icon": icon_name,
        "width": int(title_size) if title_size.isdigit() else 20,  # Default to 20 for named sizes
    }
    if icon_color:
        icon_props["style"] = {"color": icon_color}
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

    # Generate default state information for the component
    # For select-type components, pass unique values if available
    unique_values = None
    if (
        interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]
        and df is not None
    ):
        try:
            # Get unique values from the dataframe
            unique_vals = df[column_name].unique()
            # Handle both pandas and polars dataframes
            if hasattr(unique_vals, "to_list") and callable(getattr(unique_vals, "to_list", None)):
                # Polars DataFrame
                unique_vals_list = unique_vals.to_list()  # type: ignore
            elif hasattr(unique_vals, "tolist") and callable(getattr(unique_vals, "tolist", None)):
                # Pandas DataFrame
                unique_vals_list = unique_vals.tolist()  # type: ignore
            else:
                # Fallback to list conversion
                unique_vals_list = list(unique_vals)
            # Clean and limit the unique values
            unique_values = [str(val) for val in unique_vals_list if val is not None][
                :100
            ]  # Limit to 100 options
            logger.debug(
                f"Generated {len(unique_values)} unique values for {interactive_component_type}"
            )
        except Exception as e:
            logger.warning(f"Failed to extract unique values for {column_name}: {e}")
            unique_values = []

    # Generate and add default state to store_data
    # Only set if not already set (e.g., by DateRangePicker which computes actual values)
    if "default_state" not in store_data:
        default_state = get_default_state(
            interactive_component_type, column_name, cols_json, unique_values
        )
        store_data["default_state"] = default_state
        logger.debug(f"Added default_state to {interactive_component_type}: {default_state}")
    else:
        logger.debug(
            f"default_state already set, preserving existing: {store_data['default_state']}"
        )

    store_component = dcc.Store(
        id={"type": "interactive-stored-metadata", "index": str(store_index)},
        data=store_data,
        storage_type="memory",
    )

    # Create wrapper with proper sizing for interactive components
    new_interactive_component = dmc.Stack(
        [card_title_h5, interactive_component, store_component],
        gap="0",  # No gap - use title marginBottom instead for tighter control
        style={
            "width": "100%",  # Fill container width
            "minHeight": "120px",  # Ensure minimum height for better usability
            "padding": "0.5rem 1rem 0.5rem 0.5rem",  # top right bottom left - reduced padding for compact layout
            "boxSizing": "border-box",
            "display": "flex",
            "flexDirection": "column",
            "justifyContent": "flex-start",  # Align content to top instead of center
            "alignItems": "stretch",  # Stretch children to fill width
        },
    )

    if not build_frame:
        return new_interactive_component
    else:
        # Build the interactive component with frame
        interactive_component = build_interactive_frame(
            index=index, children=new_interactive_component
        )

        # For stepper mode with loading
        if not stepper:
            # Interactive components load data synchronously, no loading wrapper needed
            # Component is built with all data and options ready
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
    logger.info(
        f"🔄 ASYNC INTERACTIVE: Building interactive component (using sync) - Index: {kwargs.get('index', 'UNKNOWN')}"
    )

    # Call the synchronous build_interactive function
    # In the future, this could run in a thread pool if needed for true parallelism
    result = build_interactive(**kwargs)

    logger.info(
        f"✅ ASYNC INTERACTIVE: Interactive component built successfully - Index: {kwargs.get('index', 'UNKNOWN')}"
    )
    return result
