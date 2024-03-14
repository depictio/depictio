# Import necessary libraries
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import pandas as pd
from dash_iconify import DashIconify


import dash_jbrowse
from depictio.dash.utils import list_workflows

# Depictio imports
from depictio.dash.modules.jbrowse_component.utils import (
    my_assembly,
    my_tracks,
    my_location,
    # my_aggregate_text_search_adapters,
    # my_theme,
)

from depictio.dash.utils import (
    SELECTED_STYLE,
    UNSELECTED_STYLE,
    list_data_collections_for_dropdown,
    list_workflows_for_dropdown,
    get_columns_from_data_collection,
    load_deltatable,
)
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN


def register_callbacks_jbrowse_component(app):
    @app.callback(
        Output({"type": "jbrowse-body", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-jbrowse", "index": MATCH}, "n_clicks"),
            Input({"type": "btn-jbrowse", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def update_jbrowse(wf_id, dc_id, n_clicks, id):
        print("update_jbrowse", wf_id, dc_id, n_clicks)

        workflows = list_workflows(TOKEN)

        workflow_id = [e for e in workflows if e["workflow_tag"] == wf_id][0]["_id"]
        data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == dc_id][0]["_id"]

        import httpx

        # API_BASE_URL = "http://localhost:8058"
        # API_BASE_URL = "http://host.docker.internal:8058"

        print(workflow_id, data_collection_id)

        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()
        print(dc_specs)

        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            }
        )
        print("\n\n\n")
        print("update_jbrowse")
        print(response.status_code)
        print(response.json())
        if response.status_code != 200:
            raise Exception("Error fetching user")

        elif response.status_code == 200:
            # Session to define based on User ID & Dashboard ID
            # TODO: define dashboard ID

            print(response.json())

            user_id = response.json()["user_id"]
            dashboard_id = "1"
            session = f"{user_id}_{dashboard_id}.json"

            iframe = html.Iframe(
                src=f"http://localhost:3000?config=http://localhost:9010/sessions/{session}&loc=chr1:1-248956422&assembly=hg38",
                width="100%",
                height="1000px",
            )
            print("iframe")
            print(iframe)
            store_component = dcc.Store(
                id={"type": "store-jbrowse", "index": id["index"], "value": "jbrowse"},
                data={
                    "index": id["index"],
                    "wf_id": workflow_id,
                    "dc_id": data_collection_id,
                    "dc_config": dc_specs["config"],
                },
                storage_type="memory",
            )

            print(html.Div([iframe, store_component]))
            return html.Div([iframe, store_component])


def design_jbrowse(id):
    print("design_jbrowse", id)
    row = [
        dmc.Button(
            "Display JBrowse",
            id={"type": "btn-jbrowse", "index": id["index"]},
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color="yellow",
            leftIcon=DashIconify(icon="material-symbols:table-rows-narrow-rounded", color="white"),
        ),
        # )
        html.Div(
            html.Div(id={"type": "jbrowse-body", "index": id["index"]}),
            id={"type": "test-container", "index": id["index"]},
        ),
    ]
    # print(row)
    return row


def create_stepper_jbrowse_button(n, disabled=False):
    button = dbc.Col(
        dmc.Button(
            "JBrowse2",
            id={
                "type": "btn-option",
                "index": n,
                "value": "JBrowse2",
            },
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color="yellow",
            leftIcon=DashIconify(icon="material-symbols:table-rows-narrow-rounded", color="white"),
            disabled=disabled,
        )
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "JBrowse2",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
