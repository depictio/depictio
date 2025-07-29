import dash
import dash_bootstrap_components as dbc
import dash_draggable
import numpy as np
import plotly.express as px
from dash import dcc, html
from dash.dependencies import Input, Output, State

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

np.random.seed(int(0))

x = np.random.rand(100)
y = np.random.rand(100)
print(x)

fig = px.scatter(x=x, y=y, title="0")

app.layout = html.Div(
    children=[
        dash_draggable.ResponsiveGridLayout(
            id="draggable-box",
            children=[
                html.Div(
                    id="box",
                    children=[
                        dbc.Button("Edit", id="edit-button"),
                        dbc.Button(
                            "Remove",
                            id="remove-button",
                            color="danger",
                        ),
                        dcc.Graph(id="scatter-plot", figure=fig),
                    ],
                    # style={
                    #     "width": "200px",
                    #     "height": "100px",
                    #     "padding": "10px",
                    #     "border": "1px solid black",
                    # },
                ),
            ],
        ),
        html.Div(id="output"),
        dbc.Modal(
            [
                dbc.ModalHeader("Edit Content"),
                dbc.ModalBody(dcc.Textarea(id="edit-area", style={"width": "100%"})),
                dbc.ModalFooter(
                    [
                        dbc.Button(
                            "Save",
                            id="save-button",
                        ),
                        dbc.Button("Cancel", id="cancel-button", color="secondary"),
                    ]
                ),
            ],
            id="edit-modal",
        ),
    ]
)


@app.callback(
    Output("draggable-box", "children"),
    Input("remove-button", "n_clicks"),
    prevent_initial_call=True,
)
def remove_responsive_grid(n_clicks):
    if n_clicks is None:
        raise dash.exceptions.PreventUpdate
    return []


@app.callback(
    Output("edit-modal", "is_open"),
    [
        Input("edit-button", "n_clicks"),
        Input("save-button", "n_clicks"),
        Input("cancel-button", "n_clicks"),
    ],
    [State("edit-modal", "is_open")],
)
def toggle_modal(n1, n2, n3, is_open):
    if n1 or n2 or n3:
        return not is_open
    return is_open


@app.callback(
    Output("scatter-plot", "figure"),
    [Input("save-button", "n_clicks")],
    [State("edit-area", "value"), State("scatter-plot", "figure")],
    prevent_initial_call=True,
)
def update_content(n_clicks, new_content_title, current_content):
    np.random.seed(int(new_content_title))
    x = np.random.rand(100)
    y = np.random.rand(100)

    new_content = px.scatter(x=x, y=y, title=new_content_title)
    print(current_content["layout"]["title"]["text"])

    if n_clicks is None:
        return current_content
    return (
        new_content if str(new_content_title) else str(current_content["layout"]["title"]["text"])
    )


if __name__ == "__main__":
    app.run_server(debug=True)
