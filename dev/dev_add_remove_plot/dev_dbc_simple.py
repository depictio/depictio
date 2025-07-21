import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State

app = dash.Dash(__name__)

app.layout = html.Div(
    [html.Button("Add Plot", id="add-plot-button"), html.Div(id="plot-container")]
)


@app.callback(
    Output("plot-container", "children"),
    Input("add-plot-button", "n_clicks"),
    Input({"type": "remove-plot", "index": "ALL"}, "n_clicks"),
    State("plot-container", "children"),
    prevent_initial_call=True,
)
def update_plot(add_clicks, remove_clicks, existing_children):
    if not existing_children:
        existing_children = list()
    ctx = dash.callback_context

    if not ctx.triggered:
        return dash.no_update

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id == "add-plot-button":
        new_plot = html.Div(
            [
                html.Button(
                    "Close",
                    id={"type": "remove-plot", "index": len(existing_children)},
                    n_clicks=0,
                ),
                dcc.Graph(
                    id={"type": "plot", "index": len(existing_children)},
                    figure={
                        "data": [
                            {
                                "x": [1, 2, 3],
                                "y": [4, 1, 2],
                                "type": "scatter",
                                "mode": "markers",
                            }
                        ],
                        "layout": {"title": f"Plot {len(existing_children) + 1}"},
                    },
                ),
            ],
            className="mb-3",
        )
        return existing_children + [new_plot]

    elif "remove-plot" in button_id:
        index = int(ctx.triggered[0]["prop_id"].split(".")[-1])
        return [child for i, child in enumerate(existing_children) if i != index]

    return existing_children


if __name__ == "__main__":
    app.run_server(debug=True)
