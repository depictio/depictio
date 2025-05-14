import datetime

import dash
import dash_mantine_components as dmc
import httpx
from dash import ALL, MATCH, Input, Output, State, ctx, html
from dash_iconify import DashIconify
from pydantic import validate_call

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token, api_create_group
from depictio.dash.layouts.layouts_toolbox import (
    create_delete_confirmation_modal,
)

# register_delete_confirmation_modal_callbacks,
from depictio.dash.layouts.projects import render_project_item
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.projects import Project
from depictio.models.models.users import GroupUI, UserBase, UserBaseUI

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

    from depictio.models.models.base import convert_objectid_to_str

    dashboard_owner_raw = (
        convert_objectid_to_str(
            convert_objectid_to_str(dashboard.permissions.owners[0].model_dump(exclude_none=True))
        )
        if dashboard.permissions.owners
        else "Unknown"
    )
    # dashboard_owner = (
    #     json.dumps(dashboard_owner_raw)
    #     if dashboard_owner_raw != "Unknown"
    #     else "Unknown"
    # )
    dashboard_viewers = ["None"]
    if dashboard.permissions.viewers:
        dashboard_viewers = [
            (json.dumps(convert_objectid_to_str(viewer.mongo())) if viewer != "*" else "*")
            for viewer in dashboard.permissions.viewers
        ]

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
                                    dmc.Text(
                                        dashboard_title,
                                        weight=500,
                                        size="lg",
                                        style={"flex": 1},
                                    ),
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
                                                    dmc.Text(
                                                        "Dashboard ID: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.Text(str(dashboard_id), size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Owner: ", weight=700, size="sm"),
                                                    dmc.Text(
                                                        dashboard_owner_raw["email"],
                                                        size="sm",
                                                    ),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text(
                                                        "Viewers: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.List(
                                                        [
                                                            dmc.ListItem(viewer)
                                                            for viewer in dashboard_viewers
                                                        ],
                                                        size="sm",
                                                    ),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text(
                                                        "Components: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.Text(str(components_count), size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text(
                                                        "Last Saved: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
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


@validate_call
def render_groupwise_layout(group: GroupUI, all_users: list) -> dmc.Accordion:
    """
    Render the layout for a group.
    """

    logger.info(f"Group: {group}")
    logger.info(f"Group ID: {group.id}")
    logger.info(f"Group Name: {group.name}")

    save_group_button = dmc.Button(
        "Save",
        color="blue",
        variant="filled",
        size="xs",
        id={
            "type": "save-group-users-button",
            "index": str(group.id),
        },
    )
    actions_text = dmc.Text(
        "Actions: ",
        weight=700,
        size="sm",
    )

    if group.name not in ["admin", "users"]:
        delete_group_button_id = {"type": "delete-group-button", "index": str(group.id)}
        delete_group_button = dmc.Button(
            "Delete",
            color="red",
            variant="filled",
            size="xs",
            id=delete_group_button_id,  # Replace user.id with the appropriate identifier
        )

        modal_delete_group, modal_delete_group_id = create_delete_confirmation_modal(
            id_prefix="group",
            item_id=str(group.id),
            title=f"Delete group {group.name}?",
        )
    elif group.name == "admin":
        save_group_button = None
        delete_group_button = None
        modal_delete_group = None
        actions_text = None

    elif group.name == "users":
        modal_delete_group = None
        delete_group_button = None

    layout = dmc.Accordion(
        children=[
            dmc.AccordionItem(
                [
                    dmc.AccordionControl(
                        [
                            dmc.Group(
                                [
                                    dmc.Text(
                                        group.name,
                                        weight=500,
                                        size="lg",
                                        style={"flex": 1},
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
                                                    dmc.Text(
                                                        "Group ID: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.Text(str(group.id), size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text(
                                                        "Users: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.List(
                                                        (
                                                            [
                                                                dmc.ListItem(user.email)
                                                                for user in group.users
                                                            ]
                                                            if group.users
                                                            else [dmc.ListItem("None")]
                                                        ),
                                                        size="sm",
                                                    ),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.TransferList(
                                                        id={
                                                            "type": "group-users-transferlist",
                                                            "index": str(group.id),
                                                        },
                                                        value=[
                                                            [
                                                                {
                                                                    "value": str(user.id),
                                                                    "label": user.email,
                                                                }
                                                                for user in all_users
                                                                if user.email
                                                                not in [
                                                                    u.email for u in group.users
                                                                ]
                                                            ],
                                                            [
                                                                {
                                                                    "value": str(user.id),
                                                                    "label": user.email,
                                                                }
                                                                for user in group.users
                                                            ],
                                                        ],
                                                        titles=[
                                                            "All Users",
                                                            "Group Users",
                                                        ],
                                                        searchPlaceholder="Search users...",
                                                        style={
                                                            "flex": 1,
                                                            "width": "100%",
                                                        },
                                                    )
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    # dmc.Button(
                                                    #     "Delete",
                                                    #     color="red",
                                                    #     variant="filled",
                                                    #     size="xs",
                                                    #     id={
                                                    #         "type": "delete-group-button",
                                                    #         "index": str(group.id),
                                                    #     },
                                                    # ),
                                                    actions_text,
                                                    delete_group_button,
                                                    modal_delete_group,
                                                    save_group_button,
                                                ]
                                            ),
                                        ],
                                    ),
                                    # dmc.Button(
                                    #     [DashIconify(icon="mdi:delete", width=16, height=16), " Delete"],
                                    #     color="red",
                                    #     variant="filled",
                                    #     size="sm",
                                    #     id={"type": "delete-group-button", "index": str(group.id)},  # Replace group.id with the appropriate identifier
                                    #     styles={"root": {"marginLeft": "10px"}},
                                    # ),
                                ],
                            ),
                        ],
                    ),
                ],
                value=str(group.id),
            ),
        ],
        # withBorder=True,
        # shadow="sm",
        radius="md",
        # style=card_styles,
    )

    return layout


@validate_call
def render_userwise_layout(user: UserBaseUI) -> dmc.Accordion:
    """
    Render the layout for a user.

    """

    logger.info(f"User: {user}")

    # Badge color based on admin status
    badge_color = "blue" if user.is_admin else "gray"
    badge_label = "System Admin" if user.is_admin else "User"

    # Format dates for better readability
    registration_date = (
        user.registration_date.strftime("%B %d, %Y %H:%M")
        if isinstance(user.registration_date, datetime.datetime)
        else user.registration_date
    )
    last_login = (
        user.last_login.strftime("%B %d, %Y %H:%M")
        if isinstance(user.last_login, datetime.datetime)
        else user.last_login
    )

    delete_user_button_id = {"type": "delete-user-button", "index": str(user.id)}
    delete_user_button = dmc.Button(
        "Delete",
        color="red",
        variant="filled",
        size="xs",
        id=delete_user_button_id,  # Replace user.id with the appropriate identifier
    )

    modal_delete_user, modal_delete_user_id = create_delete_confirmation_modal(
        id_prefix="user",
        item_id=str(user.id),
        title=f"Delete user {user.email}?",
    )
    # register_delete_confirmation_modal_callbacks(
    #     app=get_app(),
    #     id_prefix=modal_delete_user_id,
    #     trigger_button_id=delete_user_button_id,
    # )

    logger.info(f"Modal ID: {modal_delete_user_id}")

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
                                    dmc.Text(
                                        user.email,
                                        weight=500,
                                        size="lg",
                                        style={"flex": 1},
                                    ),
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
                                                    dmc.Text(
                                                        "User ID: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.Text(str(user.id), size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text(
                                                        "Registration Date: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.Text(registration_date, size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text(
                                                        "Last Login: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.Text(last_login, size="sm"),
                                                ]
                                            ),
                                            # dmc.Group(
                                            #     [
                                            #         dmc.Text(
                                            #             "Groups: ",
                                            #             weight=700,
                                            #             size="sm",
                                            #         ),
                                            #         dmc.SimpleGrid(
                                            #             [
                                            #                 dmc.Group(
                                            #                     [
                                            #                         dmc.Text(
                                            #                             group.name,
                                            #                             size="sm",
                                            #                         ),
                                            #                         dmc.Text(
                                            #                             str(group.id),
                                            #                             size="sm",
                                            #                         ),
                                            #                     ],
                                            #                     style={
                                            #                         "flex": 1,
                                            #                         "border": "1px solid #e1e1e1",
                                            #                     },
                                            #                 )
                                            #                 for group in user.groups
                                            #             ]
                                            #             if user.groups
                                            #             else [
                                            #                 dmc.Text("None", size="sm")
                                            #             ],
                                            #             cols=5,
                                            #         ),
                                            #         # dmc.List([dmc.ListItem(group) for group in user.groups] if user.groups else [dmc.ListItem("None")], size="sm"),
                                            #     ]
                                            # ),
                                            dmc.Group(
                                                [
                                                    dmc.Text(
                                                        "Account Status: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.Badge(
                                                        (
                                                            "Active"
                                                            if user.is_active
                                                            else "Inactive"
                                                        ),
                                                        color=(
                                                            "green" if user.is_active else "red"
                                                        ),
                                                        variant="light",
                                                        size="sm",
                                                        radius="sm",
                                                    ),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text(
                                                        "Verified: ",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.Text(
                                                        ("Yes" if user.is_verified else "No"),
                                                        size="sm",
                                                    ),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text(
                                                        "User status:",
                                                        weight=700,
                                                        size="sm",
                                                    ),
                                                    dmc.SegmentedControl(
                                                        # "Make System Admin",
                                                        value=str(user.is_admin),
                                                        data=[
                                                            {
                                                                "label": "Standard",
                                                                "value": str(False),
                                                            },
                                                            {
                                                                "label": "System Admin",
                                                                "value": str(True),
                                                            },
                                                        ],
                                                        color="blue",
                                                        # variant="filled",
                                                        size="xs",
                                                        id={
                                                            "type": "turn-sysadmin-user-button",
                                                            "index": str(user.id),
                                                        },
                                                    ),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Actions", weight=700, size="sm"),
                                                    delete_user_button,
                                                    modal_delete_user,
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


@validate_call
def fetch_projects_for_admin(token: str) -> list[Project]:
    """
    Fetch all projects using the existing get_all_projects endpoint.
    For admin users, this will return all projects in the system.
    """
    url = f"{API_BASE_URL}/depictio/api/v1/projects/get/all"

    headers = {"Authorization": f"Bearer {token}"}
    projects = httpx.get(url, headers=headers)
    logger.info("Successfully fetched projects for admin view.")
    logger.info(f"Projects: {projects.json()}")

    projects = [Project.from_mongo(project) for project in projects.json()]
    return projects


# Override the render_project_item function to show owner email instead of "Owned"
def admin_render_project_item(project: Project, current_user: UserBase, token: str):
    """
    Modified version of render_project_item that shows the owner's email instead of "Owned".
    All badges are blue as requested.
    """
    # Get the original project item
    project_item = render_project_item(project, current_user, admin_UI=True, token=token)

    return project_item


def register_admin_callbacks(app):
    @app.callback(
        Output({"type": "user-delete-confirmation-modal", "index": MATCH}, "opened"),
        Input({"type": "delete-user-button", "index": MATCH}, "n_clicks"),
        Input({"type": "cancel-user-delete-button", "index": MATCH}, "n_clicks"),
        State({"type": "user-delete-confirmation-modal", "index": MATCH}, "opened"),
        prevent_initial_call=True,
    )
    def open_user_delete_modal(n_clicks, n_clicks_cancel, opened):
        ctx = dash.callback_context
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"Trigger ID: {trigger_id}")
        logger.info(f"Opened: {opened}")
        logger.info(f"n_clicks: {n_clicks}")
        logger.info(f"n_clicks_cancel: {n_clicks_cancel}")
        if n_clicks:
            return not opened
        elif n_clicks_cancel:
            return False
        return False

    @app.callback(
        Output({"type": "group-delete-confirmation-modal", "index": MATCH}, "opened"),
        Input({"type": "delete-group-button", "index": MATCH}, "n_clicks"),
        Input({"type": "cancel-group-delete-button", "index": MATCH}, "n_clicks"),
        State({"type": "group-delete-confirmation-modal", "index": MATCH}, "opened"),
        prevent_initial_call=True,
    )
    def open_group_delete_modal(n_clicks, n_clicks_cancel, opened):
        ctx = dash.callback_context
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"Trigger ID: {trigger_id}")
        logger.info(f"Opened: {opened}")
        logger.info(f"n_clicks: {n_clicks}")
        logger.info(f"n_clicks_cancel: {n_clicks_cancel}")
        if n_clicks:
            return not opened
        elif n_clicks_cancel:
            return False
        return False

    @app.callback(
        Output("group-add-confirmation-modal", "opened"),
        Output("group-add-confirmation-modal-message", "children"),
        Output("group-add-confirmation-modal-message", "style"),
        State("group-add-confirmation-modal", "opened"),
        Input("confirm-group-add-button", "n_clicks"),
        Input("cancel-group-add-button", "n_clicks"),
        Input("group-add-button", "n_clicks"),
        State("group-add-modal-text-input", "value"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def add_group(
        opened,
        confirm_clicks,
        cancel_clicks,
        add_clicks,
        group_name,
        local_data,
    ):
        ctx = dash.callback_context
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger_id == "group-add-button":
            return True, None, {"display": "none"}
        elif trigger_id == "confirm-group-add-button":
            if not local_data["access_token"]:
                return False, html.P("No access token found. Please log in.")
            if not group_name:
                return True, html.P("Group name cannot be empty."), {"display": "block"}
            group = api_create_group({"name": group_name}, local_data["access_token"])
            if group:
                return False, html.P("Group added successfully."), {"display": "none"}
            else:
                return (
                    True,
                    html.P(f"Error adding group. Error - {group}"),
                    {"display": "block"},
                )
        else:
            return False, None, {"display": "none"}

    @app.callback(
        Output("admin-management-content", "children"),
        Output("group-add-button", "style"),
        Input("confirm-group-add-button", "n_clicks"),
        Input({"type": "confirm-group-delete-button", "index": ALL}, "n_clicks"),
        State({"type": "confirm-group-delete-button", "index": ALL}, "id"),
        Input({"type": "save-group-users-button", "index": ALL}, "n_clicks"),
        State({"type": "save-group-users-button", "index": ALL}, "id"),
        State({"type": "group-users-transferlist", "index": ALL}, "value"),
        Input("url", "pathname"),
        Input("admin-tabs", "value"),
        Input({"type": "confirm-user-delete-button", "index": ALL}, "n_clicks"),
        State({"type": "confirm-user-delete-button", "index": ALL}, "id"),
        Input({"type": "turn-sysadmin-user-button", "index": ALL}, "value"),
        State({"type": "turn-sysadmin-user-button", "index": ALL}, "id"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def create_admin_management_content(
        add_group_clicks,
        delete_group_clicks,
        delete_group_ids,
        save_group_users_clicks,
        save_group_users_ids,
        transferlist_values,
        pathname,
        active_tab,
        delete_user_clicks,
        delete_user_ids,
        turn_sysadmin_values,
        turn_sysadmin_ids,
        local_data,
    ):
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"Trigger ID: {trigger_id}")
        logger.info(f"Trigger ID type: {type(trigger_id)}")

        if not local_data["access_token"]:
            return html.P("No access token found. Please log in.")

        # content = html.Div(
        #     f"Hi there! You are logged in as {user.email}.",
        #     style={"padding": "20px"},
        # )

        if active_tab == "users":
            # check if one of the delete user buttons was clicked
            if delete_user_clicks:
                logger.info(f"Delete user button clicked: {delete_user_ids}")
                # retrieve user id by cross-referencing the button id

                for button_id, n_click_index in zip(delete_user_ids, delete_user_clicks):
                    if n_click_index:
                        user_id = button_id["index"]
                        logger.info(f"Deleting user: {user_id}")
                        response = httpx.delete(
                            f"{API_BASE_URL}/depictio/api/v1/auth/delete/{user_id}",
                            headers={"Authorization": f"Bearer {local_data['access_token']}"},
                        )
                        logger.info(f"Response: {response}")
                        if response.status_code == 200:
                            logger.info(f"Successfully deleted user: {user_id}")
                        else:
                            logger.error(f"Error deleting user: {response.json()}")
                            return html.P("Error deleting user. Please try again later."), {
                                "display": "none"
                            }

            if "turn-sysadmin-user-button" in trigger_id:
                # turn into dict
                trigger_id = eval(trigger_id)
                logger.info(f"Trigger ID: {trigger_id}")
                logger.info(f"type of trigger_id: {type(trigger_id)}")
                trigger_id_index = trigger_id["index"]
                logger.info(f"trigger_id_index: {trigger_id_index}")
                logger.info(f"Turn sysadmin button clicked: {turn_sysadmin_ids}")
                logger.info(f"Values: {turn_sysadmin_values}")
                # retrieve user id by cross-referencing the button id

                for button_id, value in zip(turn_sysadmin_ids, turn_sysadmin_values):
                    if trigger_id_index == button_id["index"]:
                        user_id = button_id["index"]
                        is_admin = value
                        logger.info(f"Value: {value}")
                        logger.error(f"Making user system admin: {user_id}")
                        response = httpx.post(
                            f"{API_BASE_URL}/depictio/api/v1/auth/turn_sysadmin/{user_id}/{is_admin}",
                            headers={"Authorization": f"Bearer {local_data['access_token']}"},
                        )
                        logger.info(f"Response: {response}")
                        if response.status_code == 200:
                            logger.info(f"Successfully made user system admin: {user_id}")
                        else:
                            logger.error(f"Error making user system admin: {response.json()}")
                            return html.P(
                                "Error making user system admin. Please try again later"
                            ), {"display": "none"}

            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/auth/list",
                headers={"Authorization": f"Bearer {local_data['access_token']}"},
            )
            logger.info(f"Response: {response}")

            if response.status_code == 200:
                users = response.json()
                logger.info(f"Users: {users}")
                userwise_layouts = [
                    render_userwise_layout(UserBaseUI.from_mongo(user)) for user in users
                ]
                content = html.Div(userwise_layouts)
            else:
                logger.error(f"Error fetching users: {response.json()}")
                content = html.P("Error fetching users. Please try again later.")

            return content, {"display": "none"}
        elif active_tab == "groups":
            logger.info("\n GROUPS \n")

            # if delete_group_clicks:
            #     logger.info(f"Delete group button clicked: {delete_group_ids}")
            #     # retrieve group id by cross-referencing the button id

            #     for button_id, n_click_index in zip(
            #         delete_group_ids, delete_group_clicks
            #     ):
            #         if n_click_index:
            #             group_id = button_id["index"]
            #             logger.info(f"Deleting group: {group_id}")
            #             response = httpx.delete(
            #                 f"{API_BASE_URL}/depictio/api/v1/auth/delete_group/{group_id}",
            #                 headers={
            #                     "Authorization": f"Bearer {local_data['access_token']}"
            #                 },
            #             )
            #             logger.info(f"Response: {response}")
            #             if response.status_code == 200:
            #                 logger.info(f"Successfully deleted group: {group_id}")
            #             else:
            #                 logger.error(f"Error deleting group: {response.json()}")
            #                 return html.P(
            #                     "Error deleting group. Please try again later."
            #                 ), {"display": "none"}

            # if "save-group-users-button" in trigger_id:
            #     logger.info("SAVE GROUP USERS BUTTON CLICKED")
            #     logger.info(
            #         f"Save group users button clicked clicks: {save_group_users_clicks}"
            #     )
            #     logger.info(f"Save group users button clicked: {save_group_users_ids}")
            #     logger.info(f"Transferlist values: {transferlist_values}")
            #     trigger_id_index = eval(trigger_id)["index"]
            #     logger.info(f"Trigger ID: {trigger_id}")
            #     logger.info(f"Trigger ID index: {trigger_id_index}")
            #     # start at 1 to skip the first value which corresponds to admin group
            #     for transfert_list_value, save_id in zip(
            #         transferlist_values[1:], save_group_users_ids
            #     ):
            #         logger.info(f"save_id['index']: {save_id['index']}")
            #         logger.info(f"Trigger ID index: {trigger_id_index}")
            #         if str(save_id["index"]) == str(trigger_id_index):
            #             logger.info(f"Transferlist value: {transfert_list_value}")
            #             logger.info(f"Group ID: {trigger_id_index}")
            #             all_users = transfert_list_value[0]
            #             group_users = transfert_list_value[1]
            #             logger.info(f"Group users: {group_users}")

            #             group_id = trigger_id_index
            #             # group_users = transfert_list_value[1]
            #             # logger.info(f"Group users: {group_users}")
            #             from depictio.models.models.users import UserBase

            #             group_users = [
            #                 {"email": user["label"], "id": str(user["value"])}
            #                 for user in group_users
            #             ]
            #             logger.info(f"Group users: {group_users}")
            #             api_update_group_in_users(
            #                 group_id,
            #                 {"users": group_users},
            #                 local_data["access_token"],
            #             )
            #             # logger.info(f"Group users: {group_users}")
            #             # response = httpx.post(
            #             #     f"{API_BASE_URL}/depictio/api/v1/auth/update_group_users/{group_id}",
            #             #     headers={
            #             #         "Authorization": f"Bearer {local_data['access_token']}"
            #             #     },
            #             #     json={"users": group_users},
            #             # )
            #             # logger.info(f"Response: {response}")
            #             # if response.status_code == 200:
            #             #     logger.info(f"Successfully updated group users: {group_id}")
            #             # else:
            #             #     logger.error(f"Error updating group users: {response.json()}")
            #             #     return html.P(
            #             #         "Error updating group users. Please try again later."
            #             #     ), {"display": "none"}

            # reponse_all_users = httpx.get(
            #     f"{API_BASE_URL}/depictio/api/v1/auth/list",
            #     headers={"Authorization": f"Bearer {local_data['access_token']}"},
            # )
            # if reponse_all_users.status_code == 200:
            #     from depictio.models.models.users import UserBase

            #     all_users = reponse_all_users.json()
            #     all_users = [UserBase.from_mongo(user) for user in all_users]
            #     logger.info(f"Users: {all_users}")
            # else:
            #     logger.error(f"Error fetching users: {reponse_all_users.json()}")
            #     all_users = []

            # response = httpx.get(
            #     f"{API_BASE_URL}/depictio/api/v1/auth/get_all_groups_including_users",
            #     headers={"Authorization": f"Bearer {local_data['access_token']}"},
            # )
            # logger.info(f"Response: {response}")

            # if response.status_code == 200:
            #     groups = response.json()
            #     logger.info(f"Groups: {groups}")
            #     groupwise_layouts = [
            #         render_groupwise_layout(GroupUI.from_mongo(group), all_users)
            #         for group in groups
            #     ]

            #     content = html.Div(
            #         groupwise_layouts
            #         # [add_group_button, modal, html.Div(groupwise_layouts)]
            #     )
            # else:
            #     logger.error(f"Error fetching groups: {response.json()}")
            #     content = html.P("Error fetching groups. Please try again later.")

            # return content, {"display": "block"}

            content = dmc.Center(
                dmc.Paper(
                    children=[
                        dmc.Stack(
                            children=[
                                dmc.Center(
                                    DashIconify(
                                        icon="material-symbols:group-off",
                                        width=64,
                                        height=64,
                                        color="#6c757d",
                                    )
                                ),
                                dmc.Text(
                                    "No groups available - Ongoing feature",
                                    align="center",
                                    weight=700,
                                    size="xl",
                                ),
                                dmc.Text(
                                    "Groups created by users will appear here.",
                                    align="center",
                                    color="dimmed",
                                    size="sm",
                                ),
                            ],
                            align="center",
                            spacing="sm",
                        )
                    ],
                    shadow="sm",
                    radius="md",
                    p="xl",
                    withBorder=True,
                    style={"width": "100%", "maxWidth": "500px"},
                ),
                style={"height": "300px"},
            )

            return content, {"display": "none"}

        elif active_tab == "dashboards":
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/dashboards/list_all",
                headers={"Authorization": f"Bearer {local_data['access_token']}"},
            )
            logger.info(f"Response: {response}")
            # content = html.P("DASHBOARDS - Under construction.")
            if response.status_code == 200:
                dashboards = response.json()
                dashboards_layouts = [
                    render_dashboardwise_layout(dashboard) for dashboard in dashboards
                ]
                if len(dashboards_layouts) == 0:
                    dashboards_layouts = [
                        dmc.Center(
                            dmc.Paper(
                                children=[
                                    dmc.Stack(
                                        children=[
                                            dmc.Center(
                                                DashIconify(
                                                    icon="ph:empty-bold",
                                                    width=64,
                                                    height=64,
                                                    color="#6c757d",
                                                )
                                            ),
                                            dmc.Text(
                                                "No dashboards available",
                                                align="center",
                                                weight=700,
                                                size="xl",
                                            ),
                                            dmc.Text(
                                                "Dashboards created by users will appear here.",
                                                align="center",
                                                color="dimmed",
                                                size="sm",
                                            ),
                                        ],
                                        align="center",
                                        spacing="sm",
                                    )
                                ],
                                shadow="sm",
                                radius="md",
                                p="xl",
                                withBorder=True,
                                style={"width": "100%", "maxWidth": "500px"},
                            ),
                            style={"height": "300px"},
                        )
                    ]

                content = html.Div(dashboards_layouts)
            else:
                logger.error(f"Error fetching dashboards: {response.json()}")
                content = html.P("Error fetching dashboards. Please try again later.")
            return content, {"display": "none"}
        elif active_tab == "projects":
            # Fetch all projects for admin view using the existing endpoint
            try:
                projects = fetch_projects_for_admin(local_data["access_token"])
                current_user = api_call_fetch_user_from_token(local_data["access_token"])

                if projects:
                    # Create project items with modified render function to show owner email
                    project_items = [
                        admin_render_project_item(
                            project=project,
                            current_user=current_user,
                            token=local_data["access_token"],
                        )
                        for project in projects
                    ]

                    content = dmc.Container(
                        children=[
                            dmc.Accordion(
                                children=project_items,
                                chevronPosition="right",
                                className="mb-4",
                            ),
                        ],
                        fluid=True,
                    )
                else:
                    content = dmc.Center(
                        dmc.Paper(
                            children=[
                                dmc.Stack(
                                    children=[
                                        dmc.Center(
                                            DashIconify(
                                                icon="material-symbols:folder-off-outline",
                                                width=64,
                                                height=64,
                                                color="#6c757d",
                                            )
                                        ),
                                        dmc.Text(
                                            "No projects available",
                                            align="center",
                                            weight=700,
                                            size="xl",
                                        ),
                                        dmc.Text(
                                            "Projects created by users will appear here.",
                                            align="center",
                                            color="dimmed",
                                            size="sm",
                                        ),
                                    ],
                                    align="center",
                                    spacing="sm",
                                )
                            ],
                            shadow="sm",
                            radius="md",
                            p="xl",
                            withBorder=True,
                            style={"width": "100%", "maxWidth": "500px"},
                        ),
                        style={"height": "300px"},
                    )

                return content, {"display": "none"}
            except Exception as e:
                logger.error(f"Error fetching projects: {e}")
                return html.P(f"Error fetching projects: {str(e)}"), {"display": "none"}
        else:
            return html.P("Under construction."), {"display": "none"}
