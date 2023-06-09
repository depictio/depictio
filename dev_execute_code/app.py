import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        dcc.Input(
            id="input",
            type="text",
            value="",
            placeholder="Enter Python code...",
            style={"width": "100%", "height": "200px"},
        ),
        html.Button("Update Layout", id="update-button", n_clicks=0),
        html.Div(id="output"),
    ]
)


@app.callback(
    Output("output", "children"),
    [Input("update-button", "n_clicks")],
    [dash.dependencies.State("input", "value")],
)
def update_output(n_clicks, value):
    if n_clicks > 0:
        try:
            return exec(value)
        except:
            return str(value)

    return ""


if __name__ == "__main__":
    app.run_server(debug=True, port=9050)
