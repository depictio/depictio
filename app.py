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

# Define the URL of the API endpoint
API_URL = "http://seneca.embl.de:5501"

# Make a request to the API endpoint
wf_response = requests.get(f"{API_URL}/workflows")
wf_response.raise_for_status()
print(wf_response.json())

# Start the app, use_pages allows to retrieve what's present in the pages/ folder in order
# app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP], use_pages=True)
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP])
server = app.server


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
        html.H4("Select a workflow", className="card-title"),
        dcc.Dropdown(id="workflow-dropdown", options=wf_response.json(), value=wf_response.json()[0]),
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

# print([dcc.Link(f"{page['name']} - {page['path']}", href=page["relative_path"]) for page in dash.page_registry.values()])
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


# # Define a callback function that populates the dropdown
# @app.callback(Output("workflow-dropdown", "options"), [])
# def populate_dropdown():


#     return options


# Define a callback function that updates the "Runs number" card
@app.callback(Output("runs-number", "children"), [Input("workflow-dropdown", "value")])
def update_runs_number(workflow_name):
    if not workflow_name:
        return ""
    # Make a request to the API endpoint
    response = requests.get(f"{API_URL}/runs/{workflow_name}")
    response.raise_for_status()
    print(response.json())
    runs = response[f"{workflow_name}"]
    print(len(runs))
    return len(runs)


# SAMPLE DROPDOWN OPTIONS TO SAMPLE DROPDOWN VALUE
@app.callback(Output("workflow-dropdown", "value"), Input("workflow-dropdown", "options"))
def set_wf(value):
    return value


# {
#   "snakemake-dna-varlociraptor": [
#     "run-BX",
#     "run-BY"
#   ]
# }
# return runs_number


from typing import List, Tuple, Optional
from pathlib import Path
import datetime

import pandas as pd
import plotly.express as px
from pydantic import BaseModel
import dash
from dash import Dash, html, dcc, Input, Output, dash_table
import dash_bootstrap_components as dbc


class CardData(BaseModel):
    value: int
    text: str
    color: str
    inverse: bool
    value_second: Optional[int] = None


# Define card data
cards_data: List[CardData] = [
    CardData(value=20, text="Runs number", color="light", inverse=False),
    CardData(value=1000, value_second=10000, text="Samples / Cells processed", color="dark", inverse=True),
    CardData(value=1000, text="Average number of reads / cell", color="primary", inverse=True),
    CardData(value=50, text="Average rate of duplicates / cell", color="green", inverse=True),
]


# TO REGISTER THE PAGE INTO THE MAIN APP.PY
# app = dash.Dash(__name__)
# dash.register_page(__name__, path="/")

# HEADER PART
def Header(title: str, subtitle: str) -> html.Div:
    title_div = html.H2(title, style={"margin-top": 5}, className="display-4")
    subtitle_div = html.H4(subtitle, style={"margin-top": 5})
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


# Card components
def create_card(card_data: CardData) -> dbc.Card:
    if card_data.value_second is not None:
        title = "{value} / {value_second:,}".format(value=card_data.value, value_second=card_data.value_second)
    else:
        title = "{value}".format(value=card_data.value)
    return dbc.Card(
        [
            html.H2(title, className="card-title"),
            html.P(card_data.text, className="card-text"),
        ],
        body=True,
        color=card_data.color,
        inverse=card_data.inverse,
    )


cards: List[dbc.Card] = [create_card(card_data) for card_data in cards_data]


# MAIN LAYOUT OF THE DASH APP
# layout =


app.layout = html.Div(
    [
        html.Div([dcc.Location(id="url"), sidebar, content]),
        dash.page_container,
        dbc.Container(
            [
                # HEADER
                # Header("Workflow results dashboard", "snakemake/ashleys-qc-pipeline v1.4.1"),
                Header("Workflow results dashboard", ""),
                html.Hr(),
                # CARDS ROW
                dbc.Row([dbc.Col(card) for card in cards]),
                html.Br(),
            ],
            fluid=False,
        ),
    ]
)


if __name__ == "__main__":
    app.run_server(debug=True, host="seneca.embl.de", port=5000, dev_tools_hot_reload=False)
