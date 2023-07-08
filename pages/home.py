import dash
from dash.dependencies import Input, Output, State
from dash import html, dcc
import dash_bootstrap_components as dbc
from pages.login.server import app, server

import plotly.express as px
import pandas as pd
import dash_draggable
from dash import dash_table
import time
import os, json
import json
import ast
import pandas
from flask_login import logout_user, current_user

@app.callback(Output("user-name", "children"), [Input("page-content", "children")])
def cur_user(input1):
    if current_user.is_authenticated:
        return html.Div("Current user: " + current_user.username)
        # 'User authenticated' return username in get_id()
    else:
        return ""


@app.callback(Output("logout", "children"), [Input("page-content", "children")])
def user_logout(input1):
    if current_user.is_authenticated:
        return html.A("Logout", href="/logout")
    else:
        return ""


header = html.Div(
    className="header",
    children=html.Div(
        className="container-width",
        style={"height": "100%"},
        children=[
            html.Img(src="assets/dash-logo-stripe.svg", className="logo"),
            html.Div(
                className="links",
                children=[
                    html.Div(id="user-name", className="link"),
                    html.Div(id="logout", className="link"),
                ],
            ),
        ],
    ),
)


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
        header,
        dcc.Location(id="url", refresh=False),
    ],
    fluid=False,
)
