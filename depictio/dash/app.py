import os
from dash import html, Input, Output, dcc, State
import dash
import dash_bootstrap_components as dbc


# Depictio imports
from depictio.api.v1.configs.config import settings

# Depictio components imports - design step
from depictio.dash.modules.card_component.frontend import register_callbacks_card_component
from depictio.dash.modules.interactive_component.frontend import register_callbacks_interactive_component
from depictio.dash.modules.figure_component.frontend import register_callbacks_figure_component
from depictio.dash.modules.jbrowse_component.frontend import register_callbacks_jbrowse_component
from depictio.dash.modules.table_component.frontend import register_callbacks_table_component

# TODO: markdown component


# Depictio layout imports
from depictio.dash.layouts.stepper import register_callbacks_stepper
from depictio.dash.layouts.stepper_parts.part_one import register_callbacks_stepper_part_one
from depictio.dash.layouts.stepper_parts.part_two import register_callbacks_stepper_part_two
from depictio.dash.layouts.stepper_parts.part_three import register_callbacks_stepper_part_three
from depictio.dash.layouts.header import design_header, register_callbacks_header

# from depictio.dash.layouts.draggable_scenarios.add_component import register_callbacks_add_component
from depictio.dash.layouts.draggable import (
    design_draggable,
    register_callbacks_draggable,
)


# Depictio utils imports
from depictio.dash.layouts.draggable_scenarios.restore_dashboard import load_depictio_data

from depictio.api.v1.configs.config import logger


# Start the app
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        {
            "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
            "rel": "stylesheet",
        },
    ],
    suppress_callback_exceptions=True,
    title="Depictio",
)

server = app.server  # This is the Flask server instance

# Configure Flask's logger to use your logging settings
server.logger.handlers = logger.handlers
server.logger.setLevel(logger.level)

# Register callbacks for layout
register_callbacks_stepper(app)
register_callbacks_stepper_part_one(app)
register_callbacks_stepper_part_two(app)
register_callbacks_stepper_part_three(app)
register_callbacks_header(app)
register_callbacks_draggable(app)


# Register callbacks for components
register_callbacks_card_component(app)
register_callbacks_interactive_component(app)
register_callbacks_figure_component(app)
register_callbacks_jbrowse_component(app)
register_callbacks_table_component(app)

# Register callbacks for draggable layout
# register_callbacks_add_component(app)

from depictio.dash.layouts.dashboards_management import register_callbacks_management
from depictio.dash.layouts.dashboards_management import layout as management_layout

register_callbacks_management(app)


@app.callback(
    Output("page-content", "children"),
    [Input("second-url", "pathname")],
)
def display_page(pathname):
    if pathname is None:
        return dash.no_update
    elif pathname.startswith("/dashboard/"):
        dashboard_id = pathname.split("/")[-1]
        # Fetch dashboard data based on dashboard_id and return the dashboard layout
        return create_dashboard_layout(dashboard_id=dashboard_id)
        # return html.Div([f"Displaying Dashboard {dashboard_id}", dbc.Button("Go back", href="/", color="black", external_link=True)])
    else:
        # Return the dashboards management layout
        return create_management_layout()
        # return html.Div([f"Displaying Management Layout"])


def create_management_layout():
    return management_layout


@app.callback(
    Output("sidebar", "width"),
    Input("sidebar-button", "n_clicks"),
    State("sidebar", "width"),
    prevent_initial_call=True,
)
def drawer_demo(n, width):
    if n:
        if width["base"] == 200:
            return {"base": 66}
        else:
            return {"base": 200}
    else:
        raise dash.exceptions.PreventUpdate


@app.callback(
    Output("drawer-simple", "opened"),
    Input("drawer-demo-button", "n_clicks"),
    prevent_initial_call=True,
)
def drawer_dem(n_clicks):
    return True


def create_dashboard_layout(dashboard_id=None):
    # Load depictio depictio_dash_data from JSON
    depictio_dash_data = load_depictio_data()
    # logger.info(f"Loaded depictio depictio_dash_data: {depictio_dash_data}")
    # depictio_dash_data = None


    # Init layout and children if depictio_dash_data is available, else set to empty
    init_layout = depictio_dash_data["stored_layout_data"] if depictio_dash_data else {}
    logger.info(f"Loaded depictio init_layout: {init_layout}")
    init_children = depictio_dash_data["stored_children_data"] if depictio_dash_data else list()
    # init_children = [html.Div("test", id="1")]
    # logger.info(f"Loaded depictio init_children: {init_children}")
    # Generate header and backend components
    header, backend_components = design_header(depictio_dash_data)

    # Generate draggable layout
    core = design_draggable(depictio_dash_data, init_layout, init_children)

    import dash_mantine_components as dmc
    from dash_iconify import DashIconify

    depictio_logo = html.A(
        html.Img(src=dash.get_asset_url("logo.png"), height=40, style={"margin-left": "0px"}),
        # html.Img(src=dash.get_asset_url("logo_icon.png"), height=40, style={"margin-left": "0px"}),
        href="/",
    )

    navbar = dmc.Navbar(
        p="md",
        fixed=False,
        width={"base": 200},
        hidden=True,
        hiddenBreakpoint="md",
        position="right",
        height="100vh",
        id="sidebar",
        children=[
            depictio_logo,
            html.Div(
                [
                    dmc.NavLink(
                        label="HOME",
                        icon=DashIconify(icon="ant-design:home-filled", width=20),
                        href="/",
                    ),
                ],
                style={"white-space": "nowrap", "margin-top": "20px"},
            ),
        ],
        style={
            "overflow": "hidden",
            "transition": "width 0.3s ease-in-out",
        },
    )

    return dmc.Container(
        [
            backend_components,
            navbar,
            dmc.Drawer(
                title="Company Name",
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
                        [core],
                        id="page-container",
                        p=0,
                        fluid=True,
                        style={"width": "100%", "height": "100%", "margin": "0", "maxWidth": "100%", "overflow": "auto", "flexShrink": "1", "maxHeight": "100%"},
                    ),
                    html.Div(id="test-input"),
                    html.Div(id="test-output", style={"display": "none"}),
                    html.Div(id="test-output-visible"),
                ],
                #     id="page-container",
                #     p=0,
                #     fluid=True,
                #     style={"background-color": "#f4f6f9", "width": "100%", "margin": "0", "maxWidth": "100%", "overflow": "auto", "flexShrink": "1", "maxHeight": "100%"},
                fluid=True,
                size="100%",
                p=0,
                m=0,
                style={"display": "flex", "maxWidth": "100vw", "overflow": "hidden", "flexGrow": "1", "maxHeight": "100%", "flexDirection": "column"},
                id="content-container",
            ),
        ],
        size="100%",
        p=0,
        m=0,
        style={"display": "flex", "maxWidth": "100vw", "overflow": "hidden", "maxHeight": "100vh", "position": "absolute", "top": 0, "left": 0, "width": "100vw"},
        id="overall-container",
    )

    # html.Div(
    #     [
    #         # Backend components & header
    #         # Draggable layout
    #         core,
    #     ],
    # ),

    #     ],
    #     fluid=True,
    # )


def create_app_layout():
    return dbc.Container(
        [
            dcc.Location(id="second-url", refresh=False),
            html.Div(id="page-content"),
        ],
        fluid=True,
    )


app.layout = create_app_layout

# APP Layout
# app.layout = dbc.Container(
#     [
#         html.Div(
#             [
#                 # Backend components & header
#                 backend_components,
#                 header,
#                 # Draggable layout
#                 core,
#             ],
#         ),
#         html.Div(id="test-input"),
#         html.Div(id="test-output", style={"display": "none"}),
#         html.Div(id="test-output-visible"),
#     ],
#     fluid=True,
# )


if __name__ == "__main__":
    app.run_server(debug=True, host=settings.dash.host, port=settings.dash.port)
