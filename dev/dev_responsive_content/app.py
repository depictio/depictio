import dash
import dash_bootstrap_components as dbc
from dash import html

app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    external_stylesheets=[dbc.themes.MATERIA, dbc.icons.FONT_AWESOME],
)


sidebar = html.Div(
    [
        html.Div(
            [
                html.H2("Auto ML", style={"color": "white"}),
            ],
            className="sidebar-header",
        ),
        html.Hr(),
        dbc.Nav(
            [
                dbc.NavLink(
                    [html.I(className="fas fa-home me-2"), html.Span("Dashboard")],
                    href="/",
                    active="exact",
                ),
                dbc.NavLink(
                    [
                        html.I(className="fas fa-calendar-alt me-2"),
                        html.Span("Projects"),
                    ],
                    href="/projects",
                    active="exact",
                ),
                dbc.NavLink(
                    [
                        html.I(className="fas fa-envelope-open-text me-2"),
                        html.Span("Datasets"),
                    ],
                    href="/datasets",
                    active="exact",
                ),
            ],
            vertical=True,
            pills=True,
        ),
    ],
    className="sidebar",
)

app.layout = html.Div(
    [
        sidebar,
        html.Div(
            [dash.page_container, html.Div("HELLO!")],
            className="content",
        ),
    ]
)

if __name__ == "__main__":
    app.run_server(debug=True)
