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
dash.register_page(__name__, path="/")

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
layout = dbc.Container(
    [
        # HEADER
        Header("Workflow results dashboard", "snakemake/ashleys-qc-pipeline v1.4.1"),
        html.Hr(),
        # CARDS ROW
        dbc.Row([dbc.Col(card) for card in cards]),
        html.Br(),
    ],
    # fluid=False,
)
