"""
Generic edit page renderer for component modification.

This module provides page layout and rendering for component editing.
Component-specific save logic lives in the respective component modules:
- depictio/dash/modules/card_component/callbacks/edit.py
- depictio/dash/modules/interactive_component/callbacks/edit.py

Key features:
- Direct to design form (no wizard steps)
- Uses actual component ID throughout (no -tmp suffix)
- Generic page structure works for all component types
- Component-specific callbacks registered via module lazy loading
"""

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

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

    # Save button (uses component-specific type to avoid callback conflicts)
    component_type = component_data.get("component_type", "unknown")
    button_type = f"btn-save-edit-{component_type}"

    save_button = dmc.Center(
        dmc.Button(
            "Save Changes",
            id={"type": button_type, "index": component_id},
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
