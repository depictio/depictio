import dash
import dash_bootstrap_components as dbc
import dash_html_components as html
from dash.dependencies import Input, Output

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Define the second-level accordion with two dropdowns
second_level_accordion = dbc.Accordion(
    [
        dbc.AccordionItem(
            dbc.Accordion(
                [
                    dbc.AccordionItem(
                        [
                            dbc.Label("Select something"),
                            dbc.Select(
                                options=[
                                    {"label": "Option 1", "value": "1"},
                                    {"label": "Option 2", "value": "2"},
                                ]
                            ),
                        ],
                        title="Second-Level Accordion",
                    ),
                    dbc.AccordionItem(
                        [
                            dbc.Label("Select something else"),
                            dbc.Select(
                                options=[
                                    {"label": "Option A", "value": "A"},
                                    {"label": "Option B", "value": "B"},
                                ]
                            ),
                        ],
                        title="Second-Level Accordion",
                    ),
                ]
            ),
            title="Second-Level Accordion",
        ),
    ]
)

# Define the first-level collapse with the second-level accordion inside
first_level_collapse = dbc.Collapse(
    dbc.Card(
        dbc.CardBody(
            [
                html.H4("First-Level Collapse", className="card-title"),
                second_level_accordion,
            ]
        )
    ),
    id="first-level-collapse",
)

# Layout of the app
app.layout = html.Div(
    [
        dbc.Button(
            "Expand/Collapse First Level",
            id="first-level-collapse-button",
            className="mb-3",
        ),
        first_level_collapse,
    ]
)


# Callback to handle the first-level collapse
@app.callback(
    Output("first-level-collapse", "is_open"),
    [Input("first-level-collapse-button", "n_clicks")],
    [dash.dependencies.State("first-level-collapse", "is_open")],
)
def toggle_first_level_collapse(n_clicks, is_open):
    if n_clicks:
        return not is_open
    return is_open


if __name__ == "__main__":
    app.run_server(debug=True, port=5081)
