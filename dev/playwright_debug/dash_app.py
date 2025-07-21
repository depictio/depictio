import os

import dash
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
from dash import Input, Output, callback, dcc, html
from dash.exceptions import PreventUpdate

# Create sample data for scatter plot
df = px.data.iris()

# Initialize Dash app
app = dash.Dash(__name__)

# Define the layout
app.layout = html.Div(
    [
        html.H1("Dash Debug App", style={"textAlign": "center", "marginBottom": 30}),
        html.Div(
            [
                dcc.Graph(
                    id="scatter-plot",
                    figure=px.scatter(
                        df,
                        x="sepal_width",
                        y="sepal_length",
                        color="species",
                        size="petal_length",
                        title="Iris Dataset Scatter Plot",
                    ),
                )
            ],
            style={"marginBottom": 30},
        ),
        html.Div(
            [
                html.Button(
                    "Take Screenshot",
                    id="screenshot-btn",
                    n_clicks=0,
                    style={
                        "fontSize": 16,
                        "padding": "10px 20px",
                        "backgroundColor": "#007bff",
                        "color": "white",
                        "border": "none",
                        "borderRadius": "5px",
                        "cursor": "pointer",
                    },
                ),
                html.Div(id="screenshot-status", style={"marginTop": 20}),
            ],
            style={"textAlign": "center"},
        ),
    ],
    style={"padding": 20},
)


# Callback for screenshot button
@callback(
    Output("screenshot-status", "children"),
    Input("screenshot-btn", "n_clicks"),
    prevent_initial_call=True,
)
def take_screenshot(n_clicks):
    if n_clicks is None or n_clicks == 0:
        raise PreventUpdate

    try:
        # Make API call to FastAPI screenshot endpoint
        response = requests.get("http://localhost:8888/screenshot", timeout=30)

        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                return html.Div(
                    [
                        html.P("✅ Screenshot taken successfully!", style={"color": "green"}),
                        html.P(f"Saved to: {data.get('screenshot_path', 'Unknown path')}"),
                    ]
                )
            else:
                return html.Div(
                    [
                        html.P("❌ Screenshot failed", style={"color": "red"}),
                        html.P(f"Error: {data.get('error', 'Unknown error')}"),
                    ]
                )
        else:
            return html.Div(
                [
                    html.P("❌ API call failed", style={"color": "red"}),
                    html.P(f"Status code: {response.status_code}"),
                ]
            )

    except requests.exceptions.RequestException as e:
        return html.Div(
            [html.P("❌ Connection error", style={"color": "red"}), html.P(f"Error: {str(e)}")]
        )


if __name__ == "__main__":
    # Check if running in development mode
    dev_mode = os.environ.get("DEV_MODE", "false").lower() == "true"

    if dev_mode:
        # Development mode - direct run
        app.run_server(debug=True, host="0.0.0.0", port=7777)
    else:
        # Production mode - will be run by gunicorn
        # Create WSGI server for gunicorn
        server = app.server
