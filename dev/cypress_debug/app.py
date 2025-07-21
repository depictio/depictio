import dash
from dash import dcc, html

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.H1("Minimal Dash App"),
        dcc.Location(id="url"),
        html.Div(id="content", children="Working!"),
    ]
)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5080, debug=True)
