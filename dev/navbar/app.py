import dash
import dash_mantine_components as dmc
from dash import Input, Output, State, html
from dash_iconify import DashIconify


def get_icon(icon):
    return DashIconify(icon=icon, height=16, color="#c2c7d0")


app = dash.Dash(__name__, suppress_callback_exceptions=True)


app.layout = dmc.MantineProvider(
    theme={
        "fontFamily": '"Inter", sans-serif',
        "components": {"NavLink": {"styles": {"label": {"color": "#c2c7d0"}}}},
    },
    children=[
        dmc.Container(
            [
                dmc.Navbar(
                    p="md",
                    fixed=False,
                    width={"base": 300},
                    hidden=True,
                    hiddenBreakpoint="md",
                    position="right",
                    height="100vh",
                    id="sidebar",
                    children=[
                        html.Div(
                            [
                                dmc.NavLink(
                                    label="With icon",
                                    icon=get_icon(icon="bi:house-door-fill"),
                                ),
                                dmc.NavLink(
                                    opened=False,
                                    label="With right section",
                                    icon=get_icon(icon="tabler:gauge"),
                                    rightSection=get_icon(icon="tabler-chevron-right"),
                                    href="www.google.com",
                                ),
                                dmc.NavLink(
                                    label="Disabled",
                                    icon=get_icon(icon="tabler:circle-off"),
                                    disabled=True,
                                ),
                                dmc.NavLink(
                                    label="With description",
                                    description="Additional information",
                                    icon=dmc.Badge(
                                        "3",
                                        size="xs",
                                        variant="filled",
                                        color="red",
                                        w=16,
                                        h=16,
                                        p=0,
                                    ),
                                ),
                                dmc.NavLink(
                                    label="Active subtle",
                                    icon=get_icon(icon="tabler:activity"),
                                    rightSection=get_icon(icon="tabler-chevron-right"),
                                    variant="subtle",
                                    active=True,
                                ),
                            ],
                            style={"white-space": "nowrap"},
                        )
                    ],
                    style={
                        "overflow": "hidden",
                        "transition": "width 0.3s ease-in-out",
                        "background-color": "#343a40",
                    },
                ),
                dmc.Drawer(
                    title="Company Name",
                    id="drawer-simple",
                    padding="md",
                    zIndex=10000,
                    size=300,
                    overlayOpacity=0.1,
                    children=[
                        html.Div(
                            [
                                dmc.NavLink(
                                    label="With icon",
                                    icon=get_icon(icon="bi:house-door-fill"),
                                ),
                                dmc.NavLink(
                                    opened=False,
                                    label="With right section",
                                    icon=get_icon(icon="tabler:gauge"),
                                    rightSection=get_icon(icon="tabler-chevron-right"),
                                ),
                                dmc.NavLink(
                                    label="Disabled",
                                    icon=get_icon(icon="tabler:circle-off"),
                                    disabled=True,
                                ),
                                dmc.NavLink(
                                    label="With description",
                                    description="Additional information",
                                    icon=dmc.Badge(
                                        "3",
                                        size="xs",
                                        variant="filled",
                                        color="red",
                                        w=16,
                                        h=16,
                                        p=0,
                                    ),
                                    style={"body": {"overflow": "hidden"}},
                                ),
                                dmc.NavLink(
                                    label="Active subtle",
                                    icon=get_icon(icon="tabler:activity"),
                                    rightSection=get_icon(icon="tabler-chevron-right"),
                                    variant="subtle",
                                    active=True,
                                ),
                            ],
                            style={"white-space": "nowrap"},
                        )
                    ],
                    style={"background-color": ""},
                    styles={"drawer": {"background-color": "#343a40"}},
                ),
                dmc.Container(
                    [
                        dmc.Header(
                            height=60,
                            children=[
                                dmc.Group(
                                    [
                                        dmc.MediaQuery(
                                            [
                                                dmc.Button(
                                                    DashIconify(
                                                        icon="ci:hamburger-lg",
                                                        width=24,
                                                        height=24,
                                                        color="#c2c7d0",
                                                    ),
                                                    variant="subtle",
                                                    p=1,
                                                    id="sidebar-button",
                                                ),
                                            ],
                                            smallerThan="md",
                                            styles={"display": "none"},
                                        ),
                                        dmc.MediaQuery(
                                            [
                                                dmc.Button(
                                                    DashIconify(
                                                        icon="ci:hamburger-lg",
                                                        width=24,
                                                        height=24,
                                                        color="#c2c7d0",
                                                    ),
                                                    variant="subtle",
                                                    p=1,
                                                    id="drawer-demo-button",
                                                ),
                                            ],
                                            largerThan="md",
                                            styles={"display": "none"},
                                        ),
                                        dmc.Text("Company Name"),
                                    ]
                                )
                            ],
                            p="10px",
                            style={"backgroundColor": "#fff"},
                        ),
                        html.P(),
                    ],
                    id="page-container",
                    p=0,
                    fluid=True,
                    style={"background-color": "#f4f6f9", "width": "100%", "margin": "0"},
                ),
            ],
            size="100%",
            p=0,
            m=0,
            style={"display": "flex"},
        )
    ],
)


@app.callback(
    Output("sidebar", "width"),
    Input("sidebar-button", "n_clicks"),
    State("sidebar", "width"),
    prevent_initial_call=True,
)
def drawer_demo(opened, width):
    if opened:
        if width["base"] == 300:
            return {"base": 70}
        else:
            return {"base": 300}
    else:
        raise dash.PreventUpdate


@app.callback(
    Output("drawer-simple", "opened"),
    Input("drawer-demo-button", "n_clicks"),
    prevent_initial_call=True,
)
def drawer_dem(n_clicks):
    return True


if __name__ == "__main__":
    app.run_server(debug=True)
