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
                html.Li("The second chart is a bar plot and it's draggable and resizeable."),
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
        # html.Button("Save Layout", id="save-button", n_clicks=0),
        # dcc.Store(id="layout-store"),
    ]
)


# Define the callback
@app.callback(Output("scatter-plot", "figure"), Input("interval-component", "n_intervals"))
def update_figure(interval):
    # Generate random data
    x = np.random.rand(100)
    y = np.random.rand(100)

    # Create the scatter plot
    fig = px.scatter(x=x, y=y, title="Life expectancy over the years")

    return fig


# @app.callback(
#     Output("layout-store", "data"),
#     [Input("save-button", "n_clicks")],
#     [State("drag-1", "layouts")],
# )
# def save_layout(n_clicks, layout):
#     if n_clicks > 0:
#         with open("layout.json", "w") as f:
#             f.write(json.dumps(layout))
#     return layout


# @app.callback(Output("line-plot", "figure"))
# def update_figure():
#     selected_year = 2000  # Default value
#     filtered_df = df[df.year == selected_year]
#     fig = px.scatter(
#         filtered_df, x="year", y="lifeExp", title="Life expectancy over the years"
#     )
#     fig.update_layout(transition_duration=500)
#     return fig


# @app.callback(Output("bar-plot", "figure"))
# def update_bar():
#     selected_year = 2000  # Default value
#     filtered_df = df[df.year == selected_year]
#     fig = px.bar(filtered_df, x="continent", y="pop", title="Population by Continent")
#     fig.update_layout(transition_duration=500)
#     return fig


# @app.callback(Output("line-plot", "figure"), Input("year-slider", "value"))
# def update_figure(selected_year):
#     filtered_df = df[df.year == selected_year]
#     fig = px.scatter(
#         filtered_df, x="year", y="lifeExp", title="Life expectancy over the years"
#     )
#     fig.update_layout(transition_duration=500)
#     return fig


# @app.callback(Output("bar-plot", "figure"), Input("year-slider", "value"))
# def update_bar(selected_year):
#     filtered_df = df[df.year == selected_year]
#     fig = px.bar(filtered_df, x="continent", y="pop", title="Population by Continent")
#     fig.update_layout(transition_duration=500)
#     return fig


if __name__ == "__main__":
    app.run_server(debug=True, port=8051)
