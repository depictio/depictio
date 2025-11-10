"""
Direct edit page for component modification without stepper wizard.

This module provides a standalone edit page that shows only the design interface
with pre-populated settings. No stepper wizard, no -tmp index handling.

Key features:
- Direct to design form (no wizard steps)
- Uses actual component ID throughout (no -tmp suffix)
- Dedicated save callback for edit page
- Cleaner, faster UX for component editing
"""

from datetime import datetime

import dash_mantine_components as dmc
import httpx
from dash import ALL, Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite


def create_minimal_edit_header(
    dashboard_id: str, dashboard_title: str | None = None, is_edit_mode: bool = True
) -> dmc.AppShellHeader:
    """
    Create minimal header for edit page with back button.

    Args:
        dashboard_id: Dashboard ID for navigation back
        dashboard_title: Dashboard title to display
        is_edit_mode: Whether in edit mode (affects back URL)

    Returns:
        DMC AppShell header with back button
    """
    if not dashboard_title:
        dashboard_title = f"Dashboard {dashboard_id[:8]}..."

    # Determine back URL based on edit mode
    back_url = f"/dashboard-edit/{dashboard_id}" if is_edit_mode else f"/dashboard/{dashboard_id}"

    header_content = dmc.Group(
        [
            dcc.Link(
                dmc.Button(
                    "← Back to Dashboard",
                    variant="subtle",
                    leftSection=DashIconify(icon="mdi:arrow-left", width=20),
                ),
                href=back_url,
                style={"textDecoration": "none"},
            ),
            html.Div(style={"flex": 1}),
            dmc.Text(f"Editing: {dashboard_title}", size="lg", fw="bold"),
            html.Div(style={"flex": 1}),
        ],
        justify="space-between",
        align="center",
        style={"height": "100%", "padding": "0 2rem"},
    )

    return dmc.AppShellHeader(
        header_content,
    )


def create_edit_page(
    dashboard_id: str,
    component_id: str,
    component_data: dict,
    dashboard_title: str | None = None,
    theme: str = "light",
    TOKEN: str | None = None,
    is_edit_mode: bool = True,
) -> html.Div:
    """
    Create standalone edit page for component modification.

    Shows only the design interface, no stepper wizard.
    Uses the actual component ID throughout (no -tmp suffix).

    Args:
        dashboard_id: Target dashboard ID
        component_id: Component ID to edit (actual ID, not tmp)
        component_data: Existing component metadata
        dashboard_title: Dashboard title for header
        theme: Current theme ("light" or "dark")
        TOKEN: Authentication token
        is_edit_mode: Whether in edit mode (affects back button URL)

    Returns:
        Complete page layout with design interface
    """
    logger.info(
        f"🎨 CREATE EDIT PAGE - Component: {component_id}, Type: {component_data.get('component_type')}"
    )

    # Create header with proper back URL based on edit mode
    header = create_minimal_edit_header(dashboard_id, dashboard_title, is_edit_mode)

    # Load data for the component (use actual wf_id/dc_id)
    wf_id = component_data.get("wf_id")
    dc_id = component_data.get("dc_id")

    if wf_id and dc_id:
        df = load_deltatable_lite(wf_id, dc_id, TOKEN=TOKEN)
    else:
        logger.warning(f"Missing wf_id or dc_id for component {component_id}")
        import polars as pl

        df = pl.DataFrame()

    # Create design interface based on component type
    component_type = component_data.get("component_type")

    if component_type == "card":
        # Import directly from design_ui to avoid loading callbacks at import time
        from depictio.dash.modules.card_component.design_ui import design_card

        # CRITICAL: Use actual component_id, NOT tmp suffix
        # design_card() returns a list for backward compatibility with stepper code
        design_interface_raw = design_card(
            id={"type": "card-component", "index": component_id}, df=df
        )
        design_interface = (
            design_interface_raw[0]
            if isinstance(design_interface_raw, list)
            else design_interface_raw
        )
    elif component_type == "interactive":
        # Import directly from design_ui to avoid loading callbacks at import time
        from depictio.dash.modules.interactive_component.design_ui import design_interactive

        # CRITICAL: Use actual component_id, NOT tmp suffix
        # design_interactive() returns a list for backward compatibility with stepper code
        design_interface_raw = design_interactive(
            id={"type": "interactive-component", "index": component_id}, df=df
        )
        design_interface = (
            design_interface_raw[0]
            if isinstance(design_interface_raw, list)
            else design_interface_raw
        )
    else:
        # Other component types not yet implemented for editing
        design_interface = html.Div(
            dmc.Alert(
                f"Edit interface for {component_type} components is not yet implemented. Only Card and Interactive components are currently editable.",
                title="Not Implemented",
                color="yellow",
                icon=DashIconify(icon="mdi:alert", width=24),
            )
        )

    # Hidden workflow/DC dropdowns (for callbacks that need them)
    # Use actual component_id, NOT tmp
    hidden_selects = dmc.SimpleGrid(
        cols=2,
        spacing="md",
        children=[
            dmc.Select(
                id={"type": "workflow-selection-label", "index": component_id},
                value=wf_id,
            ),
            dmc.Select(
                id={"type": "datacollection-selection-label", "index": component_id},
                value=dc_id,
            ),
        ],
        style={"display": "none"},
    )

    # Save button (uses actual component_id)
    save_button = dmc.Center(
        dmc.Button(
            "Save Changes",
            id={"type": "btn-save-edit", "index": component_id},
            color="green",
            variant="filled",
            n_clicks=0,
            size="xl",
            leftSection=DashIconify(icon="bi:check-circle", width=24),
            style={"height": "60px", "fontSize": "18px", "fontWeight": "bold"},
        ),
        mt="xl",
    )

    # Store edit context (uses actual component_id)
    context_store = dcc.Store(
        id="edit-page-context",
        data={
            "dashboard_id": dashboard_id,
            "component_id": component_id,  # Actual ID, not tmp
            "component_data": component_data,
        },
    )

    # Layout with AppShell
    page_layout = html.Div(
        [
            context_store,
            hidden_selects,
            dmc.AppShell(
                [
                    header,
                    dmc.AppShellMain(
                        dmc.Container(
                            dmc.Stack(
                                [
                                    dmc.Title(
                                        f"Edit {component_type.capitalize() if component_type else 'Component'}",
                                        order=2,
                                        ta="center",
                                        mb="md",
                                    ),
                                    dmc.Text(
                                        "Modify your component settings below",
                                        size="md",
                                        ta="center",
                                        c="gray",
                                        mb="xl",
                                    ),
                                    design_interface,  # The design form
                                    save_button,
                                ],
                                gap="md",
                            ),
                            size="xl",
                            px="md",
                            py="xl",
                            style={"minHeight": "calc(100vh - 80px)"},
                        ),
                    ),
                ],
                header={"height": 80},
                padding=0,
            ),
        ],
        style={"minHeight": "100vh", "width": "100%"},
    )

    logger.info(f"✅ EDIT PAGE CREATED - Component {component_id}")

    return page_layout


def register_edit_page_callbacks(app):
    """Register callbacks for edit page functionality."""

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "btn-save-edit", "index": ALL}, "n_clicks"),
        State("edit-page-context", "data"),
        State("local-store", "data"),
        State("url", "pathname"),
        State({"type": "card-input", "index": ALL}, "value"),
        State({"type": "card-dropdown-column", "index": ALL}, "value"),
        State({"type": "card-dropdown-aggregation", "index": ALL}, "value"),
        State({"type": "card-color-background", "index": ALL}, "value"),
        State({"type": "card-color-title", "index": ALL}, "value"),
        State({"type": "card-icon-selector", "index": ALL}, "value"),
        State({"type": "card-title-font-size", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def save_edited_card_component(
        btn_clicks,
        edit_context,
        local_store,
        current_pathname,
        card_titles,
        card_columns,
        card_aggregations,
        card_bg_colors,
        card_title_colors,
        card_icons,
        card_font_sizes,
    ):
        """
        Save edited card component directly (no -tmp index handling).

        Uses the actual component ID throughout. Updates the component
        metadata in place without any temporary index gymnastics.

        Args:
            btn_clicks: List of n_clicks from save buttons
            edit_context: Edit page context with dashboard_id, component_id, component_data
            local_store: Local storage with access token
            card_titles: Card title values
            card_columns: Card column values
            card_aggregations: Card aggregation values
            card_bg_colors: Card background color values
            card_title_colors: Card title color values
            card_icons: Card icon values
            card_font_sizes: Card font size values

        Returns:
            str: Redirect pathname to dashboard
        """
        logger.info("=" * 80)
        logger.info("🚀 SAVE CALLBACK TRIGGERED")
        logger.info(f"   ctx.triggered_id: {ctx.triggered_id}")
        logger.info(f"   btn_clicks: {btn_clicks}")
        logger.info(f"   edit_context keys: {edit_context.keys() if edit_context else None}")

        if not ctx.triggered_id or not any(btn_clicks):
            logger.warning("⚠️ SAVE CALLBACK - No trigger or clicks, preventing update")
            raise PreventUpdate

        dashboard_id = edit_context["dashboard_id"]
        component_id = edit_context["component_id"]  # Actual ID, not tmp
        component_data = edit_context["component_data"]

        logger.info(f"💾 SAVE EDIT - Component: {component_id}")
        logger.info(f"   Dashboard: {dashboard_id}")
        logger.info(f"   Component type: {component_data.get('component_type')}")
        logger.info(
            f"   Received States - titles: {card_titles}, columns: {card_columns}, aggregations: {card_aggregations}"
        )

        # Get the index of the component in the arrays (should be 0 for edit page)
        idx = 0

        # Helper to safely get value from array or fall back to component_data
        def get_value(arr, idx, fallback_key, default=""):
            """Safely extract value from State array with fallback to component_data."""
            if arr and len(arr) > idx and arr[idx] is not None:
                return arr[idx]
            return component_data.get(fallback_key, default)

        # Update component metadata with new values
        # CRITICAL: Use actual component_id, no -tmp suffix
        updated_metadata = {
            **component_data,
            "index": component_id,  # Keep actual ID
            "title": get_value(card_titles, idx, "title", ""),
            "column_name": get_value(card_columns, idx, "column_name", None),
            "aggregation": get_value(card_aggregations, idx, "aggregation", None),
            "background_color": get_value(card_bg_colors, idx, "background_color", ""),
            "title_color": get_value(card_title_colors, idx, "title_color", ""),
            "icon_name": get_value(card_icons, idx, "icon_name", "mdi:chart-line"),
            "title_font_size": get_value(card_font_sizes, idx, "title_font_size", "md"),
            "last_updated": datetime.now().isoformat(),
        }

        logger.info(f"   Updated title: {updated_metadata['title']}")
        logger.info(f"   Updated column: {updated_metadata['column_name']}")
        logger.info(f"   Updated aggregation: {updated_metadata['aggregation']}")
        logger.info(f"   Updated background_color: {updated_metadata['background_color']}")
        logger.info(f"   Updated title_color: {updated_metadata['title_color']}")
        logger.info(f"   Updated icon: {updated_metadata['icon_name']}")
        logger.info(f"   Updated font_size: {updated_metadata['title_font_size']}")

        # Call API to update dashboard
        TOKEN = local_store["access_token"]

        try:
            # Fetch current dashboard data
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
                timeout=30.0,
            )
            response.raise_for_status()
            dashboard_data = response.json()

            # Update the specific component in stored_metadata
            existing_metadata = dashboard_data.get("stored_metadata", [])

            # Replace the component with updated metadata
            updated_metadata_list = []
            component_found = False
            for meta in existing_metadata:
                if str(meta.get("index")) == str(component_id):
                    updated_metadata_list.append(updated_metadata)
                    component_found = True
                    logger.info(f"   ✓ Replaced component {component_id} in metadata")
                else:
                    updated_metadata_list.append(meta)

            if not component_found:
                logger.error(f"   ✗ Component {component_id} not found in metadata!")
                return f"/dashboard/{dashboard_id}"

            # Update entire dashboard data with modified metadata
            dashboard_data["stored_metadata"] = updated_metadata_list

            # Save dashboard via API (POST /save endpoint expects full DashboardData)
            update_response = httpx.post(
                f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json=dashboard_data,
                timeout=30.0,
            )
            update_response.raise_for_status()

            logger.info(f"✅ SAVE EDIT SUCCESS - Component {component_id} updated")
            logger.info(f"   API Response status: {update_response.status_code}")
            logger.info(f"   API Response: {update_response.json()}")

        except Exception as e:
            logger.error(f"❌ SAVE EDIT FAILED - Error: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            import traceback

            logger.error(f"   Traceback: {traceback.format_exc()}")

        # Redirect back to dashboard - detect app context from current URL
        app_prefix = "dashboard"  # default to viewer
        if current_pathname and "/dashboard-edit/" in current_pathname:
            app_prefix = "dashboard-edit"

        logger.info(f"🔄 Redirecting to /{app_prefix}/{dashboard_id}")
        return f"/{app_prefix}/{dashboard_id}"

    logger.info("✅ Edit page callbacks registered")
