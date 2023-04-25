import dash
from dash.dependencies import Input, Output, State
from dash import html, dcc


import plotly.express as px
import pandas as pd

import dash_draggable

external_stylesheets = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]

app = dash.Dash(__name__, external_stylesheets=external_stylesheets, suppress_callback_exceptions=True)

df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv")


def create_initial_figure(selected_year):
    filtered_df = df[df.year == selected_year]

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
        dcc.Slider(
            id="year-slider",
            min=df["year"].min(),
            max=df["year"].max(),
            value=df["year"].min(),
            marks={str(year): str(year) for year in df["year"].unique()},
            step=None,
        ),
        html.Button("Add Plot", id="add-plot-button", n_clicks=0),
        dash_draggable.ResponsiveGridLayout(
            id="draggable",
            clearSavedLayout=True,
            layouts=dict(),
            children=[
                # Remove the initial graph and slider, as they won't be needed
            ],
        ),
    ]
)


@app.callback(
    [Output("draggable", "children"), Output("draggable", "layouts")],
    [Input("add-plot-button", "n_clicks"), Input("year-slider", "value")],
    [State("draggable", "children"), State("draggable", "layouts")],
)
def update_draggable_children(n_clicks, selected_year, current_draggable_children, current_layouts):
    ctx = dash.callback_context
    triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
    print(triggered_input)

    # print(current_draggable_children)
    print(current_layouts)
    # if current_draggable_children is None:
    #     current_draggable_children = []
    # if current_layouts is None:
    #     current_layouts = dict()

    if triggered_input == "add-plot-button":
        if n_clicks == 0:
            return [], {}

        new_plot_id = f"graph-{n_clicks}"

        new_plot = dcc.Graph(
            id=new_plot_id,
            figure=create_initial_figure(selected_year),
            responsive=True,
            style={
                "width": "100%",
                "height": "100%",
            },
        )

        new_draggable_child = html.Div(new_plot, id=f"draggable-{n_clicks}")

        # current_draggable_children = current_draggable_children or []

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

    elif triggered_input == "year-slider":
        updated_draggable_children = []
        from pprint import pprint

        # pprint(current_draggable_children)

        for child in current_draggable_children:
            # print(child)
            print(child.keys())
            print(child["props"]["children"])

            try:
                graph = child["props"]["children"]

                graph_id = graph["props"]["id"]
                print(graph_id)
                graph["props"]["figure"] = create_initial_figure(selected_year)
                updated_child = html.Div(graph, id=child.id)
                updated_draggable_children.append(updated_child)
            except:
                # If any exception occurs, just append the current child without modifications
                updated_draggable_children.append(child)

        # Return the current_layouts when the slider is updated, so that the layout information is retained
        return updated_draggable_children, current_layouts

    # Add an else condition to return the current layout when there's no triggering input
    else:
        return current_draggable_children, current_layouts

    # Remove the initial call prevention from the clientside_callback
    app.clientside_callback(
        "dash_draggable.update_layout",
        Output("draggable", "layouts"),
        Input("add-plot-button", "n_clicks"),
    )


if __name__ == "__main__":
    app.run_server(debug=True, port="5080")
