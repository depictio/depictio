"""
This app creates a simple sidebar layout using inline style arguments and the
dbc.Nav component.

dcc.Location is used to track the current location, and a callback uses the
current location to render the appropriate page content. The active prop of
each NavLink is set automatically according to the current pathname. To use
this feature you must install dash-bootstrap-components >= 0.11.0.

For more details on building multi-page Dash applications, check out the Dash
documentation: https://dash.plot.ly/urls
"""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, dcc, html, State
import dash_mantine_components as dmc
from dash_iconify import DashIconify

app = dash.Dash(external_stylesheets=[dbc.themes.BOOTSTRAP])

# the style arguments for the sidebar. We use position:fixed and a fixed width
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "16rem",
    "padding": "2rem 1rem",
    "background-color": "#f8f9fa",
    "transition": "left 0.3s ease",
}

# the styles for the main content position it to the right of the sidebar and
# add some padding.
CONTENT_STYLE = {
    "margin-left": "18rem",
    "margin-right": "2rem",
    "padding": "2rem 1rem",
    "transition": "margin-left 0.3s ease",
}

collapse_button = dmc.ActionIcon(
    DashIconify(icon="mdi:menu"),
    id="collapse-button",
    className="mr-1",
    style={"display": "none"},
    # style={"position": "fixed", "top": "10px", "left": "170px"},
    # adjust css to have flex position sticky to the top right
    # style={"position": "fixed", "top": "10px", "right": "10px"},
)

sidebar_content_expanded = [
    collapse_button,
    html.H2("Sidebar", className="display-4"),
    html.Hr(),
    html.P("A simple sidebar layout with navigation links", className="lead"),
]

sidebar_content_collapsed = [
    collapse_button,
    html.P("Col", style={"position": "absolute", "right": "0", "top": "75px"}),
]

sidebar = html.Div(
    id="sidebar-content",
    style=SIDEBAR_STYLE,
)


content = html.Div(id="page-content", style=CONTENT_STYLE)

collapse_button_store = dcc.Store(
    id="collapse-button-store", data={"state": "expanded", "n_clicks": 0}
)

app.layout = html.Div(
    [dcc.Location(id="url"), sidebar, content, collapse_button, collapse_button_store]
)


@app.callback(
    Output("sidebar-content", "style"),
    Output("page-content", "style"),
    Output("sidebar-content", "children"),
    Output("collapse-button", "style"),
    Output("collapse-button-store", "data"),
    Input("collapse-button", "n_clicks"),
    State("sidebar-content", "style"),
    State("page-content", "style"),
    State("sidebar-content", "children"),
    State("collapse-button-store", "data"),
)
def toggle_sidebar(
    n_clicks, sidebar_style, content_style, sidebar_content_raw, collapse_button_store
):
    print(f"sidebar_style: {sidebar_style}")
    print(f"content_style: {content_style}")
    print(f"sidebar_content_raw: {sidebar_content_raw}")
    print(f"n_clicks: {n_clicks}")

    if collapse_button_store["n_clicks"] % 2 != 0:
        sidebar_style["left"] = "-12rem"  # collapse by 3/4 of its width
        content_style["margin-left"] = "4rem"  # adjust the margin-left of the content
        # set the collapse button to the right of the sidebar
        collapse_button_style = {
            "position": "absolute",
            "top": 0,
            "right": "0px",
            "display": "block",
        }
        collapse_button_store["state"] = "collapsed"
        sidebar_content = [
            collapse_button,
            dbc.NavLink(
                [DashIconify(icon="mdi:home", width=24)],
                # "TEST",
                href="/",
                active="exact",
                style={
                    "position": "absolute",
                    # "top": 0,
                    "right": "22px",
                    "display": "block",
                },
                # style={"display": "none"},
            ),
        ]
    else:
        sidebar_style["left"] = "0px"
        content_style["margin-left"] = "18rem"
        collapse_button_style = {
            "position": "absolute",
            "top": 0,
            "right": "0px",
            "display": "block",
        }
        collapse_button_store["state"] = "expanded"
        sidebar_content = [
            collapse_button,
            dbc.NavLink(
                [
                    DashIconify(icon="mdi:home", width=24),
                    html.Span("Home", className="ms-2", style={"font-size": "1.25rem"}),
                ],
                href="/",
                active="exact",
            ),
        ]

    # else:
    #     sidebar_content = sidebar_content_expanded
    #     collapse_button_store["state"] = "expanded"
    #     collapse_button_style = {"display": "block"}

    print(f"sidebar_content: {sidebar_content}")
    collapse_button_store["n_clicks"] += 1
    print(f"collapse_button_store: {collapse_button_store}")

    return (
        sidebar_style,
        content_style,
        sidebar_content,
        collapse_button_style,
        collapse_button_store,
    )


if __name__ == "__main__":
    app.run_server(port=8888, debug=True)
