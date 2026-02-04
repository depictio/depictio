"""Tab creation/editing modal component - Pure DMC implementation."""

import dash_mantine_components as dmc
from dash import Input, Output, dcc, html
from dash_iconify import DashIconify

# =============================================================================
# Workflow-based Color Mapping
# =============================================================================
# Maps workflow engines/catalogs to DMC tab colors for visual consistency

WORKFLOW_COLORS = {
    # Nextflow ecosystem
    "nf-core": "green",
    "nextflow": "green",
    # Snakemake ecosystem
    "snakemake": "lime",
    # Galaxy ecosystem
    "galaxy": "yellow",
    # Python-based
    "python": "blue",
    # R-based
    "r": "violet",
    # Shell/Bash
    "bash": "gray",
    # CWL
    "cwl": "cyan",
    # Default fallback
    "default": "orange",
}


def get_workflow_tab_color(workflow_data: dict | None) -> str:
    """
    Get the tab color based on workflow engine/catalog.

    Checks for catalog first (e.g., nf-core), then falls back to engine.
    Returns default color if no workflow data or no matching mapping.

    Args:
        workflow_data: Workflow dict containing 'catalog' and/or 'engine' fields.

    Returns:
        DMC color name (e.g., 'green', 'yellow', 'orange').
    """
    if not workflow_data:
        return WORKFLOW_COLORS["default"]

    # Check catalog first (more specific)
    catalog = workflow_data.get("catalog", {})
    if isinstance(catalog, dict):
        catalog_name = catalog.get("name", "").lower()
    else:
        catalog_name = str(catalog).lower() if catalog else ""

    if catalog_name and catalog_name in WORKFLOW_COLORS:
        return WORKFLOW_COLORS[catalog_name]

    # Check engine
    engine = workflow_data.get("engine", {})
    if isinstance(engine, dict):
        engine_name = engine.get("name", "").lower()
    else:
        engine_name = str(engine).lower() if engine else ""

    if engine_name and engine_name in WORKFLOW_COLORS:
        return WORKFLOW_COLORS[engine_name]

    return WORKFLOW_COLORS["default"]


# Icon options for tab icon selection
TAB_ICON_OPTIONS = [
    {"value": "mdi:view-dashboard", "label": "Dashboard"},
    {"value": "mdi:chart-line", "label": "Line Chart"},
    {"value": "mdi:chart-bar", "label": "Bar Chart"},
    {"value": "mdi:chart-pie", "label": "Pie Chart"},
    {"value": "mdi:chart-scatter-plot", "label": "Scatter Plot"},
    {"value": "mdi:table", "label": "Table"},
    {"value": "mdi:filter", "label": "Analysis"},
    {"value": "mdi:cog", "label": "Settings"},
    {"value": "mdi:download", "label": "Download"},
    {"value": "mdi:information", "label": "Information"},
    {"value": "mdi:file-document", "label": "Document"},
    {"value": "mdi:database", "label": "Database"},
    {"value": "mdi:home", "label": "Home"},
    {"value": "mdi:map", "label": "Map"},
    {"value": "mdi:image", "label": "Image"},
    {"value": "mdi:star", "label": "Star"},
]

# Color options for tab icon color picker
TAB_COLOR_OPTIONS = [
    {"value": "", "label": "Auto (from workflow)"},  # Empty string = auto-derive
    {"value": "orange", "label": "Orange"},
    {"value": "blue", "label": "Blue"},
    {"value": "green", "label": "Green"},
    {"value": "red", "label": "Red"},
    {"value": "violet", "label": "Violet"},
    {"value": "yellow", "label": "Yellow"},
    {"value": "lime", "label": "Lime"},
    {"value": "pink", "label": "Pink"},
    {"value": "gray", "label": "Gray"},
    {"value": "cyan", "label": "Cyan"},
    {"value": "teal", "label": "Teal"},
    {"value": "indigo", "label": "Indigo"},
]


def register_tab_modal_callbacks(app):
    """Register clientside callback for live icon preview."""
    app.clientside_callback(
        """
        function(iconValue, colorValue) {
            // Default values
            const icon = iconValue || 'mdi:view-dashboard';
            const color = colorValue || 'orange';

            // Return ActionIcon with DashIconify inside (circular filled background)
            return {
                namespace: 'dash_mantine_components',
                type: 'ActionIcon',
                props: {
                    children: {
                        namespace: 'dash_iconify',
                        type: 'DashIconify',
                        props: {
                            icon: icon,
                            width: 32
                        }
                    },
                    color: color,
                    radius: 'xl',
                    size: 'xl',
                    variant: 'filled'
                }
            };
        }
        """,
        Output("tab-icon-preview", "children"),
        [
            Input("tab-icon-select", "value"),
            Input("tab-icon-color-picker", "value"),
        ],
    )

    # Clientside callback to update modal title based on edit mode
    app.clientside_callback(
        """
        function(editMode) {
            if (editMode && editMode.is_edit) {
                return "Edit Tab";
            }
            return "Create New Tab";
        }
        """,
        Output("tab-modal", "title"),
        Input("tab-modal-edit-mode", "data"),
    )

    # Clientside callback to update submit button text based on edit mode
    app.clientside_callback(
        """
        function(editMode) {
            if (editMode && editMode.is_edit) {
                return "Save Changes";
            }
            return "Create Tab";
        }
        """,
        Output("tab-modal-submit", "children"),
        Input("tab-modal-edit-mode", "data"),
    )

    # Clientside callback to show/hide delete button based on edit mode and if it's a child tab
    app.clientside_callback(
        """
        function(editMode) {
            // Show delete button only in edit mode for child tabs (not main tabs)
            if (editMode && editMode.is_edit && editMode.is_child_tab) {
                return { display: 'block' };
            }
            return { display: 'none' };
        }
        """,
        Output("tab-modal-delete", "style"),
        Input("tab-modal-edit-mode", "data"),
    )

    # Clientside callback to show/hide main_tab_name field based on whether editing a main tab
    app.clientside_callback(
        """
        function(editMode) {
            // Show main_tab_name field only when editing a main tab
            if (editMode && editMode.is_edit && !editMode.is_child_tab) {
                return { display: 'block' };
            }
            return { display: 'none' };
        }
        """,
        Output("main-tab-name-input-container", "style"),
        Input("tab-modal-edit-mode", "data"),
    )


def create_tab_modal():
    """
    Create a modal for creating and editing dashboard tabs.

    This modal uses pure DMC 2.0+ components without custom CSS.
    Theme compatibility is handled automatically by DMC's built-in theming.

    The modal supports two modes:
    - Create mode: For creating new child tabs
    - Edit mode: For editing existing tabs (main or child)

    Returns:
        html.Div: Container with the tab modal and delete confirmation modal
    """
    return html.Div(
        [
            # Store for tracking edit mode state
            dcc.Store(
                id="tab-modal-edit-mode",
                data={
                    "is_edit": False,
                    "is_child_tab": True,
                    "dashboard_id": None,
                    "parent_dashboard_id": None,
                },
            ),
            # Main tab modal
            dmc.Modal(
                id="tab-modal",
                title="Create New Tab",
                centered=True,
                size="md",
                opened=False,
                children=[
                    dmc.Stack(
                        [
                            # Tab name input (for child tabs or dashboard title for main tabs)
                            dmc.TextInput(
                                id="tab-name-input",
                                label="Tab Name",
                                placeholder="Enter tab name...",
                                required=True,
                            ),
                            # Main tab name input (only visible when editing main tabs)
                            html.Div(
                                dmc.TextInput(
                                    id="main-tab-name-input",
                                    label="Main Tab Display Name",
                                    placeholder="Main (default)",
                                    description="Custom name shown in sidebar for the main tab",
                                ),
                                id="main-tab-name-input-container",
                                style={"display": "none"},
                            ),
                            # Icon selection with DashIconify previews
                            dmc.Select(
                                id="tab-icon-select",
                                label="Icon",
                                value="mdi:view-dashboard",
                                data=TAB_ICON_OPTIONS,
                            ),
                            # Icon color picker (simple select dropdown)
                            dmc.Select(
                                id="tab-icon-color-picker",
                                label="Icon Color",
                                value="orange",
                                data=TAB_COLOR_OPTIONS,
                            ),
                            # Live preview of selected icon with color
                            dmc.Paper(
                                [
                                    dmc.Text("Preview:", size="sm", fw="bold", mb=8),
                                    dmc.Center(
                                        html.Div(
                                            id="tab-icon-preview",
                                            children=[
                                                dmc.ActionIcon(
                                                    DashIconify(
                                                        icon="mdi:view-dashboard",
                                                        width=32,
                                                    ),
                                                    color="orange",  # Default color
                                                    radius="xl",  # Circular shape
                                                    size="xl",  # Extra large for preview
                                                    variant="filled",  # Solid filled background
                                                )
                                            ],
                                        ),
                                    ),
                                ],
                                withBorder=True,
                                p="md",
                                radius="sm",
                            ),
                            # Action buttons
                            dmc.Group(
                                [
                                    # Delete button (only visible in edit mode for child tabs)
                                    dmc.Button(
                                        "Delete Tab",
                                        id="tab-modal-delete",
                                        variant="outline",
                                        color="red",
                                        leftSection=DashIconify(icon="mdi:delete", width=16),
                                        style={"display": "none"},
                                    ),
                                    dmc.Button("Cancel", id="tab-modal-cancel", variant="subtle"),
                                    dmc.Button(
                                        "Create Tab", id="tab-modal-submit", variant="filled"
                                    ),
                                ],
                                justify="flex-end",
                            ),
                        ],
                        gap="md",
                    ),
                ],
            ),
            # Delete confirmation modal
            dmc.Modal(
                id="tab-delete-confirm-modal",
                title="Delete Tab",
                centered=True,
                size="sm",
                opened=False,
                children=[
                    dmc.Stack(
                        [
                            dmc.Text(
                                "Are you sure you want to delete this tab? "
                                "This action cannot be undone.",
                                size="sm",
                            ),
                            dmc.Group(
                                [
                                    dmc.Button(
                                        "Cancel",
                                        id="tab-delete-cancel",
                                        variant="subtle",
                                    ),
                                    dmc.Button(
                                        "Delete",
                                        id="tab-delete-confirm",
                                        color="red",
                                        leftSection=DashIconify(icon="mdi:delete", width=16),
                                    ),
                                ],
                                justify="flex-end",
                            ),
                        ],
                        gap="md",
                    ),
                ],
            ),
        ]
    )
