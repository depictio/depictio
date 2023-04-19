import dash
import dash_html_components as html
import dash_core_components as dcc
import dash_draggable
import dash_responsive_grid_layout as drg
import plotly.graph_objs as go
import plotly.express as px
import uuid
from dash.dependencies import Input, Output, State


app = dash.Dash(__name__)

app.layout = html.Div(
    [
        dash_draggable.ResponsiveGridLayout(
            id="plot-container",
            className="layout",
            # layouts=initial_layout,
            # breakpoints={
            #     "lg": 1200,
            #     "md": 996,
            #     "sm": 768,
            #     "xs": 480,
            #     "xxs": 0,
            # },
            # cols={
            #     "lg": 12,
            #     "md": 10,
            #     "sm": 6,
            #     "xs": 4,
            #     "xxs": 2,
            # },
            # rowHeight=30,
            isDraggable=True,
            isResizable=True,
            useCSSTransforms=True,
            verticalCompact=False,
        ),
        html.Button("Add Plot", id="add-plot-button"),
        drg.ResponsiveGridLayout(
            id="layout-store",
            cols={i: 4 for i in range(12)},
            isResizable=True,
            isDraggable=True,
            autoSize=True,
            children=[],
            layouts={},
        ),
    ]
)


def add_plot(existing_children):
    # Generate random data
    x = [1, 2, 3]
    y = [4, 1, 2]

    # Create the scatter plot
    fig = go.Figure(data=go.Scatter(x=x, y=y, mode="markers"))

    new_child = dcc.Graph(
        id=str(uuid.uuid4()),
        figure=fig,
        style={"height": "100%", "width": "100%"},
        config={"staticPlot": False, "editable": True},
    )
    existing_children.append(new_child)
    new_item = {
        "i": str(len(existing_children) - 1),
        "x": 0,
        "y": float("inf"),
        "w": 10,
        "h": 10,
        "isResizable": True,
        "isDraggable": True,
    }
    return existing_children, new_item


@app.callback(
    [
        Output("plot-container", "children"),
        Output("layout-store", "layouts"),
    ],
    [
        Input("add-plot-button", "n_clicks"),
    ],
    [
        State("plot-container", "children"),
        State("layout-store", "layouts"),
    ],
)
def add_new_plot(n_clicks, existing_children, existing_layouts):
    if not existing_children:
        existing_children = []
    if not existing_layouts:
        existing_layouts = {"lg": []}
    new_children, new_item = add_plot(existing_children)
    existing_layouts["lg"].append(new_item)
    return new_children, existing_layouts


if __name__ == "__main__":
    app.run_server(debug=True)
