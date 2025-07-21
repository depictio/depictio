import json

import dash
from dash import html
from dash.dependencies import Input, Output, State

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.Button("Add Button", id={"type": "add-button", "index": 0}),
        html.Div(
            id="button-container",
            children=[],
        ),  # Set initial value as an empty list
        html.Div(id="output-container"),
    ]
)


@app.callback(
    Output("button-container", "children"),
    Input({"type": "add-button", "index": 0}, "n_clicks"),
    State("button-container", "children"),
)
def add_new_button(n_clicks, children):
    if n_clicks is None:
        raise dash.exceptions.PreventUpdate

    new_button_id = {"type": "dynamic-button", "index": n_clicks}
    new_button = html.Button(f"Button {n_clicks}", id=new_button_id)
    return children + [new_button]


@app.callback(
    Output("output-container", "children"),
    Input({"type": "dynamic-button", "index": dash.dependencies.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def display_button_clicks(button_clicks):
    ctx = dash.callback_context

    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate

    print(ctx.triggered[0])
    print(ctx.triggered[0]["prop_id"])
    button_props = json.loads(ctx.triggered[0]["prop_id"].split(".")[0])
    print(button_props)
    print("\n")
    button_index = button_props["index"]

    # Adjust the index for the button_clicks list
    adjusted_index = button_index - 1

    button_click_count = button_clicks[adjusted_index]

    if button_click_count is None:
        raise dash.exceptions.PreventUpdate

    return f"Button {button_index} clicked {button_click_count} times"


if __name__ == "__main__":
    app.run_server(debug=True)
