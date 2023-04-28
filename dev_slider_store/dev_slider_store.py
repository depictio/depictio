import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.H3("Slider Value:"),
        dcc.Slider(
            id="example-slider",
            min=0,
            max=10,
            step=1,
            value=5,
        ),
        html.Div(id="slider-output"),
        dcc.Store(id="slider-value-store", storage_type="session"),
        dcc.Interval(
            id="save-slider-value-interval",
            interval=500,  # Save slider value every 1 second
            n_intervals=0,
        ),
    ]
)


@app.callback(
    Output("slider-output", "children"),
    Input("example-slider", "value"),
)
def update_output(value):
    return f"Current slider value: {value}"


@app.callback(
    Output("slider-value-store", "data"),
    Input("save-slider-value-interval", "n_intervals"),
    State("example-slider", "value"),
)
def save_slider_value(n_intervals, value):
    if n_intervals == 0:
        raise dash.exceptions.PreventUpdate
    return value


@app.callback(
    Output("example-slider", "value"),
    Input("slider-value-store", "data"),
)
def update_slider_value(data):
    if data is None:
        raise dash.exceptions.PreventUpdate
    return data


if __name__ == "__main__":
    app.run_server(debug=True)
