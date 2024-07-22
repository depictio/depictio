import os
from dash import html, Input, Output, State, dcc
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

from depictio.dash.layouts.dashboards_management import register_callbacks_dashboards_management
from depictio.dash.layouts.dashboards_management import layout as dashboards_management_layout

register_callbacks_dashboards_management(app)
from depictio.dash.layouts.users_management import is_user_logged_in, register_callbacks_users_management
from depictio.dash.layouts.users_management import layout as users_management_layout

register_callbacks_users_management(app)


@app.callback(
    Output("page-content", "children"),
    Output("second-url", "pathname"),
    [Input("second-url", "pathname"), State("session-store", "data")],
)
def display_page(pathname, session_data):

    logger.info(f"session_data: {session_data}")

    if not session_data["logged_in"]:
        logger.info("User not logged in")
        logger.info(f"pathname: {pathname}")
        return create_users_management_layout(), "/auth"

    if pathname is None:
        return dash.no_update, "/"
    elif pathname.startswith("/dashboard/"):
        dashboard_id = pathname.split("/")[-1]
        logger.info(f"dashboard_id: {dashboard_id}")
        return create_dashboard_layout(dashboard_id=dashboard_id), pathname
    elif pathname == "/auth":
        return create_dashboards_management_layout(), "/"
    else:
        return create_dashboards_management_layout(), pathname


def create_dashboards_management_layout():
    return dashboards_management_layout


def create_users_management_layout():
    return users_management_layout


def create_dashboard_layout(dashboard_id=None):
    # Load depictio depictio_dash_data from JSON
    depictio_dash_data = load_depictio_data(dashboard_id)
    logger.info(f"dashboard_id: {dashboard_id}")
    logger.info(f"depictio_dash_data: {depictio_dash_data}")

    # Init layout and children if depictio_dash_data is available, else set to empty
    if depictio_dash_data:
        if "stored_layout_data" in depictio_dash_data:
            init_layout = depictio_dash_data["stored_layout_data"]
        else:
            init_layout = {}
        if "stored_children_data" in depictio_dash_data:
            init_children = depictio_dash_data["stored_children_data"]
        else:
            init_children = list()

    logger.info(f"Loaded depictio init_layout: {init_layout}")
    header, backend_components = design_header(depictio_dash_data)

    # Generate draggable layout
    core = design_draggable(depictio_dash_data, init_layout, init_children)

    return dbc.Container(
        [
            html.Div(
                [
                    # Backend components & header
                    backend_components,
                    header,
                    # Draggable layout
                    core,
                ],
            ),
            html.Div(id="test-input"),
            html.Div(id="test-output", style={"display": "none"}),
            html.Div(id="test-output-visible"),
        ],
        fluid=True,
    )


def create_app_layout():
    return dbc.Container(
        [
            dcc.Location(id="second-url", refresh=False),
            dcc.Store(id="session-store", storage_type="session", data={"logged_in": False}),
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
