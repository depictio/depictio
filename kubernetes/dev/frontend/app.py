import dash
import dash_core_components as dcc
import dash_html_components as html
import requests

app = dash.Dash(__name__)

server = app.server

def fetch_backend_data():
    response = requests.get("http://backend.dummy-app")
    if response.status_code == 200:
        return response.json().get("message")
    return "Failed to fetch data"

app.layout = html.Div([
    html.H1("Hello from Plotly Dash frontend"),
    html.Div(id="backend-response", children=fetch_backend_data())
])

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=8050)
