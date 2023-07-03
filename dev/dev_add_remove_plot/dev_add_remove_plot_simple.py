import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.Button("Add Plot", id="add-plot-button"),
        html.Button("Remove Plot", id="remove-plot-button"),
        html.Div(id="plot-container"),
    ]
)


@app.callback(
    Output("plot-container", "children"),
    [
        Input("add-plot-button", "n_clicks"),
        Input("remove-plot-button", "n_clicks"),
    ],
    State("plot-container", "children"),
    prevent_initial_call=True,
)
def update_plot(add_clicks, remove_clicks, existing_children):
    ctx = dash.callback_context

    if not ctx.triggered:
        return existing_children

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id == "add-plot-button" and existing_children is None:
        return dcc.Graph(
            id="example-plot",
            figure={
                "data": [
                    {
                        "x": [1, 2, 3],
                        "y": [4, 1, 2],
                        "type": "scatter",
                        "mode": "markers",
                    }
                ],
                "layout": {"title": "Sample Plot"},
            },
        )
    elif button_id == "remove-plot-button":
        return None

    return existing_children


if __name__ == "__main__":
    app.run_server(debug=True)
