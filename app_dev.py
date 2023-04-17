import dash
import dash_bootstrap_components as dbc
from dash import dcc
from dash import html
from dash.dependencies import Input, Output
import requests

# Define the URL of the API endpoint
API_URL = "http://seneca.embl.de:5501"

# Make a request to the API endpoint
# wf_response = requests.get(f"{API_URL}/workflows")
# wf_response.raise_for_status()

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

d = {"mosaicatcher-pipeline": ["A", "B"], "snakemake-dna-varlociraptor": ["C", "D"]}

# Define the layout of the app
app.layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.H4("Select a workflow", className="card-title"),
                                dcc.Dropdown(
                                    list(d.keys()),
                                    list(d.keys())[0],
                                    id="wf-dropdown",
                                    style={"fontSize": 12, "font-family": "sans-serif"},
                                    multi=False,
                                ),
                            ]
                        ),
                        color="light",
                        inverse=False,
                    ),
                    md=4,
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.H4("Runs number", className="card-title"),
                                html.P("", id="runs-number"),
                            ]
                        ),
                        color="light",
                        inverse=False,
                    ),
                    md=4,
                ),
            ]
        ),
    ]
)


@dash.callback(Output("wf-dropdown", "value"), Input("wf-dropdown", "options"))
def set_wf_options(value):
    return value


# # Define a callback function that populates the dropdown
# @app.callback(Output("workflow-dropdown", "options"))
# def populate_dropdown():
#     # Make a request to the API endpoint to get the list of available workflows
#     response = requests.get(f"{API_URL}/workflows")
#     response.raise_for_status()

#     # Parse the response and create a list of options for the dropdown

#     return response.json()


# Define a callback function that updates the "Runs number" card
@app.callback(Output("runs-number", "data"), [Input("wf-dropdown", "value")])
def update_runs_number(workflow_name):
    if not workflow_name:
        return ""

    # Make a request to the API endpoint to get the number of runs for the selected workflow
    # response = requests.get(f"{API_URL}/runs/{workflow_name}")
    # response.raise_for_status()
    # runs = response.json()[workflow_name]

    # return f"{len(runs)} runs"
    return len(d[workflow_name])


if __name__ == "__main__":
    app.run_server(debug=True, host="seneca.embl.de", port=5000)
