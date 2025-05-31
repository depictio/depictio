import dash
from dash import html, dcc, Input, Output, State, ALL
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_mantine_components import Button, Card, Group
from dash_iconify import DashIconify

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])


# Callback to toggle sidebar
@app.callback(
    Output("sidebar", "style"),
    Output("header", "height"),
    Output("sidebar-icon", "icon"),
    Input("sidebar-button", "n_clicks"),
    State("sidebar", "style"),
    State("header", "height"),
    State("sidebar-icon", "icon"),
    prevent_initial_call=True,
)
def toggle_sidebar(n_clicks, sidebar_style, header_height, icon):
    print(sidebar_style)

    if sidebar_style.get("display") == "none":
        sidebar_style["display"] = "flex"
        icon = "ep:d-arrow-left"
        return sidebar_style, header_height, icon
    else:
        icon = "ep:d-arrow-right"
        sidebar_style["display"] = "none"
        return sidebar_style, header_height, icon


# Callback to update sidebar-link active state
@app.callback(
    Output({"type": "sidebar-link", "index": ALL}, "active"),
    Input("url", "pathname"),
    prevent_initial_call=True,
)
def update_active_state(pathname):
    if pathname == "/dashboards":
        return [True, False]
    elif pathname == "/datasets":
        return [False, True]
    else:
        return [False, False]


# Update URL
@app.callback(
    Output("url", "pathname"),
    Input({"type": "sidebar-link", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def update_url(n_clicks):
    ctx = dash.callback_context
    index = ctx.triggered[0]["prop_id"].split(".")[1]
    if index == "dashboards":
        return "/dashboards"
    elif index == "datasets":
        return "/datasets"
    elif index == "/dashboard/1":
        return "/dashboard/1"
    else:
        return "/"


# Update page-container content based on URL
@app.callback(
    Output("page-container", "children"),
    Input("url", "pathname"),
    prevent_initial_call=True,
)
def update_page_content(pathname):
    if pathname == "/dashboards":
        recently_viewed = html.Div(
            [
                # margin left, top and bottom
                # dark grey color #333333
                dmc.Text(
                    "Dashboards recently viewed",
                    size=20,
                    weight=600,
                    color="#333333",
                    style={"margin": "10px 10px 10px 10px"},
                ),
                dmc.Divider(style={"margin": "10px 10px"}),
                dmc.SimpleGrid(
                    # Dashboards recently viewed
                    4
                    * [
                        dmc.Card(
                            children=[
                                html.A(
                                    dmc.CardSection(
                                        dmc.Image(
                                            src="dev/navbar/assets/screenshots/admin@embl.de_1.png",
                                        )
                                    ),
                                    href="/dashboard/1",
                                ),
                                html.Hr(),
                                # Center text
                                dmc.Group(
                                    [
                                        # Center text
                                        dmc.Tooltip(
                                            label="Info",
                                            offset=5,
                                            position="top",
                                            # Remove underlined text in the badge
                                            children=dmc.ActionIcon(
                                                DashIconify(icon="ci:info", width=20, height=20),
                                                color="gray",
                                                variant="subtle",
                                                p=1,
                                            ),
                                        ),
                                        dmc.Text("Test", weight=700),
                                    ],
                                    mt="md",
                                    mb="xs",
                                ),
                            ],
                            withBorder=True,
                            shadow="sm",
                            radius="md",
                            style={"width": 350},
                        ),
                    ],
                    cols=4,
                    spacing="md",
                ),
            ]
        )
        return html.Div([recently_viewed, recently_viewed])
    elif pathname == "/dashboard/1":
        return html.Div("Dashboard 1")
    elif pathname == "/datasets":
        return html.Div("Datasets")
    else:
        return html.Div("Homepage")


def design_header(data):
    """
    Design the header of the dashboard
    """

    button_menu = dmc.Group(
        [
            dmc.MediaQuery(
                [
                    dmc.ActionIcon(
                        DashIconify(
                            id="sidebar-icon",
                            icon="ep:d-arrow-left",
                            width=34,
                            height=34,
                            color="#c2c7d0",
                        ),
                        variant="subtle",
                        p=1,
                        id="sidebar-button",
                    )
                ],
                smallerThan="md",
                styles={"display": "none"},
            ),
        ]
    )

    header = dmc.Header(
        id="header",
        height=87,
        children=[
            dbc.Row(
                [
                    dbc.Col(button_menu, width=1, align="center", style={"textAlign": "center"}),
                    dbc.Col(
                        dmc.Title("Homepage", order=2, color="black"),
                        width=11,
                        align="center",
                        style={"textAlign": "left"},
                    ),
                ],
                style={"height": "100%"},
            ),
        ],
    )

    return header


header = design_header(data=None)


characters_list = [
    {
        # pastel red color: #FFC0CB
        "id": 1,
        "image": "https://ui-avatars.com/api/?format=svg&name=Organisation&background=FFC0CB&color=white&rounded=true&bold=true&format=svg&size=16",
        "label": "Organisation",
        "content": "Default Organisation",
    },
]


def create_accordion_label(label, image):
    return dmc.AccordionControl(
        dmc.Group(
            [
                dmc.Avatar(src=image, radius="xl", size="md"),
                html.Div(
                    [
                        dmc.Text(label),
                    ]
                ),
            ]
        )
    )


def create_accordion_content(content):
    return dmc.AccordionPanel(dmc.Text(content, size="sm"))


# organisation = dmc.Accordion(
#     chevronPosition="right",
#     variant="contained",
#     children=[
#         dmc.AccordionItem(
#             [
#                 create_accordion_label(character["label"], character["image"]),
#                 create_accordion_content(character["content"]),
#             ],
#             value=str(character["id"]),
#         )
#         for character in characters_list
#     ],
#     # Hide frame
#     # style={"border": "none"},
# )


organisation = html.Div(
    [
        dmc.Avatar(
            src=f"https://ui-avatars.com/api/?format=svg&name=Organisation&background=FFC0CB&color=white&rounded=true&bold=true&format=svg&size=16",
            size="md",
            radius="xl",
        ),
        dmc.Text("Organisation", size="lg", style={"fontSize": "16px", "marginLeft": "10px"}),
    ],
    style={
        "textAlign": "center",
        "justifyContent": "center",
        "display": "flex",
        "alignItems": "center",  # Aligns Avatar and Text on the same line
        "flexDirection": "row",  # Flex direction set to row (default)
    },
)

depictio_logo = html.A(
    html.Img(src=dash.get_asset_url("logo.png"), height=45),
    # html.Img(src=dash.get_asset_url("logo_icon.png"), height=40, style={"margin-left": "0px"}),
    href="/",
    style={"alignItems": "center", "justifyContent": "center", "display": "flex"},
)

email = "john.doe@gmail.com"
navbar = dmc.Navbar(
    p="md",
    fixed=False,
    width={"base": 300},
    hidden=True,
    hiddenBreakpoint="md",
    position="right",
    height="100vh",
    id="sidebar",
    style={
        "overflow": "hidden",
        "transition": "width 0.3s ease-in-out",
        "display": "flex",
        "flexDirection": "column",
    },
    children=[
        depictio_logo,
        # reduce padding
        # organisation,
        # reduce padding with accordion
        # html.Hr(style={"margin": "10px", "padding": "0px", "flexShrink": 0}),  # Prevent HR from shrinking
        html.Div(
            id="sidebar-content",
            children=[
                dmc.NavLink(
                    id={"type": "sidebar-link", "index": "dashboards"},
                    label=dmc.Text(
                        "Dashboards", size="lg", style={"fontSize": "16px"}
                    ),  # Using dmc.Text to set the font size
                    icon=DashIconify(icon="material-symbols:dashboard", height=25),
                    href="/dashboards",
                    style={"padding": "20px"},
                ),
                dmc.NavLink(
                    id={"type": "sidebar-link", "index": "datasets"},
                    label=dmc.Text(
                        "Datasets", size="lg", style={"fontSize": "16px"}
                    ),  # Using dmc.Text to set the font size
                    icon=DashIconify(icon="material-symbols:dataset", height=25),
                    href="/datasets",
                    style={"padding": "20px"},
                ),
            ],
            style={
                "white-space": "nowrap",
                "margin-top": "20px",
                "flexGrow": "1",
                "overflowY": "auto",
            },
        ),
        html.Div(
            id="sidebar-footer",
            # className="mt-auto",
            children=[
                html.Hr(),
                html.Div(
                    [
                        dmc.Avatar(
                            src=f"https://ui-avatars.com/api/?format=svg&name={email}&background=AEC8FF&color=white&rounded=true&bold=true&format=svg&size=16",
                            size="md",
                            radius="xl",
                        ),
                        dmc.Text(
                            "John Doe", size="lg", style={"fontSize": "16px", "marginLeft": "10px"}
                        ),
                    ],
                    style={
                        "textAlign": "center",
                        "justifyContent": "center",
                        "display": "flex",
                        "alignItems": "center",  # Aligns Avatar and Text on the same line
                        "flexDirection": "row",  # Flex direction set to row (default)
                    },
                ),
            ],
            style={
                "flexShrink": 0,  # Prevent footer from shrinking
            },
        ),
    ],
)
app.layout = dmc.Container(
    [
        dcc.Location(id="url", refresh=False),
        navbar,
        dmc.Drawer(
            title="",
            id="drawer-simple",
            padding="md",
            zIndex=10000,
            size=200,
            overlayOpacity=0.1,
            children=[],
        ),
        dmc.Container(
            [
                header,
                # dmc.Container(
                dmc.Container(
                    [html.Div("Hello World")],
                    id="page-container",
                    p=0,
                    fluid=True,
                    # style={"width": "100%", "height": "100%", "margin": "0", "maxWidth": "100%", "overflow": "auto", "flexShrink": "1", "maxHeight": "100%"},
                    style={
                        "width": "100%",
                        "height": "100%",
                        "overflowY": "auto",  # Allow vertical scrolling
                        "flexGrow": "1",
                    },
                ),
                html.Div(id="test-input"),
                html.Div(id="test-output", style={"display": "none"}),
                html.Div(id="test-output-visible"),
            ],
            fluid=True,
            size="100%",
            p=0,
            m=0,
            style={
                "display": "flex",
                "maxWidth": "100vw",
                "overflow": "hidden",
                "flexGrow": "1",
                "maxHeight": "100%",
                "flexDirection": "column",
            },
            id="content-container",
        ),
    ],
    # size="100%",
    fluid=True,
    p=0,
    m=0,
    style={
        "display": "flex",
        "maxWidth": "100vw",
        "overflow": "hidden",
        "maxHeight": "100vh",
        "position": "absolute",
        "top": 0,
        "left": 0,
        "width": "100vw",
    },
    id="overall-container",
)

if __name__ == "__main__":
    app.run_server(debug=True)
