# Import necessary libraries
from dash import html, dcc, Input, Output, State, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx
import dash_ag_grid as dag

# Depictio imports
from depictio.dash.utils import return_mongoid
from depictio.api.v1.deltatables_utils import load_deltatable_lite, join_deltatables

from depictio.api.v1.configs.config import API_BASE_URL, TOKEN

from depictio.dash.utils import (
    UNSELECTED_STYLE,
    get_columns_from_data_collection,
)

# TODO: interactivity when selecting table rows 

def register_callbacks_table_component(app):
    # Callback to update card body based on the selected column and aggregation
    @app.callback(
        Output({"type": "table-grid", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-table", "index": MATCH}, "n_clicks"),
            Input({"type": "btn-table", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def design_table_component(wf_tag, dc_tag, n_clicks, id):
        """
        Callback to update card body based on the selected column and aggregation
        """

        # FIXME: This is a temporary solution to get the token
        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        # Get the workflow and data collection ids from the tags selected
        workflow_id, data_collection_id = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_tag)

        # Get the data collection specs
        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers=headers,
        ).json()

        # Get the join tables for the selected workflow - used in store for metadata management
        join_tables_for_wf = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/workflows/get_join_tables/{workflow_id}",
            headers=headers,
        )

        # If the request is successful, get the join details for the selected data collection
        if join_tables_for_wf.status_code == 200:
            join_tables_for_wf = join_tables_for_wf.json()
            if data_collection_id in join_tables_for_wf:
                join_details = join_tables_for_wf[data_collection_id]
                dc_specs["config"]["join"] = join_details

        # Load deltatable from the selected data collection
        df = load_deltatable_lite(workflow_id, data_collection_id)
        cols = get_columns_from_data_collection(wf_tag, dc_tag)

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

        # TODO: use other properties of Dash AgGrid
        # Prepare ag grid table
        table_aggrid = dag.AgGrid(
            id = {"type": "table-aggrid", "index": id["index"]},
            rowData=df.to_dict("records"),
            columnDefs=columnDefs,
            dashGridOptions={
                "tooltipShowDelay": 500,
                "pagination": True,
                # "paginationAutoPageSize": False,
                # "animateRows": False,
            },
            # columnSize="sizeToFit",
            defaultColDef={"resizable": True, "sortable": True, "filter": True},
            # use the parameters above
        )

        # Metadata management - Create a store component to store the metadata of the card
        store_component = dcc.Store(
            id={
                "type": "stored-metadata-component",
                "index": id["index"],
            },
            data={
                "index": id["index"],
                "component_type": "table",
                "wf_id": workflow_id,
                "dc_id": data_collection_id,
                "dc_config": dc_specs["config"],
            },
        )

        # Create the card body - default title is the aggregation value on the selected column

        # Create the card body
        new_card_body = [
            store_component,
            table_aggrid,

        ]

        return new_card_body


def design_table(id):
    row = [
        dbc.Row(
            dmc.Center(
                dmc.Button(
                    "Display Table",
                    id={"type": "btn-table", "index": id["index"]},
                    n_clicks=1,
                    style=UNSELECTED_STYLE,
                    size="xl",
                    color="green",
                    leftIcon=DashIconify(icon="material-symbols:table-rows-narrow-rounded", color="white"),
                )
            ),
        ),
        dbc.Row(
            dbc.Card(
                dbc.CardBody(
                    html.Div(id={"type": "table-grid", "index": id["index"]}),
                    id={
                        "type": "card-body",
                        "index": id["index"],
                    },
                ),
                id={
                    "type": "component-container",
                    "index": id["index"],
                },
            )
        ),
    ]
    return row


def create_stepper_table_button(n, disabled=False):
    """
    Create the stepper table button
    """

    # Create the table button
    button = dbc.Col(
        dmc.Button(
            "Table",
            id={
                "type": "btn-option",
                "index": n,
                "value": "Table",
            },
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color="green",
            leftIcon=DashIconify(icon="octicon:table-24", color="white"),
            disabled=disabled,
        )
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
