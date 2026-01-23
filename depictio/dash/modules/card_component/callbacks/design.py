"""
Card Component - Design/Edit Mode Callbacks.

This module contains callbacks that are only needed when editing or designing cards.
These callbacks are lazy-loaded when entering edit mode to reduce initial app startup time.

Functions:
    register_design_callbacks: Register all design/edit mode callbacks

Callbacks Registered:
    pre_populate_card_settings_for_edit: Pre-fill design form in edit mode
    design_card_body: Live preview of card with design changes
"""

import dash_mantine_components as dmc
import httpx
from dash import MATCH, Input, Output, State, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.card_component.utils import agg_functions, build_card
from depictio.dash.utils import (
    get_columns_from_data_collection,
    get_component_data,
    load_depictio_data_mongo,
)


def _extract_dashboard_and_component_ids(
    pathname: str, pattern_id: dict
) -> tuple[str | None, str | None]:
    """
    Extract dashboard_id and component_id from URL pathname.

    Args:
        pathname: Current URL pathname.
        pattern_id: Component ID dictionary from pattern-matching.

    Returns:
        Tuple of (dashboard_id, input_id).
    """
    path_parts = pathname.split("/")
    if "/component/add/" in pathname or "/component/edit/" in pathname:
        dashboard_id = path_parts[2]
        input_id = str(pattern_id["index"])
    else:
        dashboard_id = path_parts[-1]
        input_id = None
    return dashboard_id, input_id


def _create_columns_description_table(cols_json: dict) -> dmc.Table:
    """
    Create a DMC Table showing column names and descriptions.

    Args:
        cols_json: Dictionary mapping column names to their metadata.

    Returns:
        dmc.Table component displaying columns and descriptions.
    """
    table_rows = []
    for col_name, col_info in cols_json.items():
        if col_info.get("description") is not None:
            table_rows.append(
                dmc.TableTr(
                    [
                        dmc.TableTd(
                            col_name,
                            style={"textAlign": "center", "fontSize": "11px", "maxWidth": "150px"},
                        ),
                        dmc.TableTd(
                            col_info["description"],
                            style={"textAlign": "center", "fontSize": "11px", "maxWidth": "150px"},
                        ),
                    ]
                )
            )

    return dmc.Table(
        [
            dmc.TableThead(
                [
                    dmc.TableTr(
                        [
                            dmc.TableTh(
                                "Column",
                                style={
                                    "textAlign": "center",
                                    "fontSize": "11px",
                                    "fontWeight": "bold",
                                },
                            ),
                            dmc.TableTh(
                                "Description",
                                style={
                                    "textAlign": "center",
                                    "fontSize": "11px",
                                    "fontWeight": "bold",
                                },
                            ),
                        ]
                    )
                ]
            ),
            dmc.TableTbody(table_rows),
        ],
        striped="odd",
        withTableBorder=True,
    )


def _create_aggregation_description(column_type: str, aggregation_value: str) -> html.Div:
    """
    Create an aggregation description tooltip badge.

    Args:
        column_type: Data type of the column.
        aggregation_value: Selected aggregation method.

    Returns:
        html.Div containing the aggregation description badge.
    """
    return html.Div(
        children=[
            html.Hr(),
            dmc.Tooltip(
                children=dmc.Badge(
                    children="Aggregation description",
                    leftSection=DashIconify(icon="mdi:information", color="white", width=20),
                    color="gray",
                    radius="lg",
                ),
                label=agg_functions[str(column_type)]["card_methods"][aggregation_value][
                    "description"
                ],
                multiline=True,
                w=300,
                transitionProps={"name": "pop", "duration": 300},
                withinPortal=False,
                withArrow=True,
                openDelay=500,
                closeDelay=500,
                color="gray",
            ),
        ]
    )


def register_design_callbacks(app) -> None:
    """
    Register design/edit mode callbacks for card component.

    Registers two callbacks:
        1. pre_populate_card_settings_for_edit: Pre-fills the design form
           with existing card settings when entering edit mode.
        2. design_card_body: Updates the card preview in real-time as
           the user modifies design settings.

    Args:
        app: Dash application instance to register callbacks on.
    """

    # Pre-populate card settings in edit mode (edit page, not stepper)
    @app.callback(
        Output({"type": "card-input", "index": MATCH}, "value"),
        Output({"type": "card-dropdown-column", "index": MATCH}, "value"),
        Output(
            {"type": "card-dropdown-aggregation", "index": MATCH}, "value", allow_duplicate=True
        ),
        Output({"type": "card-color-background", "index": MATCH}, "value"),
        Output({"type": "card-color-title", "index": MATCH}, "value"),
        Output({"type": "card-icon-selector", "index": MATCH}, "value"),
        Output({"type": "card-title-font-size", "index": MATCH}, "value"),
        Input("edit-page-context", "data"),
        State({"type": "card-input", "index": MATCH}, "id"),
        prevent_initial_call="initial_duplicate",
    )
    def pre_populate_card_settings_for_edit(edit_context, card_id):
        """
        Pre-populate card design settings when in edit mode.

        Uses actual component ID (no -tmp suffix). Only populates when
        the card_id matches the component being edited in the edit page.

        Args:
            edit_context: Edit page context containing component_data and component_id.
            card_id: Card component ID dictionary from the design form.

        Returns:
            Tuple of (title, column_name, aggregation, background_color,
            title_color, icon_name, title_font_size) or no_update for all
            if conditions not met.
        """
        import dash

        if not edit_context:
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        component_data = edit_context.get("component_data")
        if not component_data or component_data.get("component_type") != "card":
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        # Match component ID (actual ID, no -tmp)
        if str(card_id["index"]) != str(edit_context.get("component_id")):
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        # Ensure ColorInput components get empty string instead of None to avoid trim() errors
        return (
            component_data.get("title") or "",  # TextInput needs string
            component_data.get("column_name"),  # Select accepts None
            component_data.get("aggregation"),  # Select accepts None
            component_data.get("background_color") or "",  # ColorInput needs empty string, not None
            component_data.get("title_color") or "",  # ColorInput needs empty string, not None
            component_data.get("icon_name") or "mdi:chart-line",  # Select needs value
            component_data.get("title_font_size") or "md",  # Select needs value
        )

    # Callback to update card body based on the selected column and aggregation
    @app.callback(
        Output({"type": "card-body", "index": MATCH}, "children"),
        Output({"type": "aggregation-description", "index": MATCH}, "children"),
        Output({"type": "card-columns-description", "index": MATCH}, "children"),
        [
            Input({"type": "card-input", "index": MATCH}, "value"),
            Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "card-dropdown-aggregation", "index": MATCH}, "value"),
            Input({"type": "card-color-background", "index": MATCH}, "value"),
            Input({"type": "card-color-title", "index": MATCH}, "value"),
            Input({"type": "card-icon-selector", "index": MATCH}, "value"),
            Input({"type": "card-title-font-size", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "card-dropdown-column", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
        ],
        prevent_initial_call=True,
    )
    def design_card_body(
        input_value,
        column_name,
        aggregation_value,
        background_color,
        title_color,
        icon_name,
        title_font_size,
        wf_id,
        dc_id,
        id,
        local_data,
        pathname,
    ):
        """
        Update card body based on selected column and aggregation.

        Creates a live preview of the card with design changes. Fetches
        column information from the data collection and builds the card
        component with the specified styling parameters.

        Args:
            input_value: Card title text.
            column_name: Selected data column name.
            aggregation_value: Selected aggregation method.
            background_color: Card background color (hex).
            title_color: Card title text color (hex).
            icon_name: Selected icon identifier.
            title_font_size: Font size for the card title.
            wf_id: Workflow ID from hidden select.
            dc_id: Data collection ID from hidden select.
            id: Component ID dictionary for pattern-matching.
            local_data: Local storage data with authentication token.
            pathname: Current URL pathname.

        Returns:
            Tuple of (card_body, aggregation_description, columns_description).
        """
        if not local_data:
            return ([], None, None)

        TOKEN = local_data["access_token"]
        dashboard_id, input_id = _extract_dashboard_and_component_ids(pathname, id)

        # Fetch component data if we have an input_id
        component_data = None
        if input_id:
            component_data = get_component_data(
                input_id=input_id, dashboard_id=dashboard_id, TOKEN=TOKEN
            )

        # Use wf_id/dc_id from States (hidden selects) if available
        # Otherwise fall back to component_data (for backward compatibility)
        if not wf_id or not dc_id:
            if component_data:
                wf_id = component_data["wf_id"]
                dc_id = component_data["dc_id"]
            else:
                logger.error("No wf_id/dc_id available from States or component_data")
                return ([], None, None)

        # CRITICAL: Validate that wf_id and dc_id are not None after extraction
        # This prevents API calls with None values which cause 422 errors
        if not wf_id or not dc_id:
            logger.warning(
                f"Card design: wf_id or dc_id still None after extraction (wf_id={wf_id}, dc_id={dc_id}). "
                "Returning empty preview."
            )
            return ([], None, None)

        headers = {"Authorization": f"Bearer {TOKEN}"}
        cols_json = get_columns_from_data_collection(wf_id, dc_id, TOKEN)
        columns_description_df = _create_columns_description_table(cols_json)

        # If any of the input values are None, return an empty list
        if column_name is None or aggregation_value is None or wf_id is None or dc_id is None:
            if not component_data:
                return ([], None, columns_description_df)
            else:
                column_name = component_data["column_name"]
                aggregation_value = component_data["aggregation"]
                input_value = component_data["title"]

        column_type = cols_json[column_name]["type"]
        aggregation_description = _create_aggregation_description(column_type, aggregation_value)

        # Initialize relevant_metadata to empty list (defensive programming)
        relevant_metadata = []

        if dashboard_id:
            dashboard_data = load_depictio_data_mongo(dashboard_id, TOKEN=TOKEN)
            relevant_metadata = [
                m
                for m in dashboard_data["stored_metadata"]
                if m["wf_id"] == wf_id and m["component_type"] == "interactive"
            ]

        # Get the data collection specs
        # Handle joined data collection IDs
        if isinstance(dc_id, str) and "--" in dc_id:
            # For joined data collections, create synthetic specs
            dc_specs = {
                "config": {"type": "table", "metatype": "joined"},
                "data_collection_tag": f"Joined data collection ({dc_id})",
                "description": "Virtual joined data collection",
                "_id": dc_id,
            }
        else:
            # Regular data collection - fetch from API
            # DEFENSIVE: Final check before API call (should never be reached if early returns work)
            if not dc_id or dc_id == "None":
                logger.error(
                    f"Card design: dc_id is invalid before API call (dc_id={dc_id}). "
                    "This should have been caught earlier. Returning empty preview."
                )
                return ([], None, columns_description_df)

            dc_specs = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
                headers=headers,
            ).json()

        # Get the type of the selected column and the value for the selected aggregation
        column_type = cols_json[column_name]["type"]

        # Determine if we're in stepper mode vs edit mode
        # Stepper mode: component/add URLs with -tmp suffix
        # Edit mode: component/edit URLs with actual component ID
        is_stepper_mode = "/component/add/" in pathname

        card_kwargs = {
            "index": id["index"],
            "title": input_value,
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_specs["config"],
            "column_name": column_name,
            "column_type": column_type,
            "aggregation": aggregation_value,
            "access_token": TOKEN,
            "stepper": is_stepper_mode,  # Only True for stepper workflow, not edit page
            "build_frame": False,  # Don't build frame - return just the content for the card-body container
            "cols_json": cols_json,  # Pass cols_json for reference values
            # New individual style parameters
            "background_color": background_color,
            "title_color": title_color,
            "icon_name": icon_name,
            "icon_color": title_color,  # Use same as title for consistency
            "title_font_size": title_font_size,
            "metric_theme": None,  # Not using themes anymore for new cards
        }

        if relevant_metadata:
            card_kwargs["dashboard_metadata"] = relevant_metadata

        new_card_body = build_card(**card_kwargs)

        return new_card_body, aggregation_description, columns_description_df
