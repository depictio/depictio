import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output
import plotly.express as px
import pandas as pd
import dash_draggable
from dash.dependencies import Input, Output, State
import json
import os, sys

external_stylesheets = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]

app = dash.Dash(__name__, external_stylesheets=external_stylesheets)

df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
)


visualizations = {
    "Scatter plot": {
        "type": "scatter",
        "data": {"x": "year", "y": "lifeExp"},
        "layout": {"title": "Life expectancy over the years"},
    },
    "Bar chart": {
        "type": "bar",
        "data": {"x": "continent", "y": "pop"},
        "layout": {"title": "Population by Continent"},
    },
    "Line chart": {
        "type": "scatter",
        "data": {"x": "year", "y": "gdpPercap"},
        "layout": {"title": "GDP per capita over the years"},
    },
}


initial_layout = {
    "lg": [
        {"i": "line-plot", "x": 0, "y": 0, "w": 6, "h": 12, "static": True},
        {"i": "bar-plot", "x": 6, "y": 0, "w": 6, "h": 12},
    ]
}

if os.path.isfile("layout.json"):
    print("TOTO")
    with open("layout.json", "r") as f:
        initial_layout = json.load(f)

print(df)
app.layout = html.Div(
    [
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
                dcc.Graph(id="line-plot", figure={}),
                dcc.Graph(id="bar-plot", figure={}),
                dcc.Slider(
                    id="year-slider",
                    min=df["year"].min(),
                    max=df["year"].max(),
                    value=df["year"].min(),
                    marks={str(year): str(year) for year in df["year"].unique()},
                    step=None,
                ),
            ],
        ),
        dbc.Modal(
            [
                dbc.ModalHeader("Add Plot"),
                dbc.ModalBody(
                    [
                        dbc.ListGroup(
                            [
                                dbc.ListGroupItem(
                                    suggested_plot["title"],
                                    action=True,
                                    id={"type": "plot-selection", "index": i},
                                )
                                for i, suggested_plot in enumerate(visualizations)
                            ]
                        )
                    ]
                ),
                dbc.ModalFooter(
                    dbc.Button(
                        "Close",
                        id="close-modal-button",
                        className="ml-auto",
                        color="primary",
                    )
                ),
            ],
            id="add-plot-modal",
        ),
        html.Button("Save Layout", id="save-button", n_clicks=0),
        dcc.Store(id="layout-store"),
    ]
)


@app.callback(
    Output("layout-store", "data"),
    [Input("save-button", "n_clicks")],
    [State("drag-1", "layouts")],
)
def save_layout(n_clicks, layout):
    if n_clicks > 0:
        with open("layout.json", "w") as f:
            f.write(json.dumps(layout))
    return layout


@app.callback(Output("line-plot", "figure"), Input("year-slider", "value"))
def update_figure(selected_year):
    filtered_df = df[df.year == selected_year]
    fig = px.scatter(
        filtered_df, x="year", y="lifeExp", title="Life expectancy over the years"
    )
    fig.update_layout(transition_duration=500)
    return fig


@app.callback(Output("bar-plot", "figure"), Input("year-slider", "value"))
def update_bar(selected_year):
    filtered_df = df[df.year == selected_year]
    fig = px.bar(filtered_df, x="continent", y="pop", title="Population by Continent")
    fig.update_layout(transition_duration=500)
    return fig


if __name__ == "__main__":
    app.run_server(debug=True)
