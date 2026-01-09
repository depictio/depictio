from datetime import datetime

import dash
import dash_ag_grid as dag
import dash_mantine_components as dmc
import httpx
from dash import ALL, MATCH, Input, Output, State, callback, clientside_callback, ctx, html
from dash_iconify import DashIconify

# Depictio imports
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.api_calls import (
    api_call_fetch_user_from_token,
    api_call_get_dashboard,
    api_call_save_dashboard,
)

# Stepper parts imports
from depictio.dash.layouts.stepper_parts.part_one import register_callbacks_stepper_part_one
from depictio.dash.layouts.stepper_parts.part_three import register_callbacks_stepper_part_three
from depictio.dash.layouts.stepper_parts.part_two import register_callbacks_stepper_part_two
from depictio.dash.modules.card_component.frontend import design_card

# Figure component stepper integration - Phase 2A with simplified design UI
from depictio.dash.modules.figure_component.utils import design_figure
from depictio.dash.modules.interactive_component.frontend import design_interactive
from depictio.models.models.projects import ProjectResponse

min_step = 0
max_step = 3
active = 0


def _get_ag_grid_theme_class(theme: str) -> str:
    """Get the appropriate AG Grid theme class based on the theme.

    Args:
        theme: Theme name ("light", "dark", or other)

    Returns:
        AG Grid CSS theme class name
    """
    # Handle case where theme is empty dict, None, or other falsy value
    if not theme or theme == {} or theme == "{}":
        theme = "light"

    logger.debug(f"STEPPER - Using theme: {theme} for AG Grid")
    return "ag-theme-alpine-dark" if theme == "dark" else "ag-theme-alpine"


def register_callbacks_stepper(app):
    # Register callbacks from modular parts
    register_callbacks_stepper_part_one(app)
    register_callbacks_stepper_part_two(app)
    register_callbacks_stepper_part_three(app)

    # Initialize stored-add-button for stepper page
    @app.callback(
        Output("stored-add-button", "data", allow_duplicate=True),
        Input("stepper-init-trigger", "n_intervals"),
        State("stepper-page-context", "data"),
        prevent_initial_call=True,
    )
    def initialize_stepper_button_store(n_intervals, stepper_context):
        """Initialize the stored-add-button Store for stepper page on load."""
        if n_intervals and n_intervals > 0 and stepper_context:
            component_id = stepper_context.get("component_id", "stepper-component")
            logger.info(
                f"🎯 STEPPER INIT - Initializing button store with component_id: {component_id}"
            )
            # Use stepper-component as the index for pattern matching
            return {
                "count": 1,
                "_id": "stepper-component",  # Fixed index for stepper page
            }
        raise dash.exceptions.PreventUpdate

    @app.callback(
        Output("stepper-save-status", "data"),
        Input({"type": "btn-done", "index": "stepper-component"}, "n_clicks"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State("stepper-page-context", "data"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def save_stepper_component(n_clicks, stored_metadata, stepper_context, local_store):
        """
        Save component metadata from stepper page to dashboard before redirecting.

        This callback is triggered when btn-done is clicked on the stepper page.
        It collects the component configuration from the stored-metadata-component Store,
        adds it to the dashboard, and saves to the database.

        Args:
            n_clicks: Button click count
            stored_metadata: List of component metadata from all stored-metadata-component Stores
            stepper_context: Context data with dashboard_id, component_id, and mode
            local_store: User authentication data

        Returns:
            dict: Save status with success/error information
        """
        if not n_clicks or n_clicks == 0:
            raise dash.exceptions.PreventUpdate

        logger.info("💾 STEPPER SAVE - Starting component save from stepper page")

        # Validate authentication
        if not local_store or "access_token" not in local_store:
            error_msg = "User not authenticated"
            logger.error(f"❌ STEPPER SAVE - {error_msg}")
            return {"success": False, "error": error_msg}

        TOKEN = local_store["access_token"]

        # Extract context
        if not stepper_context:
            error_msg = "Stepper context missing"
            logger.error(f"❌ STEPPER SAVE - {error_msg}")
            return {"success": False, "error": error_msg}

        dashboard_id = stepper_context.get("dashboard_id")
        component_id = stepper_context.get("component_id")
        mode = stepper_context.get("mode", "add")

        logger.info(
            f"💾 STEPPER SAVE - Dashboard: {dashboard_id}, Component: {component_id}, Mode: {mode}"
        )

        # Fetch current dashboard data
        try:
            dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
            if not dashboard_data:
                error_msg = f"Failed to fetch dashboard data for {dashboard_id}"
                logger.error(f"❌ STEPPER SAVE - {error_msg}")
                return {"success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"Error fetching dashboard: {str(e)}"
            logger.error(f"❌ STEPPER SAVE - {error_msg}")
            return {"success": False, "error": error_msg}

        # Check user permissions
        current_user = api_call_fetch_user_from_token(TOKEN)
        if not current_user:
            error_msg = "Failed to fetch user from token"
            logger.error(f"❌ STEPPER SAVE - {error_msg}")
            return {"success": False, "error": error_msg}

        owner_ids = [str(e["id"]) for e in dashboard_data.get("permissions", {}).get("owners", [])]
        if str(current_user.id) not in owner_ids:
            error_msg = "User does not have permission to edit this dashboard"
            logger.error(f"❌ STEPPER SAVE - {error_msg}")
            return {"success": False, "error": error_msg}

        # Find the new component metadata
        # The stepper always uses fixed index "stepper-component" (see stepper_page.py:148)
        # We need to find metadata with this index and then update it to the final component_id
        STEPPER_INDEX = "stepper-component"
        new_component_metadata = None

        for meta in stored_metadata:
            if meta and meta.get("index"):
                meta_index = str(meta["index"])
                # Match the stepper fixed index with or without -tmp suffix
                if meta_index == STEPPER_INDEX or meta_index == f"{STEPPER_INDEX}-tmp":
                    new_component_metadata = meta.copy()
                    logger.info(
                        f"💾 STEPPER SAVE - Found component metadata with stepper index: {meta_index}"
                    )
                    break

        if not new_component_metadata:
            error_msg = f"Could not find component metadata with stepper index '{STEPPER_INDEX}'"
            logger.error(f"❌ STEPPER SAVE - {error_msg}")
            logger.error(
                f"❌ STEPPER SAVE - Available metadata indices: {[m.get('index') for m in stored_metadata if m]}"
            )
            return {"success": False, "error": error_msg}

        # Clean up metadata: remove -tmp suffix, set correct index
        new_component_metadata["index"] = component_id
        new_component_metadata["parent_index"] = None  # Not a child component
        new_component_metadata["last_updated"] = datetime.now().isoformat()

        logger.info(
            f"💾 STEPPER SAVE - Component metadata: type={new_component_metadata.get('component_type')}, "
            f"title={new_component_metadata.get('title')}"
        )

        # Get existing metadata and layout
        existing_metadata = dashboard_data.get("stored_metadata", [])
        existing_layout = dashboard_data.get("stored_layout_data", [])

        if mode == "edit":
            # Edit mode: replace existing component
            existing_metadata = [m for m in existing_metadata if m.get("index") != component_id]
            existing_layout = [
                layout_item
                for layout_item in existing_layout
                if layout_item.get("i") != f"box-{component_id}"
            ]
            logger.info(f"💾 STEPPER SAVE - EDIT mode: Replacing component {component_id}")
        else:
            # Add mode: create new component
            logger.info(f"💾 STEPPER SAVE - ADD mode: Adding new component {component_id}")

        # Add new component to metadata
        existing_metadata.append(new_component_metadata)

        # Create default layout for new component if not in edit mode
        if mode == "add" or not any(
            layout_item.get("i") == f"box-{component_id}" for layout_item in existing_layout
        ):
            # Calculate position: try to place new component in an empty spot
            # For simplicity, place at bottom of existing components
            max_y = 0
            if existing_layout:
                max_y = max(
                    layout_item.get("y", 0) + layout_item.get("h", 0)
                    for layout_item in existing_layout
                )

            new_layout = {
                "i": f"box-{component_id}",
                "x": 0,
                "y": max_y,
                "w": 6,  # Half width
                "h": 4,  # Medium height
                "minW": 2,
                "minH": 2,
            }
            existing_layout.append(new_layout)
            logger.info(f"💾 STEPPER SAVE - Created default layout: {new_layout}")

        # Update dashboard data
        dashboard_data["stored_metadata"] = existing_metadata
        dashboard_data["stored_layout_data"] = existing_layout

        # Save to database
        try:
            save_success = api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN)
            if save_success:
                logger.info(
                    f"✅ STEPPER SAVE - Successfully saved component {component_id} to dashboard {dashboard_id}"
                )
                return {
                    "success": True,
                    "dashboard_id": dashboard_id,
                    "component_id": component_id,
                    "mode": mode,
                }
            else:
                error_msg = "Save operation returned False"
                logger.error(f"❌ STEPPER SAVE - {error_msg}")
                return {"success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"Error saving dashboard: {str(e)}"
            logger.error(f"❌ STEPPER SAVE - {error_msg}")
            return {"success": False, "error": error_msg}

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input("stepper-save-status", "data"),
        State("stepper-page-context", "data"),
        prevent_initial_call=True,
    )
    def complete_component_and_return(save_status, stepper_context):
        """
        Navigate back to dashboard after component save completion.

        This callback waits for the save_stepper_component callback to complete,
        then navigates back to the dashboard.

        Args:
            save_status: Save status from save_stepper_component callback
            stepper_context: Context data with dashboard_id and component_id

        Returns:
            str: Dashboard URL to navigate to
        """
        if not save_status:
            raise dash.exceptions.PreventUpdate

        # Check if save was successful
        if not save_status.get("success"):
            error_msg = save_status.get("error", "Unknown error")
            logger.error(f"❌ STEPPER COMPLETE - Save failed: {error_msg}")
            # TODO: Show notification to user
            raise dash.exceptions.PreventUpdate

        # Get dashboard_id from save_status or context
        dashboard_id = save_status.get("dashboard_id")
        if not dashboard_id and stepper_context:
            dashboard_id = stepper_context.get("dashboard_id")

        if not dashboard_id:
            logger.error("❌ STEPPER COMPLETE - Could not determine dashboard_id")
            raise dash.exceptions.PreventUpdate

        component_id = save_status.get("component_id", "unknown")

        # Detect app context from stepper context
        is_edit_mode = stepper_context.get("is_edit_mode", False) if stepper_context else False
        app_prefix = "dashboard-edit" if is_edit_mode else "dashboard"

        logger.info(
            f"✅ STEPPER COMPLETE - Returning to {app_prefix} {dashboard_id} "
            f"(component: {component_id})"
        )

        return f"/{app_prefix}/{dashboard_id}"

    # Legacy modal close callback - kept for backward compatibility
    @app.callback(
        Output({"type": "modal", "index": MATCH}, "opened"),
        [Input({"type": "btn-done", "index": MATCH}, "n_clicks")],
        prevent_initial_call=True,
    )
    def close_modal(n_clicks):
        """Legacy modal close - kept for backward compatibility."""
        if n_clicks > 0:
            return False
        return True

    @app.callback(
        Output({"type": "modal-edit", "index": MATCH}, "opened"),
        [
            Input({"type": "btn-done-edit", "index": MATCH}, "n_clicks"),
            Input({"type": "modal-edit", "index": MATCH}, "opened"),
        ],
        prevent_initial_call=True,
    )
    def close_edit_modal(n_clicks, modal_opened):
        if not ctx.triggered:
            return True

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # If done button was clicked, close modal
        if "btn-done-edit" in trigger_id:
            if n_clicks and n_clicks > 0:
                logger.info("🔚 EDIT MODAL - Done button clicked, closing modal")
                return False

        # For modal state changes, let the draggable callback handle restoration
        # Just return the current state without interfering
        logger.info(f"🔚 EDIT MODAL - Modal state passthrough: {modal_opened}")
        return modal_opened

    @app.callback(
        Output({"type": "workflow-selection-label", "index": MATCH}, "data"),
        Output({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def set_workflow_options(n_clicks, local_store, pathname):
        logger.info(f"CTX Triggered ID: {ctx.triggered_id}")
        logger.info(f"CTX triggered: {ctx.triggered}")

        if not local_store:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_store["access_token"]

        if isinstance(ctx.triggered_id, dict):
            if ctx.triggered_id["type"] == "btn-option":
                component_selected = ctx.triggered_id["value"]
        else:
            component_selected = "None"

        # Extract dashboard_id from pathname
        # URL format: /dashboard/{dashboard_id}/component/add/{component_id}
        path_parts = pathname.split("/")
        if "/component/add/" in pathname:
            dashboard_id = path_parts[2]  # Get dashboard_id, not component_id
        else:
            dashboard_id = path_parts[-1]  # Fallback for regular dashboard URLs

        try:
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{dashboard_id}",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                },
            )
            response.raise_for_status()
            response_data = response.json()
            # Handle nested 'project' key in response (API returns {'project': {...}, 'delta_locations': {}})
            project_dict = response_data.get("project", response_data)
            # Use ProjectResponse.from_mongo() to convert _id → id recursively
            project = ProjectResponse.from_mongo(project_dict).model_dump()
        except Exception as e:
            logger.error(f"Failed to fetch project from dashboard_id {dashboard_id}: {e}")
            raise dash.exceptions.PreventUpdate

        # Guard: Check if project has workflows
        if "workflows" not in project or not project["workflows"]:
            logger.warning(f"Project has no workflows: {response_data}")
            return [], None

        all_wf_dc = project["workflows"]

        mapping_component_data_collection = {
            "table": ["Figure", "Card", "Interactive", "Table", "Text"],
            "jbrowse2": ["JBrowse2"],
            "multiqc": ["MultiQC"],
        }

        logger.info(f"Component selected: {component_selected}")

        # Use a dictionary to track unique workflows efficiently
        valid_wfs = []
        seen_workflow_ids = set()

        for wf in all_wf_dc:
            # Check if the workflow has any matching data collection
            if (
                any(
                    component_selected in mapping_component_data_collection[dc["config"]["type"]]
                    for dc in wf["data_collections"]
                )
                and wf["id"] not in seen_workflow_ids
            ):
                seen_workflow_ids.add(wf["id"])
                valid_wfs.append(
                    {
                        "label": wf.get("workflow_tag", wf.get("name", wf["id"])),
                        "value": wf["id"],
                    }
                )

        logger.info(f"valid_wfs: {valid_wfs}")
        # Return the data and the first value if the data is not empty
        if valid_wfs:
            return valid_wfs, valid_wfs[0]["value"]
        else:
            return dash.no_update, dash.no_update

    @app.callback(
        Output({"type": "datacollection-selection-label", "index": MATCH}, "data"),
        Output({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "id"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def set_datacollection_options(selected_workflow, id, n_clicks, local_store, pathname):
        if not local_store:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_store["access_token"]

        if isinstance(ctx.triggered_id, dict):
            if ctx.triggered_id["type"] == "btn-option":
                component_selected = ctx.triggered_id["value"]
        else:
            component_selected = "None"

        # Extract dashboard_id from pathname
        # URL format: /dashboard/{dashboard_id}/component/add/{component_id}
        path_parts = pathname.split("/")
        if "/component/add/" in pathname:
            dashboard_id = path_parts[2]  # Get dashboard_id, not component_id
        else:
            dashboard_id = path_parts[-1]  # Fallback for regular dashboard URLs

        try:
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{dashboard_id}",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                },
            )
            response.raise_for_status()
            response_data = response.json()
            # Handle nested 'project' key in response (API returns {'project': {...}, 'delta_locations': {}})
            project_dict = response_data.get("project", response_data)
            # Use ProjectResponse.from_mongo() to convert _id → id recursively
            project = ProjectResponse.from_mongo(project_dict).model_dump()
        except Exception as e:
            logger.error(f"Failed to fetch project from dashboard_id {dashboard_id}: {e}")
            raise dash.exceptions.PreventUpdate

        logger.info(f"Id: {id}")
        logger.info(f"Selected workflow: {selected_workflow}")

        # Guard: Check if project has workflows
        if "workflows" not in project or not project["workflows"]:
            logger.warning(f"Project has no workflows: {response_data}")
            return [], None

        all_wf_dc = project["workflows"]
        logger.info(f"All workflows and data collections: {all_wf_dc}")
        selected_wf_list = [wf for wf in all_wf_dc if wf["id"] == selected_workflow]
        logger.info(f"Selected workflow: {selected_wf_list}")

        if not selected_wf_list:
            logger.error(f"No workflow found with id '{selected_workflow}'")
            logger.error(f"Available workflow ids: {[wf['id'] for wf in all_wf_dc]}")
            return [], None

        selected_wf_data = selected_wf_list[0]

        mapping_component_data_collection = {
            "table": ["Figure", "Card", "Interactive", "Table", "Text"],
            "jbrowse2": ["JBrowse2"],
            "multiqc": ["MultiQC"],
        }

        logger.info(f"Component selected: {component_selected}")

        # Get regular data collections
        valid_dcs = [
            {
                "label": dc["data_collection_tag"],
                "value": dc["id"],
            }
            for dc in selected_wf_data["data_collections"]
            if component_selected in mapping_component_data_collection[dc["config"]["type"]]
        ]

        # Add joined data collection options only for Figure and Table components
        # Exclude Card and Interactive components from having access to joined data collections
        allowed_components_for_joined = ["Figure", "Table"]
        if component_selected in allowed_components_for_joined:
            try:
                # Fetch available joins for this workflow
                joins_response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/datacollections/get_dc_joined/{selected_workflow}",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

                if joins_response.status_code == 200:
                    joins_data = joins_response.json()
                    workflow_joins = joins_data.get(selected_workflow, {})

                    # Create a mapping from DC ID to DC tag for display names
                    dc_id_to_tag = {
                        dc["id"]: dc["data_collection_tag"]
                        for dc in selected_wf_data["data_collections"]
                    }

                    # Create a mapping from DC ID to DC type for filtering
                    dc_id_to_type = {
                        dc["id"]: dc["config"]["type"]
                        for dc in selected_wf_data["data_collections"]
                    }

                    # Add joined DC options
                    for join_key, join_config in workflow_joins.items():
                        # Extract DC IDs from join key (format: "dc_id1--dc_id2")
                        dc_ids = join_key.split("--")
                        if len(dc_ids) == 2:
                            dc1_id, dc2_id = dc_ids

                            # Skip joins involving multiqc data collections
                            # MultiQC data should only be accessible via MultiQC component
                            dc1_type = dc_id_to_type.get(dc1_id, "")
                            dc2_type = dc_id_to_type.get(dc2_id, "")
                            if dc1_type == "multiqc" or dc2_type == "multiqc":
                                logger.debug(
                                    f"Skipping join {join_key} involving multiqc data collection"
                                )
                                continue

                            dc1_tag = dc_id_to_tag.get(dc1_id, dc1_id)
                            dc2_tag = dc_id_to_tag.get(dc2_id, dc2_id)

                            # Create display name for joined DC
                            joined_label = f"🔗 Joined: {dc1_tag} + {dc2_tag}"

                            valid_dcs.append(
                                {
                                    "label": joined_label,
                                    "value": join_key,  # Use join key as value (e.g., "dc_id1--dc_id2")
                                }
                            )

                    logger.info(f"Added {len(workflow_joins)} joined data collection options")
                else:
                    logger.warning(
                        f"Failed to fetch joins for workflow {selected_workflow}: {joins_response.status_code}"
                    )

            except Exception as e:
                logger.error(f"Error fetching joined data collections: {str(e)}")

        logger.info(f"ID: {id}")
        logger.info(f"Total valid DCs (including joins): {len(valid_dcs)}")

        if not selected_workflow:
            raise dash.exceptions.PreventUpdate

        # Return the data and the first value if the data is not empty
        if valid_dcs:
            return valid_dcs, valid_dcs[0]["value"]
        else:
            raise dash.exceptions.PreventUpdate

    @app.callback(
        [
            Output({"type": "stepper-basic-usage", "index": MATCH}, "active"),
            Output({"type": "next-basic-usage", "index": MATCH}, "disabled"),
        ],
        [
            Input({"type": "back-basic-usage", "index": MATCH}, "n_clicks"),
            Input({"type": "next-basic-usage", "index": MATCH}, "n_clicks"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        ],
        [State({"type": "stepper-basic-usage", "index": MATCH}, "active")],
    )
    def update_stepper(
        back_clicks,
        next_clicks,
        workflow_selection,
        data_selection,
        btn_option_clicks,
        current_step,
    ):
        ctx = dash.callback_context

        if not ctx.triggered:
            # No inputs have fired yet, prevent update
            raise dash.exceptions.PreventUpdate

        triggered_id = ctx.triggered_id
        if isinstance(ctx.triggered_id, dict):
            triggered_input = ctx.triggered_id["type"]
        elif isinstance(ctx.triggered_id, str):
            triggered_input = ctx.triggered_id
        inputs_list = ctx.inputs_list

        logger.info(f"CTX triggered: {ctx.triggered}")
        logger.info(f"Triggered ID: {triggered_id}")
        logger.info(f"Inputs list: {inputs_list}")

        next_step = current_step  # Default to the current step if no actions require a change

        # Check if any btn-option was clicked
        btn_clicks = [btn for btn in btn_option_clicks if btn is not None and btn > 0]
        if btn_clicks:
            # Check if Text component was selected
            if isinstance(triggered_id, dict) and triggered_id.get("type") == "btn-option":
                component_selected = triggered_id.get("value")
                logger.info(f"Component selected: {component_selected}")
                if component_selected in ["Text", "MultiQC"]:
                    # Text and MultiQC components don't need data selection, skip to design step
                    next_step = 2  # Move directly to component design step
                    logger.info(
                        f"{component_selected} component selected, advancing to step {next_step}"
                    )
                    return next_step, False  # Return immediately to avoid further processing
                else:
                    # Other components need data selection
                    next_step = 1  # Move from button selection to data selection
            else:
                next_step = 1  # Default: move to data selection

        if triggered_input == "btn-option":
            if not btn_clicks:
                return current_step, True

        # Check workflow and data collection for enabling/disabling the next button
        disable_next = False
        if current_step == 1 and (not workflow_selection or not data_selection):
            disable_next = True

        # Check if the Next or Back buttons were clicked
        if "next-basic-usage" in triggered_input:
            next_step = min(3, current_step + 1)  # Move to the next step, max out at step 3
        elif "back-basic-usage" in triggered_input:
            next_step = max(0, current_step - 1)  # Move to the previous step, minimum is step 0

        return next_step, disable_next

    # Data preview callback for stepper
    @app.callback(
        Output({"type": "stepper-data-preview", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        ],
        [
            State("local-store", "data"),
            State("theme-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_stepper_data_preview(workflow_id, data_collection_id, local_data, theme):
        """Update data preview in stepper when workflow/data collection changes."""
        if not workflow_id or not data_collection_id or not local_data:
            return html.Div()

        try:
            TOKEN = local_data["access_token"]

            # Check data collection type to determine if preview is needed
            try:
                response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/datacollections/{data_collection_id}",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

                if response.status_code == 200:
                    dc_info = response.json()
                    dc_type = dc_info.get("config", {}).get("type", "").lower()

                    if dc_type == "multiqc":
                        # MultiQC data collections don't have traditional tabular data for preview
                        return dmc.Alert(
                            "MultiQC data collections don't show a data preview. Use the Figure component to visualize MultiQC reports.",
                            color="blue",
                            title="MultiQC Data Collection",
                            icon=DashIconify(icon="mdi:chart-line"),
                        )
            except Exception as e:
                logger.warning(f"Error checking data collection type for preview: {e}")
                # Continue with normal preview if check fails

            # Load data preview (first 100 rows for stepper)
            df = load_deltatable_lite(
                workflow_id=workflow_id,
                data_collection_id=data_collection_id,
                TOKEN=TOKEN,
                limit_rows=100,  # Default preview size for stepper
                load_for_preview=True,  # Use preview cache to avoid conflicts with full dataset
            )

            if df is None or df.height == 0:
                return dmc.Alert(
                    "No data available for preview",
                    color="yellow",
                    title="No Data",
                )

            # Convert to pandas for AG Grid
            df_pd = df.to_pandas()

            # Handle column names with dots
            column_mapping = {}
            for col in df_pd.columns:
                if "." in col:
                    safe_col_name = col.replace(".", "_")
                    column_mapping[col] = safe_col_name
                else:
                    column_mapping[col] = col

            # Rename DataFrame columns to safe names
            df_pd = df_pd.rename(columns=column_mapping)

            # Create column definitions with improved styling
            column_defs = []
            original_columns = list(column_mapping.keys())
            for original_col in original_columns:
                safe_col = column_mapping[original_col]

                col_def = {
                    "headerName": original_col,
                    "field": safe_col,
                    "filter": True,
                    "sortable": True,
                    "resizable": True,
                    "minWidth": 120,
                }

                # Set appropriate column types
                if df_pd[safe_col].dtype in ["int64", "float64"]:
                    col_def["type"] = "numericColumn"
                elif df_pd[safe_col].dtype == "bool":
                    col_def["cellRenderer"] = "agCheckboxCellRenderer"

                column_defs.append(col_def)

            # Create enhanced AG Grid for stepper
            grid = dag.AgGrid(
                id={"type": "stepper-data-grid", "index": workflow_id},
                columnDefs=column_defs,
                rowData=df_pd.to_dict("records"),
                defaultColDef={
                    "filter": True,
                    "sortable": True,
                    "resizable": True,
                    "minWidth": 100,
                },
                dashGridOptions={
                    "pagination": True,
                    "paginationPageSize": 10,  # Smaller page size for stepper
                    "domLayout": "normal",
                    "animateRows": True,
                    "suppressMenuHide": True,
                },
                style={"height": "350px", "width": "100%"},
                className=_get_ag_grid_theme_class(theme),
            )

            # Create summary and controls
            summary_controls = dmc.Group(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:table-eye", width=20),
                            dmc.Text("Data Preview", fw="bold", size="md"),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        [
                            dmc.Text(
                                f"Showing {min(100, df.height):,} of {df.height:,} rows",
                                size="sm",
                                c="gray",
                            ),
                            dmc.Text(f"{df.width} columns", size="sm", c="gray"),
                        ],
                        gap="lg",
                    ),
                ],
                justify="space-between",
                align="center",
            )

            return dmc.Card(
                [
                    summary_controls,
                    dmc.Space(h="sm"),
                    grid,
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="md",
            )

        except Exception as e:
            logger.error(f"Error in stepper data preview: {e}")
            # Check if this might be a MultiQC-related error (deltatable 404)
            error_str = str(e).lower()
            if "deltatable" in error_str or "404" in error_str:
                # Likely a MultiQC collection without delta table - hide error
                return html.Div()
            else:
                # Show error for other types of failures
                return dmc.Alert(
                    f"Error loading data preview: {str(e)}",
                    color="red",
                    title="Preview Error",
                )


def create_stepper_output_edit(n, parent_id, active, component_data, TOKEN):
    logger.info(f"🔍 CREATE_STEPPER_OUTPUT_EDIT - Component data: {component_data}")
    logger.info(f"🔍 n={n}, parent_id={parent_id}, active={active}")
    id = {"type": f"{component_data['component_type']}-component", "index": n}

    # wf_tag = return_wf_tag_from_id(component_data["wf_id"], TOKEN=TOKEN)
    # dc_tag = return_dc_tag_from_id(
    #     # workflow_id=component_data["wf_id"],
    #     data_collection_id=component_data["dc_id"],
    #     TOKEN=TOKEN,
    # )

    select_row = dmc.SimpleGrid(
        cols=2,
        spacing="md",
        children=[
            dmc.Select(
                id={"type": "workflow-selection-label", "index": n},
                value=component_data.get("wf_id", ""),
                label=dmc.Group(
                    [
                        DashIconify(icon="flat-color-icons:workflow", width=20),
                        dmc.Text("Workflow selection", fw="bold", size="md"),
                    ],
                    gap="xs",
                ),
                placeholder="Select workflow...",
            ),
            dmc.Select(
                id={
                    "type": "datacollection-selection-label",
                    "index": n,
                },
                value=component_data.get("dc_id", ""),
                label=dmc.Group(
                    [
                        DashIconify(icon="bxs:data", width=20),
                        dmc.Text("Data collection selection", fw="bold", size="md"),
                    ],
                    gap="xs",
                ),
                placeholder="Select data collection...",
            ),
        ],
        style={"display": "none"},
    )

    # logger.info(f"Select row: {select_row}")

    # Defensive handling for missing wf_id/dc_id
    wf_id = component_data.get("wf_id")
    dc_id = component_data.get("dc_id")
    logger.info(f"🔍 Extracted wf_id={wf_id}, dc_id={dc_id} from component_data")

    if wf_id and dc_id:
        df = load_deltatable_lite(wf_id, dc_id, TOKEN=TOKEN)
    else:
        logger.warning(f"Missing wf_id or dc_id in component_data: wf_id={wf_id}, dc_id={dc_id}")
        # Return empty dataframe as fallback
        import polars as pl

        df = pl.DataFrame()
    # logger.info(f"DF: {df}")

    def return_design_component(component_selected, id, df):
        if component_selected == "Figure":
            # Pass workflow_id, data_collection_id, and local_data for column loading
            local_data = {"access_token": TOKEN}
            logger.info(
                f"🔍 Calling design_figure with id={id}, wf_id={wf_id}, dc_id={dc_id}, TOKEN present={TOKEN is not None}"
            )
            return design_figure(
                id, workflow_id=wf_id, data_collection_id=dc_id, local_data=local_data
            )
        elif component_selected == "Card":
            return design_card(id, df)
        elif component_selected == "Interactive":
            return design_interactive(id, df)
        # elif component_selected == "Table":
        #     return design_table(id)

    component_selected = component_data["component_type"].capitalize()
    card = return_design_component(component_selected=component_selected, id=id, df=df)
    # logger.info(f"Card: {card}")

    # Handle the fact that design functions return lists, not single components
    if isinstance(card, list):
        modal_body = dmc.Stack([select_row] + card, gap="md", style={"width": "100%"})
    else:
        modal_body = dmc.Stack([select_row, card], gap="md", style={"width": "100%"})

    modal = dmc.Modal(
        id={"type": "modal-edit", "index": n},
        children=[
            dmc.Stack(
                [
                    html.Div(
                        modal_body,
                        style=MODAL_BODY_STYLE,
                    ),
                    dmc.Paper(
                        dmc.Group(
                            [
                                dmc.Button(
                                    "Confirm Edit",
                                    id={"type": "btn-done-edit", "index": n},
                                    n_clicks=0,
                                    size="lg",
                                    leftSection=DashIconify(icon="bi:check-circle", width=20),
                                    color="green",
                                    disabled=True,
                                ),
                            ],
                            justify="center",
                        ),
                        style=MODAL_FOOTER_STYLE,
                        withBorder=True,
                    ),
                ],
                style=MODAL_CONTENT_STYLE,
                gap=0,
            )
        ],
        title=html.Div(
            [
                html.Img(
                    src=dash.get_asset_url("images/icons/favicon.ico"),
                    style={
                        "height": "34px",
                        "width": "34px",
                        "marginRight": "10px",
                        "verticalAlign": "middle",
                    },
                ),
                html.Span("Edit your dashboard component", style={"verticalAlign": "middle"}),
            ]
        ),
        opened=True,
        size=MODAL_CONFIG["size"],
        centered=True,
        withCloseButton=True,
        closeOnClickOutside=True,
        closeOnEscape=True,
        trapFocus=False,  # Fix DMC Switch clickability in modals
        styles={
            "title": {
                "fontSize": "1.8rem",
                "fontWeight": "bold",
                "textAlign": "center",
                "width": "100%",
            },
            "header": {
                "justifyContent": "center",
                "textAlign": "center",
            },
        },
    )
    # logger.info(f"TEST MODAL: {modal}")

    return modal


def create_stepper_output(n, active):
    logger.info(f"Creating stepper output for index {n}")
    logger.info(f"Active step: {active}")

    # # Use component_data to pre-populate stepper if editing
    # component_selected = component_data.get("component_selected", "None") if component_data else "None"
    # workflow_selection = component_data.get("workflow_selection", "")
    # datacollection_selection = component_data.get("datacollection_selection", "")

    stepper_dropdowns = dmc.Stack(
        [
            # Component Selection Display
            dmc.Stack(
                [
                    dmc.Title(
                        "Select Data Source",
                        order=3,
                        ta="center",
                        fw="bold",
                        mb="xs",
                    ),
                    dmc.Text(
                        "Choose the workflow and data collection for your component",
                        size="sm",
                        c="gray",
                        ta="center",
                        mb="md",
                    ),
                ],
                gap="xs",
            ),
            # Selected Component Badge
            dmc.Group(
                [
                    dmc.Text(
                        "Selected Component:",
                        fw="bold",
                        size="md",
                    ),
                    html.Div(
                        id={"type": "component-selected", "index": n},
                        children=dmc.Badge(
                            "None",
                            size="lg",
                            variant="outline",
                            color="gray",
                        ),
                    ),
                ],
                justify="center",
                align="center",
                gap="sm",
            ),
            dmc.Divider(variant="solid"),
            # Data Selection
            dmc.Stack(
                [
                    # dmc.Title(
                    #     "Data Configuration",
                    #     order=4,
                    #     ta="left",
                    #     fw="normal",
                    #     size="md",
                    #     mb="sm",
                    # ),
                    dmc.SimpleGrid(
                        cols=2,
                        spacing="lg",
                        children=[
                            dmc.Select(
                                id={"type": "workflow-selection-label", "index": n},
                                label=dmc.Group(
                                    [
                                        DashIconify(icon="flat-color-icons:workflow", width=20),
                                        dmc.Text("Workflow", fw="bold", size="md"),
                                    ],
                                    gap="xs",
                                ),
                                placeholder="Select workflow...",
                                size="md",
                            ),
                            dmc.Select(
                                id={
                                    "type": "datacollection-selection-label",
                                    "index": n,
                                },
                                label=dmc.Group(
                                    [
                                        DashIconify(icon="bxs:data", width=20),
                                        dmc.Text("Data Collection", fw="bold", size="md"),
                                    ],
                                    gap="xs",
                                ),
                                placeholder="Select data collection...",
                                size="md",
                            ),
                        ],
                    ),
                ],
                gap="sm",
            ),
            # Data Collection Information
            html.Div(id={"type": "dropdown-output", "index": n}),
            # Data Preview Section
            html.Div(id={"type": "stepper-data-preview", "index": n}),
        ],
        gap="lg",
    )

    buttons_list = html.Div(
        [
            html.Div(
                id={
                    "type": "buttons-list",
                    "index": n,
                }
            ),
            html.Div(
                id={
                    "type": "store-list",
                    "index": n,
                }
            ),
        ]
    )

    step_one = dmc.StepperStep(
        label="Component Type",
        description="Choose the type of dashboard component to create",
        children=buttons_list,
        id={"type": "stepper-step-2", "index": n},
    )

    step_two = dmc.StepperStep(
        label="Data Source",
        description="Connect your component to data",
        children=stepper_dropdowns,
        id={"type": "stepper-step-1", "index": n},
    )
    step_three = dmc.StepperStep(
        label="Component Design",
        description="Customize the appearance and behavior of your component",
        children=html.Div(
            id={
                "type": "output-stepper-step-3",
                "index": n,
            },
        ),
        id={"type": "stepper-step-3", "index": n},
    )
    step_completed = dmc.StepperCompleted(
        children=[
            dmc.Stack(
                [
                    dmc.Title(
                        "Component Ready!",
                        order=2,
                        ta="center",
                        fw="bold",
                        c="green",
                    ),
                    dmc.Text(
                        "Your component has been configured and is ready to be added to your dashboard.",
                        size="md",
                        ta="center",
                        c="gray",
                        mb="xl",
                    ),
                    dmc.Center(
                        dmc.Button(
                            "Add to Dashboard",
                            id={
                                "type": "btn-done",
                                "index": n,
                            },
                            color="green",
                            variant="filled",
                            n_clicks=0,
                            size="xl",
                            style={
                                "height": "60px",
                                "fontSize": "18px",
                                "fontWeight": "bold",
                            },
                            leftSection=DashIconify(icon="bi:check-circle", width=24),
                        )
                    ),
                ],
                gap="md",
                align="center",
            ),
        ],
    )

    steps = [step_one, step_two, step_three, step_completed]

    stepper = dmc.Stepper(
        id={"type": "stepper-basic-usage", "index": n},
        active=active,
        children=steps,
        color="gray",
        size="lg",
        iconSize=42,
        styles={
            "stepLabel": {
                "fontSize": "16px",
                "fontWeight": "bold",
            },
            "stepDescription": {
                "fontSize": "14px",
                "color": "var(--mantine-color-dimmed)",
            },
        },
    )

    stepper_footer = dmc.Group(
        justify="center",
        align="center",
        children=[
            dmc.Button(
                "Back",
                id={"type": "back-basic-usage", "index": n},
                variant="outline",
                color="gray",
                size="lg",
                n_clicks=0,
                leftSection=DashIconify(icon="mdi:arrow-left", width=20),
            ),
            dmc.Button(
                "Next Step",
                id={"type": "next-basic-usage", "index": n},
                variant="filled",
                disabled=True,
                n_clicks=0,
                color="gray",
                size="lg",
                rightSection=DashIconify(icon="mdi:arrow-right", width=20),
            ),
        ],
    )

    modal = html.Div(
        [
            dmc.Modal(
                id={"type": "modal", "index": n},
                children=[
                    dmc.Stack(
                        [
                            html.Div(
                                stepper,
                                style=MODAL_BODY_STYLE,
                            ),
                            dmc.Paper(
                                stepper_footer,
                                style=MODAL_FOOTER_STYLE,
                                withBorder=True,
                            ),
                        ],
                        style={
                            **MODAL_CONTENT_STYLE,
                            "marginTop": "-7px",  # Negative margin to move title closer to top
                        },
                        gap=0,
                    )
                ],
                title=html.Div(
                    [
                        html.Img(
                            src=dash.get_asset_url("images/icons/favicon.ico"),
                            style={
                                "height": "34px",
                                "width": "34px",
                                "marginRight": "10px",
                                "verticalAlign": "middle",
                            },
                        ),
                        html.Span("Create Dashboard Component", style={"verticalAlign": "middle"}),
                    ]
                ),
                opened=True,
                size=MODAL_CONFIG["size"],
                centered=False,  # Don't center for fullscreen
                withCloseButton=False,
                closeOnClickOutside=False,
                closeOnEscape=False,
                trapFocus=False,  # Fix DMC Switch clickability in modals
                fullScreen=True,
                styles={
                    "title": {
                        "fontSize": "1.8rem",
                        "fontWeight": "bold",
                        "textAlign": "center",
                        "width": "100%",
                    },
                    "header": {
                        "justifyContent": "center",
                        "textAlign": "center",
                    },
                },
            ),
        ],
        id=n,
    )
    # logger.info(f"TEST MODAL: {modal}")

    return modal


def create_stepper_content(n, active):
    """
    Create stepper content as standard layout (not modal).

    This function creates the same stepper structure as create_stepper_output,
    but returns it as a standard page layout instead of wrapping it in a modal.
    This is used by the stepper page for route-based component creation/editing.

    Args:
        n: Component index/identifier for pattern matching callbacks
        active: Initial active step (0-3)

    Returns:
        dmc.Stack: Stepper content with footer in standard page layout
    """
    logger.info(f"Creating stepper content (standard layout) for index {n}")
    logger.info(f"Active step: {active}")

    # Component Selection Display and Data Source (Step 2)
    stepper_dropdowns = dmc.Stack(
        [
            # Component Selection Display
            dmc.Stack(
                [
                    dmc.Title(
                        "Select Data Source",
                        order=3,
                        ta="center",
                        fw="bold",
                        mb="xs",
                    ),
                    dmc.Text(
                        "Choose the workflow and data collection for your component",
                        size="sm",
                        c="gray",
                        ta="center",
                        mb="md",
                    ),
                ],
                gap="xs",
            ),
            # Selected Component Badge
            dmc.Group(
                [
                    dmc.Text(
                        "Selected Component:",
                        fw="bold",
                        size="md",
                    ),
                    html.Div(
                        id={"type": "component-selected", "index": n},
                        children=dmc.Badge(
                            "None",
                            size="lg",
                            variant="outline",
                            color="gray",
                        ),
                    ),
                ],
                justify="center",
                align="center",
                gap="sm",
            ),
            dmc.Divider(variant="solid"),
            # Data Selection
            dmc.Stack(
                [
                    dmc.SimpleGrid(
                        cols=2,
                        spacing="lg",
                        children=[
                            dmc.Select(
                                id={"type": "workflow-selection-label", "index": n},
                                label=dmc.Group(
                                    [
                                        DashIconify(icon="flat-color-icons:workflow", width=20),
                                        dmc.Text("Workflow", fw="bold", size="md"),
                                    ],
                                    gap="xs",
                                ),
                                placeholder="Select workflow...",
                                size="md",
                            ),
                            dmc.Select(
                                id={
                                    "type": "datacollection-selection-label",
                                    "index": n,
                                },
                                label=dmc.Group(
                                    [
                                        DashIconify(icon="bxs:data", width=20),
                                        dmc.Text("Data Collection", fw="bold", size="md"),
                                    ],
                                    gap="xs",
                                ),
                                placeholder="Select data collection...",
                                size="md",
                            ),
                        ],
                    ),
                ],
                gap="sm",
            ),
            # Data Collection Information
            html.Div(id={"type": "dropdown-output", "index": n}),
            # Data Preview Section
            html.Div(id={"type": "stepper-data-preview", "index": n}),
        ],
        gap="lg",
    )

    # Component Type Selection (Step 1)
    buttons_list = html.Div(
        [
            html.Div(
                id={
                    "type": "buttons-list",
                    "index": n,
                }
            ),
            html.Div(
                id={
                    "type": "store-list",
                    "index": n,
                }
            ),
        ]
    )

    # Define stepper steps
    step_one = dmc.StepperStep(
        label="Component Type",
        description="Choose the type of dashboard component to create",
        children=buttons_list,
        id={"type": "stepper-step-2", "index": n},
    )

    step_two = dmc.StepperStep(
        label="Data Source",
        description="Connect your component to data",
        children=stepper_dropdowns,
        id={"type": "stepper-step-1", "index": n},
    )

    step_three = dmc.StepperStep(
        label="Component Design",
        description="Customize the appearance and behavior of your component",
        children=html.Div(
            id={
                "type": "output-stepper-step-3",
                "index": n,
            },
        ),
        id={"type": "stepper-step-3", "index": n},
    )

    step_completed = dmc.StepperCompleted(
        children=[
            dmc.Stack(
                [
                    dmc.Title(
                        "Component Ready!",
                        order=2,
                        ta="center",
                        fw="bold",
                        c="green",
                    ),
                    # Dynamic text based on mode (add/edit)
                    html.Div(
                        id={"type": "completion-text", "index": n},
                        children=dmc.Text(
                            "Your component has been configured and is ready to be added to your dashboard.",
                            size="md",
                            ta="center",
                            c="gray",
                            mb="xl",
                        ),
                    ),
                    dmc.Center(
                        dmc.Button(
                            # Dynamic button text based on mode
                            children=html.Div(
                                id={"type": "btn-done-text", "index": n},
                                children="Add to Dashboard",
                            ),
                            id={
                                "type": "btn-done",
                                "index": n,
                            },
                            color="green",
                            variant="filled",
                            n_clicks=0,
                            size="xl",
                            style={
                                "height": "60px",
                                "fontSize": "18px",
                                "fontWeight": "bold",
                            },
                            leftSection=DashIconify(icon="bi:check-circle", width=24),
                        )
                    ),
                ],
                gap="md",
                align="center",
            ),
        ],
    )

    steps = [step_one, step_two, step_three, step_completed]

    # Create stepper component
    stepper = dmc.Stepper(
        id={"type": "stepper-basic-usage", "index": n},
        active=active,
        children=steps,
        color="gray",
        size="lg",
        iconSize=42,
        styles={
            "stepLabel": {
                "fontSize": "16px",
                "fontWeight": "bold",
            },
            "stepDescription": {
                "fontSize": "14px",
                "color": "var(--mantine-color-dimmed)",
            },
        },
    )

    # Create stepper navigation footer
    stepper_footer = dmc.Group(
        justify="center",
        align="center",
        children=[
            dmc.Button(
                "Back",
                id={"type": "back-basic-usage", "index": n},
                variant="outline",
                color="gray",
                size="lg",
                n_clicks=0,
                leftSection=DashIconify(icon="mdi:arrow-left", width=20),
            ),
            dmc.Button(
                "Next Step",
                id={"type": "next-basic-usage", "index": n},
                variant="filled",
                disabled=True,
                n_clicks=0,
                color="gray",
                size="lg",
                rightSection=DashIconify(icon="mdi:arrow-right", width=20),
            ),
        ],
    )

    # Create standard layout (NOT modal) with sticky footer
    content = dmc.Stack(
        [
            # Stepper content - scrollable
            dmc.Box(
                stepper,
                style={
                    "flex": 1,
                    "overflowY": "auto",
                    "overflowX": "hidden",
                    "padding": "1rem",
                    "minHeight": "0",  # Allow flex item to shrink
                },
            ),
            # Footer - sticky at bottom
            dmc.Paper(
                stepper_footer,
                withBorder=True,
                p="md",
                style={
                    "position": "sticky",
                    "bottom": 0,
                    "backgroundColor": "var(--app-surface-color, #ffffff)",
                    "borderTop": "1px solid var(--app-border-color, #e9ecef)",
                    "zIndex": 100,
                    "flexShrink": 0,
                },
            ),
        ],
        gap=0,
        style={
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "overflow": "hidden",
        },
    )

    logger.info(f"✅ Created stepper content (standard layout) for index {n}")
    return content


# Modal configuration constants
MODAL_CONFIG = {
    "size": "90%",
    "height": "100vh",  # Full height for fullscreen
}

# Modal styles for fullscreen mode
MODAL_CONTENT_STYLE = {
    "height": "100vh",  # Full viewport height
    "minHeight": "100vh",  # Ensure full height
    "maxHeight": "100vh",  # Prevent exceeding viewport
    "overflowY": "hidden",  # Prevent content scroll - let body handle it
    "padding": "0",  # Remove padding for fullscreen
    "display": "flex",
    "flexDirection": "column",
    "boxSizing": "border-box",
}

MODAL_BODY_STYLE = {
    "flex": "1",
    "overflowY": "auto",
    "overflowX": "hidden",  # Prevent horizontal scrolling
    "padding": "0.5rem 1rem 1rem 1rem",  # Reduced top padding
    "minHeight": "0",  # Allow flex item to shrink
    "boxSizing": "border-box",
    "marginBottom": "80px",  # Space for footer
}

MODAL_FOOTER_STYLE = {
    "flexShrink": "0",
    "padding": "1rem",
    "position": "fixed",  # Fixed to viewport
    "bottom": "0",
    "left": "0",
    "right": "0",
    "zIndex": "1000",
}


# Callback to dynamically control modal size
@callback(
    Output({"type": "modal-edit", "index": MATCH}, "size"),
    [Input({"type": "modal-edit", "index": MATCH}, "opened")],
    prevent_initial_call=True,
)
def update_modal_size(opened):
    """Update modal size when it opens."""
    return MODAL_CONFIG["size"]


@callback(
    Output({"type": "modal", "index": MATCH}, "size"),
    [Input({"type": "modal", "index": MATCH}, "opened")],
    prevent_initial_call=True,
)
def update_modal_size_regular(opened):
    """Update regular modal size when it opens."""
    return MODAL_CONFIG["size"]


# PHASE 2C: Converted to clientside callback for better performance
clientside_callback(
    """
    function(themeData) {
        const theme = themeData || 'light';
        return theme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine';
    }
    """,
    Output({"type": "stepper-data-grid", "index": MATCH}, "className"),
    Input("theme-store", "data"),
    prevent_initial_call=False,
)
