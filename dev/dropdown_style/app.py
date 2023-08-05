import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Create a button to reset the dropdowns
reset_button = dbc.Button("Reset", id="reset-button", className="mb-4")

# Create two dropdowns
dropdown1 = dbc.Accordion(
    dbc.AccordionItem(
        dcc.Dropdown(
            id="dropdown-1",
            options=[{"label": f"Option {i}", "value": i} for i in range(10)],
        ),
        title="TEST",
        id="accordionitem-1",
    ),
    start_collapsed=True,
    id="accordion-1",
)

dropdown2 = dbc.Accordion(
    dbc.AccordionItem(
        dcc.Dropdown(
            id="dropdown-2",
            options=[{"label": f"Option {i}", "value": i} for i in range(10)],
        ),
        title="TEST2",
        id="accordionitem-2",
    ),
    start_collapsed=True,
    id="accordion-2",
)

# Combine the button and the dropdowns in the app layout
app.layout = html.Div([reset_button, dropdown1, dropdown2])


# Callback to update the dropdown color when a selection is made
@app.callback(
    [
        Output("dropdown-1", "style"),
        Output("dropdown-2", "style"),
        Output("accordionitem-1", "style"),
        Output("accordionitem-2", "style"),
        Output("accordion-1", "style"),
        Output("accordion-2", "style"),
    ],
    [Input("dropdown-1", "value"), Input("dropdown-2", "value")],
    [State("dropdown-1", "style"), State("dropdown-2", "style")],
    prevent_initial_call=True,
)
def update_dropdown_style(value1, value2, style1, style2):
    style1 = {"backgroundColor": "red"} if value1 is not None else {}
    style2 = {"backgroundColor": "red"} if value2 is not None else {}
    return style1, style2, style1, style2, style1, style2


# Callback to reset the dropdowns when the button is clicked
@app.callback(
    [Output("dropdown-1", "value"), Output("dropdown-2", "value")],
    Input("reset-button", "n_clicks"),
    prevent_initial_call=True,
)
def reset_dropdowns(n_clicks):
    return None, None  # Set both dropdown values to None


if __name__ == "__main__":
    app.run_server(debug=True)
