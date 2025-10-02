import dash_mantine_components as dmc
import numpy as np
import pandas as pd
from dash import dcc

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger


def get_reference_value_from_cols_json(cols_json, column_name, aggregation):
    """
    Get reference value from cols_json statistical data instead of recomputing from full dataframe.

    Args:
        cols_json (dict): Column specifications with statistical data
        column_name (str): Name of the column
        aggregation (str): Aggregation type (count, sum, average, etc.)

    Returns:
        float or None: Reference value if available in cols_json, None otherwise
    """
    if not cols_json or column_name not in cols_json:
        logger.debug(f"Column '{column_name}' not found in cols_json")
        return None

    column_specs = cols_json[column_name].get("specs", {})
    if not column_specs:
        logger.debug(f"No specs found for column '{column_name}' in cols_json")
        return None

    # Map aggregation names to cols_json field names
    aggregation_mapping = {
        "count": "count",
        "sum": "sum",
        "average": "average",
        "median": "median",
        "min": "min",
        "max": "max",
        "nunique": "nunique",
        "unique": "unique",
        "variance": "variance",
        "std_dev": "std_dev",
        "range": "range",
        "percentile": "percentile",
    }

    # Get the corresponding field name in cols_json
    cols_json_field = aggregation_mapping.get(aggregation)
    if not cols_json_field:
        logger.debug(f"Aggregation '{aggregation}' not available in cols_json mapping")
        return None

    # Extract the value
    reference_value = column_specs.get(cols_json_field)
    if reference_value is not None:
        logger.debug(f"Found reference value for {column_name}.{aggregation}: {reference_value}")
        return reference_value
    else:
        logger.debug(f"Field '{cols_json_field}' not found in column specs for '{column_name}'")
        return None


# Mapping from custom aggregation names to pandas functions
AGGREGATION_MAPPING = {
    "count": "count",
    "sum": "sum",
    "average": "mean",
    "median": "median",
    "min": "min",
    "max": "max",
    "range": "range",  # Special handling
    "variance": "var",
    "std_dev": "std",
    "skewness": "skew",
    "kurtosis": "kurt",
    "percentile": "quantile",
    "nunique": "nunique",
    # Add more mappings if necessary
}


def compute_value(data, column_name, aggregation):
    logger.debug(f"Computing value for {column_name} with {aggregation}")

    # FIXME: optimization - consider checking if data is already a pandas DataFrame
    data = data.to_pandas()

    if aggregation == "mode":
        mode_series = data[column_name].mode()
        if not mode_series.empty:
            new_value = mode_series.iloc[0]
            logger.debug(f"Computed mode: {new_value}")
            logger.debug(f"Type of mode value: {type(new_value)}")
        else:
            new_value = None
            logger.warning("No mode found; returning None")
    elif aggregation == "range":
        series = data[column_name]
        if pd.api.types.is_numeric_dtype(series):
            new_value = series.max() - series.min()
            logger.debug(f"Computed range: {new_value} (Type: {type(new_value)})")
        else:
            logger.error(
                f"Range aggregation is not supported for non-numeric column '{column_name}'."
            )
            new_value = None

    else:
        pandas_agg = AGGREGATION_MAPPING.get(aggregation)

        if not pandas_agg:
            logger.error(f"Aggregation '{aggregation}' is not supported.")
            return None
        elif pandas_agg == "range":
            # This case is already handled above
            logger.error(
                f"Aggregation '{aggregation}' requires special handling and should not reach here."
            )
            return None
        else:
            try:
                logger.debug(f"Applying aggregation function '{pandas_agg}'")
                # logger.info(f"Column name: {column_name}")
                # logger.info(f"Data: {data}")
                # logger.info(f"Data cols {data.columns}")
                # logger.info(f"Data type: {data[column_name].dtype}")
                # logger.info(f"Data: {data[column_name]}")
                new_value = data[column_name].agg(pandas_agg)
                logger.debug(
                    f"Computed {aggregation} ({pandas_agg}): {new_value} (Type: {type(new_value)})"
                )
            except AttributeError as e:
                logger.error(f"Aggregation function '{pandas_agg}' failed: {e}")
                new_value = None

        if isinstance(new_value, np.float64):
            new_value = round(new_value, 4)
            logger.debug(f"New value rounded: {new_value}")

    return new_value


def build_card_frame(index, children=None, show_border=False):
    if not children:
        return dmc.Paper(
            children=[
                dmc.Center(
                    dmc.Text(
                        "Configure your card using the edit menu",
                        size="sm",
                        c="gray",
                        fs="italic",
                        ta="center",
                    ),
                    id={
                        "type": "card-body",
                        "index": index,
                    },
                    style={
                        "minHeight": "150px",
                        "height": "100%",
                        "minWidth": "150px",
                    },
                )
            ],
            id={
                "type": "card-component",
                "index": index,
            },
            withBorder=show_border,
            radius="sm",
            p="md",
            style={
                "width": "100%",
                "height": "100%",
                "margin": "0",
            },
        )
    else:
        return dmc.Paper(
            children=[
                dmc.Stack(
                    children=children,
                    id={
                        "type": "card-body",
                        "index": index,
                    },
                    gap="xs",
                    style={
                        "height": "100%",
                    },
                )
            ],
            id={
                "type": "card-component",
                "index": index,
            },
            withBorder=show_border,
            radius="sm",
            p="xs",
            style={
                "width": "100%",
                "height": "100%",
                "margin": "0",
            },
        )


def build_card(**kwargs):
    """
    Build card component structure with pattern-matching callback architecture.

    This function creates the card component UI structure but does NOT compute values.
    Value computation happens asynchronously in render_card_value_background callback.

    Pattern-matching IDs enable independent rendering of each card instance:
    - {"type": "card-trigger", "index": component_id} - Initiates rendering
    - {"type": "card-value", "index": component_id} - Updated by callbacks
    - {"type": "card-comparison", "index": component_id} - Shows filter comparison
    - {"type": "card-metadata", "index": component_id} - Stores reference data
    """
    # DUPLICATION TRACKING: Log card component builds
    logger.info(
        f"🔍 BUILD CARD CALLED - Index: {kwargs.get('index', 'UNKNOWN')}, Stepper: {kwargs.get('stepper', False)}"
    )

    index = kwargs.get("index")
    title = kwargs.get("title", "Default Title")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    column_name = kwargs.get("column_name")
    column_type = kwargs.get("column_type")
    aggregation = kwargs.get("aggregation")
    v = kwargs.get("value")  # Legacy support - may still be provided
    build_frame = kwargs.get("build_frame", False)
    stepper = kwargs.get("stepper", False)
    color = kwargs.get("color", None)
    cols_json = kwargs.get("cols_json", {})
    access_token = kwargs.get("access_token")
    parent_index = kwargs.get("parent_index", None)

    if stepper:
        index = f"{index}-tmp"

    # PATTERN-MATCHING ARCHITECTURE: All data loading and value computation moved to callbacks
    # This function only creates the UI structure - values populate asynchronously via:
    # - render_card_value_background() for initial values
    # - patch_card_with_filters() for filter updates
    # - update_card_theme() for theme changes

    logger.debug(f"Creating card structure for index: {index}")

    # Metadata management
    if stepper:
        store_index = index
        data_index = index.replace("-tmp", "") if index else "unknown"
    else:
        store_index = index.replace("-tmp", "") if index else "unknown"
        data_index = store_index

    # Component metadata store (for dashboard save/restore)
    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": str(store_index),
        },
        data={
            "index": str(data_index),
            "component_type": "card",
            "title": title,
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
            "aggregation": aggregation,
            "column_type": column_type,
            "column_name": column_name,
            "value": v,  # Legacy support - may be None for new pattern-matching cards
            "parent_index": parent_index,
        },
    )

    # PATTERN-MATCHING: Trigger store - initiates async rendering
    # This store triggers the render_card_value_background callback
    trigger_store = dcc.Store(
        id={
            "type": "card-trigger",
            "index": str(index),
        },
        data={
            "wf_id": wf_id,
            "dc_id": dc_id,
            "column_name": column_name,
            "column_type": column_type,
            "aggregation": aggregation,
            "title": title,
            "color": color,
            "cols_json": cols_json,
            "access_token": access_token,
            "stepper": stepper,
        },
    )

    # PATTERN-MATCHING: Metadata store - for callbacks (reference values, etc.)
    metadata_store = dcc.Store(
        id={
            "type": "card-metadata",
            "index": str(index),
        },
        data={},  # Populated by render callback with reference_value
    )

    # Create card title
    if aggregation and hasattr(aggregation, "title"):
        agg_display = aggregation.title()
    else:
        agg_display = str(aggregation).title() if aggregation else "Unknown"

    card_title = title if title else f"{agg_display} of {column_name}"

    # PATTERN-MATCHING ARCHITECTURE: Create card with placeholder content
    # Actual values will be populated by render_card_value_background callback
    # Comparison text will be added by patch_card_with_filters callback

    def ensure_string_color(color_value, default_color="gray"):
        """Ensure color value is a string that DMC can parse."""
        if color_value is None:
            return default_color
        elif isinstance(color_value, str):
            return color_value
        else:
            return str(color_value) if color_value else default_color

    title_color = ensure_string_color(color) if color else "gray"

    # Use legacy value if provided (for backward compatibility), otherwise show loading placeholder
    display_value = str(v) if v is not None else "..."

    card_content = [
        dmc.Text(
            card_title,
            size="md",
            c=title_color,
            fw="bold",
            style={"margin": "0", "marginLeft": "-2px"},
        ),
        dmc.Text(
            display_value,
            size="xl",
            fw="bold",
            id={
                "type": "card-value",
                "index": str(index),
            },
            style={"margin": "0", "marginLeft": "-2px"},
        ),
        # PATTERN-MATCHING: Comparison container - populated by patching callback
        dmc.Group(
            [],
            id={
                "type": "card-comparison",
                "index": str(index),
            },
            gap="xs",
            align="center",
            justify="flex-start",
            style={"margin": "0", "marginLeft": "-2px"},
        ),
        # Legacy metadata store (for dashboard save/restore)
        store_component,
        # Pattern-matching stores (for async rendering)
        trigger_store,
        metadata_store,
    ]

    # Create the modern card body using DMC Card component
    # When in stepper mode without frame, use minimal styling to avoid double box
    if stepper and not build_frame:
        # Return card with minimal styling - no extra borders or padding
        new_card_body = dmc.Card(
            children=card_content,
            withBorder=False,
            style={
                "boxSizing": "content-box",
                "height": "100%",
                "minHeight": "120px",
                "padding": "0",
                # Remove any styling that could create visual boundaries
            },
            id={
                "type": "card",
                "index": str(index),
            },
        )
    else:
        # Normal mode with standard card styling
        new_card_body = dmc.Card(
            children=card_content,
            withBorder=False,
            # shadow="sm",
            # radius="md",
            style={
                "boxSizing": "content-box",
                "height": "100%",
                "minHeight": "120px",
                "padding": "0",
            },
            id={
                "type": "card",
                "index": str(index),
            },
        )

    if not build_frame:
        return new_card_body
    else:
        if not stepper:
            # Dashboard mode - return card directly without extra wrapper
            from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
                create_skeleton_component,
            )

            # PERFORMANCE OPTIMIZATION: Conditional loading spinner
            if settings.performance.disable_loading_spinners:
                logger.info("🚀 PERFORMANCE MODE: Card loading spinners disabled")
                return new_card_body  # Return content directly, no loading wrapper
            else:
                # Optimized loading with fast delays
                return dcc.Loading(
                    children=new_card_body,
                    custom_spinner=create_skeleton_component("card"),
                    delay_show=5,  # Fast delay for better UX
                    delay_hide=25,  # Quick hide for performance
                    id={"index": index},
                )
        else:
            # Build the card component for stepper mode
            card_component = build_card_frame(
                index=index, children=new_card_body, show_border=stepper
            )
            return card_component


# List of all the possible aggregation methods for each data type
# TODO: reference in the documentation
agg_functions = {
    "int64": {
        "title": "Integer",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "average": {
                "pandas": "mean",
                "numpy": "mean",
                "description": "Mean of non-NA values",
            },
            "median": {
                "pandas": "median",
                "numpy": "median",
                "description": "Arithmetic median of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
            "range": {
                "pandas": "range",  # Special handling in compute_value
                "numpy": "ptp",
                "description": "Range of non-NA values",
            },
            "variance": {
                "pandas": "var",
                "numpy": "var",
                "description": "Variance of non-NA values",
            },
            "std_dev": {
                "pandas": "std",
                "numpy": "std",
                "description": "Standard Deviation of non-NA values",
            },
            "skewness": {
                "pandas": "skew",
                "numpy": None,
                "description": "Skewness of non-NA values",
            },
            "kurtosis": {
                "pandas": "kurt",
                "numpy": None,
                "description": "Kurtosis of non-NA values",
            },
        },
    },
    "float64": {
        "title": "Floating Point",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "average": {
                "pandas": "mean",
                "numpy": "mean",
                "description": "Mean of non-NA values",
            },
            "median": {
                "pandas": "median",
                "numpy": "median",
                "description": "Arithmetic median of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
            "range": {
                "pandas": lambda x: x.max() - x.min(),
                "numpy": "ptp",
                "description": "Range of non-NA values",
            },
            "variance": {
                "pandas": "var",
                "numpy": "var",
                "description": "Variance of non-NA values",
            },
            "std_dev": {
                "pandas": "std",
                "numpy": "std",
                "description": "Standard Deviation of non-NA values",
            },
            "percentile": {
                "pandas": "quantile",
                "numpy": "percentile",
                "description": "Percentiles of non-NA values",
            },
            "skewness": {
                "pandas": "skew",
                "numpy": None,
                "description": "Skewness of non-NA values",
            },
            "kurtosis": {
                "pandas": "kurt",
                "numpy": None,
                "description": "Kurtosis of non-NA values",
            },
            # "cumulative_sum": {
            #     "pandas": "cumsum",
            #     "numpy": "cumsum",
            #     "description": "Cumulative sum of non-NA values",
            # },
        },
    },
    "bool": {
        "title": "Boolean",
        "description": "Boolean values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "datetime": {
        "title": "Datetime",
        "description": "Date and time values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "timedelta": {
        "title": "Timedelta",
        "description": "Differences between two datetimes",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "category": {
        "title": "Category",
        "description": "Finite list of text values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "mode": {
                "pandas": "mode",
                "numpy": None,
                "description": "Most common value",
            },
        },
    },
    "object": {
        "title": "Object",
        "description": "Text or mixed numeric or non-numeric values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "mode": {
                "pandas": "mode",
                "numpy": None,
                "description": "Most common value",
            },
            "nunique": {
                "pandas": "nunique",
                "numpy": None,
                "description": "Number of distinct elements",
            },
        },
    },
}


# Async wrapper for background callbacks - now calls sync version
async def build_card_async(**kwargs):
    """
    Async wrapper for build_card function - async functionality disabled, calls sync version.
    """
    logger.info(
        f"🔄 ASYNC CARD: Building card component (using sync) - Index: {kwargs.get('index', 'UNKNOWN')}"
    )

    # Call the synchronous build_card function
    result = build_card(**kwargs)

    logger.info(
        f"✅ ASYNC CARD: Card component built successfully - Index: {kwargs.get('index', 'UNKNOWN')}"
    )
    return result
