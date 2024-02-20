# Import necessary libraries
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import pandas as pd
from dash_iconify import DashIconify


import dash_jbrowse
from CLI_client.cli import list_workflows


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


def register_callbacks_jbrowse_component(app):
    @app.callback(
        Output({"type": "jbrowse-body", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-jbrowse", "index": MATCH}, "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def update_jbrowse(wf_id, dc_id, n_clicks):




        token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2NGE4NDI4NDJiZjRmYTdkZWFhM2RiZWQiLCJleHAiOjE3ODQ5ODY3ODV9.a5bkSctoCNYXVh035g_wt-bio3iC3uuM9anFKiJOKrmBHDH0tmcL2O9Rc1HIQtAxCH-mc1K4q4aJsAO8oeayuPyA3w7FPIUnLsZGRHB8aBoDCoxEIpmACi0nEH8hF9xd952JuBt6ggchyMyrnxHC65Qc8mHC9PeylWonHvNl5jGZqi-uhbeLpsjuPcsyg76X2aqu_fip67eJ8mdr6yuII6DLykpfbzALpn0k66j79YzOzDuyn4IjBfBPWiqZzl_9oDMLK7ODebu6FTDmQL0ZGto_dxyIJtkf1CdxPaYkgiXVOh00Y6sXJ24jHSqfNP-dqvAQ3G8izuurq6B4SNgtDw"

        workflows = list_workflows(token)

        workflow_id = [e for e in workflows if e["workflow_tag"] == wf_id][0]["_id"]
        data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == dc_id][0]["_id"]

        import httpx
        API_BASE_URL = "http://localhost:8058"
        # API_BASE_URL = "http://host.docker.internal:8058"


        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {token}",
            },
        ).json()


        iframe = html.Iframe(
            src="http://localhost:3000?config=http://localhost:9010/config.json&loc=chr1:1-248956422&assembly=hg38",
            width="100%",
            height="1000px",
        )
        store_component = dcc.Store(
            id={"type": "store-jbrowse", "index": 0},
            data={
                "index": id["index"],
                "wf_id": workflow_id,
                "dc_id": data_collection_id,
                "dc_config": dc_specs["config"],
            },
            storage_type="memory",
        )
        return html.Div([iframe, store_component])


def design_jbrowse(id):
    row = [
        dmc.Button(
            "Display JBrowse",
            id={"type": "btn-jbrowse", "index": id["index"]},
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color="yellow",
            leftIcon=DashIconify(
                icon="material-symbols:table-rows-narrow-rounded", color="white"
            ),
        ),
        # )
        html.Div(
            # html.Iframe(
            #     src="http://localhost:3000?config=http://localhost:9010/config.json&loc=chr1:1-248956422&assembly=hg38",
            #     width="100%",
            #     height="1000px",
            #     id={"type": "jbrowse", "index": id["index"]},
            # ),
            html.Div(id={"type": "jbrowse-body", "index": id["index"]}),
            id={"type": "test-container", "index": id["index"]},
        ),
    ]
    print(row)
    return row


def create_stepper_jbrowse_button(n, disabled=False):
    """
    Create the stepper interactive button

    Args:
        n (_type_): _description_

    Returns:
        _type_: _description_
    """

    button = dbc.Col(
        dmc.Button(
            "Genome browser",
            id={
                "type": "btn-option",
                "index": n,
                "value": "genome_browser",
            },
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color="yellow",
            leftIcon=DashIconify(
                icon="material-symbols:table-rows-narrow-rounded", color="white"
            ),
            disabled=disabled,
        )
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Genome browser",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
