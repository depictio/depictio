import datetime
import dash_mantine_components as dmc
import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, ctx
import httpx
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.models import User
from depictio.api.v1.endpoints.dashboards_endpoints.models import DashboardData
from depictio.api.v1.endpoints.user_endpoints.models import UserBase

# Define styles and colors
card_styles = {
    "boxShadow": "0 4px 6px rgba(0, 0, 0, 0.1)",
    "borderRadius": "8px",
    "padding": "20px",
    "marginBottom": "20px",
}


def render_dashboardwise_layout(dashboard):
    dashboard = DashboardData.from_mongo(dashboard)

    logger.info(f"Dashboard: {dashboard}")
    logger.info(f"Owner : {dashboard.permissions.owners[0]}")
    logger.info(f"Owner : {dashboard.permissions.owners[0].mongo()}")

    # Badge color based on admin status
    import json
    from depictio.api.v1.models.base import convert_objectid_to_str

    dashboard_owner_raw = convert_objectid_to_str(dashboard.permissions.owners[0].mongo()) if dashboard.permissions.owners else "Unknown"
    dashboard_owner = json.dumps(dashboard_owner_raw) if dashboard_owner_raw != "Unknown" else "Unknown"
    dashboard_viewers = ["None"]
    if dashboard.permissions.viewers:
        dashboard_viewers = [json.dumps(convert_objectid_to_str(viewer.mongo())) if viewer != "*" else "*" for viewer in dashboard.permissions.viewers]

    # dashboard_viewers = [u.mongo() for u in dashboard.permissions.viewers] if dashboard.permissions.viewers else ["None"]
    last_saved = dashboard.last_saved_ts
    dashboard_title = f"{dashboard.title} - {dashboard_owner_raw['email']}"
    components_count = len(dashboard.stored_metadata)
    dashboard_id = dashboard.dashboard_id
    public_dashboard = True if "*" in dashboard.permissions.viewers else False

    layout = dmc.Accordion(
        children=[
            dmc.AccordionItem(
                [
                    dmc.AccordionControl(
                        [
                            dmc.Group(
                                [
                                    dmc.Text(dashboard_title, weight=500, size="lg", style={"flex": 1}),
                                    dmc.Badge(
                                        "Public" if public_dashboard else "Private",
                                        color="blue" if public_dashboard else "gray",
                                        variant="light",
                                        size="md",
                                        radius="sm",
                                    ),
                                ],
                                position="apart",
                            ),
                        ]
                    ),
                    dmc.AccordionPanel(
                        [
                            dmc.Group(
                                spacing="xs",
                                position="apart",
                                children=[
                                    dmc.Stack(
                                        spacing="xs",
                                        style={"marginBottom": "15px"},
                                        children=[
                                            dmc.Group(
                                                [
                                                    dmc.Text("Database entry ID: ", weight=700, size="sm"),
                                                    dmc.Text(str(dashboard.id), size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Dashboard ID: ", weight=700, size="sm"),
                                                    dmc.Text(str(dashboard_id), size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Owner: ", weight=700, size="sm"),
                                                    dmc.Text(dashboard_owner, size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Viewers: ", weight=700, size="sm"),
                                                    dmc.List([dmc.ListItem(viewer) for viewer in dashboard_viewers], size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Components: ", weight=700, size="sm"),
                                                    dmc.Text(str(components_count), size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Last Saved: ", weight=700, size="sm"),
                                                    dmc.Text(last_saved, size="sm"),
                                                ]
                                            ),
                                        ],
                                    ),
                                    # dmc.Button(
                                    #     [DashIconify(icon="mdi:delete", width=16, height=16), " Delete"],
                                    #     color="red",
                                    #     variant="filled",
                                    #     size="sm",
                                    #     id={"type": "delete-dashboard-button", "index": str(dashboard_id)},  # Replace dashboard_id with the appropriate identifier
                                    #     styles={"root": {"marginLeft": "10px"}},
                                    # ),
                                ],
                            ),
                        ],
                    ),
                ],
                value=str(dashboard_id),
            ),
        ],
        # withBorder=True,
        # shadow="sm",
        radius="md",
        # style=card_styles,
    )

    return layout


def render_userwise_layout(user):
    user = User.from_mongo(user)

    # Badge color based on admin status
    badge_color = "blue" if user.is_admin else "gray"
    badge_label = "System Admin" if user.is_admin else "User"

    # Format dates for better readability
    registration_date = user.registration_date.strftime("%B %d, %Y %H:%M") if isinstance(user.registration_date, datetime.datetime) else user.registration_date
    last_login = user.last_login.strftime("%B %d, %Y %H:%M") if isinstance(user.last_login, datetime.datetime) else user.last_login

    layout = dmc.Accordion(
        children=[
            # dmc.Group(
            #     # position="",
            #     style={"marginBottom": "15px"},
            #     children=[
            dmc.AccordionItem(
                [
                    dmc.AccordionControl(
                        [
                            dmc.Group(
                                [
                                    dmc.Text(user.email, weight=500, size="lg", style={"flex": 1}),
                                    dmc.Badge(
                                        badge_label,
                                        color=badge_color,
                                        variant="light",
                                        size="md",
                                        radius="sm",
                                    ),
                                ],
                                position="apart",
                            ),
                        ]
                    ),
                    dmc.AccordionPanel(
                        [
                            dmc.Group(
                                spacing="xs",
                                position="apart",
                                children=[
                                    dmc.Stack(
                                        spacing="xs",
                                        style={"marginBottom": "15px"},
                                        children=[
                                            dmc.Group(
                                                [
                                                    dmc.Text("Registration Date: ", weight=700, size="sm"),
                                                    dmc.Text(registration_date, size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Last Login: ", weight=700, size="sm"),
                                                    dmc.Text(last_login, size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Groups: ", weight=700, size="sm"),
                                                    dmc.List([dmc.ListItem(group) for group in user.groups] if user.groups else [dmc.ListItem("None")], size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Account Status: ", weight=700, size="sm"),
                                                    dmc.Badge(
                                                        "Active" if user.is_active else "Inactive",
                                                        color="green" if user.is_active else "red",
                                                        variant="light",
                                                        size="sm",
                                                        radius="sm",
                                                    ),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Verified: ", weight=700, size="sm"),
                                                    dmc.Text("Yes" if user.is_verified else "No", size="sm"),
                                                ]
                                            ),
                                        ],
                                    ),
                                    # dmc.Button(
                                    #     [DashIconify(icon="mdi:delete", width=16, height=16), " Delete"],
                                    #     color="red",
                                    #     variant="filled",
                                    #     size="sm",
                                    #     id={"type": "delete-user-button", "index": str(user.id)},  # Replace user.id with the appropriate identifier
                                    #     styles={"root": {"marginLeft": "10px"}},
                                    # ),
                                ],
                            ),
                            #     ],
                            # ),
                        ],
                    ),
                ],
                value=str(user.id),
            ),
        ],
        # withBorder=True,
        # shadow="sm",
        radius="md",
        # style=card_styles,
    )

    return layout


def register_admin_callbacks(app):
    @app.callback(
        Output("admin-management-content", "children"),
        Input("url", "pathname"),
        Input("admin-tabs", "value"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def create_admin_management_content(pathname, active_tab, local_data):
        if not local_data["access_token"]:
            return html.P("No access token found. Please log in.")

        # content = html.Div(
        #     f"Hi there! You are logged in as {user.email}.",
        #     style={"padding": "20px"},
        # )

        if active_tab == "users":
            response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/auth/list", headers={"Authorization": f"Bearer {local_data['access_token']}"})
            logger.info(f"Response: {response}")
            if response.status_code == 200:
                users = response.json()
                userwise_layouts = [render_userwise_layout(user) for user in users]
                content = html.Div(userwise_layouts)
            else:
                logger.error(f"Error fetching users: {response.json()}")
                content = html.P("Error fetching users. Please try again later.")

            return content
        elif active_tab == "dashboards":
            response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/dashboards/list_all", headers={"Authorization": f"Bearer {local_data['access_token']}"})
            logger.info(f"Response: {response}")
            # content = html.P("DASHBOARDS - Under construction.")
            if response.status_code == 200:
                dashboards = response.json()
                dashboards_layouts = [render_dashboardwise_layout(dashboard) for dashboard in dashboards]
                content = html.Div(dashboards_layouts)
            else:
                logger.error(f"Error fetching dashboards: {response.json()}")
                content = html.P("Error fetching dashboards. Please try again later.")
            return content

        else:
            return html.P("Under construction.")
