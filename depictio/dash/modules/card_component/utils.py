import dash_mantine_components as dmc
import numpy as np
import pandas as pd
from dash import dcc
from dash_iconify import DashIconify

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
    # DUPLICATION TRACKING: Log card component builds
    logger.info(
        f"🔍 BUILD CARD CALLED - Index: {kwargs.get('index', 'UNKNOWN')}, Stepper: {kwargs.get('stepper', False)}"
    )
    # def build_card(index, title, wf_id, dc_id, dc_config, column_name, column_type, aggregation, v, build_frame=False):

    index = kwargs.get("index")
    title = kwargs.get("title", "Default Title")  # Example of default parameter
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    column_name = kwargs.get("column_name")
    column_type = kwargs.get("column_type")
    aggregation = kwargs.get("aggregation")
    v = kwargs.get("value")
    build_frame = kwargs.get("build_frame", False)
    refresh = kwargs.get("refresh", False)
    stepper = kwargs.get("stepper", False)
    filter_applied = kwargs.get("filter_applied", False)
    color = kwargs.get("color", None)  # Custom color from user
    cols_json = kwargs.get("cols_json", {})  # Column specifications for reference values
    interactive_filters = kwargs.get(
        "interactive_filters", {}
    )  # Interactive filtering data from trigger

    if stepper:
        index = f"{index}-tmp"
    else:
        index = index

    # logger.debug(f"Card kwargs: {kwargs}")

    # Variables to track filtered vs unfiltered values for comparison
    reference_value = None
    is_filtered_data = False

    # CRITICAL FIX: Card components MUST always recalculate values when data is provided
    # even if refresh=False, because they need to compute aggregations on filtered data
    if refresh or not v or kwargs.get("df") is not None:
        import polars as pl

        data = kwargs.get("df", pl.DataFrame())

        # logger.info(f"Existing data: {data}")
        # logger.info(f"Existing data columns: {list(data.to_pandas().columns)}")

        if data.is_empty():
            # Check if we're in a refresh context where we should load new data
            if kwargs.get("refresh", True):
                from bson import ObjectId

                from depictio.api.v1.deltatables_utils import load_deltatable_lite

                logger.info(
                    f"Card component {index}: Loading delta table for {wf_id}:{dc_id} (no pre-loaded df)"
                )

                # Check if we need to apply interactive filtering using iterative_join
                if interactive_filters and wf_id and dc_id:
                    logger.info(
                        f"Card component {index}: Applying interactive filters using iterative_join"
                    )
                    try:
                        from depictio.api.v1.deltatables_utils import (
                            iterative_join,
                            return_joins_dict,
                        )

                        # Get joins dict for the component
                        joins_dict = return_joins_dict(
                            str(ObjectId(wf_id)), {}, kwargs.get("access_token")
                        )

                        # Apply interactive filtering using iterative_join
                        data = iterative_join(
                            ObjectId(wf_id),
                            joins_dict,
                            interactive_filters,
                            kwargs.get("access_token"),
                        )
                        logger.info(
                            f"✅ Card {index}: Applied interactive filters, resulting shape: {data.shape}"
                        )

                    except Exception as e:
                        logger.error(
                            f"❌ Failed to apply interactive filtering for card {index}: {e}"
                        )
                        # Fallback to regular loading without filtering
                        data = pl.DataFrame()

                # Validate that we have valid IDs before calling load_deltatable_lite
                elif not wf_id or not dc_id:
                    logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
                    data = pl.DataFrame()  # Return empty DataFrame if IDs are missing
                else:
                    # Handle joined data collection IDs - don't convert to ObjectId
                    if isinstance(dc_id, str) and "--" in dc_id:
                        # For joined data collections, pass the DC ID as string
                        data = load_deltatable_lite(
                            workflow_id=ObjectId(wf_id),
                            data_collection_id=dc_id,  # Keep as string for joined DCs
                            TOKEN=kwargs.get("access_token"),
                        )
                    else:
                        # Regular data collection - convert to ObjectId
                        data = load_deltatable_lite(
                            workflow_id=ObjectId(wf_id),
                            data_collection_id=ObjectId(dc_id),
                            TOKEN=kwargs.get("access_token"),
                        )
                    # When we load the full data from database (no pre-existing df), this is NOT filtered
                    is_filtered_data = False
                    logger.debug(
                        f"Card component {index}: Loaded full dataset from database (shape: {data.shape})"
                    )
            else:
                # If refresh=False and data is empty, this means filters resulted in no data
                # Keep the empty DataFrame and compute appropriate "no data" value
                is_filtered_data = True  # Empty due to filtering
                logger.info(
                    f"Card component {index}: Using empty DataFrame from filters (shape: {data.shape}) - filters exclude all data"
                )
        else:
            logger.debug(
                f"Card component {index}: Recalculating value with provided DataFrame (shape: {data.shape})"
            )

        # Determine if current data is filtered (only if we have non-empty data and haven't already determined this)
        if (
            not data.is_empty()
            and kwargs.get("df") is not None
            and wf_id
            and dc_id
            and kwargs.get("access_token")
        ):
            # A DataFrame was explicitly provided - need to check if it's different from full dataset
            try:
                from bson import ObjectId

                from depictio.api.v1.deltatables_utils import load_deltatable_lite

                # Handle joined data collection IDs - don't convert to ObjectId
                if isinstance(dc_id, str) and "--" in dc_id:
                    # For joined data collections, pass the DC ID as string
                    full_data = load_deltatable_lite(
                        workflow_id=ObjectId(wf_id),
                        data_collection_id=dc_id,  # Keep as string for joined DCs
                        TOKEN=kwargs.get("access_token"),
                    )
                else:
                    # Regular data collection - convert to ObjectId
                    full_data = load_deltatable_lite(
                        workflow_id=ObjectId(wf_id),
                        data_collection_id=ObjectId(dc_id),
                        TOKEN=kwargs.get("access_token"),
                    )

                # Compare provided data with full dataset
                data_differs = (
                    data.shape[0] != full_data.shape[0]
                    or data.shape[1] != full_data.shape[1]
                    or set(data.columns) != set(full_data.columns)
                )

                is_filtered_data = filter_applied or data_differs

                # Only compute reference value if data is actually filtered
                if is_filtered_data:
                    # Try to get reference value from cols_json first (more efficient)
                    reference_value = get_reference_value_from_cols_json(
                        cols_json, column_name, aggregation
                    )

                    if reference_value is None:
                        # Fallback to computing from full data if not available in cols_json
                        reference_value = compute_value(full_data, column_name, aggregation)
                        logger.debug(
                            f"Card component {index}: Used fallback computation (cols_json unavailable)"
                        )
                    else:
                        logger.debug(
                            f"Card component {index}: Used cols_json reference value: {reference_value}"
                        )

                    logger.debug(
                        f"Card component {index}: Detected filtered data (current: {data.shape}, full: {full_data.shape})"
                    )
                else:
                    logger.debug(
                        f"Card component {index}: Provided data matches full dataset, no filtering detected"
                    )

            except Exception as e:
                logger.warning(f"Failed to load full dataset for comparison: {e}")
                # Fallback: assume filtered if filter flag is set
                is_filtered_data = filter_applied
        elif not data.is_empty() and filter_applied:
            # filter_applied flag is set but no df provided - treat as filtered
            is_filtered_data = True

        # Always recalculate value when we have data (filtered or unfiltered)
        v = compute_value(data, column_name, aggregation)
        logger.debug(f"Card component {index}: Computed new value: {v}")

    try:
        if v is not None:
            v = round(float(v), 4)
        else:
            v = "N/A"  # Default value when None - indicates no data
    except (ValueError, TypeError):
        v = "Error"  # Default value for invalid conversions

    # Format reference value for comparison
    if reference_value is not None:
        try:
            reference_value = round(float(reference_value), 4)
        except (ValueError, TypeError):
            reference_value = None

    # Metadata management - Create a store component to store the metadata of the card
    # For stepper mode, use the temporary index to avoid conflicts with existing components
    # For normal mode, use the original index (remove -tmp suffix if present)
    if stepper:
        store_index = index  # Use the temporary index with -tmp suffix
        data_index = index.replace("-tmp", "") if index else "unknown"  # Clean index for data
    else:
        store_index = index.replace("-tmp", "") if index else "unknown"
        data_index = store_index

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
            "value": v,
            "parent_index": kwargs.get("parent_index", None),
        },
    )

    # Create improved card using DMC 2.0+ components
    # Handle potential None aggregation value
    if aggregation and hasattr(aggregation, "title"):
        agg_display = aggregation.title()
    else:
        agg_display = str(aggregation).title() if aggregation else "Unknown"

    card_title = title if title else f"{agg_display} of {column_name}"

    # Create comparison text if reference value is available
    comparison_text = None
    comparison_icon = None
    comparison_color = "gray"  # Use valid DMC color for secondary text

    if reference_value is not None and is_filtered_data and v != "N/A" and v != "Error":
        try:
            current_val = float(v)
            ref_val = float(reference_value)

            # Calculate percentage change
            if ref_val != 0:
                change_pct = ((current_val - ref_val) / ref_val) * 100
                if change_pct > 0:
                    comparison_text = f"+{change_pct:.1f}% vs unfiltered ({ref_val})"
                    comparison_color = "green"
                    comparison_icon = "mdi:trending-up"
                elif change_pct < 0:
                    comparison_text = f"{change_pct:.1f}% vs unfiltered ({ref_val})"
                    comparison_color = "red"
                    comparison_icon = "mdi:trending-down"
                else:
                    comparison_text = f"Same as unfiltered ({ref_val})"
                    comparison_color = "gray"  # Use valid DMC color for neutral trends
                    comparison_icon = "mdi:trending-neutral"
            else:
                comparison_text = f"Reference: {ref_val}"
                comparison_color = "gray"  # Use valid DMC color for reference text
                comparison_icon = "mdi:information-outline"
        except (ValueError, TypeError):
            comparison_text = f"Reference: {reference_value}"
            comparison_color = "gray"  # Use valid DMC color for error text
            comparison_icon = "mdi:information-outline"

    # Create card content using modern DMC components with theme-aware colors
    # Use theme-aware color system for better dark/light mode compatibility
    # Ensure all color values are strings for DMC compatibility
    def ensure_string_color(color_value, default_color="gray"):
        """Ensure color value is a string that DMC can parse."""
        if color_value is None:
            return default_color  # Use provided default
        elif isinstance(color_value, str):
            return color_value
        else:
            # Convert non-string values to string
            return str(color_value) if color_value else default_color

    title_color = (
        ensure_string_color(color) if color else "gray"
    )  # 'gray' is a valid DMC color for secondary text
    value_color = (
        ensure_string_color(color)
        if color and v not in ["N/A", "Error"]
        else (
            "red" if v in ["N/A", "Error"] else None
        )  # Use None for default theme-aware text color
    )

    # Create value text component with conditional color handling
    value_text_props = {
        "children": str(v),
        "size": "xl",
        "fw": "bold",
        "id": {
            "type": "card-value",
            "index": str(index),
        },
    }
    # Only add color if it's not None (let DMC use default theme-aware color)
    if value_color is not None:
        value_text_props["c"] = value_color

    card_content = [
        dmc.Text(
            card_title,
            size="md",
            c=title_color,
            fw="bold",
            style={"margin": "0", "marginLeft": "-2px"},
        ),
        dmc.Text(**value_text_props, style={"margin": "0", "marginLeft": "-2px"}),
    ]

    # Add comparison text if available
    if comparison_text:
        card_content.append(
            dmc.Group(
                [
                    DashIconify(
                        icon=comparison_icon, width=14, color=ensure_string_color(comparison_color)
                    )
                    if comparison_icon
                    else None,
                    dmc.Text(
                        comparison_text,
                        size="xs",
                        c=ensure_string_color(comparison_color),
                        fw="normal",
                        style={"margin": "0"},
                    ),  # type: ignore
                ],
                gap="xs",
                align="center",
                justify="flex-start",
                style={"margin": "0", "marginLeft": "-2px"},
            )
        )

    # card_content.append(store_component)

    # Create the modern card body using DMC Card component
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
        return new_card_body, store_component
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
