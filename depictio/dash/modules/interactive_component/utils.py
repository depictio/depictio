import math

import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import polars as pl
from bson import ObjectId
from dash import dcc, html

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite


def build_interactive_frame(index, children=None, show_border=False):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                html.Div(
                    "Configure your interactive component using the edit menu",
                    style={
                        "textAlign": "center",
                        "color": "#999",
                        "fontSize": "14px",
                        "fontStyle": "italic",
                    },
                ),
                id={
                    "type": "input-body",
                    "index": index,
                },
                style={
                    "padding": "20px",
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                    "alignItems": "center",
                    "minHeight": "150px",  # Ensure minimum height
                    "height": "100%",
                },
            ),
            style={
                "width": "100%",
                "height": "100%",
                "padding": "0",
                "margin": "0",
                "boxShadow": "none",
                "border": "1px solid #ddd" if show_border else "0px solid #ddd",
                "borderRadius": "4px",
            },
            id={
                "type": "interactive-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            dbc.CardBody(
                children=children,
                id={
                    "type": "input-body",
                    "index": index,
                },
                style={
                    "display": "flex",
                    "flexDirection": "column",
                    "overflow": "visible",  # Allow dropdown to overflow
                    "height": "100%",
                    "position": "relative",  # Ensure positioning context
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",
                "overflow": "visible",  # Allow dropdown to overflow
                "position": "relative",  # Ensure positioning context
                "border": "1px solid #ddd" if show_border else "0px solid #ddd",
                "borderRadius": "4px",
            },
            id={
                "type": "interactive-component",
                "index": index,
            },
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

        # Check if the value is effectively an integer
        if math.isclose(value, int(value), abs_tol=1e-9):
            label = f"{int(value)}"
        # handle scientific notation if the value is too large
        elif value > 1e5:
            label = f"{value:.2e}"
        else:
            label = f"{value:.2f}"
        logger.debug(f"Formatted label: {label}")
        return label
    except Exception as e:
        logger.error(f"Error formatting mark label for value '{value}': {e}")
        return None


def generate_log_marks(min_val, max_val, data_min, data_max, tolerance=0.5):
    """
    Generates a dictionary of marks for a log-scaled slider at each order of magnitude.

    Args:
        min_val (float): The minimum value of the slider in log-transformed space.
        max_val (float): The maximum value of the slider in log-transformed space.

    Returns:
        dict: A dictionary where keys are positions on the slider and values are formatted labels.
    """
    try:
        logger.debug(f"Generating log marks with min_val={min_val}, max_val={max_val}")
        logger.debug(f"Data min: {data_min}, Data max: {data_max}")

        # Calculate the exponent range
        min_exp = math.floor(min_val)
        max_exp = math.ceil(max_val)
        logger.debug(f"Exponent range: {min_exp} to {max_exp}")

        marks = {}

        # Add the min value mark
        marks[np.log10(data_min)] = format_mark_label(data_min)

        for exp in range(min_exp, max_exp + 1):
            logger.debug(f"Processing exponent: {exp}")

            # Calculate the original value at this exponent
            original_value = 10**exp
            logger.debug(f"Original value at 10^{exp}: {original_value}")

            # Position on the slider (log-transformed space)
            pos = math.log10(original_value)
            logger.debug(f"Position on slider: {pos}")

            # Check if this mark is too close to data_min or data_max
            too_close_min = data_min >= original_value * (1 - tolerance)
            logger.debug(f"Too close to data_min: {too_close_min}")
            logger.debug(f"Data min: {data_min}")
            logger.debug(f"Original value * (1 - tolerance): {original_value * (1 - tolerance)}")
            too_close_max = data_max <= original_value * (1 + tolerance)
            logger.debug(f"Too close to data_max: {too_close_max}")
            logger.debug(f"Data max: {data_max}")
            logger.debug(f"Original value * (1 + tolerance): {original_value * (1 + tolerance)}")

            if too_close_min or too_close_max:
                if too_close_max:
                    logger.info(
                        f"Mark at {original_value} is too close to data_max ({data_max}). Skipping."
                    )
                if too_close_min:
                    logger.info(
                        f"Mark at {original_value} is too close to data_min ({data_min}). Skipping."
                    )
                continue  # Skip the first mark if too close to data_min

            # Ensure that pos is within the slider's range
            if min_val <= pos <= max_val:
                label = format_mark_label(original_value)
                if label:
                    marks[int(pos)] = label
                    logger.info(f"Added mark: pos={pos}, label={label}")
                else:
                    logger.warning(f"Label for value {original_value} is None. Skipping.")

        # Add the max value mark
        marks[np.log10(data_max)] = format_mark_label(data_max)

        logger.info(f"Final generated log marks: {marks}")
        return marks

    except Exception as e:
        logger.error(f"Error generating log marks: {e}")
        return {}


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
    index = kwargs.get("index")
    title = kwargs.get("title")  # Example of default parameter
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    column_name = kwargs.get("column_name")
    column_type = kwargs.get("column_type")
    interactive_component_type = kwargs.get("interactive_component_type")
    # cols_json = {}
    cols_json = kwargs.get("cols_json")
    value = kwargs.get("value", None)
    df = kwargs.get("df", None)
    build_frame = kwargs.get("build_frame", False)
    TOKEN = kwargs.get("access_token")
    stepper = kwargs.get("stepper", False)
    parent_index = kwargs.get("parent_index", None)
    scale = kwargs.get("scale", "linear")  # Default to linear scale
    color = kwargs.get("color", "#000000")  # Default to black color
    marks_number = kwargs.get("marks_number", 5)  # Default to 5 marks

    logger.info(f"Interactive - kwargs: {kwargs}")
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
        "dc_config": dc_config,
        "column_name": column_name,
        "column_type": column_type,
        "cols_json": cols_json,
        "value": value,
        "corrected_value": value,
        "parent_index": parent_index,
    }

    logger.debug(f"Interactive component {index}: store_data: {store_data}")
    logger.info(
        f"Interactive component {index}: column_type={column_type}, interactive_component_type={interactive_component_type}"
    )
    logger.info(
        f"Interactive component {index}: available agg_functions keys: {list(agg_functions.keys())}"
    )

    # Load the delta table & get the specs
    if df is None:
        logger.info(
            f"Interactive component {index}: Loading delta table for {wf_id}:{dc_id} (no pre-loaded df)"
        )
        # Validate that we have valid IDs before calling load_deltatable_lite
        if not wf_id or not dc_id:
            logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
            df = pl.DataFrame()  # Return empty DataFrame if IDs are missing
        else:
            df = load_deltatable_lite(ObjectId(wf_id), ObjectId(dc_id), TOKEN=TOKEN)
    else:
        logger.debug(
            f"Interactive component {index}: Using pre-loaded DataFrame (shape: {df.shape})"
        )

    # Handling different aggregation values

    ## Categorical data

    # If the aggregation value is Select, MultiSelect or SegmentedControl
    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
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
        component_kwargs = {"data": data, "id": {"type": value_div_type, "index": str(index)}}

        # CRITICAL: Preserve value for ALL interactive component types, not just MultiSelect
        if value is not None:
            # For Select: only set value if it's still valid (in data options)
            if interactive_component_type == "Select":
                if value in data:
                    component_kwargs["value"] = value
                    logger.debug(
                        f"Select component {index}: Preserved value '{value}' (available in options)"
                    )
                else:
                    logger.warning(
                        f"Select component {index}: Value '{value}' no longer available in options {data}"
                    )
            # For MultiSelect and SegmentedControl: preserve value even if partially invalid
            else:
                component_kwargs["value"] = value
                logger.debug(
                    f"{interactive_component_type} component {index}: Preserved value '{value}'"
                )

        # Apply custom color to DMC components if specified
        if color and interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
            component_kwargs["styles"] = {
                "input": {"borderColor": color},
                "dropdown": {"borderColor": color},
                "label": {"color": color},
            }

        # WARNING: This is a temporary solution to avoid modifying dashboard data - the -tmp suffix is added to the id and removed once clicked on the btn-done D
        interactive_component = func_name(**component_kwargs)

        # If the aggregation value is MultiSelect, make the component searchable and clearable
        if interactive_component_type == "MultiSelect":
            # Add MultiSelect-specific styling properties
            multiselect_kwargs = {
                "searchable": True,
                "clearable": True,
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

    # If the aggregation value is TextInput
    elif interactive_component_type == "TextInput":
        logger.debug("TextInput")
        logger.debug(f"Value: {value}")
        logger.debug(f"Value type: {type(value)}")
        kwargs = {"persistence_type": "local"}
        if not value:
            value = ""
        logger.debug(f"Value: {value}")
        logger.debug(f"Value type: {type(value)}")
        kwargs.update({"value": value})

        # Apply custom color to TextInput if specified
        if color:
            kwargs["styles"] = {"input": {"borderColor": color}, "label": {"color": color}}

        interactive_component = func_name(
            placeholder="Your selected value",
            id={"type": value_div_type, "index": str(index)},
            **kwargs,
        )

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
        logger.info(f"df['{column_name}']: {df_pandas[column_name]}")

        # Drop NaN, None, and invalid values
        df_pandas = df_pandas[~df_pandas[column_name].isin([None, "None", "nan", "NaN"])]
        df_pandas[column_name] = df_pandas[column_name].replace([np.inf, -np.inf], np.nan)
        df_pandas[column_name] = df_pandas[column_name].astype(float)

        # Round the values to 2 decimal places when possible (not for inf, -inf)
        df_pandas[column_name] = df_pandas[column_name].apply(
            lambda x: round(x, 2) if x not in [float("inf"), float("-inf")] else x
        )
        df_pandas = df_pandas.dropna(subset=[column_name])
        logger.info(f"Cleaned df['{column_name}']: {df_pandas[column_name]}")

        # Always default to linear scale, only use log10 if explicitly selected
        use_log_scale = False
        if scale is not None and scale == "log10":
            use_log_scale = True
            logger.info("User explicitly selected log10 scale")
        else:
            # Always default to linear scale (including when scale is None, "linear", or any other value)
            logger.info(f"Using linear scale (scale parameter: {scale})")

        slider_series = df_pandas[column_name]

        # Apply log transformation if using log scale
        if use_log_scale:
            logger.info("Applying log transformation")
            transformed_series, shift = apply_log_transformation(df_pandas[column_name])
            # Replace the original column with transformed data
            df_pandas[f"{column_name}_log10"] = transformed_series
            slider_series = df_pandas[f"{column_name}_log10"]
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

        # Prepare kwargs for DCC slider
        kwargs_component = {
            "min": float(min_value),
            "max": float(max_value),
            "id": {"type": value_div_type, "index": str(index)},
            "persistence_type": "local",
        }

        logger.info(f"DCC Slider: Using range {min_value}-{max_value}")

        # Generate marks based on scale type
        if use_log_scale:
            # Use logarithmic marks
            marks = generate_log_marks(
                min_value, max_value, df_pandas[column_name].min(), df_pandas[column_name].max()
            )
        else:
            # Use linear marks with controlled number of marks
            logger.info(f"Generating linear marks with {marks_number} marks")

            # Ensure marks_number is at least 3 (min, max, and at least one in between)
            marks_number = max(3, min(marks_number or 5, 10))

            if slider_series.nunique() <= marks_number and slider_series.nunique() > 0:
                # If we have few unique values, use them all
                logger.info(f"Using all unique values ({slider_series.nunique()} values)")
                unique_values = slider_series.unique()
                # Filter out None and non-numeric values
                unique_values = [
                    elem
                    for elem in unique_values
                    if isinstance(elem, (int, float)) and not math.isinf(elem)
                ]
                # Sort values
                unique_values = sorted(unique_values)
                marks = {
                    int(elem)
                    if math.isclose(elem, int(elem), abs_tol=1e-9)
                    else elem: format_mark_label(elem)
                    for elem in unique_values
                    if format_mark_label(elem) is not None
                }
            else:
                # Generate evenly spaced marks using quantiles or linear interpolation
                logger.info(f"Generating {marks_number} evenly spaced marks")

                if slider_series.nunique() == 0 or len(slider_series) == 0:
                    # If DataFrame is empty, create evenly spaced marks between min and max
                    logger.warning(
                        "DataFrame is empty, creating evenly spaced marks between min/max"
                    )
                    mark_values = []
                    for i in range(marks_number):
                        if marks_number == 1:
                            mark_val = (min_value + max_value) / 2
                        else:
                            mark_val = min_value + (max_value - min_value) * i / (marks_number - 1)
                        mark_values.append(mark_val)

                    marks = {
                        int(elem)
                        if math.isclose(elem, int(elem), abs_tol=1e-9)
                        else elem: format_mark_label(elem)
                        for elem in mark_values
                        if format_mark_label(elem) is not None
                    }
                else:
                    # Create quantile positions (excluding 0 and 1 which are min/max)
                    if marks_number <= 2:
                        quantile_positions = []
                    else:
                        quantile_positions = [
                            i / (marks_number - 1) for i in range(1, marks_number - 1)
                        ]

                    logger.info(f"Quantile positions: {quantile_positions}")

                    # Compute quantiles
                    quantiles = (
                        slider_series.quantile(quantile_positions) if quantile_positions else []
                    )
                    logger.info(
                        f"Quantiles: {list(quantiles) if hasattr(quantiles, '__iter__') else quantiles}"
                    )

                    # Combine min, quantiles, and max
                    mark_elements = [min_value] + list(quantiles) + [max_value]
                    # Remove duplicates and sort
                    mark_elements = sorted(
                        list(
                            set(
                                [
                                    elem
                                    for elem in mark_elements
                                    if isinstance(elem, (int, float)) and not math.isinf(elem)
                                ]
                            )
                        )
                    )

                    marks = {
                        int(elem)
                        if math.isclose(elem, int(elem), abs_tol=1e-9)
                        else elem: format_mark_label(elem)
                        for elem in mark_elements
                        if format_mark_label(elem) is not None
                    }

            logger.info(f"Final marks: {marks}")

        # Set component values for DCC sliders
        if interactive_component_type == "RangeSlider":
            # For DCC RangeSlider, use simple value handling
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
                        f"DCC RangeSlider: Using default value [{min_value}, {max_value}] (original: {value})"
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

                # For DCC RangeSlider, use value property
                kwargs_component["value"] = cleaned_value
                logger.info(f"DCC RangeSlider: Set value: {cleaned_value}")

            except Exception as e:
                logger.error(f"DCC RangeSlider: Exception: {e}")
        elif interactive_component_type == "Slider":
            # For DCC Slider, ensure value is a single valid number
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
                        f"DCC Slider: Using middle of range as default: {cleaned_value} (original: {value})"
                    )
                else:
                    cleaned_value = float(value)
                    # Ensure value is in range
                    cleaned_value = max(min_value, min(max_value, cleaned_value))
                    logger.info(f"DCC Slider: Cleaned value from {value} to {cleaned_value}")

                # For DCC Slider, use value property
                kwargs_component["value"] = cleaned_value
            except (ValueError, TypeError) as e:
                logger.info(f"DCC Slider: Conversion failed ({e})")

        # DCC sliders don't support direct color styling like DMC
        # Color customization would need to be handled via CSS

        # For DCC sliders, marks use dict format (not list of dicts like DMC)
        if marks:
            # DCC sliders use dict format for marks: {value: label}
            dcc_marks = {}
            for k, v in marks.items():
                try:
                    # Use decimal mark value directly
                    decimal_mark = float(k)
                    if not (math.isnan(decimal_mark) or math.isinf(decimal_mark)):
                        # Ensure mark value is within decimal range
                        if min_value <= decimal_mark <= max_value:
                            dcc_marks[decimal_mark] = str(v)
                except (ValueError, TypeError):
                    logger.warning(f"Skipping invalid mark: {k} -> {v}")

            # If no valid marks were created, add min and max marks as fallback
            if not dcc_marks:
                dcc_marks = {
                    min_value: format_mark_label(min_value),
                    max_value: format_mark_label(max_value),
                }
                logger.warning("No valid marks found, using decimal min/max as fallback")

            kwargs_component["marks"] = dcc_marks
            logger.info(f"DCC marks created: {len(dcc_marks)} marks (decimal values)")

        logger.info("DCC Slider: Final kwargs before component creation:")
        logger.info(
            f"  min: {kwargs_component.get('min')} (type: {type(kwargs_component.get('min'))})"
        )
        logger.info(
            f"  max: {kwargs_component.get('max')} (type: {type(kwargs_component.get('max'))})"
        )
        logger.info(
            f"  value: {kwargs_component.get('value')} (type: {type(kwargs_component.get('value'))})"
        )
        logger.info(f"  marks: {len(kwargs_component.get('marks', {}))} marks")

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
            color="red",
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

    # Apply custom color if specified
    title_style = {"marginBottom": "0.5rem"}
    if color:
        title_style["color"] = color
        # Store color for component styling
        store_data["custom_color"] = color
        logger.info(f"Applied custom color: {color}")

    card_title_h5 = html.H5(card_title, style=title_style)

    store_component = dcc.Store(
        id={"type": "stored-metadata-component", "index": str(store_index)},
        data=store_data,
        storage_type="memory",
    )

    new_interactive_component = html.Div([card_title_h5, interactive_component, store_component])

    if not build_frame:
        return new_interactive_component
    else:
        return build_interactive_frame(index=index, children=new_interactive_component)


# List of all the possible aggregation methods for each data type and their corresponding input methods
# TODO: reference in the documentation


agg_functions = {
    "int64": {
        "title": "Integer",
        "input_methods": {
            "Slider": {
                "component": dcc.Slider,
                "description": "Single value slider: will return data equal to the selected value",
            },
            "RangeSlider": {
                "component": dcc.RangeSlider,
                "description": "Two values slider: will return data between the two selected values",
            },
        },
    },
    "float64": {
        "title": "Floating Point",
        "input_methods": {
            "Slider": {
                "component": dcc.Slider,
                "description": "Single value slider: will return data equal to the selected value",
            },
            "RangeSlider": {
                "component": dcc.RangeSlider,
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
    },
    "timedelta": {
        "title": "Timedelta",
        "description": "Differences between two datetimes",
    },
    "category": {
        "title": "Category",
        "description": "Finite list of text values",
    },
    "object": {
        "title": "Object",
        "input_methods": {
            "TextInput": {
                "component": dmc.TextInput,
                "description": "Text input: will return corresponding data to the exact text or regular expression",
            },
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
