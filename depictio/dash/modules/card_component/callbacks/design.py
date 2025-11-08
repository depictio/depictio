"""
Card Component - Design/Edit Mode Callbacks

This module contains callbacks that are only needed when editing or designing cards.
These callbacks are lazy-loaded when entering edit mode to reduce initial app startup time.

Callbacks:
- pre_populate_card_settings_for_edit: Pre-fill design form in edit mode
- design_card_body: Live preview of card with design changes
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


def register_design_callbacks(app):
    """Register design/edit mode callbacks for card component."""

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
            edit_context: Edit page context with component data
            card_id: Card component ID from the design form

        Returns:
            Tuple of pre-populated values for all card settings
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

        logger.info(f"🎨 PRE-POPULATING card settings for component {card_id['index']}")
        logger.info(f"   Title: {component_data.get('title')}")
        logger.info(f"   Column: {component_data.get('column_name')}")
        logger.info(f"   Aggregation: {component_data.get('aggregation')}")

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
        Callback to update card body based on the selected column and aggregation.
        Creates live preview of card with design changes.
        """

        input_id = str(id["index"])

        logger.info(f"input_id: {input_id}")
        logger.info(f"pathname: {pathname}")

        logger.info(f"input_value: {input_value}")
        logger.info(f"column_name: {column_name}")
        logger.info(f"aggregation_value: {aggregation_value}")
        logger.info(f"background_color: {background_color}")
        logger.info(f"title_color: {title_color}")
        logger.info(f"icon_name: {icon_name}")
        logger.info(f"title_font_size: {title_font_size}")

        if not local_data:
            return ([], None, None)

        TOKEN = local_data["access_token"]
        logger.info(f"TOKEN: {TOKEN}")

        # Extract dashboard_id and component_id from pathname
        # URL formats:
        #   /dashboard/{dashboard_id}/component/add/{component_id}
        #   /dashboard/{dashboard_id}/component/edit/{component_id}
        #   /dashboard/{dashboard_id} (regular dashboard)
        path_parts = pathname.split("/")
        if "/component/add/" in pathname or "/component/edit/" in pathname:
            dashboard_id = path_parts[2]  # Dashboard ID at index 2
            # Use component_id from pattern-matched ID
            input_id = str(id["index"])
        else:
            dashboard_id = path_parts[-1]  # Fallback for regular dashboard URLs
            input_id = None  # Regular dashboard - no specific component context

        logger.info(f"dashboard_id: {dashboard_id}")
        logger.info(f"input_id (for component data fetch): {input_id}")

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
                logger.info(f"Using wf/dc from component_data - wf_tag: {wf_id}, dc_tag: {dc_id}")
            else:
                logger.error("No wf_id/dc_id available from States or component_data")
                return ([], None, None)
        else:
            logger.info(
                f"Using wf/dc from States (hidden selects) - wf_tag: {wf_id}, dc_tag: {dc_id}"
            )

        logger.info(f"component_data: {component_data}")

        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        # Get the columns from the selected data collection
        cols_json = get_columns_from_data_collection(wf_id, dc_id, TOKEN)
        logger.info(f"cols_json: {cols_json}")

        data_columns_df = [
            {"column": c, "description": cols_json[c]["description"]}
            for c in cols_json
            if cols_json[c]["description"] is not None
        ]

        # Create DMC Table instead of DataTable for better theming
        table_rows = []
        for row in data_columns_df:
            table_rows.append(
                dmc.TableTr(
                    [
                        dmc.TableTd(
                            row["column"],
                            style={"textAlign": "center", "fontSize": "11px", "maxWidth": "150px"},
                        ),
                        dmc.TableTd(
                            row["description"],
                            style={"textAlign": "center", "fontSize": "11px", "maxWidth": "150px"},
                        ),
                    ]
                )
            )

        columns_description_df = dmc.Table(
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

        # If any of the input values are None, return an empty list
        if column_name is None or aggregation_value is None or wf_id is None or dc_id is None:
            if not component_data:
                return ([], None, columns_description_df)
            else:
                column_name = component_data["column_name"]
                aggregation_value = component_data["aggregation"]
                input_value = component_data["title"]
                logger.info("COMPONENT DATA")
                logger.info(f"column_name: {column_name}")
                logger.info(f"aggregation_value: {aggregation_value}")
                logger.info(f"input_value: {input_value}")

        # Get the type of the selected column
        column_type = cols_json[column_name]["type"]

        aggregation_description = html.Div(
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
                    transitionProps={
                        "name": "pop",
                        "duration": 300,
                    },
                    withinPortal=False,
                    withArrow=True,
                    openDelay=500,
                    closeDelay=500,
                    color="gray",
                ),
            ]
        )

        # Initialize relevant_metadata to empty list (defensive programming)
        relevant_metadata = []

        if dashboard_id:
            dashboard_data = load_depictio_data_mongo(dashboard_id, TOKEN=TOKEN)
            logger.info(f"dashboard_data: {dashboard_data}")
            relevant_metadata = [
                m
                for m in dashboard_data["stored_metadata"]
                if m["wf_id"] == wf_id and m["component_type"] == "interactive"
            ]
            logger.info(f"BUILD CARD - relevant_metadata: {relevant_metadata}")

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

        logger.info(f"card_kwargs: {card_kwargs}")

        new_card_body = build_card(**card_kwargs)

        return new_card_body, aggregation_description, columns_description_df
