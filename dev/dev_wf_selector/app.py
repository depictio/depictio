import dash
import pandas as pd
import plotly.express as px
from dash import Input, Output, State, dcc, html

app = dash.Dash(__name__)

# Online dataframes
df1 = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
df2 = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/mtcars.csv")
dataframes = {"Iris": df1, "Mtcars": df2}

app.layout = html.Div(
    [
        dcc.Store(
            id="dataframe-store",
            storage_type="session",
            data={"Iris": df1.to_dict(), "Mtcars": df2.to_dict()},
        ),
        dcc.Store(id="selections-store", storage_type="session", data={}),
        dcc.Dropdown(
            id="dataframe-dropdown",
            options=[{"label": df_name, "value": df_name} for df_name in dataframes.keys()],
            value="Iris",
        ),
        dcc.Dropdown(id="x-dropdown"),
        dcc.Dropdown(id="y-dropdown"),
        dcc.Dropdown(id="color-dropdown"),
        dcc.Graph(id="graph"),
    ]
)


@app.callback(
    [
        Output("x-dropdown", "options"),
        Output("y-dropdown", "options"),
        Output("color-dropdown", "options"),
        Output("x-dropdown", "value"),
        Output("y-dropdown", "value"),
        Output("color-dropdown", "value"),
    ],
    [Input("dataframe-dropdown", "value")],
    [State("dataframe-store", "data"), State("selections-store", "data")],
)
def update_dropdown_values(df_name, df_data, selections_dict):
    df = pd.DataFrame(df_data[df_name])
    df_columns = [{"label": col, "value": col} for col in df.columns]

    if df_name in selections_dict:
        x, y, color = (
            selections_dict[df_name]["x"],
            selections_dict[df_name]["y"],
            selections_dict[df_name]["color"],
        )
    else:
        x, y = df.columns[0], df.columns[1]
        color = df.columns[2] if len(df.columns) > 2 else None
        selections_dict[df_name] = {"x": x, "y": y, "color": color}

    return df_columns, df_columns, df_columns, x, y, color


@app.callback(
    Output("selections-store", "data"),
    [
        Input("x-dropdown", "value"),
        Input("y-dropdown", "value"),
        Input("color-dropdown", "value"),
    ],
    [State("dataframe-dropdown", "value"), State("selections-store", "data")],
)
def update_selections_store(x, y, color, df_name, selections_dict):
    if x is not None and y is not None:
        selections_dict[df_name] = {"x": x, "y": y, "color": color}
    return selections_dict


@app.callback(
    Output("graph", "figure"),
    [
        Input("x-dropdown", "value"),
        Input("y-dropdown", "value"),
        Input("color-dropdown", "value"),
        Input("dataframe-store", "data"),
        Input("dataframe-dropdown", "value"),
    ],
)
def update_figure(x, y, color, df_data, df_name):
    if x and y and df_data:
        df = pd.DataFrame(df_data[df_name])
        return px.scatter(df, x=x, y=y, color=color if color else None)
    else:
        return {}


if __name__ == "__main__":
    app.run_server(debug=True, port=9050)
