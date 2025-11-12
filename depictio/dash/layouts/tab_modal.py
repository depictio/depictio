"""Tab creation modal component - Pure DMC implementation."""

import dash_mantine_components as dmc
from dash import Input, Output, html
from dash_iconify import DashIconify


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


def create_tab_modal():
    """
    Create a modal for creating new dashboard tabs.

    This modal uses pure DMC 2.0+ components without custom CSS.
    Theme compatibility is handled automatically by DMC's built-in theming.

    Returns:
        dmc.Modal: The tab creation modal component
    """
    return dmc.Modal(
        id="tab-modal",
        title="Create New Tab",
        centered=True,
        size="md",
        opened=False,
        children=[
            dmc.Stack(
                [
                    # Tab name input
                    dmc.TextInput(
                        id="tab-name-input",
                        label="Tab Name",
                        placeholder="Enter tab name...",
                        required=True,
                    ),
                    # Icon selection with DashIconify previews
                    dmc.Select(
                        id="tab-icon-select",
                        label="Icon",
                        value="mdi:view-dashboard",
                        data=[
                            {"value": "mdi:view-dashboard", "label": "Dashboard"},
                            {"value": "mdi:chart-line", "label": "Line Chart"},
                            {"value": "mdi:chart-bar", "label": "Bar Chart"},
                            {"value": "mdi:table", "label": "Table"},
                            {"value": "mdi:filter", "label": "Analysis"},
                            {"value": "mdi:cog", "label": "Settings"},
                            {"value": "mdi:download", "label": "Download"},
                            {"value": "mdi:information", "label": "Information"},
                            {"value": "mdi:file-document", "label": "Document"},
                            {"value": "mdi:database", "label": "Database"},
                        ],
                    ),
                    # Icon color picker (simple select dropdown)
                    dmc.Select(
                        id="tab-icon-color-picker",
                        label="Icon Color",
                        value="orange",  # Default color
                        data=[
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
                        ],
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
                            dmc.Button("Cancel", id="tab-modal-cancel", variant="subtle"),
                            dmc.Button("Create Tab", id="tab-modal-submit", variant="filled"),
                        ],
                        justify="flex-end",
                    ),
                ],
                gap="md",
            ),
        ],
    )
