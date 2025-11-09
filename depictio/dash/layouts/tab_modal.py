"""Tab creation modal component - Pure DMC implementation."""

import dash_mantine_components as dmc


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
                    dmc.TextInput(
                        id="tab-name-input",
                        label="Tab Name",
                        placeholder="Enter tab name...",
                        required=True,
                    ),
                    dmc.Select(
                        id="tab-icon-select",
                        label="Icon",
                        value="mdi:view-dashboard",
                        data=[
                            {"value": "mdi:view-dashboard", "label": "📊 Dashboard"},
                            {"value": "mdi:chart-line", "label": "📈 Chart"},
                            {"value": "mdi:chart-bar", "label": "📊 Bar Chart"},
                            {"value": "mdi:table", "label": "📋 Table"},
                            {"value": "mdi:filter", "label": "🔍 Analysis"},
                            {"value": "mdi:cog", "label": "⚙️ Settings"},
                            {"value": "mdi:download", "label": "⬇️ Download"},
                            {"value": "mdi:information", "label": "ℹ️ Info"},
                        ],
                    ),
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
