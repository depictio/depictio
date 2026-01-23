"""
Table component frontend module (design and filtering utilities).

This module provides design mode UI functions and AG Grid filtering utilities
for the table component. View mode callbacks have been moved to callbacks/core.py.

For view mode functionality (infinite scroll, filtering, theme switching), use:
    from depictio.dash.modules.table_component.callbacks import (
        register_callbacks_table_component
    )

Functions:
    apply_ag_grid_filter: Apply AG Grid filter to a Polars DataFrame.
    apply_ag_grid_sorting: Apply AG Grid sorting to a Polars DataFrame.
    design_table: Create table design UI for the stepper.
    create_stepper_table_button: Create the button for adding table components.

Constants:
    OPERATORS: Mapping of AG Grid filter operators to Polars operations.
"""

import dash_mantine_components as dmc
import polars as pl
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import (
    get_component_color,
    get_dmc_button_color,
    is_enabled,
)
from depictio.dash.modules.table_component.utils import build_table_frame
from depictio.dash.utils import UNSELECTED_STYLE

# AG Grid filter operators mapping to Polars comparison operations
OPERATORS = {
    "greaterThanOrEqual": "ge",
    "lessThanOrEqual": "le",
    "lessThan": "lt",
    "greaterThan": "gt",
    "notEqual": "ne",
    "equals": "eq",
}


def _apply_string_filter(df: pl.DataFrame, col: str, filter_type: str, value: str) -> pl.DataFrame:
    """Apply string-based filter operations.

    Args:
        df: Input DataFrame.
        col: Column name to filter on.
        filter_type: Type of string filter (contains, startsWith, etc.).
        value: Value to filter by.

    Returns:
        Filtered DataFrame.
    """
    if filter_type == "contains":
        return df.filter(pl.col(col).str.contains(value, literal=False))
    if filter_type == "notContains":
        return df.filter(~pl.col(col).str.contains(value, literal=False))
    if filter_type == "startsWith":
        return df.filter(pl.col(col).str.starts_with(value))
    if filter_type == "notStartsWith":
        return df.filter(~pl.col(col).str.starts_with(value))
    if filter_type == "endsWith":
        return df.filter(pl.col(col).str.ends_with(value))
    if filter_type == "notEndsWith":
        return df.filter(~pl.col(col).str.ends_with(value))
    return df


def _apply_numeric_filter(df: pl.DataFrame, col: str, operator: str, value: float) -> pl.DataFrame:
    """Apply numeric comparison filter operations.

    Args:
        df: Input DataFrame.
        col: Column name to filter on.
        operator: Comparison operator (eq, ne, lt, le, gt, ge).
        value: Value to compare against.

    Returns:
        Filtered DataFrame.
    """
    if operator == "eq":
        return df.filter(pl.col(col) == value)
    if operator == "ne":
        return df.filter(pl.col(col) != value)
    if operator == "lt":
        return df.filter(pl.col(col) < value)
    if operator == "le":
        return df.filter(pl.col(col) <= value)
    if operator == "gt":
        return df.filter(pl.col(col) > value)
    if operator == "ge":
        return df.filter(pl.col(col) >= value)
    return df


def apply_ag_grid_filter(df: pl.DataFrame, filter_model: dict, col: str) -> pl.DataFrame:
    """Apply AG Grid filter to a Polars DataFrame.

    Supports various filter types including text filters (contains, startsWith,
    endsWith), numeric comparisons, date ranges, and set filters.

    Based on dash-ag-grid documentation examples.

    Args:
        df: Input Polars DataFrame.
        filter_model: AG Grid filter model dictionary containing filter type,
            filter values, and filter parameters.
        col: Column name to apply the filter to.

    Returns:
        Filtered DataFrame. Returns original DataFrame if filter fails.
    """
    try:
        # Extract filter criteria
        crit1 = None
        crit2 = None

        if "filter" in filter_model:
            if filter_model["filterType"] == "date":
                crit1 = filter_model["dateFrom"]
                crit2 = filter_model.get("dateTo")
            else:
                crit1 = filter_model["filter"]
                crit2 = filter_model.get("filterTo")

        if "type" in filter_model:
            filter_type = filter_model["type"]

            # Handle string filters
            if filter_type in [
                "contains",
                "notContains",
                "startsWith",
                "notStartsWith",
                "endsWith",
                "notEndsWith",
            ]:
                return _apply_string_filter(df, col, filter_type, crit1)

            # Handle range filter
            if filter_type == "inRange":
                return df.filter(pl.col(col).is_between(crit1, crit2))

            # Handle null checks
            if filter_type == "blank":
                return df.filter(pl.col(col).is_null())
            if filter_type == "notBlank":
                return df.filter(pl.col(col).is_not_null())

            # Handle numeric comparisons
            if filter_type in OPERATORS:
                return _apply_numeric_filter(df, col, OPERATORS[filter_type], crit1)

        elif filter_model.get("filterType") == "set":
            # Handle set filter (multi-select)
            return df.filter(pl.col(col).cast(pl.Utf8).is_in(filter_model["values"]))

    except Exception as e:
        logger.warning(f"Failed to apply filter for column {col}: {e}")

    return df


def apply_ag_grid_sorting(df: pl.DataFrame, sort_model: list) -> pl.DataFrame:
    """Apply AG Grid sorting to a Polars DataFrame.

    Args:
        df: Input Polars DataFrame.
        sort_model: List of sort specifications, each containing 'colId' and 'sort'
            (either 'asc' or 'desc').

    Returns:
        Sorted DataFrame. Returns original DataFrame if sorting fails.
    """
    if not sort_model:
        return df

    try:
        df = df.sort(
            [sort["colId"] for sort in sort_model],
            descending=[sort["sort"] == "desc" for sort in sort_model],
        )
        logger.debug(f"Applied sorting: {[(s['colId'], s['sort']) for s in sort_model]}")
    except Exception as e:
        logger.warning(f"Failed to apply sorting: {e}")

    return df


def design_table(id: dict) -> html.Div:
    """Create table design UI for the stepper interface.

    Tables have minimal design options - they display directly based on the
    workflow/data collection selection from step 2. No additional configuration
    button is needed.

    Args:
        id: Component ID dict containing the 'index' key.

    Returns:
        html.Div containing the table preview area.
    """
    return html.Div(
        html.Div(
            build_table_frame(index=id["index"]),
            id={
                "type": "component-container",
                "index": id["index"],
            },
        ),
    )


def create_stepper_table_button(n: int, disabled: bool | None = None) -> tuple:
    """Create the stepper table button and associated store.

    Creates the button used in the component type selection step of the stepper
    to add a table component to the dashboard.

    Args:
        n: Button index for unique identification.
        disabled: Override enabled state. If None, uses component metadata.

    Returns:
        Tuple containing (button, store) components.
    """
    if disabled is None:
        disabled = not is_enabled("table")

    dmc_color = get_dmc_button_color("table")
    hex_color = get_component_color("table")

    button = dmc.Button(
        "Table",
        id={
            "type": "btn-option",
            "index": n,
            "value": "Table",
        },
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=dmc_color,
        leftSection=DashIconify(icon="octicon:table-24", color=hex_color),
        disabled=disabled,
    )

    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Table",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
