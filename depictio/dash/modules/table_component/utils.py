import polars as pl
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc
import dash_ag_grid as dag

from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.utils import get_columns_from_data_collection
from depictio.api.v1.configs.logging import logger


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
                "border": "0px",  # Optional: Remove border
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
                "border": "0px",  # Optional: Remove border
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
        df = load_deltatable_lite(wf_id, dc_id, TOKEN=TOKEN)

    # Add dah aggrid filters to the columns
    for c in cols:
        print(c, cols[c]["type"])
        if cols[c]["type"] == "object":
            cols[c]["filter"] = "agTextColumnFilter"
        elif cols[c]["type"] in ["int64", "float64"]:
            cols[c]["filter"] = "agNumberColumnFilter"
        # FIXME: use properly this: https://dash.plotly.com/dash-ag-grid/date-filters
        elif cols[c]["type"] == "datetime":
            cols[c]["filter"] = "agDateColumnFilter"

    # print(cols)
    columnDefs = [{"field": c, "headerTooltip": f"Column type: {e['type']}", "filter": e["filter"]} for c, e in cols.items()]

    # if description in col sub dict, update headerTooltip
    for col in columnDefs:
        if "description" in cols[col["field"]] and cols[col["field"]]["description"] is not None:
            col["headerTooltip"] = f"{col['headerTooltip']} | Description: {cols[col['field']]['description']}"

    style_partial_data_displayed = {"display": "none"}

    from dash_iconify import DashIconify

    cutoff = 1000

    if df.to_pandas().shape[0] > cutoff:
        df = df.head(cutoff)
        if build_frame:
            style_partial_data_displayed = {"display": "block", "paddingBottom": "5px"}

    partial_data_badge = dmc.Tooltip(
        children=dmc.Badge(
            "Partial data displayed",
            id={"type": "graph-partial-data-displayed", "index": index},
            style=style_partial_data_displayed,
            leftSection=DashIconify(
                icon="mdi:alert-circle",
                width=20,
            ),
            # sx={"paddingLeft": 0},
            size="lg",
            radius="xl",
            color="red",
            fullWidth=False,
        ),
        label=f"Tables are currently loaded with a maximum of {cutoff} rows.",
        position="top",
        openDelay=500,
    )
    # Prepare ag grid table
    table_aggrid = dag.AgGrid(
        id={"type": value_div_type, "index": str(index)},
        rowData=df.to_pandas().to_dict("records"),
        # rowModelType="infinite",
        columnDefs=columnDefs,
        dashGridOptions={
            "tooltipShowDelay": 500,
            "pagination": True,
            "paginationAutoPageSize": False,
            "animateRows": False,
            # The number of rows rendered outside the viewable area the grid renders.
            # "rowBuffer": 0,
            # # How many blocks to keep in the store. Default is no limit, so every requested block is kept.
            # "maxBlocksInCache": 2,
            # "cacheBlockSize": 100,
            # "cacheOverflowSize": 2,
            # "maxConcurrentDatasourceRequests": 2,
            # "infiniteInitialRowCount": 1,
            "rowSelection": "multiple",
            "enableCellTextSelection": True,
            "ensureDomOrder": True,
        },
        # columnSize="sizeToFit",
        defaultColDef={"resizable": True, "sortable": True, "filter": True},
        # use the parameters above
    )

    # Metadata management - Create a store component to store the metadata of the card
    store_index = index.replace("-tmp", "")
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

    # Create the card body
    new_card_body = html.Div(
        [
            partial_data_badge,
            table_aggrid,
            store_component,
        ]
    )
    if not build_frame:
        return new_card_body
    else:
        return build_table_frame(index=index, children=new_card_body)
