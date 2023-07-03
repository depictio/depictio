from dash import Dash, html, dcc, Input, Output, dash_table
from pathlib import Path
import datetime
import os, sys
import pandas as pd
import plotly.express as px
import scipy
import dash_bootstrap_components as dbc
import dash


# Start the app, use_pages allows to retrieve what's present in the pages/ folder in order
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP,     {
        "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
        "rel": "stylesheet",
    },], use_pages=True)
server = app.server

app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <!-- Add the following link -->
        <link href="https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@400;700&display=swap" rel="stylesheet">
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""

# the style arguments for the sidebar. We use position:fixed and a fixed width
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "16rem",
    "padding": "2rem 1rem",
    "background-color": "#f8f9fa",
}

# the styles for the main content position it to the right of the sidebar and
# add some padding.
CONTENT_STYLE = {
    "margin-left": "18rem",
    "margin-right": "2rem",
    "padding": "2rem 1rem",
}

sidebar = html.Div(
    [
        html.P("Navigation", className="lead"),
        dbc.Nav(
            [
                dbc.NavLink("Dash home page", href="/", active="exact"),
                dbc.NavLink("Design visualisation", href="/design-visualisation", active="exact"),
                dbc.NavLink("Dashboard", href="/dashboard", active="exact"),
            ],
            vertical=True,
            pills=True,
        ),

    ],
    style=SIDEBAR_STYLE,
)

print([dcc.Link(f"{page['name']} - {page['path']}", href=page["relative_path"]) for page in dash.page_registry.values()])
content = dbc.Container([html.Div(id="page-content", style=CONTENT_STYLE)], fluid=False)


@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page_content(pathname):
    if pathname == "/":
        return html.Div()
    elif pathname == "/design-visualisation":
        return html.Div()
    elif pathname == "/dashboard":
        return html.Div()

    # If the user tries to reach a different page, return a 404 message
    # return html.Div(
    #     [
    #         html.H1("404: Not found", className="text-danger"),
    #         html.Hr(),
    #         html.P(f"The pathname {pathname} was not recognised..."),
    #     ],
    #     className="p-3 bg-light rounded-3",
    # )


app.layout = html.Div(
    [
        html.Div([dcc.Location(id="url"), sidebar, content]),
        dash.page_container,
    ]
)

if __name__ == "__main__":
    app.run_server(debug=True)