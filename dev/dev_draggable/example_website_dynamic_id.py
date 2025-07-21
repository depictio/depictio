import dash
import dash_draggable
import pandas as pd
import plotly.express as px
from dash import dcc, html
from dash.dependencies import Input, Output, State

external_stylesheets = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]

app = dash.Dash(
    __name__,
    external_stylesheets=external_stylesheets,
    # suppress_callback_exceptions=True,
)

df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
)

# print(df.head())


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
        dcc.Store(id="stored-children", storage_type="local"),
        dcc.Store(id="stored-layout", storage_type="local"),
        dash_draggable.ResponsiveGridLayout(
            id="draggable",
            clearSavedLayout=True,
            children=[
                # Remove the initial graph and slider, as they won't be needed
            ],
        ),
    ]
)


# @app.callback(
#     [Output("draggable", "children"), Output("draggable", "layouts")],
#     Input("add-plot-button", "n_clicks"),
#     State("draggable", "children"),
#     State("draggable", "layouts"),
#     # State("stored-layout", "data"),
# )
# def add_new_plot(
#     n_clicks, current_draggable_children, current_layouts, stored_layout_data
# ):
#     # if n_clicks == 0:
#     #     return [], stored_layout_data if stored_layout_data else {}

#     new_plot_id = f"graph-{n_clicks}"

#     new_plot = dcc.Graph(
#         id=new_plot_id,
#         figure=create_initial_figure(),
#         responsive=True,
#         style={
#             "width": "100%",
#             "height": "100%",
#         },
#     )

#     new_draggable_child = html.Div(new_plot, id=f"draggable-{n_clicks}")

#     current_draggable_children = current_draggable_children or []

#     updated_draggable_children = current_draggable_children + [new_draggable_child]

#     # Define the default size and position for the new plot
#     new_layout_item = {
#         "i": f"draggable-{n_clicks}",
#         "x": 0,
#         "y": n_clicks * 10,
#         "w": 6,
#         "h": 10,
#     }

#     # Update the layouts property for both 'lg' and 'sm' sizes
#     updated_layouts = {}
#     for size in ["lg", "sm"]:
#         if size not in current_layouts:
#             current_layouts[size] = []
#         updated_layouts[size] = current_layouts[size] + [new_layout_item]

#     return updated_draggable_children, updated_layouts


@app.callback(
    [
        Output("draggable", "children"),
        Output("draggable", "layouts"),
        Output("stored-layout", "data"),
        Output("stored-children", "data"),
    ],
    [
        Input("add-plot-button", "n_clicks"),
        Input("stored-layout", "data"),
        Input("stored-children", "data"),
        Input("draggable", "layouts"),
    ],
    [
        State("draggable", "children"),
        State("draggable", "layouts"),
        State("stored-layout", "data"),
        State("stored-children", "data"),
    ],
)
def update_draggable(
    n_clicks,
    stored_layout_data,
    stored_children_data,
    new_layouts,
    current_draggable_children,
    current_layouts,
    stored_layout,
    stored_children,
):
    ctx = dash.callback_context
    triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]

    if triggered_input == "add-plot-button":
        if n_clicks == 0:
            return [], {}, stored_layout, stored_children

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

        new_layout_item = {
            "i": f"draggable-{n_clicks}",
            "x": 0,
            "y": n_clicks * 10,
            "w": 6,
            "h": 10,
        }

        updated_layouts = {}
        for size in ["lg", "sm"]:
            if size not in current_layouts:
                current_layouts[size] = []
            updated_layouts[size] = current_layouts[size] + [new_layout_item]

        return (
            updated_draggable_children,
            updated_layouts,
            updated_layouts,
            updated_draggable_children,
        )

    elif triggered_input == "stored-layout" or triggered_input == "stored-children":
        if stored_layout_data and stored_children_data:
            return (
                stored_children_data,
                stored_layout_data,
                stored_layout_data,
                stored_children_data,
            )
        else:
            return current_draggable_children, {}, stored_layout, stored_children

    elif triggered_input == "draggable":
        return (
            current_draggable_children,
            new_layouts,
            new_layouts,
            current_draggable_children,
        )

    else:
        raise dash.exceptions.PreventUpdate


if __name__ == "__main__":
    app.run_server(debug=True, port="8050")
