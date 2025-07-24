import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import numpy as np
import pandas as pd
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger

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
        return dbc.Card(
            dbc.CardBody(
                html.Div(
                    "Configure your card using the edit menu",
                    style={
                        "textAlign": "center",
                        "color": "#999",
                        "fontSize": "14px",
                        "fontStyle": "italic",
                    },
                ),
                id={
                    "type": "card-body",
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
                    "minWidth": "150px",  # Ensure minimum width
                    "flex": "1",  # Allow growth to fill container
                },
            ),
            style={
                "width": "100%",
                "height": "100%",
                "padding": "0",
                "margin": "0",
                "boxShadow": "none",
                "border": "none",  # Remove conflicting border - parent handles styling
                "borderRadius": "4px",
                "backgroundColor": "transparent",  # Let parent handle theme colors
                # Critical flexbox properties for vertical growing
                "display": "flex",
                "flexDirection": "column",
                "flex": "1",
            },
            id={
                "type": "card-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            dbc.CardBody(
                children=children,
                id={
                    "type": "card-body",
                    "index": index,
                },
                style={
                    "padding": "5px",  # Reduce padding inside the card body
                    "display": "flex",
                    "flexDirection": "column",
                    "height": "100%",  # Make sure it fills the parent container
                    "flex": "1",  # Allow growth to fill container
                    "minHeight": "0",  # Critical: Allow shrinking below content size
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Remove shadow for a cleaner look
                "border": "none",  # Remove conflicting border - parent handles styling
                "borderRadius": "4px",
                "backgroundColor": "transparent",  # Let parent handle theme colors
                # Critical flexbox properties for vertical growing
                "display": "flex",
                "flexDirection": "column",
                "flex": "1",
            },
            id={
                "type": "card-component",
                "index": index,
            },
        )


def build_card(**kwargs):
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

                # Validate that we have valid IDs before calling load_deltatable_lite
                if not wf_id or not dc_id:
                    logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
                    data = pl.DataFrame()  # Return empty DataFrame if IDs are missing
                else:
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
                    reference_value = compute_value(full_data, column_name, aggregation)
                    logger.debug(
                        f"Card component {index}: Detected filtered data (current: {data.shape}, full: {full_data.shape})"
                    )
                    logger.debug(
                        f"Card component {index}: Computed reference value: {reference_value}"
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
    comparison_color = "gray"

    if reference_value is not None and is_filtered_data and v != "N/A" and v != "Error":
        try:
            current_val = float(v)
            ref_val = float(reference_value)

            # Calculate percentage change
            if ref_val != 0:
                change_pct = ((current_val - ref_val) / ref_val) * 100
                if change_pct > 0:
                    comparison_text = f"↗️ +{change_pct:.1f}% vs unfiltered ({ref_val})"
                    comparison_color = "green"
                    comparison_icon = "mdi:trending-up"
                elif change_pct < 0:
                    comparison_text = f"↘️ {change_pct:.1f}% vs unfiltered ({ref_val})"
                    comparison_color = "red"
                    comparison_icon = "mdi:trending-down"
                else:
                    comparison_text = f"→ Same as unfiltered ({ref_val})"
                    comparison_color = "gray"
                    comparison_icon = "mdi:trending-neutral"
            else:
                comparison_text = f"Reference: {ref_val}"
                comparison_color = "gray"
                comparison_icon = "mdi:information-outline"
        except (ValueError, TypeError):
            comparison_text = f"Reference: {reference_value}"
            comparison_color = "gray"
            comparison_icon = "mdi:information-outline"

    # Create card content using modern DMC components
    title_color = color if color else "gray"
    value_color = (
        color
        if color and v not in ["N/A", "Error"]
        else ("dark" if v not in ["N/A", "Error"] else "red")
    )

    card_content = [
        dmc.Text(card_title, size="sm", c=title_color, fw="normal"),
        dmc.Text(
            str(v),
            size="xl",
            fw="bold",
            c=value_color,
            id={
                "type": "card-value",
                "index": str(index),
            },
        ),
    ]

    # Add comparison text if available
    if comparison_text:
        card_content.append(
            dmc.Group(
                [
                    DashIconify(icon=comparison_icon, width=14, color=comparison_color)
                    if comparison_icon
                    else None,
                    dmc.Text(comparison_text, size="xs", c=comparison_color, fw="normal"),
                ],
                gap="xs",
                align="center",
            )
        )

    # Add filter badge if data is filtered
    if is_filtered_data:
        card_content.append(
            dmc.Badge(
                "Filtered Data",
                size="xs",
                color="orange",
                variant="light",
                leftSection=DashIconify(icon="mdi:filter", width=12),
                style={"marginTop": "8px"},
            )
        )

    card_content.append(store_component)

    # Create the modern card body using DMC Card component
    new_card_body = dmc.Card(
        children=card_content,
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
        style={
            "height": "100%",
            "minHeight": "120px",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "borderColor": "var(--app-border-color, #ddd)",
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
            # Show border only when in stepper mode (editing)
            from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
                create_skeleton_component,
            )

            # Build the card component
            card_component = build_card_frame(
                index=index, children=new_card_body, show_border=stepper
            )

            # NUCLEAR: Remove intermediate wrapper div that breaks flex chain
            # Return card_component directly with loading wrapper only
            return dcc.Loading(
                children=card_component,
                custom_spinner=create_skeleton_component("card"),
                delay_show=50,  # Minimal delay to prevent flashing
                delay_hide=100,  # Quick dismissal
                id={"index": index},  # Move the id to the loading component
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
