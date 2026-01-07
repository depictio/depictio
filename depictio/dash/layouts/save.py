import json

import dash
from dash import ALL, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_get_dashboard,
    api_call_save_dashboard,
)


def validate_and_clean_orphaned_layouts(stored_layout_data, stored_metadata):
    """
    Validate and clean orphaned layout entries that don't have corresponding metadata entries.

    Args:
        stored_layout_data (list): List of layout entries with 'i' field containing 'box-{index}'
        stored_metadata (list): List of metadata entries with 'index' field

    Returns:
        list: Cleaned layout data with orphaned entries removed
    """
    if not stored_layout_data or not stored_metadata:
        return stored_layout_data or []

    # Extract valid component IDs from metadata
    valid_component_ids = {
        str(meta.get("index")) for meta in stored_metadata if meta.get("index") is not None
    }
    logger.info(f"🔍 LAYOUT VALIDATION - Valid component IDs from metadata: {valid_component_ids}")

    cleaned_layout_data = []
    orphaned_layouts = []

    for layout_entry in stored_layout_data:
        layout_id = layout_entry.get("i", "")

        # Extract component ID from layout ID (format: 'box-{index}')
        if layout_id.startswith("box-"):
            component_id = layout_id[4:]  # Remove 'box-' prefix

            if component_id in valid_component_ids:
                cleaned_layout_data.append(layout_entry)
            else:
                orphaned_layouts.append(layout_entry)
                logger.info(
                    f"🗑️ SAVE - Removing orphaned layout: {layout_id} (no matching metadata)"
                )
        else:
            # Keep entries that don't follow the 'box-{index}' pattern for safety
            cleaned_layout_data.append(layout_entry)
            logger.warning(
                f"⚠️ LAYOUT VALIDATION - Layout entry with unexpected ID format: {layout_id}"
            )

    if orphaned_layouts:
        logger.info(
            f"🧹 LAYOUT VALIDATION - Removed {len(orphaned_layouts)} orphaned layout entries"
        )
        logger.info(f"🧹 LAYOUT VALIDATION - Kept {len(cleaned_layout_data)} valid layout entries")
    else:
        logger.info(
            f"✅ LAYOUT VALIDATION - No orphaned layouts found, all {len(cleaned_layout_data)} entries are valid"
        )

    return cleaned_layout_data


def register_callbacks_save_lite(app):
    """
    Minimal save callback - captures component metadata only.

    Simplified architecture:
    - Listens to component metadata stores
    - Fetches current dashboard from DB
    - Updates metadata field only
    - Validates with Pydantic DashboardData model
    - Saves to DB without enrichment

    Skipped features (for simplicity):
    - Layout positions (no draggable state)
    - Notes content (no notes-editor-store)
    - Interactive component values
    - Complex metadata deduplication
    - Edit mode state tracking
    """

    @app.callback(
        Output("notification-container", "sendNotifications"),
        Input("save-button-dashboard", "n_clicks"),
        State("url", "pathname"),
        State("local-store", "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "left-panel-grid", "index": ALL}, "itemLayout"),
        State({"type": "right-panel-grid", "index": ALL}, "itemLayout"),
        prevent_initial_call=True,
    )
    def save_dashboard_minimal(
        n_clicks,
        pathname,
        local_store,
        stored_metadata,
        interactive_metadata,
        left_panel_layouts,
        right_panel_layouts,
    ):
        """Minimal save: Capture component metadata → Build DashboardData → Save to DB"""
        from depictio.models.models.dashboards import DashboardData

        logger.info("=== MINIMAL SAVE CALLBACK TRIGGERED ===")

        # 1. Validate trigger
        if not n_clicks or not local_store:
            logger.warning("Save callback: No click or no auth token")
            raise dash.exceptions.PreventUpdate

        # Skip if on stepper page
        if pathname and "/component/add/" in pathname:
            logger.info("Skipping save on stepper page")
            raise dash.exceptions.PreventUpdate

        # 2. Extract dashboard_id and token
        # Handle both /dashboard/{id} and /dashboard/{id}/edit paths
        path_parts = pathname.split("/")
        if path_parts[-1] == "edit":
            dashboard_id = path_parts[-2]  # Get ID before /edit
        else:
            dashboard_id = path_parts[-1]  # Get last part
        TOKEN = local_store["access_token"]

        logger.info(f"Saving dashboard: {dashboard_id}")
        logger.info(f"Captured {len(stored_metadata)} component metadata entries")
        logger.info(f"Captured {len(interactive_metadata)} interactive metadata entries")

        # DEBUG: Log what's in each metadata source
        logger.info("📊 STORED METADATA (from stored-metadata-component):")
        for idx, meta in enumerate(stored_metadata):
            logger.info(f"  [{idx}] index={meta.get('index')}, type={meta.get('component_type')}")

        logger.info("📊 INTERACTIVE METADATA (from interactive-stored-metadata):")
        for idx, meta in enumerate(interactive_metadata):
            logger.info(f"  [{idx}] index={meta.get('index')}, type={meta.get('component_type')}")

        # 3. Fetch current dashboard from DB (baseline)
        dashboard_dict = api_call_get_dashboard(dashboard_id, TOKEN)
        if not dashboard_dict:
            logger.error(f"Failed to fetch dashboard {dashboard_id}")
            raise dash.exceptions.PreventUpdate

        # 4. Update with captured state (metadata + dual-panel layouts)
        # Merge both metadata lists (general components + interactive components)
        all_metadata = stored_metadata + interactive_metadata
        logger.info(f"Total metadata entries to save: {len(all_metadata)}")

        # DEBUG: Log interactive metadata to understand why left panel is empty
        logger.info(f"📊 Interactive metadata count: {len(interactive_metadata)}")
        for idx, meta in enumerate(interactive_metadata):
            logger.info(
                f"  Interactive [{idx}]: index={meta.get('index')}, "
                f"type={meta.get('component_type')}, "
                f"interactive_type={meta.get('interactive_component_type')}"
            )

        dashboard_dict["stored_metadata"] = all_metadata

        # RECALCULATE positions in Python to ensure correct IDs and dimensions
        # This avoids relying on DashGridLayout's internal state which may be stale/incorrect
        from depictio.dash.layouts.draggable import (
            calculate_left_panel_positions,
            calculate_right_panel_positions,
            separate_components_by_panel,
        )

        # Separate components by panel
        interactive_components, right_panel_components = separate_components_by_panel(all_metadata)

        # Extract layout data from pattern-matched grids with proper validation
        # Pattern-matched ALL returns list of lists: [[layout_data], ...]
        left_panel_saved_data = None
        if left_panel_layouts and len(left_panel_layouts) > 0 and left_panel_layouts[0]:
            left_panel_saved_data = left_panel_layouts[0]
            logger.info(f"📐 LEFT: Captured {len(left_panel_saved_data)} layout items from grid")
        else:
            logger.warning("⚠️ LEFT: No layout data captured from grid - using metadata only")

        right_panel_saved_data = None
        if right_panel_layouts and len(right_panel_layouts) > 0 and right_panel_layouts[0]:
            right_panel_saved_data = right_panel_layouts[0]
            logger.info(f"📐 RIGHT: Captured {len(right_panel_saved_data)} layout items from grid")
        else:
            logger.warning("⚠️ RIGHT: No layout data captured from grid - using metadata only")

        # Recalculate fresh layout positions using current metadata
        # Pass existing saved data so we preserve user's drag positions (x/y)
        # These functions PRESERVE user positions when saved_layout_data is provided
        left_panel_layout = calculate_left_panel_positions(
            interactive_components,
            saved_layout_data=left_panel_saved_data,
        )
        right_panel_layout = calculate_right_panel_positions(
            right_panel_components,
            saved_layout_data=right_panel_saved_data,
        )

        logger.info(f"Recalculated left panel layout: {len(left_panel_layout)} items")
        logger.info(f"Recalculated right panel layout: {len(right_panel_layout)} items")

        dashboard_dict["left_panel_layout_data"] = left_panel_layout
        dashboard_dict["right_panel_layout_data"] = right_panel_layout

        # 5. Validate with Pydantic model
        try:
            DashboardData.from_mongo(dashboard_dict)
            logger.info("✅ DashboardData Pydantic validation passed")
        except Exception as e:
            logger.error(f"❌ Pydantic validation failed: {e}")
            raise dash.exceptions.PreventUpdate

        # 6. LOG what would be saved (API call disabled for debugging)
        logger.info("=" * 80)
        logger.info("📝 SAVE DATA PREVIEW (API CALL DISABLED)")
        logger.info("=" * 80)
        logger.info(f"Dashboard ID: {dashboard_id}")
        logger.info(f"Total metadata entries: {len(all_metadata)}")
        logger.info(f"Left panel layout items: {len(left_panel_layout)}")
        logger.info(f"Right panel layout items: {len(right_panel_layout)}")
        logger.info("")
        logger.info("📊 LEFT PANEL LAYOUT DATA:")
        logger.info(json.dumps(left_panel_layout, indent=2))
        logger.info("")
        logger.info("📊 RIGHT PANEL LAYOUT DATA:")
        logger.info(json.dumps(right_panel_layout, indent=2))
        logger.info("")
        logger.info("📊 METADATA SUMMARY:")
        for idx, meta in enumerate(all_metadata):
            logger.info(
                f"  [{idx}] Component: {meta.get('index')}, "
                f"Type: {meta.get('component_type')}, "
                f"Title: {meta.get('title', 'N/A')}"
            )
        logger.info("=" * 80)

        # Save to database via API
        logger.info("💾 SAVE: Calling API to persist dashboard data")
        success = api_call_save_dashboard(
            dashboard_id,
            dashboard_dict,
            TOKEN,
            enrich=False,  # Fast save, no enrichment needed
        )

        if success:
            logger.info(f"✅ SAVE: Successfully saved dashboard {dashboard_id}")
        else:
            logger.error(f"❌ SAVE: Failed to save dashboard {dashboard_id}")

        # Return notification to user
        from dash_iconify import DashIconify

        if success:
            return [
                {
                    "id": "save-success",
                    "title": "Dashboard Saved",
                    "message": f"Successfully saved {len(all_metadata)} components and layout positions",
                    "color": "teal",
                    "icon": DashIconify(icon="mdi:check-circle"),
                    "autoClose": 3000,
                }
            ]
        else:
            return [
                {
                    "id": "save-error",
                    "title": "Save Failed",
                    "message": "Failed to save dashboard. Please try again.",
                    "color": "red",
                    "icon": DashIconify(icon="mdi:alert-circle"),
                    "autoClose": 5000,
                }
            ]


# ==============================================================================
# BACKUP: OLD COMPLEX SAVE CALLBACK (884 lines)
# Replaced with register_callbacks_save_lite() above
# Preserved for reference - includes complex deduplication, interactive tracking
# ==============================================================================
"""
def register_callbacks_save(app):
    # AUTO-SAVE DISABLED: All inputs except save-button-dashboard converted to State
    # to disable automatic saves on component/content changes.
    # Only manual save button click triggers save operation.
    # To re-enable auto-save for specific triggers, convert State back to Input.
    @app.callback(
        inputs=[
            Input("save-button-dashboard", "n_clicks"),  # ONLY trigger for save
            State(
                "draggable", "currentLayout"
            ),  # Changed from Input to State - avoids error when draggable doesn't exist on stepper page
            State(
                {
                    "type": "stored-metadata-component",
                    "index": ALL,
                },
                "data",
            ),  # Changed from Input to State - disable auto-save on metadata changes
            State("stored-edit-dashboard-mode-button", "data"),
            State(
                "unified-edit-mode-button", "checked"
            ),  # Changed from Input to State - avoids error when button doesn't exist on stepper page
            State("stored-add-button", "data"),
            State({"type": "interactive-component-value", "index": ALL}, "value"),
            State(
                {"type": "text-store", "index": ALL}, "data"
            ),  # Changed from Input - disable auto-save on text changes
            State(
                "notes-editor-store", "data"
            ),  # Changed from Input - disable auto-save on notes changes
            State("url", "pathname"),
            State("local-store", "data"),
            State(
                {
                    "type": "btn-done",
                    "index": ALL,
                },
                "n_clicks",
            ),  # Changed from Input - disable auto-save on component edit done
            State(
                {
                    "type": "btn-done-edit",
                    "index": ALL,
                },
                "n_clicks",
            ),  # Changed from Input - disable auto-save on edit mode done
            State(
                {
                    "type": "duplicate-box-button",
                    "index": ALL,
                },
                "n_clicks",
            ),  # Changed from Input - disable auto-save on duplicate
            State(
                {"type": "remove-box-button", "index": ALL},
                "n_clicks",
            ),  # Changed from Input - disable auto-save on remove
            State(
                "remove-all-components-button", "n_clicks"
            ),  # Changed from Input - disable auto-save on remove all
            State(
                {"type": "interactive-component-value", "index": ALL}, "value"
            ),  # Duplicate State kept for compatibility
            State(
                "interactive-values-store", "data"
            ),  # Changed from Input - disable auto-save on filter changes
            State(
                "apply-filters-button", "n_clicks"
            ),  # Changed from Input - disable auto-save on apply filters
            State("live-interactivity-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def save_data_dashboard(
        n_clicks,
        stored_layout_data,
        stored_metadata,
        edit_dashboard_mode_button,
        unified_edit_mode_button_checked,
        add_button,
        interactive_component_values,
        text_store_data,
        notes_data,
        pathname,
        local_store,
        n_clicks_done,
        n_clicks_done_edit,
        n_clicks_duplicate,
        n_clicks_remove,
        n_clicks_remove_all,
        interactive_component_values_all,
        interactive_values_store,
        n_clicks_apply,
        live_interactivity_on,
    ):
        logger.info("=== SAVE CALLBACK TRIGGERED ===")
        logger.info(f"CTX TRIGGERED: {dash.ctx.triggered_id}")
        logger.info("Saving dashboard data...")
        logger.info(
            f"📊 SAVE DEBUG - Raw stored_metadata count: {len(stored_metadata) if stored_metadata else 0}"
        )

        # GUARD: Skip if we're on the stepper page (no draggable component there)
        if pathname and "/component/add/" in pathname:
            logger.info("🚫 SAVE CALLBACK - Skipping on stepper page (no draggable component)")
            raise dash.exceptions.PreventUpdate

        # Log the first few raw metadata entries for debugging
        # if stored_metadata:
        #     for i, elem in enumerate(stored_metadata[:3]):  # Only first 3 to avoid spam
        #         logger.info(
        #             f"📊 SAVE DEBUG - Raw metadata {i}: keys={list(elem.keys()) if elem else 'None'}"
        #         )
        #         if elem:
        #             logger.info(
        #                 f"📊 SAVE DEBUG - Raw metadata {i}: mode={elem.get('mode', 'MISSING')}"
        #             )
        #             logger.info(
        #                 f"📊 SAVE DEBUG - Raw metadata {i}: code_content={'YES' if elem.get('code_content') else 'NO'} ({len(elem.get('code_content', '')) if elem.get('code_content') else 0} chars)"
        #             )
        #             logger.info(
        #                 f"📊 SAVE DEBUG - Raw metadata {i}: dict_kwargs={elem.get('dict_kwargs', 'MISSING')}"
        #             )

        stored_metadata_for_logging = [
            {
                "index": elem.get("index"),
                "component_type": elem.get("component_type"),
                "wf_id": elem.get("workflow_id"),
                "dc_id": elem.get("dc_id"),
            }
            for elem in stored_metadata
        ]
        logger.info(f"Stored metadata for logging: {stored_metadata_for_logging}")
        # logger.info(f"Stored complete metadata: {stored_metadata}")

        # Early return if user is not logged in
        if not local_store:
            logger.warning("User not logged in.")
            raise dash.exceptions.PreventUpdate

        # Validate user authentication using local-store
        from depictio.models.models.users import UserContext

        TOKEN = local_store["access_token"]
        # Fetch user data using API call (with caching)
        logger.info("🔄 Save: Fetching user data from API using local-store token")
        current_user_api = api_call_fetch_user_from_token(TOKEN)
        if not current_user_api:
            logger.warning("User not found.")
            raise dash.exceptions.PreventUpdate
        # Create UserContext from API response
        current_user = UserContext(
            id=str(current_user_api.id),
            email=current_user_api.email,
            is_admin=current_user_api.is_admin,
            is_anonymous=getattr(current_user_api, "is_anonymous", False),
        )

        # Extract dashboard ID from pathname
        dashboard_id = pathname.split("/")[-1]

        # Fetch dashboard data using API call with proper timeout
        dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
        if not dashboard_data:
            logger.error(f"Failed to fetch dashboard data for {dashboard_id}")
            raise dash.exceptions.PreventUpdate

        # Check user permissions
        owner_ids = [str(e["id"]) for e in dashboard_data.get("permissions", {}).get("owners", [])]
        if str(current_user.id) not in owner_ids:
            logger.warning("User does not have permission to edit & save this dashboard.")
            raise dash.exceptions.PreventUpdate

        # Determine trigger context
        from dash import ctx

        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"Triggered ID: {triggered_id}")

        # Define save-triggering conditions
        save_triggers = [
            "save-button-dashboard",
            "btn-done",
            "btn-done-edit",
            "duplicate-box-button",
            "remove-box-button",
            "remove-all-components-button",
            "edit-components-mode-button",
            "unified-edit-mode-button",  # Add edit mode button to save triggers
            "draggable",
            "text-store",
            "notes-editor-store",
            "interactive-component-value",
            "apply-filters-button",
        ]

        # special_save_triggers = [
        #     "interactive-component-value",
        #     "apply-filters-button",
        # ]

        # Check if save should be triggered - modified to allow edit mode state persistence
        if not any(trigger in triggered_id for trigger in save_triggers):
            raise dash.exceptions.PreventUpdate

        # PERFORMANCE OPTIMIZATION: Guard against spurious saves during component initialization
        # Buttons fire with n_clicks=0/None when mounting during progressive loading
        # This prevents unnecessary save operations that add 2+ second delays on page load
        button_triggers = [
            "save-button-dashboard",
            "btn-done",
            "btn-done-edit",
            "duplicate-box-button",
            "remove-box-button",
            "remove-all-components-button",
            "apply-filters-button",
        ]

        # Check if trigger is a button-based save
        is_button_trigger = any(trigger in triggered_id for trigger in button_triggers)
        if is_button_trigger:
            # Get the actual value from the triggered input
            triggered_value = ctx.triggered[0]["value"]

            # Skip if button hasn't been actually clicked (n_clicks=0 or None during mounting)
            if triggered_value is None or triggered_value == 0:
                logger.info(
                    f"⏸️ SAVE CALLBACK SKIPPED: {triggered_id} not actually clicked "
                    f"(n_clicks={triggered_value}, likely component mounting during progressive load)"
                )
                raise dash.exceptions.PreventUpdate

        # Check if trigger is interactive component value change
        # If so, check if live interactivity is enabled
        triggered_by_interactive = "interactive-component-value" in triggered_id
        # if triggered_by_interactive and not live_interactivity_on:
        #     logger.info(
        #         "⏸️ NON-LIVE MODE: Interactive component value changed but live interactivity is OFF - ignoring save"
        #     )
        #     raise dash.exceptions.PreventUpdate

        # Check if trigger is apply filters button
        if "apply-filters-button" in triggered_id and not live_interactivity_on:
            logger.info("NON-LIVE MODE: Apply filters button clicked > saving changes")

        # Original logic blocked saving when edit mode was OFF - removed to allow persistence

        # Deduplicate and clean metadata - prioritize complete metadata entries
        unique_metadata = []
        seen_indexes = set()
        indexed_metadata = {}

        # First pass: collect all metadata entries by index
        for elem in stored_metadata:
            index = elem["index"]
            if index not in indexed_metadata:
                indexed_metadata[index] = []
            indexed_metadata[index].append(elem)

        # Second pass: for each index, select the most complete metadata entry
        for index, metadata_list in indexed_metadata.items():
            if len(metadata_list) == 1:
                # Single entry - use it
                best_metadata = metadata_list[0]
            else:
                # Multiple entries - prioritize by completeness
                # logger.info(
                #     f"📊 SAVE DEBUG - Found {len(metadata_list)} duplicate entries for index {index}"
                # )

                # Score each metadata entry by completeness
                def score_metadata(meta):
                    score = 0
                    # Highest priority: non-empty dict_kwargs (this is the critical field we need to preserve)
                    dict_kwargs = meta.get("dict_kwargs", {})
                    if isinstance(dict_kwargs, dict) and len(dict_kwargs) > 0:
                        score += 1000  # Much higher weight for dict_kwargs
                        # Bonus points for specific important fields in dict_kwargs
                        important_fields = ["x", "y", "color", "size", "hover_data"]
                        for field in important_fields:
                            if field in dict_kwargs and dict_kwargs[field]:
                                score += 10

                    # Medium priority: component configuration fields
                    if meta.get("wf_id"):
                        score += 100
                    if meta.get("dc_id"):
                        score += 100
                    if meta.get("visu_type"):
                        score += 50
                    if meta.get("component_type"):
                        score += 25

                    # Low priority: metadata fields
                    if meta.get("last_updated"):
                        score += 1
                    if meta.get("title"):
                        score += 5

                    return score

                # Log all candidates with their scores for debugging
                candidate_scores = []
                for i, meta in enumerate(metadata_list):
                    score = score_metadata(meta)
                    candidate_scores.append((score, i, meta))
                    # logger.info(
                    #     f"📊 SAVE DEBUG - Candidate {i} for index {index}: score={score}, dict_kwargs={meta.get('dict_kwargs', 'MISSING')}"
                    # )

                # Select the metadata with the highest completeness score
                best_metadata = max(metadata_list, key=score_metadata)
                # best_score = score_metadata(best_metadata)

                # logger.info(
                #     f"📊 SAVE DEBUG - SELECTED metadata with score {best_score} for index {index}"
                # )
                # logger.info(
                #     f"📊 SAVE DEBUG - SELECTED metadata dict_kwargs: {best_metadata.get('dict_kwargs', 'MISSING')}"
                # )
                # logger.info(
                #     f"📊 SAVE DEBUG - SELECTED metadata has {len(best_metadata.get('dict_kwargs', {}))} parameters"
                # )

            # Safety check: ensure we're not accidentally selecting empty metadata when better options exist
            if len(metadata_list) > 1:
                dict_kwargs = best_metadata.get("dict_kwargs", {})
                if not isinstance(dict_kwargs, dict) or len(dict_kwargs) == 0:
                    # Double-check if any other candidate has non-empty dict_kwargs
                    alternatives = [
                        meta
                        for meta in metadata_list
                        if meta.get("dict_kwargs") and len(meta.get("dict_kwargs", {})) > 0
                    ]
                    if alternatives:
                        logger.warning(
                            f"📊 SAVE DEBUG - SAFETY CHECK: Found {len(alternatives)} alternatives with non-empty dict_kwargs for index {index}"
                        )
                        # Use the first alternative with non-empty dict_kwargs
                        best_metadata = alternatives[0]
                        logger.warning(
                            f"📊 SAVE DEBUG - SAFETY CHECK: Switched to alternative with dict_kwargs: {best_metadata.get('dict_kwargs', 'MISSING')}"
                        )

            unique_metadata.append(best_metadata)
            seen_indexes.add(index)

        # logger.info(f"📊 SAVE DEBUG - Unique metadata: {unique_metadata}")

        # Summary logging of deduplication results
        # logger.info(
        #     f"📊 SAVE DEBUG - Deduplication complete: {len(unique_metadata)} unique components"
        # )
        # components_with_dict_kwargs = sum(
        #     1
        #     for meta in unique_metadata
        #     if meta.get("dict_kwargs") and len(meta.get("dict_kwargs", {})) > 0
        # )
        # # logger.info(
        # #     f"📊 SAVE DEBUG - Components with non-empty dict_kwargs: {components_with_dict_kwargs}/{len(unique_metadata)}"
        # # )

        # # Log any components that ended up with empty dict_kwargs for investigation
        # empty_dict_kwargs_components = [
        #     meta
        #     for meta in unique_metadata
        #     if not meta.get("dict_kwargs") or len(meta.get("dict_kwargs", {})) == 0
        # ]
        # if empty_dict_kwargs_components:
        #     logger.warning(
        #         f"📊 SAVE DEBUG - WARNING: {len(empty_dict_kwargs_components)} components have empty dict_kwargs:"
        #     )
        #     for meta in empty_dict_kwargs_components:
        #         logger.warning(
        #             f"📊 SAVE DEBUG - Empty dict_kwargs component: index={meta.get('index')}, type={meta.get('component_type')}"
        #         )

        # logger.info(f"Unique metadata: {unique_metadata}")
        # logger.info(f"seen_indexes: {seen_indexes}")

        # CRITICAL FIX: Normalize all layout IDs to ensure box- prefix before processing
        # This prevents layout/metadata ID mismatches that cause component position resets
        if stored_layout_data:
            for layout in stored_layout_data:
                layout_id = layout.get("i", "")
                if layout_id and not layout_id.startswith("box-"):
                    corrected_id = f"box-{layout_id}"
                    layout["i"] = corrected_id
                    logger.info(f"🔧 NORMALIZED layout ID: {layout_id} → {corrected_id}")

        # Remove child components for edit mode
        if "btn-done-edit" in triggered_id:
            logger.info("=== BTN-DONE-EDIT TRIGGERED - PROCESSING EDIT MODE ===")
            logger.info(f"Unique metadata BEFORE filtering: {len(unique_metadata)} items")
            for i, elem in enumerate(unique_metadata):
                logger.info(
                    f"Item {i}: index={elem.get('index')}, parent_index={elem.get('parent_index')}, component_type={elem.get('component_type')}"
                )

            # In edit mode, we need to:
            # 1. Find the edited component (has parent_index)
            # 2. Remove the original component (with index = parent_index)
            # 3. Add the edited component with parent_index removed
            original_count = len(unique_metadata)

            # Find the component being edited (it will have parent_index set)
            edited_components = [
                elem for elem in unique_metadata if elem.get("parent_index") is not None
            ]
            non_edited_components = [
                elem for elem in unique_metadata if elem.get("parent_index") is None
            ]

            logger.info(
                f"Found {len(edited_components)} edited components and {len(non_edited_components)} non-edited components"
            )

            # Log all component indices for debugging
            logger.info("=== ALL COMPONENTS BEFORE PROCESSING ===")
            for i, comp in enumerate(unique_metadata):
                logger.info(
                    f"Component {i}: index={comp.get('index')}, parent_index={comp.get('parent_index')}, type={comp.get('component_type')}, title={comp.get('title')}"
                )

            logger.info("=== EDITED COMPONENTS ===")
            for i, comp in enumerate(edited_components):
                logger.info(
                    f"Edited {i}: index={comp.get('index')}, parent_index={comp.get('parent_index')}, type={comp.get('component_type')}, title={comp.get('title')}"
                )

            logger.info("=== NON-EDITED COMPONENTS ===")
            for i, comp in enumerate(non_edited_components):
                logger.info(
                    f"Non-edited {i}: index={comp.get('index')}, parent_index={comp.get('parent_index')}, type={comp.get('component_type')}, title={comp.get('title')}"
                )

            # Process edited components
            for component in edited_components:
                parent_index = component.get("parent_index")
                component_index = component.get("index")

                logger.info(
                    f"Processing edited component: {component_index} (parent_index: {parent_index})"
                )
                logger.info(
                    f"Component data: type={component.get('component_type')}, title={component.get('title')}, aggregation={component.get('aggregation')}"
                )

                # Find and log the original components that will be removed (both original and temp)
                temp_parent_index = f"{parent_index}-tmp"
                original_component = None
                temp_component = None

                for elem in non_edited_components:
                    if elem.get("index") == parent_index:
                        original_component = elem
                    elif elem.get("index") == temp_parent_index:
                        temp_component = elem

                components_to_remove = []
                if original_component:
                    components_to_remove.append(f"original ({original_component.get('index')})")
                if temp_component:
                    components_to_remove.append(f"temp ({temp_component.get('index')})")

                if components_to_remove:
                    logger.info(f"Found components to remove: {', '.join(components_to_remove)}")
                else:
                    logger.warning(
                        f"Could not find any components to remove with parent_index {parent_index}"
                    )

                # Remove the original component and its temp component that were being edited
                temp_parent_index = f"{parent_index}-tmp"
                original_count = len(non_edited_components)
                non_edited_components = [
                    elem
                    for elem in non_edited_components
                    if elem.get("index") not in [parent_index, temp_parent_index]
                ]
                removed_count = original_count - len(non_edited_components)
                logger.info(
                    f"Removed {removed_count} components with indices {parent_index} and {temp_parent_index}"
                )

                # Update the edited component's index to be the same as the original
                component["index"] = parent_index
                logger.info(
                    f"Updated edited component index from {component_index} to {parent_index}"
                )

                # Clear parent_index since this is now the final component (no longer a child)
                component["parent_index"] = None
                logger.info(f"Cleared parent_index for final component {parent_index}")

                # CRITICAL FIX: Update layout IDs to match the updated component index
                # This prevents layout destruction when dashboard reloads
                # Handle BOTH correct format (box-{uuid}) and malformed format ({uuid})
                if stored_layout_data:
                    # Try both formats: with and without 'box-' prefix
                    old_layout_ids = [
                        f"box-{component_index}",  # Correct format
                        component_index,  # Malformed format (missing box- prefix)
                    ]
                    new_layout_id = f"box-{parent_index}"  # Always use correct format

                    layout_found = False
                    for layout in stored_layout_data:
                        layout_id = layout.get("i", "")
                        # Check if this layout belongs to the edited component
                        if layout_id in old_layout_ids:
                            old_id = layout_id
                            layout["i"] = new_layout_id
                            layout_found = True
                            logger.info(
                                f"🔧 LAYOUT FIX - Updated layout ID: {old_id} → {new_layout_id}"
                            )
                            # Warn if we found a malformed layout ID
                            if not old_id.startswith("box-"):
                                logger.warning(
                                    f"⚠️ LAYOUT FIX - Corrected malformed layout ID (missing 'box-' prefix): {old_id}"
                                )
                            break  # Only one layout per component

                    if not layout_found:
                        logger.warning(
                            f"⚠️ LAYOUT FIX - Could not find layout for edited component {component_index} (searched for: {old_layout_ids})"
                        )
                        logger.warning(
                            f"⚠️ LAYOUT FIX - Available layout IDs: {[layout_entry.get('i') for layout_entry in stored_layout_data]}"
                        )

                logger.info(
                    f"Updated component data: type={component.get('component_type')}, title={component.get('title')}, aggregation={component.get('aggregation')}"
                )
                # if "parent_index" in component:
                #     del component["parent_index"]
                #     logger.info(f"Removed parent_index from component {parent_index}")

            # Combine all components back together
            unique_metadata = non_edited_components + edited_components

            logger.info(
                f"Unique metadata AFTER processing: {len(unique_metadata)} items (removed {original_count - len(unique_metadata)} items)"
            )
            # logger.debug("=== FINAL COMPONENTS AFTER PROCESSING ===")
            # for i, elem in enumerate(unique_metadata):
            #     logger.debug(
            #         f"Final item {i}: index={elem.get('index')}, parent_index={elem.get('parent_index')}, component_type={elem.get('component_type')}, title={elem.get('title')}, aggregation={elem.get('aggregation')}"
            #     )
            # logger.debug("=== BTN-DONE-EDIT PROCESSING COMPLETE ===")

        # Use draggable layout metadata if triggered by draggable
        # if "draggable" in triggered_id:
        #     unique_metadata = dashboard_data.get("stored_metadata", unique_metadata)
        # logger.info(f"Unique metadata after using draggable layout metadata: {unique_metadata}")

        # Debug logging for layout data - COMPREHENSIVE TRACKING
        # logger.debug("=" * 80)
        # logger.debug("🔍 SAVE DEBUG - LAYOUT DATA PROCESSING START")
        # logger.debug("=" * 80)
        # logger.debug(f"🔍 SAVE DEBUG - stored_layout_data received: {stored_layout_data}")
        # logger.debug(f"🔍 SAVE DEBUG - type: {type(stored_layout_data)}")
        # logger.debug(f"🔍 SAVE DEBUG - triggered_id: {triggered_id}")

        # Log the complete callback context for debugging
        from dash import ctx

        # logger.info(f"🔍 SAVE DEBUG - callback context triggered: {ctx.triggered}")
        # logger.info(f"🔍 SAVE DEBUG - callback inputs_list: {ctx.inputs_list}")

        # Identify which callback triggered this save
        # if "duplicate-box-button" in triggered_id:
        #     logger.info("🎯 SAVE DEBUG - TRIGGERED BY: DUPLICATE CALLBACK")
        # elif "draggable" in triggered_id:
        #     logger.info("🎯 SAVE DEBUG - TRIGGERED BY: DRAGGABLE/GRID LAYOUT CALLBACK")
        # elif "save-button-dashboard" in triggered_id:
        #     logger.info("🎯 SAVE DEBUG - TRIGGERED BY: SAVE BUTTON")
        # else:
        #     logger.info(f"🎯 SAVE DEBUG - TRIGGERED BY: OTHER ({triggered_id})")

        # Log current layout data details
        # if stored_layout_data:
        #     logger.info(f"🔍 SAVE DEBUG - layout data length: {len(stored_layout_data)}")
        #     for i, layout_item in enumerate(stored_layout_data):
        #         logger.info(f"🔍 SAVE DEBUG - layout item {i}: {layout_item}")
        # else:
        #     logger.info("🔍 SAVE DEBUG - stored_layout_data is empty or None")

        # Log existing dashboard layout data for comparison
        # existing_dashboard_layout = dashboard_data.get("stored_layout_data", [])
        # logger.info(f"🔍 SAVE DEBUG - existing dashboard layout: {existing_dashboard_layout}")
        # if existing_dashboard_layout:
        #     logger.info(f"🔍 SAVE DEBUG - existing layout length: {len(existing_dashboard_layout)}")
        #     for i, layout_item in enumerate(existing_dashboard_layout):
        #         logger.info(f"🔍 SAVE DEBUG - existing layout item {i}: {layout_item}")

        # Ensure layout data is in list format - no backward compatibility
        if stored_layout_data is None:
            stored_layout_data = []
            # logger.info("⚠️ SAVE DEBUG - stored_layout_data was None, set to empty list")

        # If layout data is empty but we have existing dashboard data, preserve the existing layout
        if not stored_layout_data and dashboard_data and dashboard_data.get("stored_layout_data"):
            existing_layout = dashboard_data.get("stored_layout_data")
            if isinstance(existing_layout, list):
                stored_layout_data = existing_layout
                # logger.info(f"🔄 SAVE DEBUG - preserved existing layout: {stored_layout_data}")
                # logger.info(f"🔄 SAVE DEBUG - preserved layout length: {len(stored_layout_data)}")
                # for i, layout_item in enumerate(stored_layout_data):
                #     logger.info(f"🔄 SAVE DEBUG - preserved layout item {i}: {layout_item}")
            else:
                logger.warning(
                    f"⚠️ SAVE DEBUG - existing layout is not a list: {type(existing_layout)}"
                )

        # Validate and clean orphaned layouts before saving
        # logger.debug("=" * 80)
        # logger.debug("🧹 LAYOUT VALIDATION - CLEANING ORPHANED LAYOUTS")
        # logger.debug("=" * 80)
        # logger.debug(
        #     f"🔍 LAYOUT VALIDATION - Before cleaning: {len(stored_layout_data) if stored_layout_data else 0} layout entries"
        # )
        # logger.info(f"🔍 LAYOUT VALIDATION - Available metadata: {len(unique_metadata)} entries")

        stored_layout_data = validate_and_clean_orphaned_layouts(
            stored_layout_data, unique_metadata
        )

        # logger.info(
        #     f"🔍 LAYOUT VALIDATION - After cleaning: {len(stored_layout_data) if stored_layout_data else 0} layout entries"
        # )
        # logger.info("=" * 80)

        updated_dashboard_data = {
            "stored_metadata": unique_metadata,
            "stored_layout_data": stored_layout_data,
            "stored_edit_dashboard_mode_button": edit_dashboard_mode_button,
            "stored_add_button": add_button,
            "buttons_data": {
                "unified_edit_mode": unified_edit_mode_button_checked,
                "add_components_button": add_button,
            },
            "notes_content": notes_data if notes_data else "",
            "last_saved_ts": str(datetime.now()),
        }

        # Log final layout data being prepared for database
        # logger.debug("=" * 80)
        # logger.debug("🔍 SAVE DEBUG - FINAL DATA PREPARATION")
        # logger.debug("=" * 80)
        # final_layout_data = updated_dashboard_data["stored_layout_data"]
        # logger.debug(f"🔍 SAVE DEBUG - final layout data to save: {final_layout_data}")
        # logger.debug(f"🔍 SAVE DEBUG - final layout data type: {type(final_layout_data)}")
        # if final_layout_data:
        #     logger.debug(f"🔍 SAVE DEBUG - final layout data length: {len(final_layout_data)}")
        #     for i, layout_item in enumerate(final_layout_data):
        #         logger.debug(f"🔍 SAVE DEBUG - final layout item {i}: {layout_item}")
        # else:
        #     logger.debug("🔍 SAVE DEBUG - final layout data is empty")

        # final_metadata = updated_dashboard_data["stored_metadata"]
        # logger.debug(f"🔍 SAVE DEBUG - final metadata count: {len(final_metadata)}")
        # for i, meta_item in enumerate(final_metadata):
        #     logger.debug(
        #         f"🔍 SAVE DEBUG - final metadata item {i}: index={meta_item.get('index')}, type={meta_item.get('component_type')}, title={meta_item.get('title')}"
        #     )

        # Apply interactive component values to metadata when Apply button is clicked or live mode is active
        # This uses the interactive_component_values parameter that's automatically collected from all components
        if triggered_by_interactive:
            # if ("apply-filters-button" in triggered_id and not live_interactivity_on) or (
            #     triggered_by_interactive and live_interactivity_on
            # ):
            logger.info("🔄 UPDATING METADATA WITH CURRENT INTERACTIVE COMPONENT VALUES")

            # Get interactive components from metadata to match with values
            interactive_metadata = [
                meta for meta in unique_metadata if meta.get("component_type") == "interactive"
            ]

            if interactive_component_values and interactive_metadata:
                logger.info(
                    f"🔄 Found {len(interactive_component_values)} values and {len(interactive_metadata)} interactive components"
                )

                # Match values to metadata by position (they should be in the same order)
                for i, (value, meta) in enumerate(
                    zip(interactive_component_values, interactive_metadata)
                ):
                    old_value = meta.get("value")
                    component_index = meta.get("index")

                    # Update both value and corrected_value in metadata
                    meta["value"] = value
                    meta["corrected_value"] = value

                    logger.info(
                        f"🔄 Updated metadata for component {component_index} (position {i}): {old_value} -> {value}"
                    )

                # Update the stored_metadata in the save data to include updated values
                updated_dashboard_data["stored_metadata"] = unique_metadata
            else:
                logger.warning(
                    f"🔄 Mismatch: {len(interactive_component_values or [])} values vs {len(interactive_metadata)} components!"
                )

        # Update dashboard data
        dashboard_data.update(updated_dashboard_data)

        # Log the complete dashboard data being sent to API
        # logger.debug("=" * 80)
        # logger.debug("🔍 SAVE DEBUG - DATABASE SAVE PREPARATION")
        # logger.debug("=" * 80)
        # db_layout_data = dashboard_data.get("stored_layout_data", [])
        # logger.debug(f"🔍 SAVE DEBUG - database layout data: {db_layout_data}")
        # logger.debug(
        #     f"🔍 SAVE DEBUG - database layout data length: {len(db_layout_data) if db_layout_data else 0}"
        # )
        # if db_layout_data:
        #     for i, layout_item in enumerate(db_layout_data):
        #         logger.debug(f"🔍 SAVE DEBUG - database layout item {i}: {layout_item}")

        # db_metadata = dashboard_data.get("stored_metadata", [])
        # logger.debug(f"🔍 SAVE DEBUG - database metadata count: {len(db_metadata)}")
        # for i, meta_item in enumerate(db_metadata):
        #     logger.debug(
        #         f"🔍 SAVE DEBUG - database metadata item {i}: index={meta_item.get('index')}, type={meta_item.get('component_type')}, title={meta_item.get('title')}"
        #     )

        logger.debug("=" * 80)
        logger.debug("🔍 SAVE DEBUG - CALLING API TO SAVE DASHBOARD")
        logger.debug("=" * 80)

        # Save dashboard data using API call with proper timeout
        # REFACTORING: No enrichment needed - delta_locations always fetched fresh via MongoDB join
        # Project endpoint /projects/get/from_id includes delta_locations via $lookup aggregation
        save_success = api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN, enrich=False)

        # Log save result and verify what was actually saved
        logger.debug("=" * 80)
        logger.debug("🔍 SAVE DEBUG - SAVE OPERATION RESULT")
        logger.debug("=" * 80)
        logger.debug(f"🔍 SAVE DEBUG - save_success: {save_success}")
        logger.debug(f"🔍 SAVE DEBUG - dashboard_id: {dashboard_id}")
        logger.debug(f"🔍 SAVE DEBUG - user_id: {current_user.id}")

        # for each component which is interactive, show value & corrected_value
        for i, value in enumerate(interactive_component_values):
            logger.debug(f"🔍 SAVE DEBUG - interactive component {i}: value={value}")
        for elem in dashboard_data.get("stored_metadata", []):
            if elem["component_type"] == "interactive":
                index = elem.get("index")
                logger.info(
                    f"🔍 SAVE DEBUG - interactive component metadata: index={index}, value={elem.get('value')}, corrected_value={elem.get('corrected_value')}"
                )
        if save_success:
            # Fetch the dashboard again to verify what was actually saved
            # logger.debug("🔍 SAVE DEBUG - Fetching saved dashboard to verify data...")
            # verified_data = api_call_get_dashboard(dashboard_id, TOKEN)
            # if verified_data:
            #     verified_layout = verified_data.get("stored_layout_data", [])
            #     verified_metadata = verified_data.get("stored_metadata", [])

            #     logger.debug(
            #         f"🔍 SAVE DEBUG - verified layout data from database: {verified_layout}"
            #     )
            #     logger.debug(
            #         f"🔍 SAVE DEBUG - verified layout count: {len(verified_layout) if verified_layout else 0}"
            #     )
            #     if verified_layout:
            #         for i, layout_item in enumerate(verified_layout):
            #             logger.debug(f"🔍 SAVE DEBUG - verified layout item {i}: {layout_item}")

            #     logger.debug(f"🔍 SAVE DEBUG - verified metadata count: {len(verified_metadata)}")
            #     for i, meta_item in enumerate(verified_metadata):
            #         logger.debug(
            #             f"🔍 SAVE DEBUG - verified metadata item {i}: index={meta_item.get('index')}, type={meta_item.get('component_type')}, title={meta_item.get('title')}"
            #         )
            # else:
            #     logger.error("🔍 SAVE DEBUG - Failed to fetch dashboard for verification")
            pass
        else:
            logger.error(f"Failed to save dashboard data for {dashboard_id}")

        # logger.debug("=" * 80)
        # logger.debug("🔍 SAVE DEBUG - LAYOUT DATA PROCESSING END")
        # logger.debug("=" * 80)

        # Screenshot the dashboard if save button was clicked
        if n_clicks and save_success:
            screenshot_success = api_call_screenshot_dashboard(dashboard_id)
            if not screenshot_success:
                logger.warning(f"Failed to save dashboard screenshot for {dashboard_id}")

        # Pure side-effect callback - no return needed

    # @app.callback(
    #     Output("success-modal-dashboard", "opened"),
    #     Input("save-button-dashboard", "n_clicks"),
    #     State("success-modal-dashboard", "opened"),
    #     prevent_initial_call=True,
    # )
    # def toggle_success_modal_dashboard(n_save, is_open):
    #     return not is_open
"""
# END OF OLD COMPLEX CALLBACK - See save.py.bak for full uncommented version
