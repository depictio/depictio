from dash import Dash, html, dcc, Input, Output, dash_table
from pathlib import Path
import datetime
import os, sys
import pandas as pd
import plotly.express as px
import scipy
import dash_bootstrap_components as dbc
import dash

# Login
from pages.login.server import app, server
from flask_login import logout_user, current_user
from pages.login.views import success, login, login_fd, logout

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
                dbc.NavLink("Pivot Table", href="/pivot-table", active="exact"),
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
    if pathname == '/':
        return login.layout
        # return html.Div()
    elif pathname == '/login':
        return login.layout
    elif pathname == '/success':
        print(current_user)
        print(current_user.is_authenticated)
        if current_user.is_authenticated:
            return success.layout
        else:
            return login_fd.layout
    elif pathname == '/logout':
        if current_user.is_authenticated:
            logout_user()
            return logout.layout
        else:
            return logout.layout
    elif pathname == "/design-visualisation":
        return html.Div()
    elif pathname == "/dashboard":
        return html.Div()
    elif pathname == "/pivot-table":
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

header = html.Div(
    className="header",
    children=html.Div(
        className="container-width",
        style={"height": "100%"},
        children=[
            html.Img(src="assets/dash-logo-stripe.svg", className="logo"),
            html.Div(
                className="links",
                children=[
                    html.Div(id="user-name", className="link"),
                    html.Div(id="logout", className="link"),
                ],
            ),
        ],
    ),
)

app.layout = html.Div(
    [
        header,
        html.Div([dcc.Location(id="url"), sidebar, content]),
        dash.page_container,
    ]
)

if __name__ == "__main__":
    app.run_server(debug=True)