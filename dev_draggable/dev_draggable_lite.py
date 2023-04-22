import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output
import dash_draggable
from dash.dependencies import Input, Output, State
import json
import os, sys
import numpy as np
import pandas as pd
import plotly.express as px


external_stylesheets = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]

app = dash.Dash(__name__, external_stylesheets=external_stylesheets)

df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
)


initial_layout = {
    "lg": [
        {"i": "scatter-plot", "x": 0, "y": 0, "w": 6, "h": 12},
    ]
}

if os.path.isfile("layout.json"):
    print("TOTO")
    with open("layout.json", "r") as f:
        initial_layout = json.load(f)

print(df)
app.layout = html.Div(
    [
        dcc.Interval(id="interval-component", interval=1e9, n_intervals=0),
        html.H1("Dash Draggable"),
        html.B("Description:"),
        html.Ul(
            [
                html.Li(
                    "The first chart is a line plot and it's not draggable or resizeable (with the value 'static' set to True in 'layout')."
                ),
                html.Li(
                    "The second chart is a bar plot and it's draggable and resizeable."
                ),
            ]
        ),
        dash_draggable.ResponsiveGridLayout(
            id="drag-1",
            clearSavedLayout=True,
            layouts=initial_layout,
            children=[
                dcc.Graph(id="scatter-plot", figure={}),
            ],
        ),
    ]
)


@app.callback(
    Output("scatter-plot", "figure"), Input("interval-component", "n_intervals")
)
def update_figure(interval):
    x = np.random.rand(100)
    y = np.random.rand(100)

    fig = px.scatter(x=x, y=y, title="Life expectancy over the years")

    return fig


if __name__ == "__main__":
    app.run_server(debug=True, port=8050)
