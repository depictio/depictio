from dash import html, Dash, dcc
import dash_mantine_components as dmc

app = Dash(
    __name__, external_stylesheets=["https://use.fontawesome.com/releases/v5.8.1/css/all.css"]
)

app.layout = html.Div(
    [
        dmc.MediaQuery(
            [
                dmc.Navbar(
                    fixed=True,
                    width={"base": 250},
                    height="100%",
                    style={"top": 0},
                    children=[
                        dmc.Group(
                            grow=True,
                            gap="xl",
                            children=[
                                dmc.List(
                                    center=True,
                                    children=[
                                        dmc.ListItem(
                                            dcc.Link("Home", href="/"),
                                            icon=[html.I(className="fas fa-home fa-fw fa-lg")],
                                            className="nav-list-items",
                                        ),
                                        dmc.ListItem(
                                            dcc.Link("Data", href="/analytics"),
                                            icon=[html.I(className="fas fa-chart-bar fa-fw fa-lg")],
                                            className="nav-list-items",
                                        ),
                                        dmc.ListItem(
                                            dcc.Link("Map", href="/map"),
                                            icon=[html.I(className="fas fa-map fa-fw fa-lg")],
                                            className="nav-list-items",
                                        ),
                                        dmc.ListItem(
                                            dcc.Link("More Maps", href="/maps"),
                                            icon=[
                                                html.I(className="fas fa-map-marker fa-fw fa-lg")
                                            ],
                                            className="nav-list-items",
                                        ),
                                    ],
                                )
                            ],
                        )
                    ],
                )
            ],
            smallerThan="md",
            styles={"display": "none"},
        ),
        dmc.MediaQuery(
            [
                dmc.Navbar(
                    fixed=True,
                    width={"base": 60},
                    height="100%",
                    style={"top": 0},
                    children=[
                        dmc.List(
                            center=True,
                            children=[
                                dmc.ListItem(
                                    dcc.Link(html.I(className="fas fa-home fa-fw fa-lg"), href="/"),
                                    className="nav-list-items",
                                ),
                                dmc.ListItem(
                                    dcc.Link(
                                        html.I(className="fas fa-chart-bar fa-fw fa-lg"),
                                        href="/analytics",
                                    ),
                                    className="nav-list-items",
                                ),
                                dmc.ListItem(
                                    dcc.Link(
                                        html.I(className="fas fa-map fa-fw fa-lg"), href="/map"
                                    ),
                                    className="nav-list-items",
                                ),
                                dmc.ListItem(
                                    dcc.Link(
                                        html.I(className="fas fa-map-marker fa-fw fa-lg"),
                                        href="/maps",
                                    ),
                                    className="nav-list-items",
                                ),
                            ],
                        )
                    ],
                )
            ],
            largerThan="md",
            styles={"display": "none"},
        ),
    ]
)

if __name__ == "__main__":
    app.run_server(debug=True)
