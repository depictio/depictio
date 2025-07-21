import dash
import dash_core_components as dcc
import dash_draggable
import dash_html_components as html
import pandas as pd
import plotly.express as px
from dash.dependencies import Input, Output

external_stylesheets = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]

app = dash.Dash(__name__, external_stylesheets=external_stylesheets)

server = app.server

df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
)

app.layout = html.Div(
    [
        html.H1("Dash Draggable"),
        dash_draggable.ResponsiveGridLayout(
            id="draggable",
            children=[
                html.Div(
                    children=[
                        dcc.Graph(
                            id="graph-with-slider",
                            responsive=True,
                            style={"min-height": "0", "flex-grow": "1"},
                        ),
                        dcc.Slider(
                            id="year-slider",
                            min=df["year"].min(),
                            max=df["year"].max(),
                            value=df["year"].min(),
                            marks={str(year): str(year) for year in df["year"].unique()},
                            step=None,
                        ),
                    ],
                    style={
                        "height": "100%",
                        "width": "100%",
                        "display": "flex",
                        "flex-direction": "column",
                        "flex-grow": "0",
                    },
                ),
                html.Div(
                    children=[
                        dcc.Graph(
                            id="graph-with-slider",
                            responsive=True,
                            style={"min-height": "0", "flex-grow": "1"},
                        ),
                        dcc.Slider(
                            id="year-slider",
                            min=df["year"].min(),
                            max=df["year"].max(),
                            value=df["year"].min(),
                            marks={str(year): str(year) for year in df["year"].unique()},
                            step=None,
                        ),
                    ],
                    style={
                        "height": "100%",
                        "width": "100%",
                        "display": "flex",
                        "flex-direction": "column",
                        "flex-grow": "0",
                    },
                ),
            ],
        ),
    ]
)


@app.callback(Output("graph-with-slider", "figure"), Input("year-slider", "value"))
def update_figure(selected_year):
    filtered_df = df[df.year == selected_year]

    fig = px.scatter(
        filtered_df,
        x="gdpPercap",
        y="lifeExp",
        size="pop",
        color="continent",
        hover_name="country",
        log_x=True,
        size_max=55,
    )

    fig.update_layout(transition_duration=500)

    return fig


# import dash
# import dash_core_components as dcc
# import dash_html_components as html
# import dash_draggable as draggable


# app = dash.Dash(__name__)

# # Define the layout with draggable components
# app.layout = html.Div(
#     [
#         draggable.Draggable(html.Div("Header", className="header"), bounds="body"),
#         draggable.Draggable(html.Div("Sidebar", className="sidebar"), bounds="body"),
#         draggable.Draggable(html.Div("Main content", className="main-content"), bounds="body"),
#     ],
#     className="layout-container",
# )

# # Define the CSS stylesheet
# app.css.append_css({"external_url": "https://cdnjs.cloudflare.com/ajax/libs/normalize/8.0.1/normalize.min.css"})
# app.css.append_css({"external_url": "https://cdnjs.cloudflare.com/ajax/libs/meyer-reset/2.0/reset.min.css"})
# app.css.append_css({"external_url": "https://fonts.googleapis.com/css?family=Lato&display=swap"})
# app.css.append_css(
#     {
#         "external_url": """
#         .layout-container {
#             font-family: 'Lato', sans-serif;
#             display: grid;
#             grid-template-columns: 200px auto;
#             grid-template-rows: 50px auto;
#             grid-template-areas:
#                 "header header"
#                 "sidebar main-content";
#             height: 100vh;
#         }
#         .header {
#             grid-area: header;
#             background-color: #4CAF50;
#             color: white;
#             display: flex;
#             align-items: center;
#             justify-content: center;
#         }
#         .sidebar {
#             grid-area: sidebar;
#             background-color: #333;
#             color: white;
#             display: flex;
#             align-items: center;
#             justify-content: center;
#         }
#         .main-content {
#             grid-area: main-content;
#             background-color: #fff;
#             color: #333;
#             display: flex;
#             align-items: center;
#             justify-content: center;
#         }
#     """
#     }
# )

if __name__ == "__main__":
    app.run_server(debug=False, host="seneca.embl.de", port=5101)
