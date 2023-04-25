import dash
from dash.dependencies import Input, Output, State
import dash_core_components as dcc
import dash_html_components as html

import plotly.express as px
import pandas as pd

import dash_draggable

external_stylesheets = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]

app = dash.Dash(__name__, external_stylesheets=external_stylesheets, suppress_callback_exceptions=True)

df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv")


def create_initial_figure():
    filtered_df = df[df.year == df["year"].min()]

    fig = px.scatter(
        filtered_df,
        x="gdpPercap",
        y="lifeExp",
        size="pop",
        color="continent",
        hover_name="country",
        log_x=True,
        size_max=55,
    )

    fig.update_layout(transition_duration=500)

    return fig


app.layout = html.Div(
    [
        html.H1("Dash Draggable"),
        html.B("Description:"),
        html.Ul(
            [
                html.Li("The charts are draggable and resizeable."),
                html.Li("Click the 'Add Plot' button to add a new plot."),
            ]
        ),
        html.Button("Add Plot", id="add-plot-button", n_clicks=0),
        dash_draggable.ResponsiveGridLayout(
            id="draggable",
            clearSavedLayout=True,
            children=[
                # Remove the initial graph and slider, as they won't be needed
            ],
        ),
    ]
)


@app.callback(
    [Output("draggable", "children"), Output("draggable", "layouts")],
    Input("add-plot-button", "n_clicks"),
    State("draggable", "children"),
    State("draggable", "layouts"),
)
def add_new_plot(n_clicks, current_draggable_children, current_layouts):
    if n_clicks == 0:
        return [], {}

    new_plot_id = f"graph-{n_clicks}"

    new_plot = dcc.Graph(
        id=new_plot_id,
        figure=create_initial_figure(),
        responsive=True,
        style={
            "width": "100%",
            "height": "100%",
        },
    )

    new_draggable_child = html.Div(new_plot, id=f"draggable-{n_clicks}")

    current_draggable_children = current_draggable_children or []

    updated_draggable_children = current_draggable_children + [new_draggable_child]

    # Define the default size and position for the new plot
    new_layout_item = {"i": f"draggable-{n_clicks}", "x": 0, "y": n_clicks * 10, "w": 6, "h": 10}

    # Update the layouts property for both 'lg' and 'sm' sizes
    updated_layouts = {}
    for size in ["lg", "sm"]:
        if size not in current_layouts:
            current_layouts[size] = []
        updated_layouts[size] = current_layouts[size] + [new_layout_item]

    return updated_draggable_children, updated_layouts


if __name__ == "__main__":
    app.run_server(debug=True, port="5080")
