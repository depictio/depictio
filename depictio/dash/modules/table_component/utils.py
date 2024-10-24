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
                }
            ),
            style={"width": "100%"},
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
            ),
            style={"width": "100%"},
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
            "enableCellTextSelection": True, "ensureDomOrder": True
        },
        # columnSize="sizeToFit",
        defaultColDef={"resizable": True, "sortable": True, "filter": True},
        # use the parameters above
    )

    # Metadata management - Create a store component to store the metadata of the card
    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": str(index),
        },
        data={
            "index": str(index),
            "component_type": "table",
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
            "cols_json": cols,
        },
    )

    # Create the card body - default title is the aggregation value on the selected column

    # Create the card body
    new_card_body = html.Div(
        [
            table_aggrid,
            store_component,
        ]
    )
    if not build_frame:
        return new_card_body
    else:
        return build_table_frame(index=index, children=new_card_body)
