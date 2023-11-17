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


# def register_callbacks_jbrowse_component(app):


def design_jbrowse(id):
    row = [
        html.Div(
            # html.Div("TOTO",  id={"type": "jbrowse", "index": id["index"]}),
            html.Iframe(src="http://localhost:5500/", width="100%", height="500px", id={"type": "jbrowse", "index": id["index"]}),
            # dash_jbrowse.LinearGenomeView(
            #     id={"type": "jbrowse", "index": id["index"]},
            #     assembly=my_assembly,
            #     tracks=my_tracks,
            #     # # defaultSession=my_default_session,
            #     location=my_location,
            #     # aggregateTextSearchAdapters=my_aggregate_text_search_adapters,
            #     # configuration=my_theme,
            # ),
            id={"type": "test-container", "index": id["index"]},
        )
    ]
    return row


def create_stepper_jbrowse_button(n):
    """
    Create the stepper interactive button

    Args:
        n (_type_): _description_

    Returns:
        _type_: _description_
    """

    button = dmc.Button(
        "Genome browser",
        id={
            "type": "btn-option",
            "index": n,
            "value": "genome_browser",
        },
        n_clicks=0,
        # style={
        #     "display": "inline-block",
        #     "width": "250px",
        #     "height": "100px",
        # },
        style=UNSELECTED_STYLE,
        size="xl",
        color="orange",
        leftIcon=DashIconify(
            icon="material-symbols:table-rows-narrow-rounded", color="white"
        ),
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
