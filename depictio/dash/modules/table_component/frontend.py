"""
DEPRECATED: View mode callbacks have been moved to callbacks/core.py

This file now maintains only design/edit callbacks temporarily for backward compatibility.
These will be migrated to callbacks/design.py and callbacks/edit.py in a future PR.

For view mode functionality (infinite scroll, filtering, theme switching), use:
    from depictio.dash.modules.table_component.callbacks import register_callbacks_table_component
"""

# Import necessary libraries
import dash_mantine_components as dmc
import polars as pl
from dash import dcc, html
from dash_iconify import DashIconify

# Depictio imports
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import (
    get_dmc_button_color,
    is_enabled,
)
from depictio.dash.modules.table_component.utils import build_table_frame
from depictio.dash.utils import UNSELECTED_STYLE

# TODO: interactivity when selecting table rows

# AG Grid filter operators mapping to Polars operations
OPERATORS = {
    "greaterThanOrEqual": "ge",
    "lessThanOrEqual": "le",
    "lessThan": "lt",
    "greaterThan": "gt",
    "notEqual": "ne",
    "equals": "eq",
}


def apply_ag_grid_filter(df: pl.DataFrame, filter_model: dict, col: str) -> pl.DataFrame:
    """
    Apply AG Grid filter to a Polars DataFrame.
    Based on dash-ag-grid documentation examples.
    """
    try:
        if "filter" in filter_model:
            if filter_model["filterType"] == "date":
                crit1 = filter_model["dateFrom"]
                if "dateTo" in filter_model:
                    crit2 = filter_model["dateTo"]
            else:
                crit1 = filter_model["filter"]
                if "filterTo" in filter_model:
                    crit2 = filter_model["filterTo"]

        if "type" in filter_model:
            filter_type = filter_model["type"]

            if filter_type == "contains":
                df = df.filter(pl.col(col).str.contains(crit1, literal=False))
            elif filter_type == "notContains":
                df = df.filter(~pl.col(col).str.contains(crit1, literal=False))
            elif filter_type == "startsWith":
                df = df.filter(pl.col(col).str.starts_with(crit1))
            elif filter_type == "notStartsWith":
                df = df.filter(~pl.col(col).str.starts_with(crit1))
            elif filter_type == "endsWith":
                df = df.filter(pl.col(col).str.ends_with(crit1))
            elif filter_type == "notEndsWith":
                df = df.filter(~pl.col(col).str.ends_with(crit1))
            elif filter_type == "inRange":
                if filter_model["filterType"] == "date":
                    # Handle date range filtering
                    df = df.filter(pl.col(col).is_between(crit1, crit2))
                else:
                    df = df.filter(pl.col(col).is_between(crit1, crit2))
            elif filter_type == "blank":
                df = df.filter(pl.col(col).is_null())
            elif filter_type == "notBlank":
                df = df.filter(pl.col(col).is_not_null())
            else:
                # Handle numeric comparisons
                if filter_type in OPERATORS:
                    op = OPERATORS[filter_type]
                    if op == "eq":
                        df = df.filter(pl.col(col) == crit1)
                    elif op == "ne":
                        df = df.filter(pl.col(col) != crit1)
                    elif op == "lt":
                        df = df.filter(pl.col(col) < crit1)
                    elif op == "le":
                        df = df.filter(pl.col(col) <= crit1)
                    elif op == "gt":
                        df = df.filter(pl.col(col) > crit1)
                    elif op == "ge":
                        df = df.filter(pl.col(col) >= crit1)

        elif filter_model["filterType"] == "set":
            # Handle set filter (multi-select)
            df = df.filter(pl.col(col).cast(pl.Utf8).is_in(filter_model["values"]))

    except Exception as e:
        logger.warning(f"Failed to apply filter for column {col}: {e}")
        # Return original dataframe if filter fails
        pass

    return df


def apply_ag_grid_sorting(df: pl.DataFrame, sort_model: list) -> pl.DataFrame:
    """
    Apply AG Grid sorting to a Polars DataFrame.
    """
    if not sort_model:
        return df

    try:
        # Apply sorting - Polars uses descending parameter differently
        df = df.sort(
            [sort["colId"] for sort in sort_model],
            descending=[sort["sort"] == "desc" for sort in sort_model],
        )

        logger.debug(f"Applied sorting: {[(s['colId'], s['sort']) for s in sort_model]}")

    except Exception as e:
        logger.warning(f"Failed to apply sorting: {e}")

    return df


# ============================================================================
# Design Mode UI Functions (TODO: Move to design_ui.py in future PR)
# ============================================================================


def design_table(id):
    row = [
        dmc.Center(
            dmc.Button(
                "Display Table",
                id={"type": "btn-table", "index": id["index"]},
                n_clicks=1,
                style=UNSELECTED_STYLE,
                size="xl",
                color="green",
                leftSection=DashIconify(
                    icon="material-symbols:table-rows-narrow-rounded", color="white"
                ),
            )
        ),
        html.Div(
            html.Div(
                build_table_frame(index=id["index"]),
                # dbc.CardBody(
                #     html.Div(id={"type": "table-grid", "index": id["index"]}),
                #     id={
                #         "type": "card-body",
                #         "index": id["index"],
                #     },
                # ),
                id={
                    "type": "component-container",
                    "index": id["index"],
                },
            ),
            # dbc.Card(
            #     dbc.CardBody(
            #         html.Div(id={"type": "table-grid", "index": id["index"]}),
            #         id={
            #             "type": "card-body",
            #             "index": id["index"],
            #         },
            #     ),
            #     id={
            #         "type": "component-container",
            #         "index": id["index"],
            #     },
            # )
        ),
    ]
    return row
    # return html.Div(
    #             build_table_frame(index=id["index"]),
    #             # dbc.CardBody(
    #             #     html.Div(id={"type": "table-grid", "index": id["index"]}),
    #             #     id={
    #             #         "type": "card-body",
    #             #         "index": id["index"],
    #             #     },
    #             # ),
    #             id={
    #                 "type": "component-container",
    #                 "index": id["index"],
    #             },
    #         )


def create_stepper_table_button(n, disabled=None):
    """
    Create the stepper table button

    Args:
        n (_type_): _description_
        disabled (bool, optional): Override enabled state. If None, uses metadata.
    """

    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("table")

    from depictio.dash.component_metadata import get_component_color

    dmc_color = get_dmc_button_color("table")
    hex_color = get_component_color("table")  # This returns the hex color from colors.py
    logger.info(f"Table button DMC color: {dmc_color}, hex color: {hex_color}")

    # Create the table button with outline variant and larger text
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
