"""
Table component utilities for building AG Grid tables.

This module provides functions to create and configure Dash AG Grid table components
with features like infinite scrolling, pagination, filtering, and theme support.

Functions:
    build_table_frame: Creates the outer Paper container for a table.
    build_table: Builds a complete AG Grid table with all configurations.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
import polars as pl
from bson import ObjectId
from dash import dcc, html

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.modules.figure_component.utils import stringify_id


def build_table_frame(index: str, children: html.Div | None = None) -> dmc.Paper:
    """Create the outer Paper container frame for a table component.

    Args:
        index: Unique identifier for the table component.
        children: Optional content to display inside the frame. If None,
            displays a placeholder message.

    Returns:
        A dmc.Paper component configured as the table container.
    """
    if not children:
        return dmc.Paper(
            children=[
                dmc.Center(
                    dmc.Text(
                        "Configure your table using the edit menu",
                        size="sm",
                        fs="italic",
                        ta="center",
                    ),
                    id={
                        "type": "table-body",
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
                "type": "table-component",
                "index": index,
            },
            withBorder=True,
            radius="sm",
            p="md",
            w="100%",
            h="100%",
        )

    return dmc.Paper(
        children=children,
        id={
            "type": "table-component",
            "index": index,
        },
        withBorder=True,
        radius="sm",
        p="xs",
        w="100%",
        h="100%",
        style={
            "display": "flex",
            "flexDirection": "column",
            "overflow": "hidden",
            "paddingBottom": "12px",
        },
    )


def _get_theme_template(theme: str) -> str:
    """Get the appropriate AG Grid theme class based on the theme setting.

    Args:
        theme: Theme name ("light", "dark", or other).

    Returns:
        AG Grid theme class name (e.g., "ag-theme-alpine" or "ag-theme-alpine-dark").
    """
    if not theme or theme == {} or theme == "{}":
        theme = "light"

    return "ag-theme-alpine-dark" if theme == "dark" else "ag-theme-alpine"


def _load_dataframe(
    wf_id: str | None,
    dc_id: str | None,
    token: str,
    index: str,
    refresh: bool,
    init_data: dict[str, dict] | None = None,
) -> pl.DataFrame:
    """Load DataFrame from delta table if needed.

    Args:
        wf_id: Workflow ID.
        dc_id: Data collection ID.
        token: Authentication token.
        index: Component index for logging.
        refresh: Whether to refresh data from source.
        init_data: Dashboard initialization data with delta locations and dc_type.

    Returns:
        Loaded DataFrame or empty DataFrame if loading fails.
    """
    if not refresh:
        return pl.DataFrame()

    if not wf_id or not dc_id:
        logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
        return pl.DataFrame()

    try:
        # Handle joined data collection IDs - don't convert to ObjectId
        if isinstance(dc_id, str) and "--" in dc_id:
            return load_deltatable_lite(ObjectId(wf_id), dc_id, TOKEN=token, init_data=init_data)

        return load_deltatable_lite(
            ObjectId(wf_id), ObjectId(dc_id), TOKEN=token, init_data=init_data
        )
    except Exception as e:
        # Graceful error handling for missing delta tables (e.g., "no log files" error)
        # Returns an error DataFrame instead of crashing the dashboard viewer
        logger.error(f"Failed to load delta table for DC {dc_id} (index={index}): {e}")
        return pl.DataFrame({"error": [f"Data unavailable: {str(e)}"]})


def _configure_column_filters(cols: dict | None) -> None:
    """Configure AG Grid filters for each column based on data type.

    Modifies the cols dictionary in place to add appropriate filter configurations.

    Args:
        cols: Dictionary of column configurations keyed by column name.
    """
    if not cols:
        return

    for col_name, col_config in cols.items():
        if "type" not in col_config:
            continue

        col_type = col_config["type"]

        if col_type == "object":
            col_config["filter"] = "agTextColumnFilter"
            col_config["floatingFilter"] = True
        elif col_type in ["int64", "float64"]:
            col_config["filter"] = "agNumberColumnFilter"
            col_config["floatingFilter"] = True
            col_config["filterParams"] = {
                "filterOptions": ["equals", "lessThan", "greaterThan", "inRange"],
                "maxNumConditions": 2,
            }
        elif col_type == "datetime":
            # FIXME: use properly: https://dash.plotly.com/dash-ag-grid/date-filters
            col_config["filter"] = "agDateColumnFilter"
            col_config["floatingFilter"] = True
        elif col_type == "bool":
            col_config["filter"] = "agTextColumnFilter"
            col_config["floatingFilter"] = True
        else:
            col_config["filter"] = "agTextColumnFilter"
            col_config["floatingFilter"] = True


def _build_column_definitions(cols: dict | None) -> list[dict]:
    """Build AG Grid column definitions from column configuration.

    Args:
        cols: Dictionary of column configurations keyed by column name.

    Returns:
        List of AG Grid column definition dictionaries.
    """
    column_defs = []

    if not cols:
        return column_defs

    # Build column definitions with checkboxSelection on first column
    for idx, (col_name, col_config) in enumerate(cols.items()):
        # Handle field names with dots - replace with underscores
        safe_field_name = col_name.replace(".", "_") if "." in col_name else col_name

        column_def = {
            "headerName": " ".join(word.capitalize() for word in col_name.split(".")),
            "headerTooltip": f"Column type: {col_config.get('type', 'unknown')}",
            "field": safe_field_name,
            "filter": col_config.get("filter", "agTextColumnFilter"),
            "floatingFilter": col_config.get("floatingFilter", False),
            "filterParams": col_config.get("filterParams", {}),
            "sortable": True,
            "resizable": True,
            "minWidth": 150,
        }

        # Add checkbox selection to first column
        if idx == 0:
            column_def["checkboxSelection"] = True
            column_def["headerCheckboxSelection"] = True

        column_defs.append(column_def)

    return column_defs


def _add_description_tooltips(column_defs: list[dict], cols: dict | None) -> None:
    """Add description tooltips to column definitions.

    Modifies column_defs in place to append descriptions to header tooltips.

    Args:
        column_defs: List of AG Grid column definitions.
        cols: Dictionary of column configurations with optional descriptions.
    """
    if not cols:
        return

    for col_def in column_defs:
        field = col_def.get("field")
        if not field or field not in cols:
            continue

        description = cols[field].get("description")
        if description:
            col_def["headerTooltip"] = f"{col_def['headerTooltip']} | Description: {description}"


def _create_ag_grid_component(
    index: str,
    column_defs: list[dict],
    theme: str,
) -> dag.AgGrid:
    """Create the AG Grid component with infinite row model configuration.

    Args:
        index: Unique identifier for the table.
        column_defs: List of column definitions.
        theme: Theme name for styling.

    Returns:
        Configured dag.AgGrid component.
    """
    aggrid_theme = _get_theme_template(theme)

    return dag.AgGrid(
        id={"type": "table-aggrid", "index": str(index)},
        rowModelType="infinite",
        columnDefs=column_defs,
        dashGridOptions={
            "tooltipShowDelay": 500,
            # Infinite model configuration
            "rowBuffer": 0,
            "maxBlocksInCache": 10,
            "cacheBlockSize": 100,
            "cacheOverflowSize": 2,
            "infiniteInitialRowCount": 1000,
            # Pagination settings
            "pagination": True,
            "paginationPageSize": 100,
            "paginationPageSizeSelector": [50, 100, 200, 500],
            # Selection and interaction
            "rowSelection": "multiple",
            "suppressRowClickSelection": True,  # Only checkbox triggers selection
            "enableCellTextSelection": True,
            "ensureDomOrder": True,
            "domLayout": "normal",
            # Status bar
            "statusBar": {
                "statusPanels": [
                    {"statusPanel": "agTotalRowCountComponent", "align": "left"},
                    {"statusPanel": "agFilteredRowCountComponent"},
                    {"statusPanel": "agSelectedRowCountComponent"},
                ]
            },
            # Cache management
            "purgeClosedRowNodes": True,
            "resetRowDataOnUpdate": True,
            "maxConcurrentDatasourceRequests": 1,
            "blockLoadDebounceMillis": 0,
        },
        # Visual highlighting for rows matching highlight filter
        rowClassRules={"ag-row-highlighted": "params.data && params.data._is_highlighted === true"},
        defaultColDef={
            "flex": 1,
            "minWidth": 150,
            "sortable": True,
            "resizable": True,
            "floatingFilter": True,
            "filter": True,
        },
        className=aggrid_theme,
    )


def _create_metadata_store(
    index: str,
    wf_id: str | None,
    dc_id: str | None,
    dc_config: dict | None,
    cols: dict | None,
    row_selection_enabled: bool = False,
    row_selection_column: str | None = None,
    highlight_filter: dict | None = None,
) -> dcc.Store:
    """Create the metadata store component for the table.

    Args:
        index: Component index.
        wf_id: Workflow ID.
        dc_id: Data collection ID.
        dc_config: Data collection configuration.
        cols: Column definitions.
        row_selection_enabled: Whether row selection filtering is enabled.
        row_selection_column: Column to extract from selected rows.

    Returns:
        dcc.Store component with table metadata.
    """
    store_index = str(index)
    clean_index = str(index).replace("-tmp", "")

    # Normalize ObjectId format from MongoDB to plain strings
    # Dashboard JSON may have {"$oid": "..."} format for MongoDB ObjectIds
    if isinstance(wf_id, dict) and "$oid" in wf_id:
        wf_id = wf_id["$oid"]
    if isinstance(dc_id, dict) and "$oid" in dc_id:
        dc_id = dc_id["$oid"]

    store_data: dict = {
        "index": clean_index,
        "component_type": "table",
        "wf_id": wf_id,
        "dc_id": dc_id,
        "dc_config": dc_config,
        "cols_json": cols,
        "parent_index": None,
        "row_selection_enabled": row_selection_enabled,
        "row_selection_column": row_selection_column,
    }
    if highlight_filter is not None:
        store_data["highlight_filter"] = highlight_filter

    return dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": store_index,
        },
        data=store_data,
    )


def _create_highlight_cards(index: str, highlight_filter: dict | None) -> html.Div | None:
    """Create highlight summary cards to display under the table.

    NOTE: This is currently disabled - cards are now shown under the figure component.

    Args:
        index: Component index.
        highlight_filter: Highlight filter configuration.

    Returns:
        None (cards disabled, moved to figure component).
    """
    return None


def _create_table_body(
    index: str,
    ag_grid: dag.AgGrid,
    store: dcc.Store,
    highlight_filter: dict | None = None,
) -> html.Div:
    """Create the table body container with AG Grid and supporting components.

    Args:
        index: Component index.
        ag_grid: The AG Grid component.
        store: The metadata store component.
        highlight_filter: Optional highlight filter configuration.

    Returns:
        html.Div containing the complete table body.
    """
    download_component = dcc.Download(id={"type": "download-table-csv", "index": str(index)})
    export_notification = html.Div(
        id={"type": "export-notification-container", "index": str(index)}
    )

    hidden_style = {"position": "absolute", "visibility": "hidden"}

    # Cards are now under the figure component, not the table
    children = [
        html.Div(
            ag_grid,
            style={
                "width": "100%",
                "height": "calc(100% - 4px)",
                "minHeight": "0",
                "position": "relative",
                "overflow": "auto",
            },
        ),
    ]

    # Cache-busting store for forcing AG Grid refresh when slider changes
    cache_version_store = dcc.Store(id={"type": "table-cache-version", "index": str(index)}, data=0)

    children.extend(
        [
            html.Div(store, style=hidden_style),
            html.Div(download_component, style=hidden_style),
            html.Div(export_notification, style=hidden_style),
            html.Div(cache_version_store, style=hidden_style),
        ]
    )

    return html.Div(
        children,
        id={"type": "table-content", "index": index},
        style={
            "width": "100%",
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "minHeight": "0",
            "position": "relative",
            "paddingBottom": "8px",
        },
    )


def build_table(**kwargs) -> html.Div | dmc.Paper | dcc.Loading:
    """Build a complete AG Grid table component with all configurations.

    This function creates a fully configured table with infinite scrolling,
    pagination, filtering, and theme support. It handles data loading,
    column configuration, and optional loading spinners.

    Args:
        **kwargs: Keyword arguments containing:
            - index (str): Unique identifier for the table.
            - wf_id (str): Workflow ID.
            - dc_id (str): Data collection ID.
            - dc_config (dict): Data collection configuration.
            - cols_json (dict): Column definitions with types.
            - theme (str): Theme name ("light" or "dark").
            - build_frame (bool): Whether to wrap in a Paper frame.
            - df (pl.DataFrame): Pre-loaded DataFrame (optional).
            - access_token (str): Authentication token.
            - stepper (bool): Whether in stepper mode.
            - refresh (bool): Whether to refresh data from source.
            - row_selection_enabled (bool): Enable row selection filtering.
            - row_selection_column (str): Column to extract from selected rows.

    Returns:
        The table component, optionally wrapped in a frame and/or loading spinner.
    """

    # Extract parameters
    index = kwargs.get("index")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    cols = kwargs.get("cols_json")
    theme = kwargs.get("theme", "light")
    build_frame = kwargs.get("build_frame", False)
    df = kwargs.get("df", pl.DataFrame())
    token = kwargs.get("access_token")
    stepper = kwargs.get("stepper", False)
    # Row selection filtering configuration
    row_selection_enabled = kwargs.get("row_selection_enabled", False)
    row_selection_column = kwargs.get("row_selection_column")
    highlight_filter = kwargs.get("highlight_filter")

    # Load data if needed
    if df.is_empty():
        init_data = kwargs.get("init_data")
        df = _load_dataframe(wf_id, dc_id, token, index, kwargs.get("refresh", True), init_data)
    # Configure columns
    _configure_column_filters(cols)
    column_defs = _build_column_definitions(cols)
    _add_description_tooltips(column_defs, cols)

    # Build components
    ag_grid = _create_ag_grid_component(index, column_defs, theme)
    store = _create_metadata_store(
        index,
        wf_id,
        dc_id,
        dc_config,
        cols,
        row_selection_enabled,
        row_selection_column,
        highlight_filter=highlight_filter,
    )

    table_body = _create_table_body(index, ag_grid, store, highlight_filter)

    if not build_frame:
        return table_body

    # Build the table component with frame
    table_component = build_table_frame(index=index, children=table_body)

    if stepper:
        return table_component

    # Dashboard mode - add loading spinner
    from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
        create_skeleton_component,
    )

    if settings.performance.disable_loading_spinners:
        return table_body

    graph_id_dict = {"type": "table-aggrid", "index": str(index)}
    target_id = stringify_id(graph_id_dict)

    loading = dcc.Loading(
        children=table_body,
        custom_spinner=create_skeleton_component("table"),
        target_components={target_id: "rowData"},
        delay_show=50,
        delay_hide=300,
        id={"type": "table-loading", "index": index},
    )
    return loading
