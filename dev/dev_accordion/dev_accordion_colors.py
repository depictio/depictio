import dash
import dash_bootstrap_components as dbc
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

accordion_items = []

for i in range(5):
    accordion_item = dbc.Card(
        [
            dbc.CardHeader(
                html.H5(
                    dbc.Button(
                        f"Accordion {i+1}",
                        id=f"group-{i}-toggle",
                        className="text-left",
                    ),
                    className="mb-0",
                ),
                id=f"card-header-{i}",
            ),
            dbc.Collapse(
                dbc.CardBody(
                    [
                        dbc.Input(
                            id=f"input-{i}", type="text", placeholder="Type something"
                        ),
                    ]
                ),
                id=f"collapse-{i}",
            ),
        ],
        id=f"card-{i}",
        className="mb-2",
    )
    accordion_items.append(accordion_item)

app.layout = html.Div(accordion_items)


for i in range(5):

    @app.callback(
        Output(f"collapse-{i}", "is_open"),
        [Input(f"group-{i}-toggle", "n_clicks")],
        [dash.dependencies.State(f"collapse-{i}", "is_open")],
    )
    def toggle_accordion(n, is_open):
        if n:
            return not is_open
        return is_open

    @app.callback(
        Output(f"card-header-{i}", "className"),
        [Input(f"input-{i}", "value")],
    )
    def change_accordion_color(value):
        base_class = "mb-0"
        if value:
            return f"{base_class} bg-success text-white"
        return base_class


if __name__ == "__main__":
    app.run_server(debug=True, port=8051)
