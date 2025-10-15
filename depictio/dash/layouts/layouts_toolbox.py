import dash_mantine_components as dmc
from dash import dcc, html
from dash_extensions import EventListener
from dash_iconify import DashIconify

from depictio.dash.colors import colors


def get_workflow_icon_mapping():
    """
    Map workflow systems to their logo image paths.

    Returns:
        dict: Workflow system to image path mapping
    """
    return {
        "nextflow": "/assets/images/workflows/nextflow.png",
        "snakemake": "/assets/images/workflows/snakemake.png",
        "nf-core": "/assets/images/workflows/nf-core.png",
        "galaxy": "/assets/images/workflows/galaxy.png",
        "iwc": "/assets/images/workflows/iwc.png",
        "none": None,  # Use custom icon
    }


def get_workflow_icon_color():
    """
    Map workflow systems to their brand colors.

    Returns:
        dict: Workflow system to color mapping
    """
    return {
        "nextflow": "teal",  # Nextflow green
        "snakemake": "green",  # Snakemake green
        "nf-core": "blue",  # nf-core blue
        "galaxy": "blue",  # Galaxy blue
        "iwc": "purple",  # IWC purple
        "none": "orange",  # Default
    }


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
            dmc.Stack(
                gap="lg",
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
                    # Two-column grid layout
                    dmc.Grid(
                        gutter="xl",
                        children=[
                            # Left column - Main form fields
                            dmc.GridCol(
                                span=7,
                                children=[
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
                                                leftSection=DashIconify(
                                                    icon="mdi:text-box-outline"
                                                ),
                                                style={"width": "100%"},
                                            ),
                                            # Dashboard subtitle input
                                            dmc.Textarea(
                                                label="Dashboard Subtitle (Optional)",
                                                description="Add a brief description for your dashboard",
                                                placeholder="Enter subtitle (optional)",
                                                id=f"{id_prefix}-subtitle-input",
                                                value="",
                                                autosize=True,
                                                minRows=2,
                                                maxRows=4,
                                                style={"width": "100%"},
                                            ),
                                            # Project dropdown
                                            dmc.Select(
                                                label="Project",
                                                description="Select the project this dashboard belongs to",
                                                data=[],  # Start empty, will be populated by callback
                                                id=f"{id_prefix}-projects",
                                                placeholder="Loading projects...",
                                                style={"width": "100%"},
                                                searchable=False,
                                                clearable=False,
                                                comboboxProps={"withinPortal": False},
                                            ),
                                            # Warning message (hidden by default)
                                            dmc.Alert(
                                                "Dashboard title must be unique",
                                                color="red",
                                                id="unique-title-warning",
                                                icon=DashIconify(icon="mdi:alert"),
                                                style={"display": "none"},
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            # Right column - Icon customization
                            dmc.GridCol(
                                span=5,
                                children=[
                                    dmc.Paper(
                                        shadow="sm",
                                        radius="md",
                                        withBorder=True,
                                        p="md",
                                        style={
                                            "height": "100%",
                                        },
                                        children=[
                                            dmc.Stack(
                                                gap="md",
                                                children=[
                                                    # Section header
                                                    dmc.Group(
                                                        justify="space-between",
                                                        children=[
                                                            dmc.Text(
                                                                "Icon Customization",
                                                                size="sm",
                                                                fw="bold",
                                                                c="gray",
                                                            ),
                                                        ],
                                                    ),
                                                    # Compact preview with form inputs
                                                    dmc.Group(
                                                        justify="space-between",
                                                        align="center",
                                                        children=[
                                                            dmc.Stack(
                                                                gap="2px",
                                                                children=[
                                                                    dmc.Text(
                                                                        "Preview",
                                                                        size="xs",
                                                                        c="gray",
                                                                    ),
                                                                    html.Div(
                                                                        id=f"{id_prefix}-icon-preview",
                                                                        children=[
                                                                            dmc.ActionIcon(
                                                                                DashIconify(
                                                                                    icon="mdi:view-dashboard",
                                                                                    width=24,
                                                                                    height=24,
                                                                                ),
                                                                                color="orange",  # Default orange, updated by callback
                                                                                radius="xl",
                                                                                size="lg",
                                                                                variant="filled",
                                                                                disabled=False,
                                                                            ),
                                                                        ],
                                                                    ),
                                                                ],
                                                                align="center",
                                                            ),
                                                        ],
                                                    ),
                                                    dmc.Divider(),
                                                    # Icon input
                                                    dmc.TextInput(
                                                        label="Dashboard Icon",
                                                        description="Icon from Iconify (e.g., mdi:chart-line)",
                                                        placeholder="mdi:view-dashboard",
                                                        id=f"{id_prefix}-icon-input",
                                                        value="mdi:view-dashboard",
                                                        leftSection=DashIconify(
                                                            icon="mdi:emoticon-outline", width=16
                                                        ),
                                                        size="sm",
                                                        style={"width": "100%"},
                                                    ),
                                                    # Link to browse icons
                                                    html.A(
                                                        dmc.Group(
                                                            [
                                                                DashIconify(
                                                                    icon="mdi:open-in-new",
                                                                    width=14,
                                                                ),
                                                                dmc.Text(
                                                                    "Browse MDI icons",
                                                                    size="xs",
                                                                    c="blue",
                                                                    style={
                                                                        "textDecoration": "none",
                                                                    },
                                                                ),
                                                            ],
                                                            gap="4px",
                                                            style={
                                                                "marginTop": "-8px",
                                                                "marginBottom": "4px",
                                                            },
                                                        ),
                                                        href="https://pictogrammers.com/library/mdi/",
                                                        target="_blank",
                                                        style={
                                                            "textDecoration": "none",
                                                            "display": "inline-block",
                                                        },
                                                    ),
                                                    # Icon color selection
                                                    dmc.Select(
                                                        label="Icon Color",
                                                        description="Color for the dashboard icon",
                                                        data=[
                                                            {"value": "blue", "label": "Blue"},
                                                            {"value": "teal", "label": "Teal"},
                                                            {"value": "orange", "label": "Orange"},
                                                            {"value": "red", "label": "Red"},
                                                            {"value": "purple", "label": "Purple"},
                                                            {"value": "pink", "label": "Pink"},
                                                            {"value": "green", "label": "Green"},
                                                            {"value": "gray", "label": "Gray"},
                                                        ],
                                                        id=f"{id_prefix}-icon-color-select",
                                                        value="orange",
                                                        leftSection=DashIconify(
                                                            icon="mdi:palette", width=16
                                                        ),
                                                        size="sm",
                                                        style={"width": "100%"},
                                                        comboboxProps={"withinPortal": False},
                                                    ),
                                                    # Workflow system selection
                                                    dmc.Divider(
                                                        label="Workflow System (Optional)",
                                                        labelPosition="center",
                                                        style={"marginTop": "16px"},
                                                    ),
                                                    dmc.Select(
                                                        label="Workflow System",
                                                        description="Auto-set icon based on workflow",
                                                        data=[
                                                            {
                                                                "value": "none",
                                                                "label": "None (Use Custom Icon)",
                                                            },
                                                            {
                                                                "value": "nextflow",
                                                                "label": "Nextflow",
                                                            },
                                                            {
                                                                "value": "snakemake",
                                                                "label": "Snakemake",
                                                            },
                                                            {
                                                                "value": "nf-core",
                                                                "label": "nf-core",
                                                            },
                                                            {
                                                                "value": "galaxy",
                                                                "label": "Galaxy",
                                                            },
                                                            {
                                                                "value": "iwc",
                                                                "label": "IWC (Intergalactic Workflow Commission)",
                                                            },
                                                        ],
                                                        id=f"{id_prefix}-workflow-system-select",
                                                        value="none",
                                                        leftSection=DashIconify(
                                                            icon="mdi:cog-outline", width=16
                                                        ),
                                                        size="sm",
                                                        comboboxProps={"withinPortal": False},
                                                    ),
                                                    dmc.Text(
                                                        "Selecting a workflow will override the custom icon",
                                                        size="xs",
                                                        c="gray",
                                                        style={"marginTop": "4px"},
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    # Buttons
                    dmc.Group(
                        justify="flex-end",
                        gap="md",
                        mt="md",
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
                                ],
                                id=f"{id_prefix}-type-select",
                                placeholder="Select data type",
                                value="table",  # Default to table
                                required=True,
                                leftSection=DashIconify(icon="mdi:format-list-bulleted", width=16),
                                style={"width": "100%"},
                                comboboxProps={"withinPortal": True, "zIndex": 10001},
                                disabled=True,  # Disabled since only one option
                            ),
                            # File format selection
                            dmc.Select(
                                label="File Format",
                                description="Format of your data file",
                                data=[
                                    {"value": "csv", "label": "CSV (Comma Separated)"},
                                    {"value": "tsv", "label": "TSV (Tab Separated)"},
                                    {"value": "parquet", "label": "Parquet"},
                                    {"value": "feather", "label": "Feather"},
                                    {"value": "xls", "label": "Excel (.xls)"},
                                    {"value": "xlsx", "label": "Excel (.xlsx)"},
                                ],
                                id=f"{id_prefix}-format-select",
                                placeholder="Select file format",
                                value="csv",  # Default to CSV
                                required=True,
                                leftSection=DashIconify(icon="mdi:file-table", width=16),
                                style={"width": "100%"},
                                comboboxProps={"withinPortal": True, "zIndex": 10001},
                            ),
                            # Separator selection (for delimited files)
                            html.Div(
                                id=f"{id_prefix}-separator-container",
                                children=[
                                    dmc.Select(
                                        label="Field Separator",
                                        description="Character that separates fields in your file",
                                        data=[
                                            {"value": ",", "label": "Comma (,)"},
                                            {"value": "\t", "label": "Tab (\\t)"},
                                            {"value": ";", "label": "Semicolon (;)"},
                                            {"value": "|", "label": "Pipe (|)"},
                                            {"value": "custom", "label": "Custom"},
                                        ],
                                        id=f"{id_prefix}-separator-select",
                                        value=",",  # Default to comma
                                        leftSection=DashIconify(
                                            icon="mdi:format-columns", width=16
                                        ),
                                        style={"width": "100%"},
                                        comboboxProps={"withinPortal": True, "zIndex": 10001},
                                    ),
                                ],
                            ),
                            # Custom separator input (hidden by default)
                            html.Div(
                                id=f"{id_prefix}-custom-separator-container",
                                children=[
                                    dmc.TextInput(
                                        label="Custom Separator",
                                        description="Enter your custom field separator",
                                        placeholder="e.g., #, @, etc.",
                                        id=f"{id_prefix}-custom-separator-input",
                                        leftSection=DashIconify(icon="mdi:format-text", width=16),
                                        style={"width": "100%"},
                                    ),
                                ],
                                style={"display": "none"},
                            ),
                            # Compression selection
                            dmc.Select(
                                label="Compression",
                                description="Compression format (if applicable)",
                                data=[
                                    {"value": "none", "label": "No Compression"},
                                    {"value": "gzip", "label": "GZIP (.gz)"},
                                    {"value": "zip", "label": "ZIP (.zip)"},
                                    {"value": "bz2", "label": "BZIP2 (.bz2)"},
                                ],
                                id=f"{id_prefix}-compression-select",
                                value="none",  # Default to no compression
                                leftSection=DashIconify(icon="mdi:archive", width=16),
                                style={"width": "100%"},
                                comboboxProps={"withinPortal": True, "zIndex": 10001},
                            ),
                            # Header row option
                            dmc.Switch(
                                label="File has header row",
                                description="Check if your file contains column names in the first row",
                                id=f"{id_prefix}-has-header-switch",
                                checked=True,  # Default to true
                                color="teal",
                                styles={
                                    "root": {"marginTop": "1rem"},
                                    "label": {"fontFamily": "inherit"},
                                    "description": {"fontFamily": "inherit"},
                                },
                            ),
                            # Scan mode selection (disabled since only one option)
                            dmc.Select(
                                label="Scan Mode",
                                description="Single file upload mode (metadata only)",
                                data=[
                                    {"value": "single", "label": "Single File (Metadata)"},
                                ],
                                id=f"{id_prefix}-scan-mode-select",
                                value="single",  # Default to single
                                leftSection=DashIconify(icon="mdi:file-document", width=16),
                                style={"width": "100%"},
                                comboboxProps={"withinPortal": True, "zIndex": 10001},
                                disabled=True,  # Disabled since only one option
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
                    # Error message display (hidden by default)
                    dmc.Alert(
                        "",
                        id=f"{id_prefix}-error-alert",
                        color="red",
                        icon=DashIconify(icon="mdi:alert"),
                        style={"display": "none"},
                        variant="filled",
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


def create_data_collection_overwrite_modal(
    opened=False,
    id_prefix="data-collection-overwrite",
    data_collection_name="",
    data_collection_id="",
):
    """
    Creates a modal for overwriting data collection files with schema validation.

    Parameters:
    - opened: Whether the modal is initially open
    - id_prefix: Prefix for all IDs in the modal
    - data_collection_name: Name of the data collection being overwritten
    - data_collection_id: ID of the data collection being overwritten

    Returns:
    - modal: The overwrite modal
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
                                icon="mdi:database-refresh",
                                width=40,
                                height=40,
                                color=colors["orange"],
                            ),
                            dmc.Title(
                                "Overwrite Data Collection",
                                order=2,
                                c="orange",
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(style={"marginTop": 5, "marginBottom": 5}),
                    # Info section
                    dmc.Alert(
                        f"You are about to overwrite the data in '{data_collection_name}'. The new file must match the existing schema (same column names and types).",
                        color="yellow",
                        icon=DashIconify(icon="mdi:information"),
                        variant="light",
                    ),
                    # File upload section
                    dmc.Stack(
                        gap="sm",
                        children=[
                            dmc.Text(
                                "Upload New File",
                                size="sm",
                                fw="bold",
                                c="gray",
                            ),
                            dmc.Text(
                                "Select a file to replace the existing data (maximum 5MB)",
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
                            # Schema validation results
                            html.Div(
                                id=f"{id_prefix}-schema-validation",
                                children=[],
                            ),
                        ],
                    ),
                    # Error message display (hidden by default)
                    dmc.Alert(
                        "",
                        id=f"{id_prefix}-error-alert",
                        color="red",
                        icon=DashIconify(icon="mdi:alert"),
                        style={"display": "none"},
                        variant="filled",
                    ),
                    # Hidden inputs to store data collection info
                    dcc.Store(id=f"{id_prefix}-dc-name", data=data_collection_name),
                    dcc.Store(id=f"{id_prefix}-dc-id", data=data_collection_id),
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
                                "Overwrite Data Collection",
                                id=f"confirm-{id_prefix}-submit",
                                color="orange",
                                radius="md",
                                leftSection=DashIconify(icon="mdi:database-refresh", width=16),
                                disabled=True,  # Start disabled
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    return modal, modal_id


def create_data_collection_edit_name_modal(
    opened=False,
    id_prefix="data-collection-edit-name",
    current_name="",
    data_collection_id="",
):
    """
    Creates a modal for editing data collection names.

    Parameters:
    - opened: Whether the modal is initially open
    - id_prefix: Prefix for all IDs in the modal
    - current_name: Current name of the data collection
    - data_collection_id: ID of the data collection being edited

    Returns:
    - modal: The edit name modal
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
        size="md",
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
                                icon="mdi:pencil",
                                width=40,
                                height=40,
                                color=colors["blue"],
                            ),
                            dmc.Title(
                                "Edit Data Collection Name",
                                order=2,
                                c="blue",
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(style={"marginTop": 5, "marginBottom": 5}),
                    # Form field
                    dmc.Stack(
                        gap="md",
                        children=[
                            dmc.TextInput(
                                label="Data Collection Name",
                                description="Enter a new name for the data collection",
                                placeholder="Enter new name",
                                id=f"{id_prefix}-name-input",
                                value=current_name,
                                required=True,
                                leftSection=DashIconify(icon="mdi:tag", width=16),
                                style={"width": "100%"},
                            ),
                        ],
                    ),
                    # Error message display (hidden by default)
                    dmc.Alert(
                        "",
                        id=f"{id_prefix}-error-alert",
                        color="red",
                        icon=DashIconify(icon="mdi:alert"),
                        style={"display": "none"},
                        variant="filled",
                    ),
                    # Hidden input to store data collection ID
                    dcc.Store(id=f"{id_prefix}-dc-id", data=data_collection_id),
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
                                "Save Changes",
                                id=f"confirm-{id_prefix}-submit",
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

    return modal, modal_id


def create_data_collection_delete_modal(
    opened=False,
    id_prefix="data-collection-delete",
    data_collection_name="",
    data_collection_id="",
):
    """
    Creates a modal for confirming data collection deletion.

    Parameters:
    - opened: Whether the modal is initially open
    - id_prefix: Prefix for all IDs in the modal
    - data_collection_name: Name of the data collection to delete
    - data_collection_id: ID of the data collection to delete

    Returns:
    - modal: The delete confirmation modal
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
        size="md",
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
                                icon="mdi:delete-alert",
                                width=40,
                                height=40,
                                color="red",
                            ),
                            dmc.Title(
                                "Delete Data Collection",
                                order=2,
                                c="red",
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(style={"marginTop": 5, "marginBottom": 5}),
                    # Warning message
                    dmc.Alert(
                        f"Are you sure you want to permanently delete the data collection '{data_collection_name}'? This action cannot be undone and will remove all associated data.",
                        color="red",
                        icon=DashIconify(icon="mdi:alert-circle"),
                        variant="light",
                    ),
                    # Confirmation text
                    dmc.Stack(
                        gap="sm",
                        children=[
                            dmc.Text(
                                "This will permanently remove:",
                                size="sm",
                                fw="bold",
                                c="gray",
                            ),
                            dmc.List(
                                [
                                    dmc.ListItem("All data files and metadata"),
                                    dmc.ListItem("Delta table information"),
                                    dmc.ListItem("Any associated visualizations"),
                                    dmc.ListItem("Join relationships with other collections"),
                                ],
                                size="sm",
                                c="gray",
                            ),
                        ],
                    ),
                    # Error message display (hidden by default)
                    dmc.Alert(
                        "",
                        id=f"{id_prefix}-error-alert",
                        color="red",
                        icon=DashIconify(icon="mdi:alert"),
                        style={"display": "none"},
                        variant="filled",
                    ),
                    # Hidden inputs to store data collection info
                    dcc.Store(id=f"{id_prefix}-dc-name", data=data_collection_name),
                    dcc.Store(id=f"{id_prefix}-dc-id", data=data_collection_id),
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
                                "Delete Data Collection",
                                id=f"confirm-{id_prefix}-submit",
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
