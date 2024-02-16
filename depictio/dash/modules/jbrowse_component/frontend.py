# Import necessary libraries
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import pandas as pd
from dash_iconify import DashIconify


import dash_jbrowse


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
        Output({"type": "jbrowse_body", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-jbrowse", "index": MATCH}, "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def update_jbrowse(wf_id, dc_id, n_clicks):
        iframe = html.Iframe(
            src="http://localhost:3000?config=http://localhost:9010/config.json&loc=chr1:1-248956422&assembly=hg38",
            width="100%",
            height="1000px",
        )
        store_component = dcc.Store(
            id={"type": "store-jbrowse", "index": 0},
            data={},
            storage_type="memory",
        )
        return [iframe, store_component]


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
            html.Div(id={"type": "jbrowse_body", "index": id["index"]}),
            id={"type": "test-container", "index": id["index"]},
        ),
    ]
    print(row)
    return row


def create_stepper_jbrowse_button(n):
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
