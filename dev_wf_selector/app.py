import dash
from dash import dcc, html, Input, Output, State
import plotly.express as px
import pandas as pd

app = dash.Dash(__name__)

# Online dataframes
df1 = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
df2 = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/mtcars.csv")
dataframes = {"Iris": df1, "Mtcars": df2}

initial_selections = {
    df_name: {
        "x": df.columns[0],
        "y": df.columns[1],
        "color": df.columns[2] if len(df.columns) > 2 else None,
    }
    for df_name, df in dataframes.items()
}
print(initial_selections)

app.layout = html.Div(
    [
        dcc.Store(
            id="dataframe-store",
            storage_type="session",
        ),
        dcc.Store(id="selections-store", storage_type="session", data={}),
        dcc.Dropdown(
            id="dataframe-dropdown",
            options=[
                {"label": df_name, "value": df_name} for df_name in dataframes.keys()
            ],
            value=list(dataframes.keys())[0],
        ),
        dcc.Dropdown(id="x-dropdown", value=df1.columns[0]),
        dcc.Dropdown(id="y-dropdown", value=df1.columns[1]),
        dcc.Dropdown(
            id="color-dropdown", value=df1.columns[2] if len(df1.columns) > 2 else None
        ),
        dcc.Graph(id="graph"),
    ]
)


@app.callback(
    Output("dataframe-store", "data"),
    Input("dataframe-dropdown", "value"),
)
def update_data(df_name):
    return dataframes[df_name].to_dict()


@app.callback(
    Output("x-dropdown", "options"),
    Output("y-dropdown", "options"),
    Output("color-dropdown", "options"),
    Input("dataframe-store", "data"),
)
def update_dropdown_options(df_data):
    df = pd.DataFrame(df_data)
    options = [{"label": col, "value": col} for col in df.columns]
    return options, options, options


@app.callback(
    [
        Output("x-dropdown", "value"),
        Output("y-dropdown", "value"),
        Output("color-dropdown", "value"),
        Output("selections-store", "data"),
    ],
    [
        Input("dataframe-store", "data"),
        Input("dataframe-dropdown", "value"),
        Input("x-dropdown", "value"),
        Input("y-dropdown", "value"),
        Input("color-dropdown", "value"),
    ],
    [State("selections-store", "data")],
)
def update_dropdown_values_and_save_selections(
    df_data, df_name, x, y, color, selections_dict
):
    ctx = dash.callback_context
    df = pd.DataFrame(df_data)

    if ctx.triggered and ctx.triggered[0]["prop_id"] == "dataframe-dropdown.value":
        # If the dataframe has changed, update x, y, color values based on the saved selections or defaults
        selections = selections_dict.get(df_name)
        if selections:
            x, y, color = selections["x"], selections["y"], selections["color"]
        else:
            x, y = df.columns[0], df.columns[1]
            color = df.columns[2] if len(df.columns) > 2 else None
            selections_dict[df_name] = {"x": x, "y": y, "color": color}
    elif ctx.triggered and ctx.triggered[0]["prop_id"] in [
        "x-dropdown.value",
        "y-dropdown.value",
        "color-dropdown.value",
    ]:
        # If dropdown value has changed, save the current selection
        selections_dict[df_name] = {"x": x, "y": y, "color": color}
    elif not ctx.triggered:
        # This part runs when the page is refreshed
        selections = selections_dict.get(df_name)
        if selections and all(
            column in df.columns
            for column in [selections["x"], selections["y"], selections.get("color")]
        ):
            x, y, color = selections["x"], selections["y"], selections["color"]
        else:
            x, y = df.columns[0], df.columns[1]
            color = df.columns[2] if len(df.columns) > 2 else None
            selections_dict[df_name] = {"x": x, "y": y, "color": color}

    return x, y, color, selections_dict


@app.callback(
    Output("graph", "figure"),
    [
        Input("x-dropdown", "value"),
        Input("y-dropdown", "value"),
        Input("color-dropdown", "value"),
        Input("dataframe-store", "data"),
    ],
)
def update_figure(x, y, color, df_data):
    if x and y and df_data:
        df = pd.DataFrame(df_data)
        return px.scatter(df, x=x, y=y, color=color if color else None)
    else:
        return {}


if __name__ == "__main__":
    app.run_server(debug=True, port=9050)
