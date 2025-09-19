"""
Tab and Section Management Module

Provides functionality to add, edit, and delete tabs and sections in the dashboard.
"""

import dash_mantine_components as dmc
from dash import Input, Output, State, callback_context, html

from depictio.api.v1.configs.logging_init import logger


def create_tab_edit_modal():
    """Create modal for editing tab names."""
    return dmc.Modal(
        title="Edit Tab Name",
        id="tab-edit-modal",
        opened=False,
        children=[
            dmc.TextInput(
                label="Tab Name",
                placeholder="Enter tab name",
                id="tab-name-input",
                value="",
                required=True,
            ),
            dmc.Group(
                children=[
                    dmc.Button(
                        "Cancel",
                        variant="light",
                        id="tab-edit-cancel-btn",
                        color="gray",
                    ),
                    dmc.Button(
                        "Save",
                        id="tab-edit-save-btn",
                        color="blue",
                    ),
                ],
                justify="flex-end",
                mt="md",
            ),
        ],
    )


def create_section_edit_modal():
    """Create modal for editing section names."""
    return dmc.Modal(
        title="Edit Section Name",
        id="tab-mgmt-section-edit-modal",
        opened=False,
        children=[
            dmc.TextInput(
                label="Section Name",
                placeholder="Enter section name",
                id="section-name-input",
                value="",
                required=True,
            ),
            dmc.Group(
                children=[
                    dmc.Button(
                        "Cancel",
                        variant="light",
                        id="section-edit-cancel-btn",
                        color="gray",
                    ),
                    dmc.Button(
                        "Save",
                        id="section-edit-save-btn",
                        color="blue",
                    ),
                ],
                justify="flex-end",
                mt="md",
            ),
        ],
    )


def create_add_tab_modal():
    """Create modal for adding new tabs."""
    return dmc.Modal(
        title="Add New Tab",
        id="tab-mgmt-add-tab-modal",
        opened=False,
        children=[
            dmc.TextInput(
                label="Tab Name",
                placeholder="Enter tab name",
                id="new-tab-name-input",
                value="",
                required=True,
            ),
            dmc.Select(
                label="Tab Icon",
                placeholder="Select an icon",
                id="new-tab-icon-select",
                data=[
                    {"value": "mdi:view-dashboard", "label": "Dashboard"},
                    {"value": "mdi:chart-analytics", "label": "Analytics"},
                    {"value": "mdi:table", "label": "Table"},
                    {"value": "mdi:chart-line", "label": "Chart"},
                    {"value": "mdi:cog", "label": "Settings"},
                ],
                value="mdi:view-dashboard",
            ),
            dmc.Group(
                children=[
                    dmc.Button(
                        "Cancel",
                        variant="light",
                        id="add-tab-cancel-btn",
                        color="gray",
                    ),
                    dmc.Button(
                        "Add Tab",
                        id="add-tab-confirm-btn",
                        color="blue",
                    ),
                ],
                justify="flex-end",
                mt="md",
            ),
        ],
    )


def create_add_section_modal():
    """Create modal for adding new sections."""
    return dmc.Modal(
        title="Add New Section",
        id="tab-mgmt-add-section-modal",
        opened=False,
        children=[
            dmc.TextInput(
                label="Section Name",
                placeholder="Enter section name",
                id="new-section-name-input",
                value="",
                required=True,
            ),
            dmc.Select(
                label="Section Icon",
                placeholder="Select an icon",
                id="new-section-icon-select",
                data=[
                    {"value": "material-symbols:dashboard", "label": "Dashboard"},
                    {"value": "material-symbols:analytics", "label": "Analytics"},
                    {"value": "material-symbols:bar-chart", "label": "Bar Chart"},
                    {"value": "material-symbols:table", "label": "Table"},
                    {"value": "material-symbols:settings", "label": "Settings"},
                ],
                value="material-symbols:dashboard",
            ),
            dmc.Group(
                children=[
                    dmc.Button(
                        "Cancel",
                        variant="light",
                        id="add-section-cancel-btn",
                        color="gray",
                    ),
                    dmc.Button(
                        "Add Section",
                        id="add-section-confirm-btn",
                        color="green",
                    ),
                ],
                justify="flex-end",
                mt="md",
            ),
        ],
    )


def register_tab_management_callbacks(app):
    """Register callbacks for tab and section management."""

    # Tab edit modal callbacks
    @app.callback(
        Output("tab-edit-modal", "opened"),
        [
            Input("edit-tab-name-btn", "n_clicks"),
            Input("sidebar-edit-tab-btn", "n_clicks"),
            Input("tab-edit-cancel-btn", "n_clicks"),
            Input("tab-edit-save-btn", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def toggle_tab_edit_modal(edit_btn1, edit_btn2, cancel_btn, save_btn):
        """Toggle the tab edit modal."""
        ctx = callback_context
        if not ctx.triggered:
            return False

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger_id in ["edit-tab-name-btn", "sidebar-edit-tab-btn"]:
            return True  # Open modal
        elif trigger_id in ["tab-edit-cancel-btn", "tab-edit-save-btn"]:
            return False  # Close modal

        return False

    # Add tab modal callbacks
    @app.callback(
        Output("tab-mgmt-add-tab-modal", "opened"),
        [
            Input("add-tab-btn", "n_clicks"),
            Input("add-tab-cancel-btn", "n_clicks"),
            Input("add-tab-confirm-btn", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def toggle_add_tab_modal(add_btn, cancel_btn, confirm_btn):
        """Toggle the add tab modal."""
        ctx = callback_context
        if not ctx.triggered:
            return False

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger_id == "add-tab-btn":
            return True  # Open modal
        elif trigger_id in ["add-tab-cancel-btn", "add-tab-confirm-btn"]:
            return False  # Close modal

        return False

    # Section edit modal callbacks
    @app.callback(
        Output("tab-mgmt-section-edit-modal", "opened"),
        [
            Input("edit-section-name-btn", "n_clicks"),
            Input("section-edit-cancel-btn", "n_clicks"),
            Input("section-edit-save-btn", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def toggle_section_edit_modal(edit_btn, cancel_btn, save_btn):
        """Toggle the section edit modal."""
        ctx = callback_context
        if not ctx.triggered:
            return False

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger_id == "edit-section-name-btn":
            return True  # Open modal
        elif trigger_id in ["section-edit-cancel-btn", "section-edit-save-btn"]:
            return False  # Close modal

        return False

    # Add section modal callbacks
    @app.callback(
        Output("tab-mgmt-add-section-modal", "opened"),
        [
            Input("add-section-btn", "n_clicks"),
            Input("sidebar-add-section-btn", "n_clicks"),
            Input("add-section-cancel-btn", "n_clicks"),
            Input("add-section-confirm-btn", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def toggle_add_section_modal(add_btn1, add_btn2, cancel_btn, confirm_btn):
        """Toggle the add section modal."""
        ctx = callback_context
        if not ctx.triggered:
            return False

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger_id in ["add-section-btn", "sidebar-add-section-btn"]:
            return True  # Open modal
        elif trigger_id in ["add-section-cancel-btn", "add-section-confirm-btn"]:
            return False  # Close modal

        return False

    # Tab save callback
    @app.callback(
        Output("dummy-tab-output", "children", allow_duplicate=True),
        Input("tab-edit-save-btn", "n_clicks"),
        State("tab-name-input", "value"),
        prevent_initial_call=True,
    )
    def save_tab_name(save_btn, new_name):
        """Save the edited tab name."""
        if save_btn and new_name:
            logger.info(f"📝 TAB EDIT: Saving tab name as '{new_name}'")
            # TODO: Update the actual dashboard structure
            return f"Tab name updated to: {new_name}"
        return ""

    # Section save callback
    @app.callback(
        Output("dummy-section-output", "children", allow_duplicate=True),
        Input("section-edit-save-btn", "n_clicks"),
        State("section-name-input", "value"),
        prevent_initial_call=True,
    )
    def save_section_name(save_btn, new_name):
        """Save the edited section name."""
        if save_btn and new_name:
            logger.info(f"📝 SECTION EDIT: Saving section name as '{new_name}'")
            # TODO: Update the actual dashboard structure
            return f"Section name updated to: {new_name}"
        return ""

    # Add tab callback
    @app.callback(
        Output("dashboard-structure-store", "data", allow_duplicate=True),
        Input("add-tab-confirm-btn", "n_clicks"),
        [
            State("new-tab-name-input", "value"),
            State("new-tab-icon-select", "value"),
            State("dashboard-structure-store", "data"),
            State("url", "pathname"),  # To get dashboard ID
            State("local-store", "data"),  # To get auth token
        ],
        prevent_initial_call=True,
    )
    def add_new_tab(confirm_btn, tab_name, tab_icon, current_structure, pathname, local_data):
        """Add a new tab to the dashboard structure."""
        if confirm_btn and tab_name:
            logger.info(f"➕ TAB ADD: Adding new tab '{tab_name}' with icon '{tab_icon}'")

            from depictio.dash.layouts.app_layout import normalize_tab_name_for_url
            from depictio.models.dashboard_tab_structure import DashboardTab, DashboardTabStructure

            # Parse current structure
            if current_structure:
                dashboard_structure = DashboardTabStructure(**current_structure)
            else:
                # Create new structure if none exists
                dashboard_structure = DashboardTabStructure()

            # Generate normalized tab ID from tab name
            base_tab_id = normalize_tab_name_for_url(tab_name)

            # Check if this tab name already exists and make it unique if needed
            existing_tab_ids = {tab.id for tab in dashboard_structure.tabs}
            tab_id = base_tab_id
            counter = 1
            while tab_id in existing_tab_ids:
                tab_id = f"{base_tab_id}_{counter}"
                counter += 1

            # Create new tab with basic structure
            new_tab = DashboardTab(
                id=tab_id,
                name=tab_name,
                icon=tab_icon,
                filters=[],  # Empty filters initially
                sections=[],  # Empty sections initially
                is_default=False,
                order=len(dashboard_structure.tabs),  # Append to end
            )

            # Add the new tab to the structure
            dashboard_structure.tabs.append(new_tab)

            logger.info(f"✅ TAB ADD: Successfully added tab '{tab_name}' with ID '{tab_id}'")

            # Extract dashboard ID from pathname and save to backend
            if pathname and local_data:
                import re

                dashboard_match = re.match(r"/dashboard/([a-f0-9]{24})", pathname)
                if dashboard_match and local_data.get("access_token"):
                    dashboard_id = dashboard_match.group(1)
                    auth_token = local_data["access_token"]

                    # Save the updated dashboard structure to backend
                    from depictio.dash.api_calls import (
                        api_call_get_dashboard,
                        api_call_save_dashboard,
                    )

                    # Load current dashboard data to maintain all existing fields
                    current_dashboard_data = api_call_get_dashboard(dashboard_id, auth_token)
                    if current_dashboard_data:
                        # Update only the tab_structure field in the existing dashboard data
                        current_dashboard_data["tab_structure"] = dashboard_structure.model_dump()

                        # Save to backend
                        save_success = api_call_save_dashboard(
                            dashboard_id, current_dashboard_data, auth_token
                        )
                    else:
                        logger.error(
                            f"❌ TAB ADD: Failed to load current dashboard data for {dashboard_id}"
                        )
                        save_success = False
                    if save_success:
                        logger.info(f"💾 TAB ADD: Successfully saved tab '{tab_name}' to backend")
                    else:
                        logger.error(f"❌ TAB ADD: Failed to save tab '{tab_name}' to backend")

            # Return updated structure
            return dashboard_structure.model_dump()

        return current_structure

    # Add section callback
    @app.callback(
        Output("dashboard-structure-store", "data", allow_duplicate=True),
        Input("add-section-confirm-btn", "n_clicks"),
        [
            State("new-section-name-input", "value"),
            State("new-section-icon-select", "value"),
            State("dashboard-structure-store", "data"),
            State("url", "pathname"),  # To get dashboard ID and current tab
            State("local-store", "data"),  # To get auth token
        ],
        prevent_initial_call=True,
    )
    def add_new_section(
        confirm_btn, section_name, section_icon, current_structure, pathname, local_data
    ):
        """Add a new section to the current tab."""
        if confirm_btn and section_name:
            logger.info(
                f"➕ SECTION ADD: Adding new section '{section_name}' with icon '{section_icon}'"
            )

            from depictio.models.dashboard_tab_structure import (
                DashboardSection,
                DashboardTabStructure,
            )

            # Parse current structure
            if current_structure:
                dashboard_structure = DashboardTabStructure(**current_structure)
            else:
                logger.error("❌ SECTION ADD: No dashboard structure available")
                return current_structure

            # Get current tab ID from URL
            current_tab_id = None
            if pathname:
                import re

                tab_match = re.search(r"/dashboard/[a-f0-9]{24}/tab/([^/?]+)", pathname)
                if tab_match:
                    current_tab_id = tab_match.group(1)
                else:
                    # If no tab in URL, use default tab
                    default_tab = dashboard_structure.get_default_tab()
                    if default_tab:
                        current_tab_id = default_tab.id
                    elif dashboard_structure.tabs:
                        current_tab_id = dashboard_structure.tabs[0].id
                    else:
                        logger.error("❌ SECTION ADD: No tabs available")
                        return current_structure

            if not current_tab_id:
                logger.error("❌ SECTION ADD: Could not determine current tab")
                return current_structure

            # Find the current tab
            current_tab = dashboard_structure.get_tab_by_id(current_tab_id)
            if not current_tab:
                logger.error(f"❌ SECTION ADD: Tab '{current_tab_id}' not found")
                return current_structure

            # Generate unique section ID
            from depictio.dash.layouts.app_layout import normalize_tab_name_for_url

            base_section_id = normalize_tab_name_for_url(section_name)

            # Check if this section name already exists in the current tab
            existing_section_ids = {section.id for section in current_tab.sections}
            section_id = base_section_id
            counter = 1
            while section_id in existing_section_ids:
                section_id = f"{base_section_id}_{counter}"
                counter += 1

            # Create new section with basic structure
            new_section = DashboardSection(
                id=section_id,
                name=section_name,
                icon=section_icon,
                components=[],  # Empty components initially
                layout_type="grid",
                description=f"Section {section_name} in tab {current_tab.name}",
            )

            # Add the new section to the current tab
            current_tab.sections.append(new_section)

            logger.info(
                f"✅ SECTION ADD: Successfully added section '{section_name}' with ID '{section_id}' to tab '{current_tab.name}'"
            )

            # Extract dashboard ID from pathname and save to backend
            if pathname and local_data:
                dashboard_match = re.match(r"/dashboard/([a-f0-9]{24})", pathname)
                if dashboard_match and local_data.get("access_token"):
                    dashboard_id = dashboard_match.group(1)
                    auth_token = local_data["access_token"]

                    # Save the updated dashboard structure to backend
                    from depictio.dash.api_calls import (
                        api_call_get_dashboard,
                        api_call_save_dashboard,
                    )

                    # Load current dashboard data to maintain all existing fields
                    current_dashboard_data = api_call_get_dashboard(dashboard_id, auth_token)
                    if current_dashboard_data:
                        # Update only the tab_structure field in the existing dashboard data
                        current_dashboard_data["tab_structure"] = dashboard_structure.model_dump()

                        # Save to backend
                        save_success = api_call_save_dashboard(
                            dashboard_id, current_dashboard_data, auth_token
                        )
                    else:
                        logger.error(
                            f"❌ SECTION ADD: Failed to load current dashboard data for {dashboard_id}"
                        )
                        save_success = False

                    if save_success:
                        logger.info(
                            f"💾 SECTION ADD: Successfully saved section '{section_name}' to backend"
                        )
                    else:
                        logger.error(
                            f"❌ SECTION ADD: Failed to save section '{section_name}' to backend"
                        )

            # Return updated structure
            return dashboard_structure.model_dump()

        return current_structure

    # Update header tabs when dashboard structure changes
    @app.callback(
        Output("dashboard-tabs", "children"),
        Input("dashboard-structure-store", "data"),
        prevent_initial_call=True,
    )
    def update_header_tabs(dashboard_structure_data):
        """Update the header tabs when dashboard structure changes."""
        if not dashboard_structure_data:
            return []

        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        from depictio.models.dashboard_tab_structure import DashboardTabStructure

        dashboard_structure = DashboardTabStructure(**dashboard_structure_data)

        # Create tab items for all tabs in structure
        tab_items = []
        for tab in dashboard_structure.tabs:
            tab_items.append(
                dmc.TabsTab(
                    tab.name,
                    value=tab.id,
                    leftSection=DashIconify(icon=tab.icon, height=16) if tab.icon else None,
                )
            )

        logger.info(f"🔄 HEADER TABS: Updated with {len(tab_items)} tabs")
        return [dmc.TabsList(tab_items)]

    logger.info("✅ TAB MANAGEMENT: Callbacks registered successfully")


def get_tab_management_modals():
    """Get tab management modals for inclusion in layout."""
    return html.Div(
        [
            create_tab_edit_modal(),
            create_add_tab_modal(),
            create_section_edit_modal(),
            create_add_section_modal(),
        ]
    )
