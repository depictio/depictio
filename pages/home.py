import dash
from dash.dependencies import Input, Output, State
from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd
import dash_draggable
from dash import dash_table
import time
import os, json
import json
import ast
import pandas


# TO REGISTER THE PAGE INTO THE MAIN APP.PY
# app = dash.Dash(__name__)
dash.register_page(__name__, path="/")

layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.H1(
                            [
                                html.I(
                                    className="material-icons mr-2",
                                    children="insert_chart_outlined",
                                    style={"margin-left": "10px", "font-size": "32px"},
                                ),
                                "Depictio",
                            ],
                            className="text-center mb-4",
                            style={
                                "font-family": "Roboto Slab, serif",
                                "font-weight": "700",
                                "font-size": "48px",
                            },
                        ),
                        html.Hr(),
                    ]
                ),
            ]
        ),
    ],
    fluid=False,
)
