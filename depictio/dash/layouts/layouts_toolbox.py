import dash_mantine_components as dmc
from dash_iconify import DashIconify
from dash import Input, Output, State, MATCH
from depictio.api.v1.configs.custom_logging import logger


def create_dashboard_modal(
    dashboard_title="",
    projects=[],
    selected_project=None,
    opened=False,
    id_prefix="dashboard",
):
    """
    Creates a stylish modal for dashboard creation with improved visual design.

    Parameters:
    - dashboard_title: Pre-filled dashboard title (optional)
    - projects: List of project options for the dropdown
    - selected_project: Pre-selected project (optional)
    - opened: Whether the modal is initially open
    - id_prefix: Prefix for all IDs in the modal

    Returns:
    - modal: The dashboard creation modal
    - modal_id: The ID of the modal for callbacks
    """
    modal_id = f"{id_prefix}-modal"

    modal = dmc.Modal(
        opened=opened,
        id=modal_id,
        centered=True,
        withCloseButton=True,
        closeOnClickOutside=False,
        closeOnEscape=False,
        overlayOpacity=0.55,
        overlayBlur=3,
        shadow="xl",
        radius="md",
        size=1000,
        # size=2000,
        zIndex=10000,
        styles={
            "modal": {
                "padding": "28px",
            }
        },
        children=[
            # dmc.Grid(
            #     [
            #         dmc.Col(
            dmc.Stack(
                spacing="xl",
                children=[
                    # Header with icon and title
                    dmc.Group(
                        position="center",
                        spacing="sm",
                        children=[
                            DashIconify(
                                icon="mdi:view-dashboard-outline",
                                width=40,
                                height=40,
                                color="orange",
                            ),
                            dmc.Title(
                                "Create New Depictio Dashboard",
                                order=1,
                                color="orange",
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(style={"marginTop": 5, "marginBottom": 5}),
                    # Form elements
                    dmc.Stack(
                        spacing="md",
                        children=[
                            # Dashboard title input
                            dmc.TextInput(
                                label="Dashboard Title",
                                description="Give your dashboard a descriptive name",
                                placeholder="Enter dashboard title",
                                id=f"{id_prefix}-title-input",
                                value=dashboard_title,
                                required=True,
                                icon=DashIconify(icon="mdi:text-box-outline"),
                                style={"width": "100%"},
                            ),
                            # Warning message (hidden by default)
                            dmc.Alert(
                                "Dashboard title must be unique",
                                color="red",
                                id="unique-title-warning",
                                icon=DashIconify(icon="mdi:alert"),
                                style={"display": "none"},
                            ),
                            # Project dropdown
                            dmc.Select(
                                label="Project",
                                description="Select the project this dashboard belongs to",
                                data=projects,
                                value=selected_project,
                                id=f"{id_prefix}-projects",
                                searchable=True,
                                clearable=True,
                                icon=DashIconify(icon="mdi:jira"),
                                style={"width": "100%"},
                            ),
                            # Available templates dropdown
                            # dmc.Select(
                            #     label="Available templates",
                            #     description="Select a template for your dashboard",
                            #     data=[],  # This would be populated with actual templates
                            #     id=f"{id_prefix}-templates",
                            #     searchable=True,
                            #     clearable=True,
                            #     icon=DashIconify(icon="mdi:palette"),
                            #     style={"width": "100%"},
                            # ),
                            # Template selection message
                            # dmc.Center(
                            #     dmc.Badge(
                            #         "You picked a Depictio template for the workflow X",
                            #         radius="xl",
                            #         size="xl",
                            #         # variant="gradient",
                            #         # gradient={
                            #         #     "from": "orange",
                            #         #     "to": "red",
                            #         # },
                            #         className="animated-badge",
                            #     )
                            # ),
                        ],
                    ),
                    # Buttons
                    dmc.Group(
                        position="right",
                        spacing="md",
                        mt="lg",
                        children=[
                            dmc.Button(
                                "Cancel",
                                variant="outline",
                                color="gray",
                                radius="md",
                                id=f"cancel-{id_prefix}-button",
                            ),
                            dmc.Button(
                                "Create Dashboard",
                                id=f"create-{id_prefix}-submit",
                                color="orange",
                                radius="md",
                                leftIcon=DashIconify(icon="mdi:plus", width=16),
                            ),
                        ],
                    ),
                ],
            ),
            #     span=6,
            # ),
            # dmc.Col(
            #     # Image
            #     dmc.Image(
            #         src="https://placehold.co/600x400",
            #         alt="Placeholder image",
            #         width="100%",
            #         height="auto",
            #         fit="cover",
            #     ),
            #     span=6,
            # ),
            # ]
            # ),
        ],
    )

    return modal, modal_id


# Define the delete confirmation modal function
def create_delete_confirmation_modal(
    id_prefix,
    item_id,
    title="Confirm Deletion",
    message="Are you sure you want to delete this item? This action cannot be undone.",
    delete_button_text="Delete",
    cancel_button_text="Cancel",
    icon="mdi:alert-circle",
    opened=False,
):
    """
    Creates a reusable deletion confirmation modal with improved styling.
    """
    modal_id = {
        "type": f"{id_prefix}-delete-confirmation-modal",
        "index": item_id,
    }
    modal = dmc.Modal(
        opened=opened,
        id=modal_id,
        centered=True,
        withCloseButton=False,
        overlayOpacity=0.55,
        overlayBlur=3,
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
                spacing="lg",
                children=[
                    # Header with icon and title
                    dmc.Group(
                        position="left",
                        spacing="sm",
                        children=[
                            DashIconify(
                                icon=icon,
                                width=28,
                                height=28,
                                color="red",
                            ),
                            dmc.Title(
                                title,
                                order=4,
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(),
                    # Warning message
                    dmc.Text(
                        message,
                        size="sm",
                        color="dimmed",
                        style={"lineHeight": 1.5},
                    ),
                    # Buttons
                    dmc.Group(
                        position="right",
                        spacing="md",
                        mt="md",
                        children=[
                            dmc.Button(
                                cancel_button_text,
                                id={
                                    "type": f"cancel-{id_prefix}-delete-button",
                                    "index": item_id,
                                },
                                color="gray",
                                variant="outline",
                                radius="md",
                            ),
                            dmc.Button(
                                delete_button_text,
                                id={
                                    "type": f"confirm-{id_prefix}-delete-button",
                                    "index": item_id,
                                },
                                color="red",
                                radius="md",
                                leftIcon=DashIconify(icon="mdi:delete", width=16),
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    return modal, modal_id


def create_add_with_input_modal(
    id_prefix,
    input_field,
    item_id=None,
    title="Add Item",
    title_color="blue",
    message="Please complete the input field to add a new item.",
    confirm_button_text="Add",
    confirm_button_color="blue",
    cancel_button_text="Cancel",
    # + Add input field
    icon="mdi:plus",
    opened=False,
):
    """
    Creates a reusable add confirmation modal with improved styling.
    """
    if item_id:
        modal_id = {
            "type": f"{id_prefix}-add-confirmation-modal",
            "index": item_id,
        }
    else:
        modal_id = f"{id_prefix}-add-confirmation-modal"
    # input_id = {
    #     "type": f"{id_prefix}-input",
    #     "index": item_id,
    # }
    modal = dmc.Modal(
        opened=opened,
        id=modal_id,
        centered=True,
        withCloseButton=False,
        overlayOpacity=0.55,
        overlayBlur=3,
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
                spacing="lg",
                children=[
                    # Header with icon and title
                    dmc.Group(
                        position="left",
                        spacing="sm",
                        children=[
                            DashIconify(
                                icon=icon,
                                width=28,
                                height=28,
                                color=title_color if title_color else None,
                            ),
                            dmc.Title(
                                title,
                                order=4,
                                style={"margin": 0},
                                color=title_color if title_color else None,
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(),
                    # Warning message
                    dmc.Text(
                        message,
                        id=f"{id_prefix}-add-confirmation-modal-message",
                        size="sm",
                        color="dimmed",
                        style={"lineHeight": 1.5},
                    ),
                    # Input field
                    input_field,
                    # Buttons
                    dmc.Group(
                        position="right",
                        spacing="md",
                        mt="md",
                        children=[
                            dmc.Button(
                                cancel_button_text,
                                id=f"cancel-{id_prefix}-add-button",
                                color="gray",
                                variant="outline",
                                radius="md",
                            ),
                            dmc.Button(
                                confirm_button_text,
                                id=f"confirm-{id_prefix}-add-button",
                                color=confirm_button_color,
                                radius="md",
                                leftIcon=DashIconify(icon="mdi:check-circle", width=16),
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    return modal, modal_id


# def register_delete_confirmation_modal_callbacks(
#     app,
#     id_prefix,
#     trigger_button_id,
# ):

#     logger.info(f"App: {app}")
#     logger.info(f"ID Prefix: {id_prefix}")
#     logger.info(f"Trigger Button ID: {trigger_button_id}")
#     # Register generic callbacks for the delete confirmation modal
#     @app.callback(
#         Output(
#             {"type": f"{id_prefix}-delete-confirmation-modal", "index": MATCH}, "opened"
#         ),
#         Input({"type": trigger_button_id["type"], "index": MATCH}, "n_clicks"),
#         State(
#             {"type": f"{id_prefix}-delete-confirmation-modal", "index": MATCH}, "opened"
#         ),
#     )
#     def toggle_delete_confirmation_modal(n_clicks, opened):
#         if n_clicks:
#             return not opened
#         return opened
