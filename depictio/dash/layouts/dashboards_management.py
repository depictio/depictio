import os
import shutil
from datetime import datetime

import dash
import dash_mantine_components as dmc
import httpx
from bson import ObjectId
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token, api_get_project_from_id
from depictio.dash.colors import colors  # Import Depictio color palette
from depictio.dash.layouts.layouts_toolbox import (
    create_dashboard_modal,
    create_delete_confirmation_modal,
)
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission

modal, modal_id = create_dashboard_modal()

layout = html.Div(
    [
        dcc.Store(id="dashboard-modal-store", storage_type="session", data={"title": ""}),
        dcc.Store(id="init-create-dashboard-button", storage_type="memory", data=False),
        modal,
        html.Div(id="landing-page"),  # Initially hidden
    ]
)


def load_dashboards_from_db(token):
    logger.info("Loading dashboards from the database")
    if not token:
        raise ValueError("Token is required to load dashboards from the database.")

    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/list",
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code == 200:
            dashboards = response.json()

            return {"dashboards": dashboards}

        else:
            raise ValueError(f"Failed to load dashboards from the database. Error: {response.text}")

    except Exception as e:
        logger.error(f"Error loading dashboards from the database: {e}")
        return {"dashboards": []}


def insert_dashboard(dashboard_id, dashboard_data, token):
    logger.info(f"Inserting dashboard with ID: {dashboard_id} and data: {dashboard_data}")
    if not token:
        raise ValueError("Token is required to insert a dashboard into the database.")

    if not dashboard_data:
        raise ValueError("Dashboard data is required to insert a dashboard into the database.")

    if not dashboard_id:
        raise ValueError("Dashboard ID is required to insert a dashboard into the database.")
    dashboard_data = convert_objectid_to_str(dashboard_data)
    logger.debug(f"Inserting dashboard with ID: {dashboard_id} and data: {dashboard_data}")

    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}",
        headers={"Authorization": f"Bearer {token}"},
        json=dashboard_data,
    )

    if response.status_code == 200:
        logger.info(f"Successfully inserted dashboard: {dashboard_data}")

    else:
        raise ValueError(f"Failed to insert dashboard into the database. Error: {response.text}")


def delete_dashboard(dashboard_id, token):
    logger.info(f"Deleting dashboard with ID: {dashboard_id}")
    response = httpx.delete(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/delete/{dashboard_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    if response.status_code == 200:
        logger.info(f"Successfully deleted dashboard with ID: {dashboard_id}")

    else:
        raise ValueError(f"Failed to delete dashboard from the database. Error: {response.text}")


def edit_dashboard_name(new_name, dashboard_id, dashboards, token):
    logger.info(f"Editing dashboard name for dashboard ID: {dashboard_id}")

    updated_dashboards = list()

    # Iterate over the dashboards to find the dashboard with the matching ID and update the name
    for dashboard in dashboards:
        if dashboard.dashboard_id == dashboard_id:
            logger.info(f"Found dashboard to edit: {dashboard}")
            dashboard.title = new_name
        updated_dashboards.append(dashboard)

    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/edit_name/{dashboard_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_name": new_name},
    )

    if response.status_code == 200:
        logger.info(f"Successfully edited dashboard name: {dashboard}")

    else:
        raise ValueError(f"Failed to edit dashboard name in the database. Error: {response.text}")

    return updated_dashboards


def render_welcome_section(email, is_anonymous=False):
    # Check if user is anonymous and disable button accordingly
    button_disabled = is_anonymous
    button_text = "+ New Dashboard" if not is_anonymous else "Login to Create Dashboards"
    button_variant = "gradient" if not is_anonymous else "outline"
    button_color = {"from": "black", "to": "grey", "deg": 135} if not is_anonymous else "gray"

    return dmc.Grid(
        children=[
            dmc.GridCol(
                dcc.Link(
                    dmc.Tooltip(
                        dmc.Avatar(
                            src=f"https://ui-avatars.com/api/?format=svg&name={email}&background=AEC8FF&color=white&rounded=true&bold=true&format=svg&size=16",
                            size="lg",
                            radius="xl",
                        ),
                        withinPortal=False,
                        label=email,
                        position="bottom",
                    ),
                    href="/profile",
                ),
                span="auto",
            ),
            dmc.GridCol(
                [
                    dmc.Title(
                        f"Welcome, {email}!", order=2, ta="center"
                    ),  # align -> ta in DMC 2.0+
                    dmc.Center(
                        dmc.Button(
                            button_text,
                            id={"type": "create-dashboard-button", "index": email},
                            n_clicks=0,
                            variant=button_variant,
                            gradient=button_color if not is_anonymous else None,
                            color="gray" if is_anonymous else None,
                            style={"margin": "20px 0", "fontFamily": "Virgil"},
                            size="xl",
                            disabled=button_disabled,
                        ),
                    ),
                    dmc.Divider(style={"margin": "20px 0"}),
                    dmc.Title("Your Dashboards", order=3),
                    dmc.Divider(style={"margin": "20px 0"}),
                ],
                span="auto",
                style={"flex": "1"},
            ),
        ],
        gutter="xl",
    )


def render_dashboard_list_section(email):
    return html.Div(
        id={"type": "dashboard-list", "index": email},
        style={
            "padding": "30px",  # Consistent padding with header
            "minHeight": "calc(100vh - 80px)",  # Full height minus header (80px)
        },
    )


def register_callbacks_dashboards_management(app):
    def create_dashboards_view(dashboards):
        logger.debug(f"dashboards: {dashboards}")

        dashboards_view = [
            dmc.Paper(
                dmc.Group(
                    [
                        html.Div(
                            [
                                dmc.Center(dmc.Title(dashboard["title"], order=5)),
                                # dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                                dmc.Text(f"Version: {dashboard['version']}"),
                                dmc.Text(
                                    f"Owner: {dashboard['permissions']['owners'][0]['email']}"
                                ),
                            ],
                            style={"flex": "1"},
                        ),
                        html.A(
                            dmc.Button(
                                "View",
                                id={
                                    "type": "view-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color="blue",
                            ),
                            href=f"/dashboard/{dashboard['dashboard_id']}",
                        ),
                        dmc.Button(
                            "Delete",
                            id={
                                "type": "delete-dashboard-button",
                                "index": dashboard["dashboard_id"],
                            },
                            variant="outline",
                            color="red",
                        ),
                    ],
                    align="center",
                    justify="space-between",
                    grow=False,
                    noWrap=False,
                    style={"width": "100%"},
                ),
                shadow="xs",
                p="md",
                style={"marginBottom": 20},
            )
            for dashboard in dashboards
        ]
        return dashboards_view

    def create_homepage_view(dashboards, user_id, token, current_user):
        logger.debug(f"dashboards: {dashboards}")

        # Create project cache to avoid redundant API calls
        project_cache = {}

        def modal_edit_name_dashboard(dashboard):
            modal = dmc.Modal(
                id={"type": "edit-password-modal", "index": dashboard["dashboard_id"]},
                opened=False,
                centered=True,
                withCloseButton=False,
                # overlayOpacity=0.55,
                # overlayBlur=3,
                overlayProps={
                    "overlayOpacity": 0.55,
                    "overlayBlur": 3,
                },
                shadow="xl",
                radius="md",
                size="md",
                zIndex=1000,
                styles={
                    "modal": {
                        "padding": "24px",
                    }
                },
                children=[
                    dmc.Stack(
                        gap="lg",
                        children=[
                            # Header with icon and title
                            dmc.Group(
                                justify="flex-start",
                                gap="sm",
                                children=[
                                    DashIconify(
                                        icon="mdi:rename-box",
                                        width=28,
                                        height=28,
                                        color="#228be6",  # Dash Mantine blue color
                                    ),
                                    dmc.Title(
                                        "Edit Dashboard Name",
                                        order=4,
                                        style={"margin": 0},
                                    ),
                                ],
                            ),
                            # Divider
                            dmc.Divider(),
                            # Text input field
                            dmc.TextInput(
                                placeholder="Enter new dashboard name",
                                label="Dashboard Name",
                                id={
                                    "type": "new-name-dashboard",
                                    "index": dashboard["dashboard_id"],
                                },
                                radius="md",
                                size="md",
                            ),
                            # Error message
                            dmc.Text(
                                id={
                                    "type": "message-edit-name-dashboard",
                                    "index": dashboard["dashboard_id"],
                                },
                                c="red",
                                size="sm",
                                style={"display": "none"},
                            ),
                            # Buttons
                            dmc.Group(
                                justify="flex-end",
                                gap="md",
                                mt="md",
                                children=[
                                    dmc.Button(
                                        "Cancel",
                                        id={
                                            "type": "cancel-edit-name-dashboard",
                                            "index": dashboard["dashboard_id"],
                                        },
                                        color="gray",
                                        variant="outline",
                                        radius="md",
                                    ),
                                    dmc.Button(
                                        "Save",
                                        id={
                                            "type": "save-edit-name-dashboard",
                                            "index": dashboard["dashboard_id"],
                                        },
                                        color="blue",
                                        radius="md",
                                        leftSection=DashIconify(icon="mdi:content-save", width=16),
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            )
            return modal

        def create_dashboad_view_header(dashboard, user_id, token):
            public = dashboard["is_public"]

            if str(user_id) in [str(owner["_id"]) for owner in dashboard["permissions"]["owners"]]:
                color_badge_ownership = colors["blue"]  # Use Depictio blue
            else:
                color_badge_ownership = "gray"
            badge_icon = "material-symbols:public" if public else "material-symbols:lock"

            badge_owner = dmc.Badge(
                f"Owner: {dashboard['permissions']['owners'][0]['email']}",
                # f"Owner: {dashboard['permissions']['owners'][0]['email']} - {str(dashboard['permissions']['owners'][0]['_id'])}",
                color=color_badge_ownership,
                leftSection=DashIconify(icon="mdi:account", width=16, color="white"),
            )

            # Use project cache to avoid redundant API calls
            project_id_str = str(dashboard["project_id"])
            if project_id_str in project_cache:
                project_name = project_cache[project_id_str]
            else:
                response = api_get_project_from_id(project_id=dashboard["project_id"], token=token)
                if response.status_code == 200:
                    # logger.debug(f"Project response: {response.json()}")
                    project = response.json()
                    project_name = project["name"]
                    project_cache[project_id_str] = project_name  # Cache for next use
                else:
                    logger.error(f"Failed to get project from ID: {dashboard['project_id']}")
                    project_name = "Unknown"
                    project_cache[project_id_str] = project_name  # Cache the failure too

            badge_project = dmc.Badge(
                f"Project: {project_name}",
                color=colors["teal"],  # Use Depictio teal instead of green
                leftSection=DashIconify(icon="mdi:jira", width=16, color="white"),
                style={
                    "maxWidth": "100%",
                    "overflow": "visible",
                    "whiteSpace": "normal",
                    "wordWrap": "break-word",
                },  # Allow text wrapping for long project names
            )
            badge_status = dmc.Badge(
                "Public" if public else "Private",
                color=colors["green"] if public else colors["purple"],  # Use Depictio colors
                leftSection=DashIconify(icon=badge_icon, width=16, color="white"),
            )

            # badge_tooltip_additional_info = dmc.HoverCard(
            #     [
            #         dmc.HoverCardTarget(
            #             dmc.Badge(
            #                 "Additional Info",
            #                 color="gray",
            #                 leftSection=DashIconify(
            #                     icon="material-symbols:info-outline",
            #                     width=16,
            #                     color="gray",
            #                 ),
            #             )
            #         ),
            #         dmc.HoverCardDropdown(
            #             [
            #                 dmc.Text(f"Dashboard ID: {dashboard['dashboard_id']}"),
            #                 dmc.Text(f"Last Modified: {dashboard['last_saved_ts']}"),
            #                 # dmc.Text(f"Version: {str(dashboard['version'])}"),
            #             ],
            #             style={"padding": "10px"},
            #         ),
            #     ]
            # )

            group = html.Div(
                [
                    dmc.Space(h=10),
                    dmc.Group(
                        [
                            html.Div(
                                [
                                    dmc.Title(
                                        f"{dashboard['title']}",
                                        # f"{dashboard['title']} - {str(dashboard['dashboard_id'])}",
                                        order=4,  # Slightly smaller title (order=4 instead of 3)
                                        style={
                                            "maxWidth": "100%",
                                            "overflow": "visible",
                                            "whiteSpace": "normal",
                                            "wordWrap": "break-word",
                                        },  # Allow title wrapping
                                        # ta="center",  # Center align the title
                                    ),
                                    # dmc.Title(dashboard["title"], order=5),
                                    # dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                                    # dmc.Text(f"Version: {dashboard['version']}"),
                                    # dmc.Text(f"Owner: {dashboard['permissions']['owners'][0]['email']}"),
                                ],
                                style={"flex": "1"},
                            )
                        ]
                    ),
                    dmc.Space(h=10),
                    dmc.Stack(
                        [
                            badge_project,
                            badge_owner,
                            badge_status,
                            # badge_tooltip_additional_info,
                        ],
                        justify="center",
                        align="flex-start",
                    ),
                    dmc.Space(h=10),
                ]
            )
            return group

        def create_buttons(dashboard, user_id, current_user):
            disabled = (
                True
                if str(user_id)
                not in [str(owner["_id"]) for owner in dashboard["permissions"]["owners"]]
                else False
            )

            # Disable duplicate button for anonymous users in unauthenticated mode
            duplicate_disabled = (
                settings.auth.unauthenticated_mode
                and hasattr(current_user, "is_anonymous")
                and current_user.is_anonymous
                and not getattr(current_user, "is_temporary", False)
            )
            public = dashboard["is_public"]
            # public = True if "*" in [e for e in dashboard["permissions"]["viewers"]] else False
            privacy_button_title = "Make private" if public else "Make public"
            color_privacy_button = (
                colors["purple"] if public else colors["green"]
            )  # Use Depictio colors

            group = html.Div(
                [
                    dmc.Group(
                        [
                            html.A(
                                dmc.Button(
                                    "View",
                                    id={
                                        "type": "view-dashboard-button",
                                        "index": dashboard["dashboard_id"],
                                    },
                                    variant="outline",
                                    color=colors["blue"],  # Use Depictio blue
                                    size="sm",
                                    # style={"fontFamily": "Virgil"},
                                    # leftIcon=DashIconify(icon="mdi:eye", width=12, color="black"),
                                    style={"padding": "2px 6px", "fontSize": "12px"},
                                ),
                                href=f"/dashboard/{dashboard['dashboard_id']}",
                            ),
                            dmc.Button(
                                "Edit name",
                                id={
                                    "type": "edit-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color=colors["teal"],  # Use Depictio teal
                                # style={"fontFamily": "Virgil"},
                                disabled=disabled,
                                size="sm",
                                style={"padding": "2px 6px", "fontSize": "12px"},
                            ),
                            dmc.Button(
                                "Duplicate",
                                id={
                                    "type": "duplicate-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color=colors["pink"],  # Use Depictio gray
                                # style={"fontFamily": "Virgil"},
                                size="sm",
                                style={"padding": "2px 6px", "fontSize": "12px"},
                                disabled=duplicate_disabled,
                            ),
                            dmc.Button(
                                "Delete",
                                id={
                                    "type": "delete-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color=colors["red"],  # Use Depictio red
                                # style={"fontFamily": "Virgil"},
                                disabled=disabled,
                                size="sm",
                                style={"padding": "2px 6px", "fontSize": "12px"},
                            ),
                            dmc.Button(
                                privacy_button_title,
                                id={
                                    "type": "make-public-dashboard-button",
                                    "index": dashboard["dashboard_id"],
                                },
                                variant="outline",
                                color=color_privacy_button,
                                # style={"fontFamily": "Virgil"},
                                disabled=disabled,
                                size="sm",
                                style={"padding": "2px 6px", "fontSize": "12px", "display": "none"},
                            ),
                        ]
                        # align="center",
                        # position="apart",
                        # grow=False,
                        # noWrap=False,
                        # style={"width": "100%"},
                    ),
                ]
            )
            return group

        def return_thumbnail(user_id, dashboard):
            import os

            # Define the output folder where screenshots are saved
            output_folder = (
                "/app/depictio/dash/static/screenshots"  # Directly set to the desired path
            )
            # output_folder = os.path.join(os.path.dirname(__file__), 'static', 'screenshots')

            # Define the filename and paths
            filename = f"{dashboard['_id']}.png"
            # Filesystem path to check existence
            thumbnail_fs_path = os.path.join(output_folder, filename)
            # URL path for the Image src
            thumbnail_url = f"/static/screenshots/{filename}"

            # Simple responsive thumbnail styling for 1920x1080 images
            # Using fixed height with proper object-fit to avoid crushing

            # Check if the thumbnail exists in the static/screenshots folder
            if not os.path.exists(thumbnail_fs_path):
                logger.warning(f"Thumbnail not found at path: {thumbnail_fs_path}")
                # Use the default thumbnail from static/
                default_thumbnail_url = "/assets/images/backgrounds/default_thumbnail.png"

                thumbnail = html.Div(
                    [
                        html.A(
                            dmc.CardSection(
                                html.Div(
                                    [
                                        dmc.Image(
                                            src=default_thumbnail_url,
                                            style={
                                                "width": "180px",
                                                "height": "180px",
                                                "objectFit": "contain",
                                            },
                                            alt="Default dashboard thumbnail",
                                        ),
                                        dmc.Text(
                                            "No thumbnail available",
                                            size="sm",
                                            ta="center",
                                            c="gray",
                                            style={"marginTop": "12px", "fontSize": "13px"},
                                        ),
                                    ],
                                    style={
                                        "width": "100%",
                                        "height": "280px",  # Match optimized thumbnail height
                                        "display": "flex",
                                        "flexDirection": "column",
                                        "alignItems": "center",
                                        "justifyContent": "center",
                                        "borderRadius": "8px 8px 0 0",
                                    },
                                ),
                                withBorder=True,
                            ),
                            href=f"/dashboard/{dashboard['dashboard_id']}",
                            style={"textDecoration": "none"},
                        ),
                    ]
                )
            else:
                # Better thumbnail display for 1920x1080 (16:9) aspect ratio
                # Use object-fit: cover to fill the container and crop if needed
                thumbnail = html.A(
                    dmc.CardSection(
                        dmc.Image(
                            src=thumbnail_url,
                            style={
                                "width": "100%",
                                "height": "280px",  # Optimized height for 3-column layout
                                "objectFit": "cover",  # Fill container completely
                                "objectPosition": "center center",  # Center the image content
                                "borderRadius": "8px 8px 0 0",
                                "display": "block",  # Ensure proper display
                            },
                            alt=f"Thumbnail for {dashboard['title']}",
                        ),
                        withBorder=True,
                    ),
                    href=f"/dashboard/{dashboard['dashboard_id']}",
                    style={"textDecoration": "none"},
                )

            return thumbnail

        def loop_over_dashboards(user_id, dashboards, token, current_user):
            view = list()
            for dashboard in dashboards:
                # delete_modal = modal_delete_dashboard(dashboard)
                delete_modal, delete_modal_id = create_delete_confirmation_modal(
                    id_prefix="dashboard",
                    item_id=dashboard["dashboard_id"],
                    title=f"Delete dashboard : {dashboard['title']}",
                )
                edit_name_modal = modal_edit_name_dashboard(dashboard)
                buttons = create_buttons(dashboard, user_id, current_user)
                dashboard_header = create_dashboad_view_header(dashboard, user_id, token)

                buttons = dmc.Accordion(
                    [
                        dmc.AccordionItem(
                            value="actions",
                            children=[
                                dmc.AccordionControl(
                                    dmc.Group(
                                        [
                                            DashIconify(
                                                icon="mdi:cog-outline",
                                                width=12,  # Even smaller icon
                                                color="#6c757d",  # Subtle gray
                                            ),
                                            dmc.Text(
                                                "Actions",
                                                style={
                                                    "fontSize": "12px",  # Even smaller font
                                                    "fontWeight": "400",
                                                    "color": "#6c757d",
                                                },
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                    # style={
                                    #     "minHeight": "24px",  # Very compact height
                                    #     "padding": "2px 6px",  # Minimal padding
                                    # },
                                ),
                                dmc.AccordionPanel(
                                    buttons,
                                    # style={
                                    #     "padding": "4px 6px",  # Very compact padding
                                    # },
                                ),
                            ],
                        ),
                    ],
                    variant="default",
                    # radius="sm",
                    # style={
                    #     "width": "100%",
                    #     "margin": "2px 0",  # Minimal margin
                    #     "border": "1px solid #e9ecef",  # Subtle border only
                    #     # Remove backgroundColor completely
                    # },
                    # chevronPosition="right",
                )

                thumbnail = return_thumbnail(user_id, dashboard)
                view.append(
                    dmc.Card(
                        withBorder=True,
                        shadow="sm",
                        radius="md",
                        # style={"width": 480},
                        # Remove fixed width to allow flexibility
                        style={
                            "width": "100%",
                            "height": "100%",
                            "display": "flex",
                            "flexDirection": "column",
                        },
                        children=[
                            thumbnail,
                            dmc.Space(h=15),  # Add space between image and title
                            dashboard_header,
                            buttons,
                            delete_modal,
                            edit_name_modal,
                        ],
                    )
                )
            return view

        # Categorize dashboards based on ownership and access
        owned_dashboards = [
            d
            for d in dashboards
            if str(user_id) in [str(owner["_id"]) for owner in d["permissions"]["owners"]]
        ]
        # Check if current user is anonymous
        is_anonymous = hasattr(current_user, "is_anonymous") and current_user.is_anonymous

        accessed_dashboards = [
            d
            for d in dashboards
            if str(user_id) not in [str(owner["_id"]) for owner in d["permissions"]["owners"]]
            and (
                not is_anonymous or d.get("is_public", False)
            )  # Anonymous users only see public dashboards
        ]

        owned_dashboards_section_header = dmc.Title(
            [
                DashIconify(icon="mdi:account-check", width=18, color="#1c7ed6"),
                " Owned Dashboards",
            ],
            order=3,
        )
        owned_dashboards_view = dmc.SimpleGrid(
            loop_over_dashboards(user_id, owned_dashboards, token, current_user),
            cols={
                "base": 1,
                "sm": 2,
                "lg": 3,  # Back to 3 columns as requested
            },  # Responsive columns: 1 on mobile, 2 on small, 3 on large
            spacing="xl",
            verticalSpacing="xl",
            style={"width": "100%"},
        )
        accessed_dashboards_section_header = dmc.Title(
            [
                DashIconify(icon="mdi:eye", width=18, color="#54ca74"),
                " Accessed Dashboards",
            ],
            order=3,
        )

        accessed_dashboards_view = dmc.SimpleGrid(
            loop_over_dashboards(user_id, accessed_dashboards, token, current_user),
            cols={
                "base": 1,
                "sm": 2,
                "lg": 3,
            },  # Responsive columns: 1 on mobile, 2 on small, 3 on large, 4 on xl
            spacing="xl",
            verticalSpacing="xl",
            style={"width": "100%"},
        )

        # Optional: Add padding to the parent div for better spacing on smaller screens
        return html.Div(
            [
                # Show owned dashboards section
                owned_dashboards_section_header,
                dmc.Space(h=10),
                owned_dashboards_view,
                dmc.Space(h=20),
                html.Hr(),
                # Show accessed dashboards section
                accessed_dashboards_section_header,
                dmc.Space(h=10),
                accessed_dashboards_view,
            ],
            style={"width": "100%"},
        )

    @app.callback(
        Output("dashboard-projects", "data"),
        Input("dashboard-modal", "opened"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def load_projects(modal_opened, user_data):
        # Only load projects when modal is opened
        if not modal_opened:
            logger.info("Modal not opened, returning empty list")
            return []

        # Check if user data is valid
        if not user_data or "access_token" not in user_data:
            logger.warning("No valid user data or access token")
            return []

        try:
            logger.info("Making API call to fetch projects...")
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/projects/get/all",
                headers={"Authorization": f"Bearer {user_data['access_token']}"},
                timeout=settings.performance.api_request_timeout,
            )

            if response.status_code == 200:
                projects = response.json()
                projects_multiselect_options = [
                    {
                        "label": f"{project['name']} ({str(project['id'])})",
                        "value": project["id"],
                    }
                    for project in projects
                ]
                return projects_multiselect_options
            else:
                logger.error(f"API Error: {response.status_code} - {response.text}")
                return []

        except Exception as e:
            logger.error(f"Exception in load_projects: {e}")
            return []

    @app.callback(
        Output({"type": "dashboard-list", "index": ALL}, "children"),
        # [Output({"type": "dashboard-list", "index": ALL}, "children"), Output({"type": "dashboard-index-store", "index": ALL}, "data")],
        [
            # Input({"type": "cancel-dashboard-delete-button", "index": ALL}, "n_clicks"),
            Input({"type": "confirm-dashboard-delete-button", "index": ALL}, "n_clicks"),
            Input({"type": "save-edit-name-dashboard", "index": ALL}, "n_clicks"),
            Input({"type": "duplicate-dashboard-button", "index": ALL}, "n_clicks"),
            Input({"type": "make-public-dashboard-button", "index": ALL}, "n_clicks"),
            Input({"type": "make-public-dashboard-button", "index": ALL}, "children"),
            Input({"type": "make-public-dashboard-button", "index": ALL}, "id"),
        ],
        [
            State({"type": "create-dashboard-button", "index": ALL}, "id"),
            # State({"type": "dashboard-index-store", "index": ALL}, "data"),
            State({"type": "confirm-dashboard-delete-button", "index": ALL}, "index"),
            State({"type": "new-name-dashboard", "index": ALL}, "value"),
            State({"type": "new-name-dashboard", "index": ALL}, "id"),
            State("local-store", "data"),
            State("user-cache-store", "data"),
            Input("dashboard-modal-store", "data"),
        ],
    )
    def update_dashboards(
        # cancel_n_clicks_list,
        delete_n_clicks_list,
        edit_n_clicks_list,
        duplicate_n_clicks_list,
        make_public_n_clicks_list,
        make_public_children_list,
        make_public_id_list,
        # create_ids_list,
        store_data_list,
        delete_ids_list,
        new_name_list_values,
        new_name_list_ids,
        user_data,
        user_cache,
        modal_data,
    ):
        # log_context_info()

        # Use consolidated user cache instead of individual API call
        from depictio.models.models.users import UserContext

        current_user = UserContext.from_cache(user_cache)
        if not current_user:
            # Fallback to direct API call if cache not available
            logger.info("🔄 Dashboards: Using fallback API call for user data")
            current_user_api = api_call_fetch_user_from_token(user_data["access_token"])
            if not current_user_api:
                logger.warning("User not found in dashboards management.")
                # Return empty list for each dashboard-list component
                # Ensure we always return a list, even if store_data_list is empty
                list_length = max(len(store_data_list), 1)
                return [html.Div("User not found. Please login again.")] * list_length
            # Create UserContext from API response for consistency
            current_user = UserContext(
                id=str(current_user_api.id),
                email=current_user_api.email,
                is_admin=current_user_api.is_admin,
                is_anonymous=getattr(current_user_api, "is_anonymous", False),
            )
        else:
            logger.info("✅ Dashboards: Using consolidated cache for user data")
        # current_userbase = UserBase(
        #     convert_model_to_dict(current_user, exclude_none=True).dict(
        #         exclude={
        #             "tokens",
        #             "is_active",
        #             "is_verified",
        #             "last_login",
        #             "registration_date",
        #             "password",
        #         }
        #     )
        # )
        current_userbase = current_user.turn_to_userbase()

        index_data = load_dashboards_from_db(user_data["access_token"])
        dashboards = [
            DashboardData.from_mongo(dashboard) for dashboard in index_data.get("dashboards", [])
        ]
        # next_index = index_data.get("next_index", 1)

        if not ctx.triggered_id:
            return handle_no_trigger(dashboards, store_data_list, current_userbase, user_data)
            # return handle_no_trigger(dashboards, next_index, store_data_list, current_userbase)

        if "type" not in ctx.triggered_id:
            if ctx.triggered_id == "dashboard-modal-store":
                return handle_dashboard_creation(
                    dashboards, modal_data, user_data, current_userbase, store_data_list
                )
                # return handle_dashboard_creation(dashboards, next_index, modal_data, user_data, current_userbase, store_data_list)

        if ctx.triggered_id.get("type") == "confirm-dashboard-delete-button":
            return handle_dashboard_deletion(
                dashboards,
                delete_ids_list,
                user_data,
                store_data_list,
                current_userbase,
            )

        if ctx.triggered_id.get("type") == "duplicate-dashboard-button":
            return handle_dashboard_duplication(
                dashboards, user_data, store_data_list, current_userbase
            )

        if ctx.triggered_id.get("type") == "make-public-dashboard-button":
            logger.info(f"Make public dashboard button clicked with ID: {ctx.triggered_id}")
            public_current_status = [
                child
                for child, id in zip(make_public_children_list, make_public_id_list)
                if str(id["index"]) == str(ctx.triggered_id["index"])
            ][0]
            public_current_status = False if public_current_status == "Make public" else True

            return handle_dashboard_make_public(
                dashboards,
                user_data,
                store_data_list,
                current_userbase,
                public_current_status,
            )

        if ctx.triggered_id.get("type") == "save-edit-name-dashboard":
            # Extract the new name from the input field
            index = ctx.triggered_id["index"]

            # Iterate over the new_name_list to find the new name corresponding to the index
            new_name = [
                value
                for value, id in zip(new_name_list_values, new_name_list_ids)
                if id["index"] == index
            ][0]

            return handle_dashboard_edit(
                new_name, dashboards, user_data, store_data_list, current_userbase
            )

        return generate_dashboard_view_response(
            dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def log_context_info():
        logger.info(f"CTX triggered: {ctx.triggered}")
        logger.info(f"CTX triggered prop IDs: {ctx.triggered_prop_ids}")
        logger.info(f"CTX triggered ID: {ctx.triggered_id}")
        logger.info(f"CTX inputs: {ctx.inputs}")

    def handle_no_trigger(dashboards, store_data_list, current_userbase, user_data):
        logger.info("No trigger")
        return generate_dashboard_view_response(
            dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def handle_dashboard_creation(
        dashboards, modal_data, user_data, current_userbase, store_data_list
    ):
        if modal_data.get("title"):
            logger.info("Creating new dashboard")

            dashboard_id = PyObjectId()
            # dashboard_id = generate_unique_index()

            new_dashboard = DashboardData(
                id=dashboard_id,
                title=modal_data["title"],
                last_saved_ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                permissions=Permission(owners=[current_userbase]),
                # permissions={"owners": [current_userbase], "viewers": []},
                dashboard_id=dashboard_id,
                project_id=PyObjectId(modal_data["project_id"]),
            )
            logger.debug(f"New dashboard: {format_pydantic(new_dashboard)}")
            dashboards.append(new_dashboard)
            insert_dashboard(dashboard_id, new_dashboard.mongo(), user_data["access_token"])
            # next_index += 1

        return generate_dashboard_view_response(
            dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def handle_dashboard_deletion(
        dashboards, delete_ids_list, user_data, store_data_list, current_userbase
    ):
        ctx_triggered_dict = ctx.triggered[0]
        index_confirm_delete = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
        delete_dashboard(index_confirm_delete, user_data["access_token"])

        dashboards = [
            dashboard
            for dashboard in dashboards
            if str(dashboard.dashboard_id) != str(index_confirm_delete)
        ]
        return generate_dashboard_view_response(
            dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(dashboards, len(dashboards) + 1, store_data_list, current_userbase)

    def handle_dashboard_make_public(
        dashboards, user_data, store_data_list, current_userbase, public_current_status
    ):
        logger.info("Make public dashboard button clicked")
        ctx_triggered_dict = ctx.triggered[0]
        index_make_public = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]

        updated_dashboards = list()
        for dashboard in dashboards:
            if str(dashboard.dashboard_id) == str(index_make_public):
                logger.debug(f"Found dashboard to update status: {dashboard}")
                response = httpx.post(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/toggle_public_status/{index_make_public}",
                    headers={"Authorization": f"Bearer {user_data['access_token']}"},
                    json={"is_public": not public_current_status},
                )
                if response.status_code != 200:
                    raise ValueError(f"Failed to update dashboard status. Error: {response.text}")
                dashboard.is_public = response.json()["is_public"]
                # dashboard.permissions = response.json()["permissions"]
                updated_dashboards.append(dashboard)

                if response.status_code == 200:
                    logger.debug(
                        f"Successfully made dashboard '{not public_current_status}': {dashboard}"
                    )

                else:
                    raise ValueError(f"Failed to make dashboard public. Error: {response.text}")
            else:
                updated_dashboards.append(dashboard)

        return generate_dashboard_view_response(
            updated_dashboards, store_data_list, current_userbase, user_data
        )

    def handle_dashboard_duplication(dashboards, user_data, store_data_list, current_userbase):
        logger.info("Duplicate dashboard button clicked")
        ctx_triggered_dict = ctx.triggered[0]
        index_duplicate = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]

        updated_dashboards = list()
        for dashboard in dashboards:
            updated_dashboards.append(dashboard)
            if str(dashboard.dashboard_id) == str(index_duplicate):
                logger.info(f"Found dashboard to duplicate: {dashboard}")

                # Load full dashboard data from the database
                dashboard_data_response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{index_duplicate}",
                    headers={"Authorization": f"Bearer {user_data['access_token']}"},
                )
                if dashboard_data_response.status_code != 200:
                    raise ValueError(
                        f"Failed to load dashboard data from the database. Error: {dashboard_data_response.text}"
                    )
                else:
                    dashboard_data_response = dashboard_data_response.json()

                # deep copy the dashboard object
                new_dashboard = DashboardData.from_mongo(dashboard_data_response)
                new_dashboard.id = ObjectId()
                new_dashboard.title = f"{dashboard.title} (copy)"
                new_dashboard.dashboard_id = str(new_dashboard.id)
                new_dashboard.permissions.owners = [current_userbase]
                new_dashboard.permissions.viewers = []
                new_dashboard.is_public = False  # Always make duplicated dashboards private
                logger.info(f"New dashboard: {format_pydantic(new_dashboard)}")
                # new_dashboard.dashboard_id = generate_unique_index()
                # new_dashboard.dashboard_id = str(len(dashboards) + 1)
                updated_dashboards.append(new_dashboard)
                insert_dashboard(
                    new_dashboard.dashboard_id,
                    new_dashboard.mongo(),
                    user_data["access_token"],
                )

                # Copy thumbnail
                thumbnail_filename = f"{str(dashboard.id)}.png"
                # thumbnail_filename = f"{str(current_userbase.id)}_{str(dashboard.id)}.png"
                thumbnail_fs_path = f"/app/depictio/dash/static/screenshots/{thumbnail_filename}"

                if not os.path.exists(thumbnail_fs_path):
                    logger.warning(f"Thumbnail not found at path: {thumbnail_fs_path}")
                else:
                    # Copy the thumbnail to the new dashboard ID
                    new_thumbnail_fs_path = (
                        f"/app/depictio/dash/static/screenshots/{str(new_dashboard.id)}.png"
                    )
                    shutil.copy(thumbnail_fs_path, new_thumbnail_fs_path)

        return generate_dashboard_view_response(
            updated_dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(updated_dashboards, len(updated_dashboards) + 1, store_data_list, current_userbase)

    def handle_dashboard_edit(new_name, dashboards, user_data, store_data_list, current_userbase):
        logger.info("Edit dashboard button clicked")
        ctx_triggered_dict = ctx.triggered[0]
        index_edit = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
        updated_dashboards = edit_dashboard_name(
            new_name, index_edit, dashboards, user_data["access_token"]
        )

        return generate_dashboard_view_response(
            updated_dashboards, store_data_list, current_userbase, user_data
        )
        # return generate_dashboard_view_response(updated_dashboards, len(updated_dashboards) + 1, store_data_list, current_userbase)

    def generate_dashboard_view_response(dashboards, store_data_list, current_userbase, user_data):
        dashboards = [convert_objectid_to_str(dashboard.mongo()) for dashboard in dashboards]
        logger.debug(f"dashboards: {dashboards}")
        current_user = api_call_fetch_user_from_token(user_data["access_token"])
        dashboards_view = create_homepage_view(
            dashboards, current_userbase.id, user_data["access_token"], current_user
        )
        return [dashboards_view] * len(store_data_list)

    @app.callback(
        Output({"type": "edit-password-modal", "index": MATCH}, "opened"),
        [
            Input({"type": "edit-dashboard-button", "index": MATCH}, "n_clicks"),
            Input({"type": "cancel-edit-name-dashboard", "index": MATCH}, "n_clicks"),
        ],
        [State({"type": "edit-password-modal", "index": MATCH}, "opened")],
        prevent_initial_call=True,
    )
    def handle_edit_name_modal(edit_clicks, cancel_clicks, opened):
        # Check which button was clicked
        ctx = dash.callback_context
        if not ctx.triggered:
            return opened

        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # If edit button was clicked, toggle modal
        if "edit-dashboard-button" in triggered_id:
            return not opened
        # If cancel button was clicked, close modal
        elif "cancel-edit-name-dashboard" in triggered_id:
            return False

        return opened

    @app.callback(
        [
            Output("dashboard-modal-store", "data"),
            Output("dashboard-modal", "opened"),
            Output("init-create-dashboard-button", "data"),
            Output("unique-title-warning", "style"),
            Output("unique-title-warning", "children"),
            Output("url", "pathname", allow_duplicate=True),
        ],
        [
            Input({"type": "create-dashboard-button", "index": ALL}, "n_clicks"),
            Input("create-dashboard-submit", "n_clicks"),
            Input("cancel-dashboard-button", "n_clicks"),
        ],
        [
            State("dashboard-title-input", "value"),
            State("dashboard-modal", "opened"),
            State("local-store", "data"),
            State("user-cache-store", "data"),
            State("init-create-dashboard-button", "data"),
            State("dashboard-projects", "value"),
        ],
        prevent_initial_call=True,
    )
    def handle_create_dashboard_and_toggle_modal(
        n_clicks_create,
        n_clicks_submit,
        n_clicks_cancel,
        title,
        opened,
        user_data,
        user_cache,
        init_create_dashboard_button,
        project,
    ):
        data = {"title": "", "project_id": ""}

        logger.debug(
            f"Create dashboard n_clicks: {n_clicks_create}, {n_clicks_submit}, {n_clicks_cancel}"
        )
        logger.debug(f"Title: {title}, Opened: {opened}")
        logger.debug(f"User data: {user_data}")
        logger.debug(f"Init create dashboard button: {init_create_dashboard_button}")
        logger.debug(f"Project selected: {project}")

        if not init_create_dashboard_button:
            logger.info("Init create dashboard button")
            return data, opened, True, dash.no_update, dash.no_update, dash.no_update

        if "type" in ctx.triggered_id:
            triggered_id = ctx.triggered_id["type"]
        else:
            triggered_id = ctx.triggered_id

        if triggered_id == "create-dashboard-button":
            logger.info("Create button clicked")

            # Check if user is anonymous and redirect to profile page - use consolidated cache
            from depictio.models.models.users import UserContext

            current_user = UserContext.from_cache(user_cache)
            if not current_user:
                # Fallback to direct API call if cache not available
                logger.info("🔄 Dashboard Create: Using fallback API call for user data")
                current_user_api = api_call_fetch_user_from_token(user_data["access_token"])
                if not current_user_api:
                    logger.warning("User not found in dashboard creation.")
                    return data, opened, True, dash.no_update, dash.no_update, dash.no_update
                # Create UserContext from API response for consistency
                current_user = UserContext(
                    id=str(current_user_api.id),
                    email=current_user_api.email,
                    is_admin=current_user_api.is_admin,
                    is_anonymous=getattr(current_user_api, "is_anonymous", False),
                )
            else:
                logger.info("✅ Dashboard Create: Using consolidated cache for user data")
            if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
                logger.info(
                    "Anonymous user clicked 'Login to Create Dashboards' - redirecting to profile"
                )
                return (
                    dash.no_update,
                    False,  # Keep modal closed
                    dash.no_update,
                    {"display": "none"},  # Hide any warning messages
                    dash.no_update,
                    "/profile",  # Redirect to profile page
                )

            # Toggle the modal when the create button is clicked (for authenticated users)
            return (
                dash.no_update,
                True,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        if triggered_id == "cancel-dashboard-button":
            logger.info("Create button clicked")
            # Toggle the modal when the create button is clicked
            return (
                dash.no_update,
                False,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        if triggered_id == "create-dashboard-submit":
            logger.info("Submit button clicked")
            dashboards = load_dashboards_from_db(user_data["access_token"])["dashboards"]
            if len(dashboards) > 0:
                existing_titles = [dashboard["title"] for dashboard in dashboards]

                if title in existing_titles:
                    logger.warning(f"Dashboard with title '{title}' already exists.")
                    return (
                        dash.no_update,
                        True,
                        dash.no_update,
                        {"display": "block"},
                        dmc.Badge(
                            children="Title already exists",
                            color="red",
                            # size="xl",
                            id="unique-title-warning-badge",
                        ),
                        dash.no_update,
                    )

                if not title:
                    logger.warning("Title is empty")
                    return (
                        dash.no_update,
                        True,
                        dash.no_update,
                        {"display": "block"},
                        dmc.Badge(
                            children="Title cannot be empty",
                            color="red",
                            # size="xl",
                            id="unique-title-warning-badge",
                        ),
                        dash.no_update,
                    )
            if not project:
                logger.warning("Project not selected")
                return (
                    dash.no_update,
                    True,
                    dash.no_update,
                    {"display": "block"},
                    dmc.Badge(
                        children="Project not selected",
                        color="red",
                        # size="xl",
                        id="unique-title-warning-badge",
                    ),
                    dash.no_update,
                )

            # Set the title and keep the modal open (or toggle it based on your preference)
            data["title"] = title
            data["project_id"] = project
            return data, False, False, {"display": "none"}, dash.no_update, dash.no_update

        logger.debug("No relevant clicks")
        # Return default values if no relevant clicks happened
        return data, opened, False, dash.no_update, dash.no_update, dash.no_update

    @app.callback(
        Output({"type": "dashboard-delete-confirmation-modal", "index": MATCH}, "opened"),
        [
            Input({"type": "delete-dashboard-button", "index": MATCH}, "n_clicks"),
            Input({"type": "confirm-dashboard-delete-button", "index": MATCH}, "n_clicks"),
            Input({"type": "cancel-dashboard-delete-button", "index": MATCH}, "n_clicks"),
        ],
        [
            State(
                {"type": "dashboard-delete-confirmation-modal", "index": MATCH},
                "opened",
            )
        ],
        prevent_initial_call=True,
    )
    def open_delete_modal(n1, n2, n3, opened):
        return not opened

    @app.callback(
        Output("landing-page", "children"),
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
            State("user-cache-store", "data"),
        ],
    )
    def update_landing_page(
        pathname,
        data,
        user_cache,
    ):
        # Use consolidated user cache instead of individual API call
        from depictio.models.models.users import UserContext

        user_context = UserContext.from_cache(user_cache)
        if user_context:
            logger.info("✅ Landing Page: Using consolidated cache for user data")
            user = user_context
        else:
            # Fallback to direct API call if cache not available
            logger.info("🔄 Landing Page: Using fallback API call for user data")
            user = api_call_fetch_user_from_token(data["access_token"])

        def render_landing_page(data):
            return html.Div(
                [
                    # dcc.Store(id={"type": "dashboard-index-store", "index": user.email}, storage_type="session", data={"next_index": 1}),  # Store for dashboard index management
                    # render_welcome_section(user.email),
                    render_dashboard_list_section(user.email),
                ]
            )

        # Check which input triggered the callback
        if not ctx.triggered:
            # return dash.no_update
            raise dash.exceptions.PreventUpdate
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # Respond to URL changes
        if trigger_id == "url":
            if pathname == "/dashboards":
                # if pathname.startswith("/dashboard/"):
                # dashboard_id = pathname.split("/")[-1]
                # Fetch dashboard data based on dashboard_id and return the appropriate layout
                # return html.Div([f"Displaying Dashboard {dashboard_id}", dbc.Button("Go back", href="/", color="black", external_link=True)])
                # return dash.no_update
                # elif pathname
                return render_landing_page(data)

        # Respond to modal-store data changes
        elif trigger_id == "local-store":
            if data:
                return render_landing_page(data)
            # return html.Div("Please login to view this page.")
            return dash.no_update

        return dash.no_update
