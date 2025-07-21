import dash
import dash_bootstrap_components as dbc
import dash_core_components as dcc
import dash_html_components as html
import plotly.graph_objs as go
from dash.dependencies import Input, Output, State

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = html.Div(
    [
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Input(id="title-input", placeholder="Enter title..."),
                        dbc.Input(id="x-axis-label", placeholder="Enter x-axis label..."),
                        dbc.Input(id="y-axis-label", placeholder="Enter y-axis label..."),
                        html.Button("Save", id="save-button"),
                    ]
                ),
            ]
        ),
        dbc.Row([dbc.Col([dcc.Graph(id="scatter-plot", config={"displayModeBar": False})])]),
        dcc.Store(id="local-storage", storage_type="local"),
    ]
)


@app.callback(Output("scatter-plot", "figure"), Input("local-storage", "data"))
def update_scatter_plot(data):
    if not data:
        title = "Scatter Plot"
        x_label = "X"
        y_label = "Y"
    else:
        title = data["title"]
        x_label = data["x_label"]
        y_label = data["y_label"]

    figure = go.Figure(
        data=[go.Scatter(x=[1, 2, 3], y=[4, 1, 2], mode="markers")],
        layout=go.Layout(
            title=title,
            xaxis=dict(title=x_label),
            yaxis=dict(title=y_label),
        ),
    )

    return figure


@app.callback(
    Output("local-storage", "data"),
    Input("save-button", "n_clicks"),
    State("title-input", "value"),
    State("x-axis-label", "value"),
    State("y-axis-label", "value"),
    prevent_initial_call=True,
)
def save_to_local_storage(n_clicks, title, x_label, y_label):
    return {
        "title": title or "Scatter Plot",
        "x_label": x_label or "X",
        "y_label": y_label or "Y",
    }


if __name__ == "__main__":
    app.run_server(debug=True)
