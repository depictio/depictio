from datetime import datetime

import dash
from dash import ALL, Input, Output, State
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_fetch_user_from_token,
    api_call_get_dashboard,
    api_call_save_dashboard,
    api_call_screenshot_dashboard,
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


def register_callbacks_save(app):
    @app.callback(
        inputs=[
            Input("save-button-dashboard", "n_clicks"),
            Input("draggable", "currentLayout"),
            Input(
                {
                    "type": "stored-metadata-component",
                    "index": ALL,
                },
                "data",
            ),
            State("stored-edit-dashboard-mode-button", "data"),
            Input("unified-edit-mode-button", "checked"),
            State("stored-add-button", "data"),
            State({"type": "interactive-component-value", "index": ALL}, "value"),
            Input({"type": "text-store", "index": ALL}, "data"),
            Input("notes-editor-store", "data"),
            State("url", "pathname"),
            State("local-store", "data"),
            State("user-cache-store", "data"),
            Input(
                {
                    "type": "btn-done",
                    "index": ALL,
                },
                "n_clicks",
            ),
            Input(
                {
                    "type": "btn-done-edit",
                    "index": ALL,
                },
                "n_clicks",
            ),
            Input(
                {
                    "type": "duplicate-box-button",
                    "index": ALL,
                },
                "n_clicks",
            ),
            Input(
                {"type": "remove-box-button", "index": ALL},
                "n_clicks",
            ),
            Input("remove-all-components-button", "n_clicks"),
            Input({"type": "interactive-component-value", "index": ALL}, "value"),
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
        user_cache,
        n_clicks_done,
        n_clicks_done_edit,
        n_clicks_duplicate,
        n_clicks_remove,
        n_clicks_remove_all,
        interactive_component_values_all,
    ):
        logger.info("Saving dashboard data...")
        logger.info(
            f"📊 SAVE DEBUG - Raw stored_metadata count: {len(stored_metadata) if stored_metadata else 0}"
        )

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

        # Early return if user is not logged in
        if not local_store:
            logger.warning("User not logged in.")
            raise dash.exceptions.PreventUpdate

        # Validate user authentication using consolidated cache
        from depictio.models.models.users import UserContext

        TOKEN = local_store["access_token"]
        current_user = UserContext.from_cache(user_cache)
        if not current_user:
            # Fallback to direct API call if cache not available
            logger.info("🔄 Save: Using fallback API call for user authentication")
            current_user_api = api_call_fetch_user_from_token(TOKEN)
            if not current_user_api:
                logger.warning("User not found.")
                raise dash.exceptions.PreventUpdate
            # Create UserContext from API response for consistency
            current_user = UserContext(
                id=str(current_user_api.id),
                email=current_user_api.email,
                is_admin=current_user_api.is_admin,
                is_anonymous=getattr(current_user_api, "is_anonymous", False),
            )
        else:
            logger.info("✅ Save: Using consolidated cache for user authentication")

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
            "draggable",
            "text-store",
            "notes-editor-store",
            "interactive-component-value",
        ]

        # Check if save should be triggered
        if (
            not any(trigger in triggered_id for trigger in save_triggers)
            or not unified_edit_mode_button_checked
        ):
            raise dash.exceptions.PreventUpdate

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

        # logger.debug("=" * 80)
        # logger.debug("🔍 SAVE DEBUG - CALLING API TO SAVE DASHBOARD")
        # logger.debug("=" * 80)

        # Save dashboard data using API call with proper timeout
        save_success = api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN)

        # Log save result and verify what was actually saved
        # logger.debug("=" * 80)
        # logger.debug("🔍 SAVE DEBUG - SAVE OPERATION RESULT")
        # logger.debug("=" * 80)
        # logger.debug(f"🔍 SAVE DEBUG - save_success: {save_success}")

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

    @app.callback(
        Output("success-modal-dashboard", "is_open"),
        Input("save-button-dashboard", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_success_modal_dashboard(n_save):
        if n_save:
            return True
        raise dash.exceptions.PreventUpdate

    # Auto-dismiss modal after 3 seconds
    app.clientside_callback(
        """
        function(is_open) {
            if (is_open) {
                setTimeout(function() {
                    // Find and click outside to close modal
                    const backdrop = document.querySelector('.modal-backdrop');
                    if (backdrop) {
                        backdrop.click();
                    }
                }, 3000);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("success-modal-dashboard", "id"),
        Input("success-modal-dashboard", "is_open"),
    )
