import dash_mantine_components as dmc
from dash import dcc, html
from dash_extensions import EventListener
from dash_iconify import DashIconify

from depictio.dash.colors import colors


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
        # overlayOpacity=0.55,
        # overlayBlur=3,
        overlayProps={
            "overlayBlur": 3,
            "overlayOpacity": 0.55,
        },
        shadow="xl",
        radius="md",
        # size="xl",
        size=1500,
        zIndex=10000,
        styles={
            "modal": {
                "padding": "28px",
            },
            # "height": "80vh",  # Set a fixed height for the modal
        },
        children=[
            # dmc.Grid(
            #     [
            #         dmc.Col(
            dmc.Stack(
                gap="xl",
                children=[
                    # Header with icon and title
                    dmc.Group(
                        justify="center",
                        gap="sm",
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
                                c="orange",
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(style={"marginTop": 5, "marginBottom": 5}),
                    # Form elements
                    dmc.Stack(
                        gap="md",
                        children=[
                            # Dashboard title input
                            dmc.TextInput(
                                label="Dashboard Title",
                                description="Give your dashboard a descriptive name",
                                placeholder="Enter dashboard title",
                                id=f"{id_prefix}-title-input",
                                value=dashboard_title,
                                required=True,
                                leftSection=DashIconify(icon="mdi:text-box-outline"),
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
                            # Project dropdown - simplified for debugging
                            dmc.Select(
                                label="Project",
                                description="Select the project this dashboard belongs to",
                                data=[],  # Start empty, will be populated by callback
                                id=f"{id_prefix}-projects",
                                placeholder="Loading projects...",
                                style={"width": "100%"},
                                searchable=False,  # Disable search for now
                                clearable=False,  # Disable clear for now
                                # comboboxProps={"zIndex": 1000},
                                comboboxProps={"withinPortal": False},
                            ),
                            # Available templates dropdown
                            # dmc.Select(
                            #     label="Available templates",
                            #     description="Select a template for your dashboard",
                            #     data=[],  # This would be populated with actual templates
                            #     id=f"{id_prefix}-templates",
                            #     searchable=True,
                            #     clearable=True,
                            #     leftSection=DashIconify(icon="mdi:palette"),
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
                        justify="flex-end",
                        gap="md",
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
                                leftSection=DashIconify(icon="mdi:plus", width=16),
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
                        c="gray",
                        style={"lineHeight": 1.5},
                    ),
                    # Buttons
                    dmc.Group(
                        justify="flex-end",
                        gap="md",
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
                                leftSection=DashIconify(icon="mdi:delete", width=16),
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
                                icon=icon,
                                width=28,
                                height=28,
                                color=title_color if title_color else None,
                            ),
                            dmc.Title(
                                title,
                                order=4,
                                style={"margin": 0},
                                c=title_color if title_color else None,
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
                        c="gray",
                        style={"lineHeight": 1.5},
                    ),
                    # Input field
                    input_field,
                    # Buttons
                    dmc.Group(
                        justify="flex-end",
                        gap="md",
                        mt="md",
                        children=[
                            dmc.Button(
                                cancel_button_text,
                                id={
                                    "type": f"cancel-{id_prefix}-add-button",
                                    "index": item_id,
                                }
                                if item_id
                                else f"cancel-{id_prefix}-add-button",
                                color="gray",
                                variant="outline",
                                radius="md",
                            ),
                            dmc.Button(
                                confirm_button_text,
                                id={
                                    "type": f"confirm-{id_prefix}-add-button",
                                    "index": item_id,
                                }
                                if item_id
                                else f"confirm-{id_prefix}-add-button",
                                color=confirm_button_color,
                                radius="md",
                                leftSection=DashIconify(icon="mdi:check-circle", width=16),
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


def create_edit_password_modal(
    title="Edit Password",
    opened=False,
    event=None,
):
    """
    Creates a password editing modal with improved styling.

    Parameters:
    -----------
    title : str, optional
        Title for the modal
    opened : bool, optional
        Whether the modal is initially opened
    event : dict, optional
        Event dictionary for EventListener

    Returns:
    --------
    dmc.Modal
        The modal component
    """
    modal = dmc.Modal(
        opened=opened,
        id="edit-password-modal",
        centered=True,
        withCloseButton=False,
        closeOnEscape=True,
        closeOnClickOutside=True,
        size="lg",
        # title=title,
        # overlayOpacity=0.55,
        # overlayBlur=3,
        overlayProps={
            "overlayOpacity": 0.55,
            "overlayBlur": 3,
        },
        shadow="xl",
        radius="md",
        styles={
            "modal": {
                "padding": "24px",
            }
        },
        children=[
            EventListener(
                html.Div(
                    [
                        dmc.Stack(
                            gap="md",
                            children=[
                                # Header with icon and title
                                dmc.Group(
                                    justify="flex-start",
                                    gap="sm",
                                    children=[
                                        DashIconify(
                                            icon="carbon:password",
                                            width=28,
                                            height=28,
                                            color="gray",
                                        ),
                                        dmc.Title(
                                            title,
                                            order=4,
                                            style={"margin": 0},
                                            c="blue",
                                        ),
                                    ],
                                ),
                                # Divider
                                dmc.Divider(),
                                # Form inputs
                                dmc.PasswordInput(
                                    placeholder="Old Password",
                                    label="Old Password",
                                    id="old-password",
                                    required=True,
                                    radius="md",
                                ),
                                dmc.PasswordInput(
                                    placeholder="New Password",
                                    label="New Password",
                                    id="new-password",
                                    required=True,
                                    radius="md",
                                ),
                                dmc.PasswordInput(
                                    placeholder="Confirm Password",
                                    label="Confirm Password",
                                    id="confirm-new-password",
                                    required=True,
                                    radius="md",
                                ),
                                dmc.Text(
                                    id="message-password",
                                    c="red",
                                    size="sm",
                                    style={"display": "none"},
                                ),
                                # Button
                                dmc.Group(
                                    justify="flex-end",
                                    mt="lg",
                                    children=[
                                        dmc.Button(
                                            "Save",
                                            color="blue",
                                            id="save-password",
                                            radius="md",
                                            leftSection=DashIconify(
                                                icon="mdi:content-save", width=16
                                            ),
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ]
                ),
                events=[event] if event else [],
                logging=True,
                id="edit-password-modal-listener",
            ),
        ],
    )

    return modal


# Example usage:
# password_modal = create_edit_password_modal(
#     title="Update Password",
#     opened=False,
#     event={"event": "click", "props": ["n_clicks"]}
# )

# Example usage:
# password_modal, password_modal_id = create_edit_password_modal(
#     id_prefix="user",
#     item_id="123",
#     title="Update Password",
#     save_button_text="Update"
# )


def create_data_collection_modal(
    opened=False,
    id_prefix="data-collection-creation",
):
    """
    Creates a data collection creation modal with form fields for metadata-only data collections.

    Parameters:
    - opened: Whether the modal is initially open
    - id_prefix: Prefix for all IDs in the modal

    Returns:
    - modal: The data collection creation modal
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
        overlayProps={
            "overlayBlur": 3,
            "overlayOpacity": 0.55,
        },
        shadow="xl",
        radius="md",
        size="lg",
        zIndex=10000,
        styles={
            "modal": {
                "padding": "28px",
            },
        },
        children=[
            dmc.Stack(
                gap="lg",
                children=[
                    # Header with icon and title
                    dmc.Group(
                        justify="center",
                        gap="sm",
                        children=[
                            DashIconify(
                                icon="mdi:database-plus",
                                width=40,
                                height=40,
                                color=colors["teal"],
                            ),
                            dmc.Title(
                                "Create Data Collection",
                                order=2,
                                c="teal",
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(style={"marginTop": 5, "marginBottom": 5}),
                    # Form fields
                    dmc.Stack(
                        gap="md",
                        children=[
                            # Data collection name
                            dmc.TextInput(
                                label="Data Collection Name",
                                description="Unique identifier for your data collection",
                                placeholder="Enter data collection name",
                                id=f"{id_prefix}-name-input",
                                required=True,
                                leftSection=DashIconify(icon="mdi:tag", width=16),
                                style={"width": "100%"},
                            ),
                            # Description
                            dmc.Textarea(
                                label="Description",
                                description="Optional description of your data collection",
                                placeholder="Enter description (optional)",
                                id=f"{id_prefix}-description-input",
                                autosize=True,
                                minRows=2,
                                maxRows=4,
                                style={"width": "100%"},
                            ),
                            # Data type selection
                            dmc.Select(
                                label="Data Type",
                                description="Type of data in your collection",
                                data=[
                                    {"value": "table", "label": "Table Data"},
                                    {"value": "jbrowse2", "label": "JBrowse2 Data"},
                                ],
                                id=f"{id_prefix}-type-select",
                                placeholder="Select data type",
                                value="table",  # Default to table
                                required=True,
                                leftSection=DashIconify(icon="mdi:format-list-bulleted", width=16),
                                style={"width": "100%"},
                            ),
                            # Scan mode indicator (read-only)
                            dmc.TextInput(
                                label="Scan Mode",
                                description="Single file upload mode (metadata only)",
                                value="Single File (Metadata)",
                                id=f"{id_prefix}-scan-mode-display",
                                readOnly=True,
                                leftSection=DashIconify(icon="mdi:file-document", width=16),
                                style={"width": "100%"},
                                styles={
                                    "input": {
                                        "backgroundColor": "var(--mantine-color-gray-1)",
                                        "color": "var(--mantine-color-gray-7)",
                                    }
                                },
                            ),
                            # File upload section
                            dmc.Stack(
                                gap="sm",
                                children=[
                                    dmc.Text(
                                        "File Upload",
                                        size="sm",
                                        fw="bold",
                                        c="gray",
                                    ),
                                    dmc.Text(
                                        "Upload your data file (maximum 5MB)",
                                        size="xs",
                                        c="gray",
                                    ),
                                    dcc.Loading(
                                        id=f"{id_prefix}-upload-loading",
                                        type="default",
                                        children=[
                                            dcc.Upload(
                                                id=f"{id_prefix}-file-upload",
                                                children=dmc.Paper(
                                                    children=[
                                                        dmc.Stack(
                                                            align="center",
                                                            gap="sm",
                                                            children=[
                                                                DashIconify(
                                                                    icon="mdi:cloud-upload",
                                                                    width=48,
                                                                    height=48,
                                                                    color="gray",
                                                                ),
                                                                dmc.Text(
                                                                    "Drag and drop a file here, or click to select",
                                                                    ta="center",
                                                                    size="sm",
                                                                    c="gray",
                                                                ),
                                                                dmc.Text(
                                                                    "Maximum file size: 5MB",
                                                                    ta="center",
                                                                    size="xs",
                                                                    c="gray",
                                                                ),
                                                            ],
                                                        )
                                                    ],
                                                    withBorder=True,
                                                    radius="md",
                                                    p="xl",
                                                    style={
                                                        "borderStyle": "dashed",
                                                        "borderWidth": "2px",
                                                        "cursor": "pointer",
                                                        "minHeight": "120px",
                                                        "display": "flex",
                                                        "alignItems": "center",
                                                        "justifyContent": "center",
                                                    },
                                                ),
                                                style={
                                                    "width": "100%",
                                                    "minHeight": "120px",
                                                },
                                                multiple=False,
                                                max_size=5 * 1024 * 1024,  # 5MB in bytes
                                            ),
                                        ],
                                    ),
                                    # File info display
                                    html.Div(
                                        id=f"{id_prefix}-file-info",
                                        children=[],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    # Buttons
                    dmc.Group(
                        justify="flex-end",
                        gap="md",
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
                                "Create Data Collection",
                                id=f"create-{id_prefix}-submit",
                                color="teal",
                                radius="md",
                                leftSection=DashIconify(icon="mdi:plus", width=16),
                                disabled=True,  # Start disabled
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    return modal, modal_id
