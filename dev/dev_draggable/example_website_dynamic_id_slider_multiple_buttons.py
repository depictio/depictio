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
    suppress_callback_exceptions=True,
)

df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
)

AVAILABLE_PLOT_TYPES = {
    "scatter-plot": {
        "function": px.scatter,
        "kwargs": {
            "x": "gdpPercap",
            "y": "lifeExp",
            "size": "pop",
            "color": "continent",
            "hover_name": "country",
            "log_x": True,
            "size_max": 55,
        },
    },
    "bar-plot": {
        "function": px.bar,
        "kwargs": {
            "x": "year",
            "y": "gdpPercap",
            "color": "continent",
            "hover_name": "country",
        },
    },
    "line-plot": {
        "function": px.line,
        "kwargs": {
            "x": "year",
            "y": "gdpPercap",
            "color": "continent",
            "hover_name": "country",
        },
    },
}


def create_initial_figure(selected_year, plot_type):
    filtered_df = df[df.year == selected_year]

    fig = AVAILABLE_PLOT_TYPES[plot_type]["function"](
        filtered_df, **AVAILABLE_PLOT_TYPES[plot_type]["kwargs"]
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
        html.Div(
            [
                # Add a button for each available plot type
                html.Button(
                    f"Add {plot_type}",
                    id=f"add-plot-button-{plot_type.lower().replace(' ', '-')}",
                    n_clicks=0,
                )
                for plot_type in AVAILABLE_PLOT_TYPES.keys()
            ],
            style={"display": "inline-block"},
        ),
        dcc.Store(id="stored-figures", data={}, storage_type="local"),
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
    [
        Output("draggable", "children"),
        Output("draggable", "layouts"),
        Output("stored-figures", "data"),
    ],
    [
        Input(f"add-plot-button-{plot_type.lower().replace(' ', '-')}", "n_clicks")
        for plot_type in AVAILABLE_PLOT_TYPES.keys()
    ]
    + [Input("year-slider", "value")],
    [
        State("draggable", "children"),
        State("draggable", "layouts"),
        State("stored-figures", "data"),
    ],
)
def update_draggable_children(
    # n_clicks, selected_year, current_draggable_children, current_layouts, stored_figures
    *args,
):
    ctx = dash.callback_context
    triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
    print(triggered_input)
    stored_figures = args[-1]
    current_layouts = args[-2]
    current_draggable_children = args[-3]
    selected_year = args[-4]
    print(selected_year)

    # print(current_draggable_children)
    print(current_layouts)
    # if current_draggable_children is None:
    #     current_draggable_children = []
    # if current_layouts is None:
    #     current_layouts = dict()

    if triggered_input.startswith("add-plot-button-"):
        print(triggered_input)
        plot_type = triggered_input.replace("add-plot-button-", "")
        print(plot_type)
        print(ctx.triggered)

        n_clicks = ctx.triggered[0]["value"]

        new_plot_id = f"graph-{n_clicks}-{plot_type.lower().replace(' ', '-')}"
        print(new_plot_id)
        new_plot_type = plot_type

        new_plot = dcc.Graph(
            id=new_plot_id,
            figure=create_initial_figure(selected_year, new_plot_type),
            responsive=True,
            style={
                "width": "100%",
                "height": "100%",
            },
        )
        # print(new_plot)

        new_draggable_child = html.Div(new_plot, id=f"draggable-{new_plot_id}")

        # current_draggable_children = current_draggable_children or []

        updated_draggable_children = current_draggable_children + [new_draggable_child]
        print(len(updated_draggable_children))
        print((len(updated_draggable_children) + 1) % 2)

        # Define the default size and position for the new plot
        new_layout_item = {
            "i": f"draggable-{new_plot_id}",
            "x": 10 * ((len(updated_draggable_children) + 1) % 2),
            "y": n_clicks * 10,
            "w": 6,
            "h": 12,
        }

        # Update the layouts property for both 'lg' and 'sm' sizes
        updated_layouts = {}
        for size in ["lg", "sm"]:
            if size not in current_layouts:
                current_layouts[size] = []
            updated_layouts[size] = current_layouts[size] + [new_layout_item]

        # Store the newly created figure in stored_figures
        stored_figures[new_plot_id] = new_plot

        return updated_draggable_children, updated_layouts, stored_figures

    elif triggered_input == "year-slider":
        updated_draggable_children = []

        for child in current_draggable_children:
            print(child["props"]["children"])
            try:
                graph = child["props"]["children"]

                # Extract the figure type and its corresponding function
                figure_type = "-".join(graph["props"]["id"].split("-")[2:])

                graph_id = graph["props"]["id"]
                updated_fig = create_initial_figure(selected_year, figure_type)
                stored_figures[graph_id] = updated_fig
                graph["props"]["figure"] = stored_figures[graph_id]
                updated_child = html.Div(graph, id=child.id)
                updated_draggable_children.append(updated_child)
            except:
                # If any exception occurs, just append the current child without modifications
                updated_draggable_children.append(child)

        return updated_draggable_children, current_layouts, stored_figures

    # Add an else condition to return the current layout when there's no triggering input
    else:
        return current_draggable_children, current_layouts, stored_figures

    # Remove the initial call prevention from the clientside_callback
    app.clientside_callback(
        "dash_draggable.update_layout",
        Output("draggable", "layouts"),
        [
            Input(f"add-plot-button-{plot_type.lower().replace(' ', '-')}", "n_clicks")
            for plot_type in AVAILABLE_PLOT_TYPES.keys()
        ],
    )


if __name__ == "__main__":
    app.run_server(debug=True, port="8052")
