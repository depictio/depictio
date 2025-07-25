import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import polars as pl
from bson import ObjectId
from dash import dcc, html

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.modules.figure_component.utils import stringify_id


def build_table_frame(index, children=None):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                id={
                    "type": "table-body",
                    "index": index,
                },
                style={
                    "padding": "5px",  # Reduce padding inside the card body
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                    "height": "100%",  # Make sure it fills the parent container
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Optional: Remove shadow for a cleaner look
                # "border": "1px solid #ddd",  # Optional: Add a light border
                # "borderRadius": "4px",  # Optional: Slightly round the corners
                "border": "1px solid var(--app-border-color, #ddd)",  # Always show border for draggable delimitation  # Optional: Remove border
            },
            id={
                "type": "table-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            dbc.CardBody(
                children=children,
                id={
                    "type": "table-body",
                    "index": index,
                },
                style={
                    "padding": "5px",  # Reduce padding inside the card body
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                    "height": "100%",  # Make sure it fills the parent container
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Optional: Remove shadow for a cleaner look
                # "border": "1px solid #ddd",  # Optional: Add a light border
                # "borderRadius": "4px",  # Optional: Slightly round the corners
                "border": "1px solid var(--app-border-color, #ddd)",  # Always show border for draggable delimitation  # Optional: Remove border
            },
            id={
                "type": "table-component",
                "index": index,
            },
        )


def build_table(**kwargs):
    logger.info("build_table")
    # def build_card(index, title, wf_id, dc_id, dc_config, column_name, column_type, aggregation, v, build_frame=False):
    index = kwargs.get("index")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    cols = kwargs.get("cols_json")
    build_frame = kwargs.get("build_frame", False)

    df = kwargs.get("df", pl.DataFrame())
    TOKEN = kwargs.get("access_token")
    stepper = kwargs.get("stepper", False)

    df = kwargs.get("df", pl.DataFrame())

    # if stepper:
    #     value_div_type = "table-aggrid-tmp"
    # else:
    value_div_type = "table-aggrid"

    if df.is_empty():
        # Check if we're in a refresh context where we should load new data
        if kwargs.get("refresh", True):
            logger.info(
                f"Table component {index}: Loading delta table for {wf_id}:{dc_id} (no pre-loaded df)"
            )
            # Validate that we have valid IDs before calling load_deltatable_lite
            if not wf_id or not dc_id:
                logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
                df = pl.DataFrame()  # Return empty DataFrame if IDs are missing
            else:
                df = load_deltatable_lite(ObjectId(wf_id), ObjectId(dc_id), TOKEN=TOKEN)
        else:
            # If refresh=False and df is empty, this means filters resulted in no data
            # Keep the empty DataFrame to properly reflect the filtered state
            logger.info(
                f"Table component {index}: Using empty DataFrame from filters (shape: {df.shape}) - filters exclude all data"
            )
    else:
        logger.debug(f"Table component {index}: Using pre-loaded DataFrame (shape: {df.shape})")

    # Add dash aggrid filters to the columns with enhanced filter configuration
    if cols:
        for c in cols:
            if c in cols and "type" in cols[c]:
                logger.debug(f"Configuring column {c} with type {cols[c]['type']}")
                if cols[c]["type"] == "object":
                    cols[c]["filter"] = "agTextColumnFilter"
                    # Enable floating filters for better UX
                    cols[c]["floatingFilter"] = True
                elif cols[c]["type"] in ["int64", "float64"]:
                    cols[c]["filter"] = "agNumberColumnFilter"
                    cols[c]["floatingFilter"] = True
                    # Add filter parameters for number columns
                    cols[c]["filterParams"] = {
                        "filterOptions": ["equals", "lessThan", "greaterThan", "inRange"],
                        "maxNumConditions": 2,
                    }
                # FIXME: use properly this: https://dash.plotly.com/dash-ag-grid/date-filters
                elif cols[c]["type"] == "datetime":
                    cols[c]["filter"] = "agDateColumnFilter"
                    cols[c]["floatingFilter"] = True

    # Add ID column for SpinnerCellRenderer (following documentation example exactly)
    columnDefs = [{"field": "ID", "maxWidth": 100, "cellRenderer": "SpinnerCellRenderer"}]

    # Add data columns with enhanced filtering and sorting support
    if cols:
        data_columns = [
            {
                "field": c,
                "headerTooltip": f"Column type: {e['type']}",
                "filter": e["filter"],
                "floatingFilter": e.get("floatingFilter", False),
                "filterParams": e.get("filterParams", {}),
                "sortable": True,  # Enable sorting for all columns
                "resizable": True,  # Enable column resizing
                "minWidth": 150,  # Ensure readable column width
            }
            for c, e in cols.items()  # type: ignore[possibly-unbound-attribute]
        ]
        columnDefs.extend(data_columns)

    # if description in col sub dict, update headerTooltip
    for col in columnDefs:
        if (
            cols
            and "field" in col  # Check if field exists in column definition
            and col["field"] in cols
            and "description" in cols[col["field"]]
            and cols[col["field"]]["description"] is not None
        ):
            col["headerTooltip"] = (
                f"{col['headerTooltip']} | Description: {cols[col['field']]['description']}"
            )
    logger.info(f"Columns definitions for table {index}: {columnDefs}")

    # INFINITE ROW MODEL: No cutoff needed - data is loaded on demand
    from dash_iconify import DashIconify

    # Show infinite scroll + pagination badge instead of partial data badge
    infinite_scroll_badge = html.Div(
        dmc.Tooltip(
            children=dmc.Badge(
                "Infinite + Spinner",
                id={"type": "table-infinite-scroll-badge", "index": index},
                style={"display": "block", "paddingBottom": "5px"}
                if build_frame
                else {"display": "none"},
                leftSection=DashIconify(
                    icon="mdi:infinity",
                    width=20,
                ),
                size="lg",
                radius="xl",
                color="blue",
                fullWidth=False,
            ),
            label=f"Table uses infinite scrolling with loading spinners - data loads in blocks as you navigate through {df.shape[0]} total rows.",
            position="top",
            openDelay=500,
            withinPortal=False,
        ),
        style={"width": "fit-content"},  # Badge should not affect layout
    )

    logger.info(
        f"♾️ Table {index}: No data cutoff applied - infinite scrolling + pagination will handle {df.shape[0]} rows"
    )
    # INFINITE ROW MODEL: Enable infinite scrolling for large datasets
    logger.info(
        f"📊 Table {index}: Configuring infinite row model for dataset with {df.shape[0]} rows"
    )

    # Prepare ag grid table with infinite row model
    table_aggrid = dag.AgGrid(
        id={"type": value_div_type, "index": str(index)},
        # CRITICAL: Don't set rowData for infinite model - data comes from getRowsResponse
        rowModelType="infinite",  # Enable infinite scrolling
        columnDefs=columnDefs,
        dashGridOptions={
            "tooltipShowDelay": 500,
            # INFINITE MODEL CONFIGURATION (optimized for spinner loading)
            # The number of rows rendered outside the viewable area the grid renders.
            "rowBuffer": 0,  # Match documentation example
            # How many blocks to keep in the store. Default is no limit, so every requested block is kept.
            "maxBlocksInCache": 10,  # Increased for better caching with spinner
            "cacheBlockSize": 100,  # Each block contains 100 rows
            "cacheOverflowSize": 2,  # Allow 2 extra blocks beyond maxBlocksInCache
            # "maxConcurrentDatasourceRequests": 1,  # Limit to 1 for spinner demo
            "infiniteInitialRowCount": 1000,  # Higher initial count to show spinner effect
            # OTHER OPTIONS
            "rowSelection": "multiple",
            "enableCellTextSelection": True,
            "ensureDomOrder": True,
            # ENABLE PAGINATION with infinite model (as per documentation example)
            "pagination": True,
        },
        # CRITICAL: getRowId is needed for SpinnerCellRenderer to work properly
        getRowId="params.data.ID",
        # columnSize="sizeToFit",
        defaultColDef={
            "flex": 1,
            "minWidth": 150,
            "sortable": True,
            "resizable": True,
            "floatingFilter": True,  # Enable floating filters by default
            "filter": True,
        },
        # Remove height, let CSS handle it dynamically
        style={
            "width": "100%",
        },
        className="ag-theme-alpine",
        # use the parameters above
    )

    logger.info(
        f"🚀 Table {index}: Infinite row model configured - blocks of {100} rows, max {10} cached blocks, pagination + spinner enabled"
    )

    # Metadata management - Create a store component to store the metadata of the card
    store_index = index.replace("-tmp", "")  # type: ignore[possibly-unbound-attribute]
    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": str(store_index),
        },
        data={
            "index": str(store_index),
            "component_type": "table",
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
            "cols_json": cols,
            "parent_index": None,
        },
    )

    # Create the card body - default title is the aggregation value on the selected column

    # Create the card body - simple structure
    new_card_body = html.Div(
        [
            infinite_scroll_badge,
            table_aggrid,
            store_component,
        ]
    )
    if not build_frame:
        return new_card_body
    else:
        # Build the table component with frame
        table_component = build_table_frame(index=index, children=new_card_body)

        if not stepper:
            # Add targeted loading for the AG Grid component specifically
            from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
                create_skeleton_component,
            )

            graph_id_dict = {"type": "table-aggrid", "index": str(index)}
            target_id = stringify_id(graph_id_dict)
            logger.debug(f"Target ID for loading: {target_id}")

            return dcc.Loading(
                children=table_component,
                custom_spinner=create_skeleton_component("table"),
                # target_components={f'{{"index":"{index}","type":"table-aggrid"}}': "rowData"},
                target_components={target_id: "rowData"},
                # delay_show=50,  # Minimal delay to prevent flashing
                # delay_hide=100,  # Quick dismissal
                delay_show=50,  # Minimal delay to prevent flashing
                delay_hide=300,  #
                id={"index": index},  # Move the id to the loading component
            )

        else:
            # For stepper mode without loading
            return table_component
