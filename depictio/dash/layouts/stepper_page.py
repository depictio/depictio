"""
Standalone stepper page for component creation and editing.

This module provides a dedicated page layout for the component stepper,
replacing the modal-based approach. Benefits:
- No dashboard components loaded during creation/editing (performance)
- No pattern matching index conflicts
- Clean URL-based routing
- Browser history support
"""

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_get_dashboard
from depictio.dash.layouts.stepper import create_stepper_content


def create_minimal_header(
    dashboard_id: str, dashboard_title: str | None = None, is_edit_mode: bool = True
) -> dmc.AppShellHeader:
    """
    Create a minimal header for the stepper page.

    Args:
        dashboard_id: Dashboard ID for navigation back
        dashboard_title: Optional dashboard title to display
        is_edit_mode: Whether in edit mode (affects back URL)

    Returns:
        DMC AppShell header with back button and title
    """
    # If no title provided, use a placeholder
    if not dashboard_title:
        dashboard_title = f"Dashboard {dashboard_id[:8]}..."

    # Determine back URL based on edit mode
    back_url = f"/dashboard-edit/{dashboard_id}" if is_edit_mode else f"/dashboard/{dashboard_id}"

    header_content = dmc.Group(
        [
            # Back button - navigates to dashboard
            dmc.ActionIcon(
                DashIconify(icon="mdi:arrow-left", width=24),
                id="stepper-back-button",
                variant="subtle",
                size="lg",
                color="gray",
            ),
            dcc.Link(
                dmc.Text(
                    f"← Back to {dashboard_title}",
                    size="lg",
                    fw="normal",
                    c="gray",
                ),
                href=back_url,
                style={"textDecoration": "none"},
            ),
            # Spacer
            html.Div(style={"flex": 1}),
            # Logo/Title
            dmc.Group(
                [
                    html.Img(
                        src="/assets/images/icons/favicon.ico",
                        style={"height": "32px", "width": "32px"},
                    ),
                    dmc.Text(
                        "Component Designer",
                        size="xl",
                        fw="bold",
                    ),
                ],
                gap="sm",
            ),
            # Spacer
            html.Div(style={"flex": 1}),
        ],
        justify="space-between",
        align="center",
        style={
            "height": "100%",
            "padding": "0 2rem",
        },
    )

    return dmc.AppShellHeader(
        header_content,
    )


def create_stepper_page(
    dashboard_id: str,
    component_id: str,
    theme: str = "light",
    TOKEN: str | None = None,
    is_edit_mode: bool = True,
) -> html.Div:
    """
    Create standalone stepper page for component CREATION only.

    For editing existing components, use create_edit_page() from edit_page.py instead.
    This function always creates a new component with the provided component_id.

    Args:
        dashboard_id: Target dashboard ID
        component_id: New component UUID
        theme: Current theme ("light" or "dark")
        TOKEN: Authentication token
        is_edit_mode: Whether in edit mode (affects back button URL)

    Returns:
        Complete page layout with stepper wizard
    """
    logger.info(
        f"🎨 STEPPER PAGE (ADD MODE) - Dashboard: {dashboard_id}, Component: {component_id}"
    )

    # Fetch dashboard data for context
    dashboard_data = None
    dashboard_title = None
    if TOKEN:
        try:
            dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
            dashboard_title = dashboard_data.get("dashboard_name", dashboard_data.get("title"))
        except Exception as e:
            logger.error(f"Failed to fetch dashboard data: {e}")

    # Create header with proper back URL based on edit mode
    header = create_minimal_header(dashboard_id, dashboard_title, is_edit_mode)

    # Create stepper content
    # IMPORTANT: Use fixed index "stepper-component" to avoid conflicts
    stepper_index = "stepper-component"

    # Create stepper wizard for new component creation
    stepper_content = create_stepper_content(
        n=stepper_index,
        active=0,  # Start at first step (component type selection)
    )

    # Store component context for callbacks (add mode only)
    component_context_store = dcc.Store(
        id="stepper-page-context",
        data={
            "dashboard_id": dashboard_id,
            "component_id": component_id,
            "mode": "add",
            "is_edit_mode": is_edit_mode,
        },
    )

    # CRITICAL: Add Store components that stepper callbacks depend on
    # These normally come from the header, but the stepper page doesn't have a header
    # The update_button_list callback in stepper_parts/part_two.py depends on these
    required_stores = [
        dcc.Store(
            id="stored-add-button",
            storage_type="memory",  # Use memory to avoid localStorage caching issues
            data=None,  # Start with None, will be populated by init callback
        ),
        dcc.Store(
            id="initialized-add-button",
            storage_type="memory",
            data=True,
        ),
        # Trigger to initialize the stored-add-button Store on page load
        dcc.Interval(
            id="stepper-init-trigger",
            interval=100,  # Fire after 100ms
            n_intervals=0,
            max_intervals=1,  # Fire only once
        ),
        # Store to track save completion status for btn-done flow
        dcc.Store(
            id="stepper-save-status",
            storage_type="memory",
            data=None,  # Will be populated by save_stepper_component callback
        ),
        # Hidden save button required for global save callback validation
        # The global save callback in save.py has Input("save-button-dashboard", "n_clicks")
        # Dash validates all callback components before execution, even if the callback has guards
        html.Button(id="save-button-dashboard", style={"display": "none"}),
    ]

    # Create main layout with AppShell
    page_layout = html.Div(
        [
            component_context_store,
            *required_stores,  # Unpack the required Store components
            dmc.AppShell(
                [
                    header,
                    dmc.AppShellMain(
                        dmc.Container(
                            stepper_content,
                            size="xl",
                            px="md",
                            py="xl",
                            style={
                                "minHeight": "calc(100vh - 80px)",  # Full height minus header
                            },
                        ),
                    ),
                ],
                header={"height": 80},
                padding=0,
            ),
        ],
        style={
            "minHeight": "100vh",
            "width": "100%",
        },
    )

    logger.info(
        f"✅ STEPPER PAGE - Created ADD page for component {component_id} in dashboard {dashboard_id}"
    )

    return page_layout
