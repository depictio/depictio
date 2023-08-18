from dash import Dash, html, dcc, Input, Output, dash_table
from pathlib import Path
import datetime
import os, sys
import pandas as pd
import plotly.express as px
import scipy
import dash_bootstrap_components as dbc
import dash
import requests


from typing import List, Tuple, Optional
from pathlib import Path
import datetime

import pandas as pd
import plotly.express as px
from pydantic import BaseModel
import dash
from dash import Dash, html, dcc, Input, Output, dash_table
import dash_bootstrap_components as dbc


# app = dash.Dash(__name__)


# Start the app, use_pages allows to retrieve what's present in the pages/ folder in order
# app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP], use_pages=True)
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP])


# the style arguments for the sidebar. We use position:fixed and a fixed width
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "16rem",
    "padding": "2rem 1rem",
    "background-color": "#f8f9fa",
}

# the styles for the main content position it to the right of the sidebar and
# add some padding.
CONTENT_STYLE = {
    "margin-left": "18rem",
    "margin-right": "2rem",
    "padding": "2rem 1rem",
}


sidebar = html.Div(
    [
        # DROPDOWN,
        html.Hr(),
        html.P("Navigation", className="lead"),
        dbc.Nav(
            [
                dbc.NavLink("Dash home page", href="/", active="exact"),
                # dbc.NavLink("Grafana home page", href="http://localhost:3000", active="exact"),
            ],
            vertical=True,
            pills=True,
        ),
        html.Hr(),
    ],
    style=SIDEBAR_STYLE,
)

content = html.Div(id="page-content", style=CONTENT_STYLE)


@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page_content(pathname):
    if pathname == "/":
        return html.Div()
    return html.Div(
        [
            html.H1("404: Not found", className="text-danger"),
            html.Hr(),
            html.P(f"The pathname {pathname} was not recognised..."),
        ],
        className="p-3 bg-light rounded-3",
    )


@app.callback(Output("workflow-dropdown", "options"), [Input("interval-component", "n_intervals")])
def populate_dropdown(n_intervals):
    # Make a request to the API endpoint
    response = requests.get(f"http://seneca.embl.de:5501/workflows")
    response.raise_for_status()

    # Parse the response and create a list of options for the dropdown
    options = [{"label": workflow, "value": workflow} for workflow in response.json()]

    return options


@app.callback(Output("output", "children"), [Input("workflow-dropdown", "value")])
def display_output(workflow_name):
    if workflow_name:
        # Make a request to the API endpoint
        response = requests.get(f"http://seneca.embl.de:5501/runs/{workflow_name}")
        response.raise_for_status()

        runs = response.json().get(workflow_name, [])
        # print(runs)
        num_elements = len(runs)
        return f"Runs number {num_elements}"
    else:
        return ""


@app.callback(Output("output_card_runs", "children"), [Input("workflow-dropdown", "value")])
def display_output_card_runs(workflow_name):
    if workflow_name:
        # Make a request to the API endpoint
        response = requests.get(f"http://seneca.embl.de:5501/runs/{workflow_name}")
        response.raise_for_status()

        runs = response.json().get(workflow_name, [])
        num_elements = len(runs)
        return create_card(CardData(value=num_elements, text="Runs nb"))
    else:
        return ""


@app.callback(Output("output_card_multiqc_data_sources", "children"), [Input("workflow-dropdown", "value")])
def display_output_card_multiqc_data_sources(workflow_name):
    if workflow_name:
        # Make a request to the API endpoint
        response = requests.get(f"http://seneca.embl.de:5501/multiqc_data_sources/{workflow_name}")
        response.raise_for_status()

        sources_dict = response.json().get(workflow_name, [])
        # print(sources_dict)
        # for elem in sources_dict:
        #     for tools, functions in elem.items():
        #         print(tools, functions.keys())

        # print([sub_e for tools, functions in sources_dict.items() for sub_e in list(e.keys())])
        num_elements = len(set([sub_e for e in sources_dict for sub_e in list(e.keys())]))
        return create_card(CardData(value=num_elements, text="MultiQC sources nb"))
    else:
        return ""


# HEADER PART
def Header(title: str, subtitle: str) -> html.Div:
    title_div = html.H2(title, style={"margin-top": 0}, className="display-4")
    subtitle_div = html.H4(subtitle, style={"margin-top": 0})
    logo_embl = html.Img(src="https://upload.wikimedia.org/wikipedia/en/thumb/b/b1/EMBL_logo.svg/1200px-EMBL_logo.svg.png", width="200")
    logo_snakemake = html.Img(src=dash.get_asset_url("snake.png"), width="200")
    return dbc.Card(
        dbc.CardBody(
            [
                dbc.Row([dbc.Col(title_div, md=9), dbc.Col(logo_embl, md=3)]),
                html.Hr(),
                dbc.Row([dbc.Col(subtitle_div, md=9), dbc.Col(logo_snakemake, md=3)]),
            ]
        )
    )


@app.callback(Output("header", "children"), [Input("workflow-dropdown", "value")])
def display_workflow_name(workflow_name):
    if workflow_name:
        return Header("Workflow results dashboard", f"snakemake/{workflow_name}")
    else:
        return ""


class CardData(BaseModel):
    value: int
    text: str
    # color: str
    # inverse: bool
    # value_second: Optional[int] = None


# Define card data
# cards_data: List[CardData] = [
#     CardData(value=20, text="Runs number"),
#     CardData(value=1000, value_second=10000, text="Samples / Cells processed"),
#     CardData(value=1000, text="Average number of reads / cell"),
#     CardData(value=50, text="Average rate of duplicates / cell"),
# ]


# TO REGISTER THE PAGE INTO THE MAIN APP.PY
# app = dash.Dash(__name__)
# dash.register_page(__name__, path="/")


# Card components
def create_card(card_data: CardData) -> dbc.Card:
    title = "{value}".format(value=card_data.value)
    return dbc.Card(
        [
            html.H2(title, className="card-title"),
            html.P(card_data.text, className="card-text"),
        ],
        body=True,
        # color=card_data.color,
        # inverse=card_data.inverse,
    )


cards = [html.Div(id="output_card_runs"), html.Div(id="output_card_multiqc_data_sources")]

import pymongo

mongo_client = pymongo.MongoClient("mongodb://localhost:27018/")
mongo_db = mongo_client["depictioDB"]

workflow_name = "ashleys-qc-pipeline"
collection = mongo_db[workflow_name]
data_sources = collection.distinct("metadata.report_general_stats_headers", {"wf_name": workflow_name})

import pandas as pd

df = pd.DataFrame.from_records([d[key] | {"key": key} for d in data_sources for key in d])
data = df.groupby("namespace")["description"].unique().to_dict()


# Define the app callbacks
@app.callback(Output("child-dropdown", "options"), Input("parent-dropdown", "value"))
def update_child_dropdown(selected_category):
    print(selected_category)
    if selected_category is None:
        # Return an empty list if no category is selected
        return []
    else:
        # Return the options for the selected category
        print([{"label": value, "value": value} for cat in selected_category for value in data[cat]])
        return [{"label": f"{cat} - {value}", "value": value} for cat in selected_category for value in data[cat]]


@app.callback(Output("child-dropdown", "value"), Input("child-dropdown", "options"))
def update_child_dropdown_value(options):
    if options:
        # Return the first value in the options list
        return options[0]["value"]
    else:
        # Return an empty string if no options are available
        return ""


import dash_bio as dashbio


app.layout = html.Div(
    [
        html.Div(
            style={"display": "flex", "flex-direction": "column", "align-items": "center", "padding-top": "5px"},
            children=[
                html.Div(
                    style={"width": "50%"},
                    children=[
                        html.H4("Select a workflow", className="card-title"),
                        html.Br(),
                        dcc.Dropdown(id="workflow-dropdown", value=workflow_name, placeholder="Select a workflow...", clearable=False),
                    ],
                ),
                html.Div(id="output"),
                dcc.Interval(id="interval-component", interval=86400000, n_intervals=0),  # set to a high value to disable automatic refresh
            ],
        ),
        # html.Div([dcc.Location(id="url"), sidebar, content]),
        html.Div([dcc.Location(id="url"), content]),
        dash.page_container,
        dbc.Container(
            [
                html.Hr(),
                html.Div(id="header"),
                html.Br(),
                dbc.Row([dbc.Col(e) for e in cards]),
                html.H1("Nested Dropdown Example"),
                dbc.Row(
                    [
                        dbc.Col(
                            dcc.Dropdown(
                                id="parent-dropdown",
                                options=[{"label": key, "value": key} for key in data.keys()],
                                value=None,
                                multi=True,
                                placeholder="Select a category",
                            ),
                            width={"size": 4},
                        ),
                        dbc.Col(
                            dcc.Dropdown(
                                id="child-dropdown",
                                multi=True,
                                placeholder="Select a value",
                            ),
                            width={"size": 8},
                        ),
                    ],
                ),
                html.H1("Dash Bio Ideogram Example"),
                dashbio.Ideogram(
                    id="my-dashbio-ideogram",
                    # chromosomes=["13", "17"],
                    # assembly="GRCh37",
                    organism="human",
                    orientation="vertical",
                    # chrHeight=500,
                    # chrWidth=1500,
                    annotationsLayout="",
                    annotationHeight=3,
                    barWidth=3,
                    annotationsPath="https://eweitz.github.io/ideogram/data/annotations/1000_virtual_snvs.json",
                    annotationTracks=[
                        {
                            "id": "pathogenicTrack",
                            "displayName": "Pathogenic",
                            "color": "#F00",
                            "shape": "triangle",
                        },
                        {
                            "id": "uncertainSignificanceTrack",
                            "displayName": "Uncertain significance",
                            "color": "#CCC",
                            "shape": "triangle",
                        },
                        {
                            "id": "benignTrack",
                            "displayName": "Benign",
                            "color": "#8D4",
                            "shape": "triangle",
                        },
                    ],
                ),
            ]
        ),
    ]
)


if __name__ == "__main__":
    app.run_server(debug=True, host="seneca.embl.de", port=5000)
