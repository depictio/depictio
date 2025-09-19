"""
Navigation editor callbacks for dynamic tab and navlink creation.
"""

import dash_mantine_components as dmc
from dash import Input, Output, State, ctx, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger


def register_navigation_editor_callbacks(app):
    """Register callbacks for navigation editing functionality"""

    # Edit mode toggle callback - only for edit mode store and button appearance
    @app.callback(
        [
            Output("edit-mode-store", "data"),
            Output("edit-mode-toggle-btn", "color"),
            Output("edit-mode-toggle-btn", "variant"),
        ],
        Input("edit-mode-toggle-btn", "n_clicks"),
        State("edit-mode-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_edit_mode(n_clicks, edit_mode):
        """Toggle edit mode on/off"""
        logger.info(f"🔧 EDIT MODE CALLBACK: n_clicks={n_clicks}, current_edit_mode={edit_mode}")

        if not n_clicks:
            logger.info("🔧 EDIT MODE: No clicks, returning defaults")
            return (
                edit_mode or False,
                "orange",
                "light",
            )

        new_edit_mode = not edit_mode
        logger.info(f"🔧 EDIT MODE TOGGLED: {edit_mode} -> {new_edit_mode}")

        # Update button appearance
        color = "red" if new_edit_mode else "orange"
        variant = "filled" if new_edit_mode else "light"

        logger.info(f"🔧 EDIT MODE: Button appearance -> color={color}, variant={variant}")

        return new_edit_mode, color, variant

    # Clientside callback to handle add button visibility when components exist
    app.clientside_callback(
        """
        function(edit_mode) {
            console.log('🔧 CLIENTSIDE: Edit mode changed to:', edit_mode);

            // Handle add-tab-container if it exists
            const addTabContainer = document.getElementById('add-tab-container');
            if (addTabContainer) {
                addTabContainer.style.display = edit_mode ? 'flex' : 'none';
                if (edit_mode) {
                    addTabContainer.style.alignItems = 'center';
                }
                console.log('🔧 CLIENTSIDE: Tab container display set to:', addTabContainer.style.display);
            }

            // Handle add-navlink-container-dashboard if it exists - DISABLED
            // const addNavlinkContainer = document.getElementById('add-navlink-container-dashboard');
            // if (addNavlinkContainer) {
            //     addNavlinkContainer.style.display = edit_mode ? 'block' : 'none';
            //     addNavlinkContainer.style.margin = '10px 0';
            //     console.log('🔧 CLIENTSIDE: NavLink container display set to:', addNavlinkContainer.style.display);
            // }

            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-tab-output", "children", allow_duplicate=True),
        Input("edit-mode-store", "data"),
        prevent_initial_call=True,
    )

    # Debug callback to check if components exist
    app.clientside_callback(
        """
        function(pathname) {
            console.log('🔍 DEBUG: Checking component existence for path:', pathname);

            const editBtn = document.getElementById('edit-mode-toggle-btn');
            const addTabContainer = document.getElementById('add-tab-container');
            // const addNavlinkContainer = document.getElementById('add-navlink-container-dashboard');  // DISABLED
            // const addNavlinkBtn = document.getElementById('add-navlink-btn-dashboard');  // DISABLED

            console.log('🔍 edit-mode-toggle-btn exists:', !!editBtn);
            console.log('🔍 add-tab-container exists:', !!addTabContainer);
            // console.log('🔍 add-navlink-container-dashboard exists:', !!addNavlinkContainer);  // DISABLED
            // console.log('🔍 add-navlink-btn-dashboard exists:', !!addNavlinkBtn);  // DISABLED

            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-tab-output", "children", allow_duplicate=True),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    # Add tab modal callbacks
    @app.callback(
        Output("add-tab-modal", "opened"),
        [
            Input("add-tab-btn", "n_clicks"),
            Input("tab-modal-cancel", "n_clicks"),
            Input("tab-modal-confirm", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def handle_tab_modal(add_clicks, cancel_clicks, confirm_clicks):
        """Handle opening/closing of add tab modal"""
        trigger = ctx.triggered_id

        if trigger == "add-tab-btn" and add_clicks:
            return True
        elif trigger in ["tab-modal-cancel", "tab-modal-confirm"] and (
            cancel_clicks or confirm_clicks
        ):
            return False

        return False

    # Add navlink modal callbacks - DISABLED
    # @app.callback(
    #     Output("add-navlink-modal", "opened"),
    #     [
    #         Input("add-navlink-btn-dashboard", "n_clicks"),
    #         Input("navlink-modal-cancel", "n_clicks"),
    #         Input("navlink-modal-confirm", "n_clicks"),
    #     ],
    #     prevent_initial_call=True,
    # )
    # def handle_navlink_modal(add_clicks, cancel_clicks, confirm_clicks):
    #     """Handle opening/closing of add navlink modal"""
    #     trigger = ctx.triggered_id

    #     if trigger == "add-navlink-btn-dashboard" and add_clicks:
    #         return True
    #     elif trigger in ["navlink-modal-cancel", "navlink-modal-confirm"] and (
    #         cancel_clicks or confirm_clicks
    #     ):
    #         return False

    #     return False

    # Clear modal inputs when opening
    @app.callback(
        [
            Output("tab-name-input", "value"),
            Output("tab-icon-select", "value"),
        ],
        Input("add-tab-modal", "opened"),
        prevent_initial_call=True,
    )
    def clear_tab_modal_inputs(opened):
        """Clear tab modal inputs when opening"""
        if opened:
            return "", None
        return "", None

    @app.callback(
        [
            Output("navlink-name-input", "value"),
            Output("navlink-icon-select", "value"),
            Output("navlink-url-input", "value"),
            Output("navlink-nested-switch", "checked"),
        ],
        Input("add-navlink-modal", "opened"),
        prevent_initial_call=True,
    )
    def clear_navlink_modal_inputs(opened):
        """Clear navlink modal inputs when opening"""
        if opened:
            return "", None, "", False
        return "", None, "", False

    # Dynamic tab addition callback
    @app.callback(
        Output("dynamic-tabs-list", "children"),
        Input("tab-modal-confirm", "n_clicks"),
        [
            State("tab-name-input", "value"),
            State("tab-icon-select", "value"),
            State("dynamic-tabs-list", "children"),
        ],
        prevent_initial_call=True,
    )
    def add_new_tab(n_clicks, tab_name, icon, current_tabs):
        """Add a new tab to the UI dynamically"""
        if not n_clicks or not tab_name:
            return current_tabs

        logger.info(f"✅ ADDING NEW TAB: {tab_name} with icon: {icon}")

        # Import here to avoid circular imports
        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        # Create new tab value from name (lowercase, no spaces)
        tab_value = tab_name.lower().replace(" ", "_")

        # Create new tab component
        new_tab = dmc.TabsTab(
            tab_name,
            value=tab_value,
            leftSection=DashIconify(icon=icon or "material-symbols:tab", height=16),
        )

        # Find the add-tab-container and insert new tab before it
        updated_tabs = []
        add_tab_container = None

        for child in current_tabs:
            if hasattr(child, "props") and child.props.get("id") == "add-tab-container":
                add_tab_container = child
            else:
                updated_tabs.append(child)

        # Add the new tab
        updated_tabs.append(new_tab)

        # Add back the add-tab-container at the end
        if add_tab_container:
            updated_tabs.append(add_tab_container)

        logger.info(f"✅ TAB ADDED: {tab_name} -> {tab_value}")
        return updated_tabs

    # Dynamic navlink addition callback
    @app.callback(
        Output("sidebar-content", "children", allow_duplicate=True),
        Input("navlink-modal-confirm", "n_clicks"),
        [
            State("navlink-name-input", "value"),
            State("navlink-icon-select", "value"),
            State("navlink-url-input", "value"),
            State("navlink-nested-switch", "checked"),
            State("sidebar-content", "children"),
            State("url", "pathname"),
        ],
        prevent_initial_call=True,
    )
    def add_new_navlink(n_clicks, navlink_name, icon, url, nested, current_content, pathname):
        """Add a new navlink to the sidebar dynamically"""
        if not n_clicks or not navlink_name:
            return current_content

        logger.info(
            f"✅ ADDING NEW NAVLINK: {navlink_name} with icon: {icon}, url: {url}, nested: {nested}"
        )

        # Import here to avoid circular imports
        import re

        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        # Check if we're on a dashboard page
        dashboard_match = re.match(r"/dashboard/([a-f0-9]{24})", pathname)
        if not dashboard_match:
            logger.info("❌ Not on dashboard page, not adding navlink")
            return current_content

        dashboard_id = dashboard_match.group(1)

        # Create new navlink
        href = url if url else f"/dashboard/{dashboard_id}/{navlink_name.lower().replace(' ', '_')}"

        new_navlink = dmc.NavLink(
            label=navlink_name,
            href=href,
            leftSection=DashIconify(icon=icon or "material-symbols:link", height=20),
        )

        # Find where to insert (before the divider and add button)
        updated_content = []
        add_button_section = []
        found_divider = False

        for item in current_content:
            if hasattr(item, "props"):
                # Check if this is the divider
                if hasattr(item, "type") and "Divider" in str(item.type):
                    found_divider = True

                # If we found the divider, collect everything after it
                if found_divider:
                    add_button_section.append(item)
                else:
                    updated_content.append(item)
            else:
                if found_divider:
                    add_button_section.append(item)
                else:
                    updated_content.append(item)

        # Add the new navlink before the divider section
        updated_content.append(new_navlink)

        # Add back the divider and add button section
        updated_content.extend(add_button_section)

        logger.info(f"✅ NAVLINK ADDED: {navlink_name} -> {href}")
        return updated_content


def create_add_navlink_button(section_id="main"):
    """Create an 'Add NavLink' button for edit mode"""
    return html.Div(
        dmc.ActionIcon(
            DashIconify(icon="material-symbols:add", height=16),
            id={"type": "add-navlink-btn", "index": section_id},
            variant="light",
            size="sm",
            color="green",
            style={"marginLeft": "10px"},
        ),
        id=f"add-navlink-container-{section_id}",
        style={"display": "none", "padding": "5px 0"},  # Hidden by default
    )


def add_edit_mode_navlinks_to_section(navlinks, section_id="main"):
    """Add edit mode buttons to a navlink section"""
    # Add the add navlink button after the existing navlinks
    return navlinks + [create_add_navlink_button(section_id)]
