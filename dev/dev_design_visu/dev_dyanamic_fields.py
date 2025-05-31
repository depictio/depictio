import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output
import plotly.express as px
import inspect

# Define the available visualizations
plotly_vizu_list = [px.scatter, px.line, px.bar, px.histogram, px.box]

common_params = set.intersection(
    *[set(inspect.signature(func).parameters.keys()) for func in plotly_vizu_list]
)
common_param_names = [p for p in list(common_params)]
common_param_names.sort(
    key=lambda x: list(inspect.signature(plotly_vizu_list[0]).parameters).index(x)
)

specific_params = {}

for vizu_func in plotly_vizu_list:
    func_params = inspect.signature(vizu_func).parameters
    param_names = list(func_params.keys())

    common_params_tmp = (
        common_params.intersection(func_params.keys()) if common_params else set(func_params.keys())
    )

    specific_params[vizu_func.__name__] = [p for p in param_names if p not in common_params_tmp]

print(specific_params)

# Define the app layout
app = dash.Dash(__name__)
app.layout = html.Div(
    [
        dcc.Dropdown(
            id="visualization-type",
            options=[{"label": func.__name__, "value": func.__name__} for func in plotly_vizu_list],
            value=plotly_vizu_list[0].__name__,
        ),
        html.Div(id="specific-params-container"),
    ]
)


# Define the callback to update the specific parameters dropdowns
@app.callback(
    Output("specific-params-container", "children"),
    Input("visualization-type", "value"),
)
def update_specific_params(value):
    if value is not None:
        specific_params_options = [
            {"label": param_name, "value": param_name} for param_name in specific_params[value]
        ]
        specific_params_dropdowns = [
            html.Div(
                [
                    html.H4(param_name.replace("_", " ").title()),
                    dcc.Dropdown(
                        id=f"{value}-{param_name}",
                        options=specific_params_options,
                        value=None,
                    ),
                ]
            )
            for param_name in specific_params[value]
        ]
        return html.Div(specific_params_dropdowns)
    else:
        return html.Div()


if __name__ == "__main__":
    app.run_server(debug=True)
