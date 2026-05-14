"""Reusable UI component toolbox for Depictio dashboard layouts.

This module provides factory functions for creating commonly used modal
dialogs and UI components throughout the application, including:

- Dashboard creation modal with icon customization
- Delete confirmation modal
- Add/Edit modals with input fields
- Password editing modal
- Data collection CRUD modals (create, edit, delete, overwrite)

All components follow DMC 2.0+ patterns and support dark/light themes.
"""

import dash_mantine_components as dmc
from dash import dcc, html
from dash_extensions import EventListener
from dash_iconify import DashIconify

from depictio.dash.colors import colors

# Shared options for icon color selection across create and edit modals
ICON_COLOR_OPTIONS = [
    {"value": "blue", "label": "Blue"},
    {"value": "teal", "label": "Teal"},
    {"value": "orange", "label": "Orange"},
    {"value": "red", "label": "Red"},
    {"value": "purple", "label": "Purple"},
    {"value": "pink", "label": "Pink"},
    {"value": "green", "label": "Green"},
    {"value": "gray", "label": "Gray"},
]

# Shared options for workflow system selection
WORKFLOW_SYSTEM_OPTIONS = [
    {"value": "none", "label": "None (Use Custom Icon)"},
    {"value": "nextflow", "label": "Nextflow"},
    {"value": "snakemake", "label": "Snakemake"},
    {"value": "nf-core", "label": "nf-core"},
    {"value": "galaxy", "label": "Galaxy"},
    {"value": "iwc", "label": "IWC (Intergalactic Workflow Commission)"},
]


def get_workflow_icon_mapping() -> dict[str, str | None]:
    """Map workflow systems to their logo image paths.

    Returns:
        Dictionary mapping workflow system names to asset paths.
        Value is None for systems using custom Iconify icons.
    """
    return {
        "nextflow": "/assets/images/workflows/nextflow.png",
        "snakemake": "/assets/images/workflows/snakemake.png",
        "nf-core": "/assets/images/workflows/nf-core.png",
        "galaxy": "/assets/images/workflows/galaxy.png",
        "iwc": "/assets/images/workflows/iwc.png",
        "none": None,  # Use custom icon
    }


def get_workflow_icon_color() -> dict[str, str]:
    """Map workflow systems to their brand colors.

    Returns:
        Dictionary mapping workflow system names to Mantine color names.
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
    dashboard_title: str = "",
    projects: list = [],
    selected_project: str | None = None,
    opened: bool = False,
    id_prefix: str = "dashboard",
) -> tuple[dmc.Modal, str]:
    """Create a dashboard creation modal with icon customization and import option.

    The modal includes tabs for:
    - Create New: Title, subtitle, project selection, icon customization
    - Import: JSON file upload with validation

    The Import tab is disabled in public/demo deployments — letting an
    anonymous visitor write user-supplied JSON into shared projects would
    bypass the project-permission model. Mirrored in the React equivalent at
    `depictio/viewer/src/dashboards/CreateDashboardModal.tsx`.

    Args:
        dashboard_title: Pre-filled dashboard title.
        projects: List of project options for dropdown (unused, populated by callback).
        selected_project: Pre-selected project ID.
        opened: Whether the modal starts open.
        id_prefix: Prefix for component IDs.

    Returns:
        Tuple of (modal component, modal ID string).
    """
    from depictio.api.v1.configs.config import settings

    import_disabled = bool(settings.auth.is_public_mode)
    modal_id = f"{id_prefix}-modal"

    # Create New tab content
    create_new_content = dmc.Stack(
        gap="lg",
        children=[
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
                                        leftSection=DashIconify(icon="mdi:text-box-outline"),
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
                                style={"height": "100%"},
                                children=[
                                    dmc.Stack(
                                        gap="md",
                                        children=[
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
                                            dmc.Group(
                                                justify="space-between",
                                                align="center",
                                                children=[
                                                    dmc.Stack(
                                                        gap="2px",
                                                        children=[
                                                            dmc.Text(
                                                                "Preview", size="xs", c="gray"
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
                                                                        color="orange",
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
                                            html.A(
                                                dmc.Group(
                                                    [
                                                        DashIconify(
                                                            icon="mdi:open-in-new", width=14
                                                        ),
                                                        dmc.Text(
                                                            "Browse MDI icons",
                                                            size="xs",
                                                            c="blue",
                                                            style={"textDecoration": "none"},
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
                                            dmc.Select(
                                                label="Icon Color",
                                                description="Color for the dashboard icon",
                                                data=ICON_COLOR_OPTIONS,
                                                id=f"{id_prefix}-icon-color-select",
                                                value="orange",
                                                leftSection=DashIconify(
                                                    icon="mdi:palette", width=16
                                                ),
                                                size="sm",
                                                style={"width": "100%"},
                                                comboboxProps={"withinPortal": False},
                                            ),
                                            dmc.Divider(
                                                label="Workflow System (Optional)",
                                                labelPosition="center",
                                                style={"marginTop": "16px"},
                                            ),
                                            dmc.Select(
                                                label="Workflow System",
                                                description="Auto-set icon based on workflow",
                                                data=WORKFLOW_SYSTEM_OPTIONS,
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
            # Create buttons
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
    )

    # Import tab content - two column layout
    import_content = dmc.Stack(
        gap="lg",
        children=[
            # Two-column grid layout
            dmc.Grid(
                gutter="xl",
                children=[
                    # Left column - File upload
                    dmc.GridCol(
                        span=6,
                        children=[
                            dmc.Paper(
                                p="lg",
                                radius="md",
                                withBorder=True,
                                style={"height": "100%"},
                                children=[
                                    dmc.Stack(
                                        gap="md",
                                        children=[
                                            dmc.Text("Upload JSON File", size="sm", fw=500),
                                            dcc.Upload(
                                                id="import-dashboard-upload",
                                                children=dmc.Stack(
                                                    gap="sm",
                                                    align="center",
                                                    children=[
                                                        DashIconify(
                                                            icon="mdi:file-upload-outline",
                                                            height=48,
                                                            color=colors["grey"],
                                                        ),
                                                        dmc.Text(
                                                            "Drag and drop or click to upload",
                                                            size="sm",
                                                            c="dimmed",
                                                        ),
                                                        dmc.Text(
                                                            "Accepts .json files",
                                                            size="xs",
                                                            c="dimmed",
                                                        ),
                                                    ],
                                                ),
                                                style={
                                                    "width": "100%",
                                                    "borderWidth": "2px",
                                                    "borderStyle": "dashed",
                                                    "borderRadius": "8px",
                                                    "borderColor": "var(--app-border-color, #ddd)",
                                                    "padding": "40px 20px",
                                                    "textAlign": "center",
                                                    "cursor": "pointer",
                                                },
                                                accept=".json",
                                                multiple=False,
                                            ),
                                            # Uploaded file info
                                            html.Div(id="import-dashboard-file-info"),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    # Right column - Instructions and options
                    dmc.GridCol(
                        span=6,
                        children=[
                            dmc.Stack(
                                gap="md",
                                children=[
                                    # Instructions
                                    dmc.Alert(
                                        "Upload a JSON file exported from Depictio to import a "
                                        "dashboard. The import will validate that data collections "
                                        "exist in the target project.",
                                        icon=DashIconify(icon="mdi:information-outline"),
                                        color="blue",
                                    ),
                                    # Project selection
                                    dmc.Select(
                                        id="import-dashboard-project-select",
                                        label="Target Project",
                                        description="Select the project to import the dashboard into",
                                        placeholder="Select a project...",
                                        data=[],
                                        searchable=True,
                                        clearable=True,
                                        comboboxProps={"withinPortal": False},
                                    ),
                                    # Options
                                    dmc.Checkbox(
                                        id="import-dashboard-validate-integrity",
                                        label="Validate data integrity (check that data collections exist)",
                                        checked=True,
                                    ),
                                    # Validation results area
                                    html.Div(id="import-dashboard-validation-results"),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            # Store for JSON content
            dcc.Store(id="import-dashboard-json-store", data=None),
            # Import buttons
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
                        id="import-dashboard-cancel",
                    ),
                    dmc.Button(
                        "Validate",
                        id="import-dashboard-validate-btn",
                        variant="outline",
                        color="blue",
                        radius="md",
                        leftSection=DashIconify(icon="mdi:check-circle-outline", width=16),
                        disabled=True,
                    ),
                    dmc.Button(
                        "Import Dashboard",
                        id="import-dashboard-submit",
                        color="orange",
                        radius="md",
                        leftSection=DashIconify(icon="mdi:import", width=16),
                        disabled=True,
                    ),
                ],
            ),
        ],
    )

    modal = dmc.Modal(
        opened=opened,
        id=modal_id,
        centered=True,
        withCloseButton=True,
        closeOnClickOutside=False,
        closeOnEscape=False,
        overlayProps={"overlayBlur": 3, "overlayOpacity": 0.55},
        shadow="xl",
        radius="md",
        size=1500,
        zIndex=10000,
        styles={"modal": {"padding": "28px"}},
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
                                "New Dashboard",
                                order=1,
                                c="orange",
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Tabs with pills style
                    dmc.Tabs(
                        id="dashboard-modal-tabs",
                        value="create",
                        variant="pills",
                        children=[
                            dmc.TabsList(
                                [
                                    dmc.TabsTab(
                                        dmc.Text(
                                            "Create New",
                                            size="md",
                                            fw=500,
                                            style={"fontFamily": "Virgil"},
                                        ),
                                        value="create",
                                        leftSection=DashIconify(icon="mdi:plus", width=18),
                                        color="orange",
                                    ),
                                    dmc.TabsTab(
                                        dmc.Text(
                                            "Import",
                                            size="md",
                                            fw=500,
                                            style={"fontFamily": "Virgil"},
                                        ),
                                        value="import",
                                        leftSection=DashIconify(icon="mdi:import", width=18),
                                        color="orange",
                                        disabled=import_disabled,
                                    ),
                                ],
                                justify="center",
                                style={"gap": "12px"},
                            ),
                            dmc.TabsPanel(create_new_content, value="create", pt="lg"),
                            dmc.TabsPanel(import_content, value="import", pt="lg"),
                        ],
                    ),
                ],
            ),
        ],
    )

    return modal, modal_id


def create_delete_confirmation_modal(
    id_prefix: str,
    item_id: str,
    title: str = "Confirm Deletion",
    message: str = "Are you sure you want to delete this item? This action cannot be undone.",
    delete_button_text: str = "Delete",
    cancel_button_text: str = "Cancel",
    icon: str = "mdi:alert-circle",
    opened: bool = False,
) -> tuple[dmc.Modal, dict]:
    """Create a reusable deletion confirmation modal.

    Args:
        id_prefix: Prefix for component IDs (used in pattern matching).
        item_id: Unique identifier for the item being deleted.
        title: Modal title text.
        message: Warning message displayed to user.
        delete_button_text: Text for delete confirmation button.
        cancel_button_text: Text for cancel button.
        icon: Iconify icon name for header.
        opened: Whether the modal starts open.

    Returns:
        Tuple of (modal component, modal ID dict for pattern matching).
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


def create_edit_dashboard_modal(
    dashboard_id: str,
    title: str = "",
    subtitle: str = "",
    icon: str = "mdi:view-dashboard",
    icon_color: str = "orange",
    workflow_system: str = "none",
    opened: bool = False,
) -> tuple[dmc.Modal, dict]:
    """Create a dashboard edit modal with all editable fields.

    The modal includes:
    - Title input (required)
    - Subtitle textarea (optional)
    - Icon customization (icon identifier and color)
    - Workflow system selection

    Args:
        dashboard_id: The unique dashboard ID for pattern matching.
        title: Pre-filled dashboard title.
        subtitle: Pre-filled dashboard subtitle.
        icon: Pre-filled icon identifier.
        icon_color: Pre-filled icon color.
        workflow_system: Pre-filled workflow system.
        opened: Whether the modal starts open.

    Returns:
        Tuple of (modal component, modal ID dict for pattern matching).
    """
    modal_id = {
        "type": "edit-dashboard-modal",
        "index": dashboard_id,
    }

    modal = dmc.Modal(
        id=modal_id,
        opened=opened,
        centered=True,
        withCloseButton=True,
        closeOnClickOutside=False,
        closeOnEscape=True,
        overlayProps={
            "overlayOpacity": 0.55,
            "overlayBlur": 3,
        },
        shadow="xl",
        radius="md",
        size="lg",
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
                                icon="mdi:pencil-box-outline",
                                width=28,
                                height=28,
                                color="#228be6",
                            ),
                            dmc.Title(
                                "Edit Dashboard",
                                order=4,
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(),
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
                                                id={
                                                    "type": "edit-dashboard-title",
                                                    "index": dashboard_id,
                                                },
                                                value=title,
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
                                                id={
                                                    "type": "edit-dashboard-subtitle",
                                                    "index": dashboard_id,
                                                },
                                                value=subtitle,
                                                autosize=True,
                                                minRows=2,
                                                maxRows=4,
                                                style={"width": "100%"},
                                            ),
                                            # Error message placeholder
                                            dmc.Text(
                                                id={
                                                    "type": "edit-dashboard-error",
                                                    "index": dashboard_id,
                                                },
                                                c="red",
                                                size="sm",
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
                                                    # Compact preview
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
                                                                        id={
                                                                            "type": "edit-dashboard-icon-preview",
                                                                            "index": dashboard_id,
                                                                        },
                                                                        children=[
                                                                            dmc.ActionIcon(
                                                                                DashIconify(
                                                                                    icon=icon,
                                                                                    width=24,
                                                                                    height=24,
                                                                                ),
                                                                                color=icon_color,
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
                                                        id={
                                                            "type": "edit-dashboard-icon",
                                                            "index": dashboard_id,
                                                        },
                                                        value=icon,
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
                                                        data=ICON_COLOR_OPTIONS,
                                                        id={
                                                            "type": "edit-dashboard-icon-color",
                                                            "index": dashboard_id,
                                                        },
                                                        value=icon_color,
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
                                                        data=WORKFLOW_SYSTEM_OPTIONS,
                                                        id={
                                                            "type": "edit-dashboard-workflow",
                                                            "index": dashboard_id,
                                                        },
                                                        value=workflow_system,
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
                                id={
                                    "type": "cancel-edit-dashboard",
                                    "index": dashboard_id,
                                },
                                color="gray",
                                variant="outline",
                                radius="md",
                            ),
                            dmc.Button(
                                "Save Changes",
                                id={
                                    "type": "save-edit-dashboard",
                                    "index": dashboard_id,
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

    return modal, modal_id


def create_add_with_input_modal(
    id_prefix: str,
    input_field,
    item_id: str | None = None,
    title: str = "Add Item",
    title_color: str = "blue",
    message: str = "Please complete the input field to add a new item.",
    confirm_button_text: str = "Add",
    confirm_button_color: str = "blue",
    cancel_button_text: str = "Cancel",
    icon: str = "mdi:plus",
    opened: bool = False,
) -> tuple[dmc.Modal, dict | str]:
    """Create a reusable modal with a custom input field.

    Used for adding or editing items with form input validation.

    Args:
        id_prefix: Prefix for component IDs.
        input_field: Dash component for user input (TextInput, Select, etc.).
        item_id: Optional unique identifier for pattern matching.
        title: Modal title text.
        title_color: Mantine color for title and icon.
        message: Description text shown above input.
        confirm_button_text: Text for confirmation button.
        confirm_button_color: Mantine color for confirm button.
        cancel_button_text: Text for cancel button.
        icon: Iconify icon name for header.
        opened: Whether the modal starts open.

    Returns:
        Tuple of (modal component, modal ID - dict if item_id provided, else string).
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
    title: str = "Edit Password",
    opened: bool = False,
    event: dict | None = None,
) -> dmc.Modal:
    """Create a password editing modal with validation fields.

    Includes fields for old password, new password, and confirmation.
    Uses EventListener for enhanced interaction handling.

    Args:
        title: Modal title text.
        opened: Whether the modal starts open.
        event: Optional event dictionary for EventListener.

    Returns:
        Modal component with password change form.
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
    opened: bool = False,
    id_prefix: str = "data-collection-creation",
) -> tuple[dmc.Modal, str]:
    """Unified data-collection modal with mode-driven section visibility.

    A single mode-agnostic modal that supports three runtime behaviors,
    selected via a sibling ``dcc.Store(id="data-collection-modal-mode")``:

    - ``create``: name/description/type fields, dropzone, "Create" submit.
    - ``update``: replace toggle + dropzone, "Append folders" / "Replace all
      data" submit (label tracks the toggle).
    - ``clear``: warning banner, folder list preview, typed-name confirm
      input, red "Clear data collection" submit.

    All sections render unconditionally; the calling layout module wires a
    callback that toggles each section's ``style.display`` based on the
    active mode. Section container IDs (used by that callback):

    - ``f"{id_prefix}-name-input-container"``
    - ``f"{id_prefix}-description-input-container"``
    - ``f"{id_prefix}-type-select-container"``
    - ``f"{id_prefix}-table-options-container"``
    - ``f"{id_prefix}-multiqc-options-container"``
    - ``f"{id_prefix}-replace-toggle-container"``
    - ``f"{id_prefix}-dropzone-container"``
    - ``f"{id_prefix}-clear-warning-container"``
    - ``f"{id_prefix}-clear-summary-container"``
    - ``f"{id_prefix}-clear-confirm-container"``

    Other notable IDs:

    - Title text: ``f"{id_prefix}-title-text"``
    - Title icon: ``f"{id_prefix}-title-icon"`` (DashIconify)
    - Submit button: ``f"create-{id_prefix}-submit"``
    - Cancel button: ``f"cancel-{id_prefix}-button"``
    - Replace toggle: ``f"{id_prefix}-replace-toggle"``
    - Dropzone: ``f"{id_prefix}-file-upload"``
    - File info: ``f"{id_prefix}-file-info"``
    - Clear summary text: ``f"{id_prefix}-clear-summary"``
    - Clear folder list code block: ``f"{id_prefix}-clear-folder-list"``
    - Clear typed-name input: ``f"{id_prefix}-clear-confirm-name-input"``
    - Clear expected-name store: ``f"{id_prefix}-clear-expected-name"``

    Args:
        opened: Whether the modal starts open.
        id_prefix: Prefix for component IDs.

    Returns:
        Tuple of (modal component, modal ID string).
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
                    # Header with icon and title (icon + color updated by mode callback)
                    dmc.Group(
                        justify="center",
                        gap="sm",
                        children=[
                            html.Div(
                                id=f"{id_prefix}-title-icon-container",
                                children=[
                                    DashIconify(
                                        id=f"{id_prefix}-title-icon",
                                        icon="mdi:database-plus",
                                        width=40,
                                        height=40,
                                        color=colors["teal"],
                                    ),
                                ],
                            ),
                            dmc.Title(
                                "Create Data Collection",
                                id=f"{id_prefix}-title-text",
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
                            # Data collection name (visible only in create mode)
                            html.Div(
                                id=f"{id_prefix}-name-input-container",
                                style={"width": "100%"},
                                children=[
                                    dmc.TextInput(
                                        label="Data Collection Name",
                                        description="Unique identifier for your data collection",
                                        placeholder="Enter data collection name",
                                        id=f"{id_prefix}-name-input",
                                        required=True,
                                        leftSection=DashIconify(icon="mdi:tag", width=16),
                                        style={"width": "100%"},
                                    ),
                                ],
                            ),
                            # Description (visible only in create mode)
                            html.Div(
                                id=f"{id_prefix}-description-input-container",
                                style={"width": "100%"},
                                children=[
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
                                ],
                            ),
                            # Data type selection (visible only in create mode)
                            html.Div(
                                id=f"{id_prefix}-type-select-container",
                                style={"width": "100%"},
                                children=[
                                    dmc.Select(
                                        label="Data Type",
                                        description="Type of data in your collection",
                                        data=[
                                            {"value": "table", "label": "Table Data"},
                                            {"value": "multiqc", "label": "MultiQC Report"},
                                        ],
                                        id=f"{id_prefix}-type-select",
                                        placeholder="Select data type",
                                        value="table",  # Default to table
                                        required=True,
                                        leftSection=DashIconify(
                                            icon="mdi:format-list-bulleted", width=16
                                        ),
                                        style={"width": "100%"},
                                        comboboxProps={"withinPortal": True, "zIndex": 10001},
                                    ),
                                ],
                            ),
                            # Table-specific options container
                            html.Div(
                                id=f"{id_prefix}-table-options-container",
                                children=[
                                    dmc.Stack(
                                        gap="md",
                                        children=[
                                            # File format selection
                                            dmc.Select(
                                                label="File Format",
                                                description="Format of your data file",
                                                data=[
                                                    {
                                                        "value": "csv",
                                                        "label": "CSV (Comma Separated)",
                                                    },
                                                    {
                                                        "value": "tsv",
                                                        "label": "TSV (Tab Separated)",
                                                    },
                                                    {"value": "parquet", "label": "Parquet"},
                                                    {"value": "feather", "label": "Feather"},
                                                    {"value": "xls", "label": "Excel (.xls)"},
                                                    {"value": "xlsx", "label": "Excel (.xlsx)"},
                                                ],
                                                id=f"{id_prefix}-format-select",
                                                placeholder="Select file format",
                                                value="csv",  # Default to CSV
                                                required=True,
                                                leftSection=DashIconify(
                                                    icon="mdi:file-table", width=16
                                                ),
                                                style={"width": "100%"},
                                                comboboxProps={
                                                    "withinPortal": True,
                                                    "zIndex": 10001,
                                                },
                                            ),
                                            # Separator selection (for delimited files)
                                            html.Div(
                                                id=f"{id_prefix}-separator-container",
                                                children=[
                                                    dmc.Select(
                                                        label="Field Separator",
                                                        description="Character that separates fields in your file",
                                                        data=[
                                                            {
                                                                "value": ",",
                                                                "label": "Comma (,)",
                                                            },
                                                            {
                                                                "value": "\t",
                                                                "label": "Tab (\\t)",
                                                            },
                                                            {
                                                                "value": ";",
                                                                "label": "Semicolon (;)",
                                                            },
                                                            {
                                                                "value": "|",
                                                                "label": "Pipe (|)",
                                                            },
                                                            {
                                                                "value": "custom",
                                                                "label": "Custom",
                                                            },
                                                        ],
                                                        id=f"{id_prefix}-separator-select",
                                                        value=",",  # Default to comma
                                                        leftSection=DashIconify(
                                                            icon="mdi:format-columns", width=16
                                                        ),
                                                        style={"width": "100%"},
                                                        comboboxProps={
                                                            "withinPortal": True,
                                                            "zIndex": 10001,
                                                        },
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
                                                        leftSection=DashIconify(
                                                            icon="mdi:format-text", width=16
                                                        ),
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
                                                    {
                                                        "value": "none",
                                                        "label": "No Compression",
                                                    },
                                                    {"value": "gzip", "label": "GZIP (.gz)"},
                                                    {"value": "zip", "label": "ZIP (.zip)"},
                                                    {"value": "bz2", "label": "BZIP2 (.bz2)"},
                                                ],
                                                id=f"{id_prefix}-compression-select",
                                                value="none",  # Default to no compression
                                                leftSection=DashIconify(
                                                    icon="mdi:archive", width=16
                                                ),
                                                style={"width": "100%"},
                                                comboboxProps={
                                                    "withinPortal": True,
                                                    "zIndex": 10001,
                                                },
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
                                            # Scan mode selection
                                            dmc.Select(
                                                label="Scan Mode",
                                                description="Single file upload mode (metadata only)",
                                                data=[
                                                    {
                                                        "value": "single",
                                                        "label": "Single File (Metadata)",
                                                    },
                                                ],
                                                id=f"{id_prefix}-scan-mode-select",
                                                value="single",
                                                leftSection=DashIconify(
                                                    icon="mdi:file-document", width=16
                                                ),
                                                style={"width": "100%"},
                                                comboboxProps={
                                                    "withinPortal": True,
                                                    "zIndex": 10001,
                                                },
                                                disabled=True,
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            # MultiQC-specific options container (hidden by default)
                            html.Div(
                                id=f"{id_prefix}-multiqc-options-container",
                                children=[
                                    dmc.Stack(
                                        gap="md",
                                        children=[
                                            dmc.Alert(
                                                "Upload one or more MultiQC parquet files "
                                                "(multiqc.parquet). Only .parquet format is "
                                                "supported, generated by MultiQC >= 1.30. "
                                                "Max 50MB per file, 500MB total.",
                                                color="teal",
                                                icon=DashIconify(icon="mdi:information"),
                                                variant="light",
                                            ),
                                        ],
                                    ),
                                ],
                                style={"display": "none"},
                            ),
                            # Action segment (visible only in manage flow — i.e.,
                            # update + clear modes). Lets the user switch between
                            # "Modify" (drop folders) and "Clear" (wipe contents)
                            # in a single modal without leaving it.
                            html.Div(
                                id=f"{id_prefix}-action-segment-container",
                                style={"display": "none"},
                                children=[
                                    dmc.SegmentedControl(
                                        id=f"{id_prefix}-action-segment",
                                        value="modify",
                                        fullWidth=True,
                                        data=[
                                            {
                                                "value": "modify",
                                                "label": "Modify data",
                                            },
                                            {
                                                "value": "clear",
                                                "label": "Clear contents",
                                            },
                                        ],
                                        mb="md",
                                    ),
                                ],
                            ),
                            # Replace toggle (visible only in update mode) — controls
                            # whether the incoming upload appends to or wipes the
                            # existing DC. Wrapped in a stable container so the
                            # mode-visibility callback can toggle display.
                            html.Div(
                                id=f"{id_prefix}-replace-toggle-container",
                                style={"display": "none"},
                                children=[
                                    dmc.Switch(
                                        id=f"{id_prefix}-replace-toggle",
                                        label="Replace existing data",
                                        description=(
                                            "When OFF, new folders are appended. "
                                            "When ON, the entire DC is wiped and re-ingested."
                                        ),
                                        checked=False,
                                        color="red",
                                        mb="md",
                                    ),
                                ],
                            ),
                            # File upload section (visible in create + update)
                            html.Div(
                                id=f"{id_prefix}-dropzone-container",
                                children=[
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
                                                "Upload your data file(s) (max 5MB for tables; "
                                                "for MultiQC: drop folders containing multiqc.parquet, "
                                                "50MB per file, 500MB total)",
                                                size="xs",
                                                c="gray",
                                                id=f"{id_prefix}-upload-size-hint",
                                            ),
                                            dcc.Loading(
                                                id=f"{id_prefix}-upload-loading",
                                                type="default",
                                                children=[
                                                    dcc.Upload(
                                                        id=f"{id_prefix}-file-upload",
                                                        # className is toggled by a clientside
                                                        # callback to enable folder-pick mode
                                                        # (webkitdirectory) for MultiQC uploads.
                                                        className="",
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
                                                                            "Drag and drop file(s) or folder(s) here, or click to select",
                                                                            ta="center",
                                                                            size="sm",
                                                                            c="gray",
                                                                        ),
                                                                        dmc.Text(
                                                                            "Tables: 1 file, max 5MB | MultiQC: drop folder(s); only multiqc.parquet is extracted",
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
                                                        # MultiQC allows multiple parquet files.
                                                        multiple=True,
                                                        max_size=50 * 1024 * 1024,  # 50MB per file
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
                            # Clear-mode warning banner (visible only in clear mode)
                            html.Div(
                                id=f"{id_prefix}-clear-warning-container",
                                style={"display": "none"},
                                children=[
                                    dmc.Alert(
                                        (
                                            "This will permanently delete all reports and "
                                            "ingested data. The DC itself, its name, and any "
                                            "links pointing to it will be preserved. This "
                                            "action cannot be undone."
                                        ),
                                        color="red",
                                        icon=DashIconify(icon="mdi:alert"),
                                        variant="light",
                                    ),
                                ],
                            ),
                            # Clear-mode summary + folder list (visible only in clear mode)
                            html.Div(
                                id=f"{id_prefix}-clear-summary-container",
                                style={"display": "none"},
                                children=[
                                    dmc.Stack(
                                        gap="xs",
                                        children=[
                                            dmc.Text(
                                                "",
                                                id=f"{id_prefix}-clear-summary",
                                                size="sm",
                                                fw="bold",
                                                c="gray",
                                            ),
                                            dmc.Code(
                                                "",
                                                id=f"{id_prefix}-clear-folder-list",
                                                block=True,
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            # Clear-mode typed-name confirmation (visible only in clear mode)
                            html.Div(
                                id=f"{id_prefix}-clear-confirm-container",
                                style={"display": "none"},
                                children=[
                                    dmc.TextInput(
                                        id=f"{id_prefix}-clear-confirm-name-input",
                                        label="Type the data collection name to confirm:",
                                        placeholder="data collection name",
                                        required=True,
                                    ),
                                ],
                            ),
                            # Hidden store carrying the expected DC name (clear mode).
                            dcc.Store(id=f"{id_prefix}-clear-expected-name"),
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
                                leftSection=DashIconify(
                                    id=f"create-{id_prefix}-submit-icon",
                                    icon="mdi:plus",
                                    width=16,
                                ),
                                disabled=True,  # Start disabled; mode callback re-evaluates.
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    return modal, modal_id


def create_dc_link_modal(
    opened: bool = False,
    id_prefix: str = "dc-link-creation",
) -> tuple[dmc.Modal, str]:
    """Create a modal for linking data collections together.

    Allows users to define cross-DC filtering relationships by selecting
    a source DC + column, target DC, target type, and resolver strategy.

    Args:
        opened: Whether the modal starts open.
        id_prefix: Prefix for component IDs.

    Returns:
        Tuple of (modal component, modal ID string).
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
                    # Header
                    dmc.Group(
                        justify="center",
                        gap="sm",
                        children=[
                            DashIconify(
                                icon="mdi:link-variant-plus",
                                width=40,
                                height=40,
                                color=colors["blue"],
                            ),
                            dmc.Title(
                                "Link Data Collections",
                                order=2,
                                c="blue",
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    dmc.Divider(style={"marginTop": 5, "marginBottom": 5}),
                    # Info alert
                    dmc.Alert(
                        "Links enable cross-DC filtering: when you filter data in the "
                        "source collection, the target collection updates automatically. "
                        "For example, filtering a metadata table by sample ID can update "
                        "a MultiQC report to show only matching samples.",
                        color="blue",
                        icon=DashIconify(icon="mdi:information"),
                        variant="light",
                    ),
                    # Form fields
                    dmc.Stack(
                        gap="md",
                        children=[
                            # Source DC selection
                            dmc.Select(
                                label="Source Data Collection",
                                description="The collection where filters are applied",
                                placeholder="Select source collection",
                                id=f"{id_prefix}-source-dc-select",
                                data=[],
                                required=True,
                                leftSection=DashIconify(icon="mdi:database-arrow-right", width=16),
                                style={"width": "100%"},
                                comboboxProps={"withinPortal": True, "zIndex": 10001},
                            ),
                            # Source column selection
                            dmc.Select(
                                label="Source Column",
                                description="Column containing the values to link on",
                                placeholder="Select a column from the source",
                                id=f"{id_prefix}-source-column-select",
                                data=[],
                                required=True,
                                leftSection=DashIconify(icon="mdi:table-column", width=16),
                                style={"width": "100%"},
                                comboboxProps={"withinPortal": True, "zIndex": 10001},
                                disabled=True,
                            ),
                            dmc.Divider(
                                label="links to",
                                labelPosition="center",
                                style={"marginTop": 8, "marginBottom": 8},
                            ),
                            # Target DC selection
                            dmc.Select(
                                label="Target Data Collection",
                                description="The collection that receives filtered values",
                                placeholder="Select target collection",
                                id=f"{id_prefix}-target-dc-select",
                                data=[],
                                required=True,
                                leftSection=DashIconify(icon="mdi:database-arrow-left", width=16),
                                style={"width": "100%"},
                                comboboxProps={"withinPortal": True, "zIndex": 10001},
                            ),
                            # Target type (auto-detected)
                            dmc.TextInput(
                                label="Target Type",
                                description="Auto-detected from the selected target collection",
                                id=f"{id_prefix}-target-type-input",
                                value="",
                                disabled=True,
                                leftSection=DashIconify(icon="mdi:tag", width=16),
                                style={"width": "100%"},
                            ),
                            # Resolver strategy
                            dmc.Select(
                                label="Resolver Strategy",
                                description="How to map values from source to target",
                                data=[
                                    {"value": "direct", "label": "Direct (1:1 mapping)"},
                                    {
                                        "value": "sample_mapping",
                                        "label": "Sample Mapping (expand canonical IDs)",
                                    },
                                    {"value": "regex", "label": "Regex (pattern matching)"},
                                    {"value": "wildcard", "label": "Wildcard (glob matching)"},
                                ],
                                id=f"{id_prefix}-resolver-select",
                                value="direct",
                                required=True,
                                leftSection=DashIconify(icon="mdi:swap-horizontal", width=16),
                                style={"width": "100%"},
                                comboboxProps={"withinPortal": True, "zIndex": 10001},
                            ),
                            # Description
                            dmc.Textarea(
                                label="Description",
                                description="Optional description of the link purpose",
                                placeholder="e.g., Link metadata samples to MultiQC reports",
                                id=f"{id_prefix}-description-input",
                                autosize=True,
                                minRows=2,
                                maxRows=3,
                                style={"width": "100%"},
                            ),
                        ],
                    ),
                    # Error alert
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
                                "Create Link",
                                id=f"create-{id_prefix}-submit",
                                color="blue",
                                radius="md",
                                leftSection=DashIconify(icon="mdi:link-variant-plus", width=16),
                                disabled=True,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    return modal, modal_id


def create_data_collection_overwrite_modal(
    opened: bool = False,
    id_prefix: str = "data-collection-overwrite",
    data_collection_name: str = "",
    data_collection_id: str = "",
) -> tuple[dmc.Modal, str]:
    """Create a modal for overwriting data collection files.

    Includes schema validation to ensure the new file matches
    the existing column structure.

    Args:
        opened: Whether the modal starts open.
        id_prefix: Prefix for component IDs.
        data_collection_name: Name of collection being overwritten.
        data_collection_id: ID of collection being overwritten.

    Returns:
        Tuple of (modal component, modal ID string).
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
    opened: bool = False,
    id_prefix: str = "data-collection-edit-name",
    current_name: str = "",
    data_collection_id: str = "",
) -> tuple[dmc.Modal, str]:
    """Create a modal for renaming a data collection.

    Args:
        opened: Whether the modal starts open.
        id_prefix: Prefix for component IDs.
        current_name: Current name to pre-fill in input.
        data_collection_id: ID of collection being renamed.

    Returns:
        Tuple of (modal component, modal ID string).
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
    opened: bool = False,
    id_prefix: str = "data-collection-delete",
    data_collection_name: str = "",
    data_collection_id: str = "",
) -> tuple[dmc.Modal, str]:
    """Create a modal for confirming data collection deletion.

    Shows a warning about permanent deletion and lists all
    data that will be removed (files, delta tables, visualizations, joins).

    Args:
        opened: Whether the modal starts open.
        id_prefix: Prefix for component IDs.
        data_collection_name: Name of collection to delete.
        data_collection_id: ID of collection to delete.

    Returns:
        Tuple of (modal component, modal ID string).
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


def create_dashboard_import_modal(
    projects: list | None = None,
    id_prefix: str = "import-dashboard",
) -> tuple[dmc.Modal, str]:
    """Create a dashboard import modal with file upload and validation.

    The modal includes:
    - JSON file upload area
    - Project selection dropdown
    - Validation results display
    - Import button with validation toggle

    Args:
        projects: List of project options for dropdown (populated by callback).
        id_prefix: Prefix for component IDs.

    Returns:
        Tuple of (modal component, modal ID string).
    """
    modal_id = f"{id_prefix}-modal"

    modal = dmc.Modal(
        id=modal_id,
        title=dmc.Group(
            [
                DashIconify(icon="mdi:import", height=24, color=colors["purple"]),
                dmc.Text("Import Dashboard", fw=600, size="lg"),
            ],
            gap="sm",
        ),
        opened=False,
        centered=True,
        size="lg",
        children=[
            dmc.Stack(
                gap="lg",
                children=[
                    # Instructions
                    dmc.Alert(
                        "Upload a JSON file exported from Depictio to import a dashboard. "
                        "The import will validate that data collections exist in the target project.",
                        icon=DashIconify(icon="mdi:information-outline"),
                        color="blue",
                    ),
                    # File upload area
                    dmc.Paper(
                        p="lg",
                        radius="md",
                        withBorder=True,
                        children=[
                            dmc.Stack(
                                gap="md",
                                children=[
                                    dmc.Text("Upload JSON File", size="sm", fw=500),
                                    dcc.Upload(
                                        id=f"{id_prefix}-upload",
                                        children=dmc.Stack(
                                            gap="sm",
                                            align="center",
                                            children=[
                                                DashIconify(
                                                    icon="mdi:file-upload-outline",
                                                    height=48,
                                                    color=colors["grey"],
                                                ),
                                                dmc.Text(
                                                    "Drag and drop or click to upload",
                                                    size="sm",
                                                    c="dimmed",
                                                ),
                                                dmc.Text(
                                                    "Accepts .json files",
                                                    size="xs",
                                                    c="dimmed",
                                                ),
                                            ],
                                        ),
                                        style={
                                            "width": "100%",
                                            "borderWidth": "2px",
                                            "borderStyle": "dashed",
                                            "borderRadius": "8px",
                                            "borderColor": "var(--app-border-color, #ddd)",
                                            "padding": "20px",
                                            "textAlign": "center",
                                            "cursor": "pointer",
                                        },
                                        accept=".json",
                                        multiple=False,
                                    ),
                                    # Uploaded file info
                                    html.Div(id=f"{id_prefix}-file-info"),
                                ],
                            ),
                        ],
                    ),
                    # Project selection
                    dmc.Select(
                        id=f"{id_prefix}-project-select",
                        label="Target Project",
                        description="Select the project to import the dashboard into",
                        placeholder="Select a project...",
                        data=projects or [],
                        searchable=True,
                        clearable=True,
                    ),
                    # Validation results area
                    html.Div(id=f"{id_prefix}-validation-results"),
                    # Options
                    dmc.Checkbox(
                        id=f"{id_prefix}-validate-integrity",
                        label="Validate data integrity (check that data collections exist)",
                        checked=True,
                    ),
                    # Store for JSON content
                    dcc.Store(id=f"{id_prefix}-json-store", data=None),
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
                                id=f"{id_prefix}-cancel",
                            ),
                            dmc.Button(
                                "Validate",
                                id=f"{id_prefix}-validate-btn",
                                variant="outline",
                                color="blue",
                                radius="md",
                                leftSection=DashIconify(icon="mdi:check-circle-outline", width=16),
                                disabled=True,
                            ),
                            dmc.Button(
                                "Import Dashboard",
                                id=f"{id_prefix}-submit",
                                color="violet",
                                radius="md",
                                leftSection=DashIconify(icon="mdi:import", width=16),
                                disabled=True,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    return modal, modal_id
