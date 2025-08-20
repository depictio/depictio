import asyncio
import collections
import concurrent.futures
from typing import Any, List, Tuple

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token, api_call_get_dashboard
from depictio.dash.component_metadata import get_async_build_functions

# Moved import to inside function to avoid circular import
from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
    create_skeleton_component,
)
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.models.models.dashboards import DashboardData
from depictio.models.utils import convert_model_to_dict

# Get async build functions from centralized metadata
build_functions = get_async_build_functions()


async def build_component_async(child_metadata: dict, theme: str) -> Tuple[Any, str]:
    """
    Async wrapper for building a component using async build functions.

    Args:
        child_metadata: Component metadata dictionary
        theme: Theme to use for the component

    Returns:
        Tuple of (built_component, component_type)
    """
    import time

    component_type = child_metadata.get("component_type", None)
    component_index = child_metadata.get("index", "unknown")

    start_time = time.time()
    logger.info(f"🚀 ASYNC BUILD: Starting {component_type} component {component_index}")

    if component_type is None or component_type not in build_functions:
        logger.warning(f"Unsupported child type: {component_type}")
        raise ValueError(f"Unsupported child type: {component_type}")

    # At this point, component_type is guaranteed to be a string

    # Get the build function based on the type
    build_function = build_functions[component_type]

    # Add theme to child metadata for figure generation
    if component_type == "figure":
        child_metadata["theme"] = theme
        logger.info(f"🎨 ASYNC BUILD: Using theme {theme} for figure {component_index}")

    # Check if build function is async (which it should be for all components except jbrowse)
    import inspect

    if inspect.iscoroutinefunction(build_function):
        # Call async build function directly
        logger.info(
            f"⚡ ASYNC BUILD: Executing async {component_type} function for {component_index}"
        )
        function_start = time.time()
        child = await build_function(**child_metadata)
        function_end = time.time()
        logger.info(
            f"⚡ ASYNC BUILD: {component_type} {component_index} async function completed in {(function_end - function_start) * 1000:.1f}ms"
        )
    else:
        # Fallback for non-async functions (like jbrowse) - use thread pool
        logger.info(
            f"🔄 ASYNC BUILD: Using thread pool for sync {component_type} function {component_index}"
        )
        function_start = time.time()
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            child = await loop.run_in_executor(executor, build_function, **child_metadata)
        function_end = time.time()
        logger.info(
            f"🔄 ASYNC BUILD: {component_type} {component_index} thread pool execution completed in {(function_end - function_start) * 1000:.1f}ms"
        )

    end_time = time.time()
    total_time = (end_time - start_time) * 1000
    logger.info(
        f"✅ ASYNC BUILD: {component_type} {component_index} TOTAL build time: {total_time:.1f}ms"
    )

    return (child, component_type)


async def build_components_parallel(
    stored_metadata: List[dict], bulk_component_data: dict, theme: str, TOKEN: str
) -> List[Tuple[Any, str]]:
    """
    Build dashboard components in parallel using async processing.

    Args:
        stored_metadata: List of component metadata dictionaries
        bulk_component_data: Pre-fetched component data from bulk API call
        theme: Theme to use for rendering components
        TOKEN: Access token for API calls

    Returns:
        List of (component, component_type) tuples
    """
    import time

    parallel_start_time = time.time()
    logger.info(f"🚀 ASYNC PARALLEL: Starting parallel build of {len(stored_metadata)} components")

    # Prepare all component metadata with required fields
    prepared_metadata = []
    prep_start_time = time.time()

    for i, child_metadata in enumerate(stored_metadata):
        # Make a copy to avoid modifying the original
        metadata_copy = child_metadata.copy()
        metadata_copy["build_frame"] = True
        metadata_copy["access_token"] = TOKEN

        # PERFORMANCE OPTIMIZATION: Pass pre-fetched component data to avoid individual API calls
        component_index = metadata_copy.get("index")
        component_type = metadata_copy.get("component_type", "unknown")

        if component_index in bulk_component_data:
            metadata_copy["_bulk_component_data"] = bulk_component_data[component_index]
            logger.debug(
                f"✅ BULK ATTACH: Attached pre-fetched data for component {component_index} ({component_type})"
            )
        else:
            logger.warning(
                f"⚠️ NO BULK DATA: Component {component_index} ({component_type}) will fetch individually (performance hit)"
            )
            if bulk_component_data:
                logger.warning(f"🔍 AVAILABLE BULK KEYS: {list(bulk_component_data.keys())}")

        prepared_metadata.append(metadata_copy)

    prep_end_time = time.time()
    logger.info(
        f"📋 ASYNC PARALLEL: Metadata preparation completed in {(prep_end_time - prep_start_time) * 1000:.1f}ms"
    )

    # Create async tasks for all components
    task_creation_start = time.time()
    tasks = [build_component_async(metadata, theme) for metadata in prepared_metadata]
    task_creation_end = time.time()
    logger.info(
        f"⚡ ASYNC PARALLEL: Created {len(tasks)} async tasks in {(task_creation_end - task_creation_start) * 1000:.1f}ms"
    )

    # Execute all tasks in parallel with progress logging
    gather_start_time = time.time()
    logger.info(f"🔄 ASYNC GATHER: Executing {len(tasks)} component build tasks in PARALLEL")

    # Log the component types being built in parallel
    component_types_count = {}
    for metadata in prepared_metadata:
        comp_type = metadata.get("component_type", "unknown")
        component_types_count[comp_type] = component_types_count.get(comp_type, 0) + 1

    logger.info(f"🎯 ASYNC PARALLEL: Building component types: {dict(component_types_count)}")

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        gather_end_time = time.time()
        gather_duration = (gather_end_time - gather_start_time) * 1000
        logger.info(f"⚡ ASYNC GATHER: All {len(tasks)} tasks completed in {gather_duration:.1f}ms")

        # Process results and handle any exceptions
        processing_start = time.time()
        successful_builds = []
        failed_builds = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                component_index = prepared_metadata[i].get("index", "unknown")
                component_type = prepared_metadata[i].get("component_type", "unknown")
                logger.error(
                    f"❌ ASYNC BUILD FAILED: Component {component_index} ({component_type}): {result}"
                )
                failed_builds.append((component_index, component_type, result))
            else:
                successful_builds.append(result)

        processing_end = time.time()
        logger.info(
            f"📊 ASYNC PARALLEL: Result processing completed in {(processing_end - processing_start) * 1000:.1f}ms"
        )

        # Log performance summary by component type
        success_by_type = {}
        for comp, comp_type in successful_builds:
            success_by_type[comp_type] = success_by_type.get(comp_type, 0) + 1

        logger.info(
            f"✅ ASYNC COMPLETE: {len(successful_builds)} components built successfully: {dict(success_by_type)}"
        )

        if failed_builds:
            logger.info(f"❌ ASYNC FAILURES: {len(failed_builds)} components failed")
            for component_index, component_type, error in failed_builds:
                logger.error(f"📋 FAILED COMPONENT: {component_index} ({component_type}) - {error}")

        total_parallel_time = (time.time() - parallel_start_time) * 1000
        logger.info(
            f"🏁 ASYNC PARALLEL: TOTAL parallel build process completed in {total_parallel_time:.1f}ms"
        )
        logger.info(
            f"🚀 ASYNC PARALLEL: Average time per component: {total_parallel_time / len(prepared_metadata):.1f}ms"
        )

        return successful_builds

    except Exception as e:
        gather_error_time = time.time()
        logger.error(
            f"❌ ASYNC GATHER FAILED after {(gather_error_time - gather_start_time) * 1000:.1f}ms: {type(e).__name__}: {e}"
        )
        import traceback

        logger.error(f"📚 ASYNC TRACEBACK: {traceback.format_exc()}")
        # Fallback to sequential processing if parallel processing fails
        logger.warning("🔄 FALLBACK: Switching to sequential component building")
        return await build_components_sequential(stored_metadata, bulk_component_data, theme, TOKEN)


async def build_components_sequential(
    stored_metadata: List[dict], bulk_component_data: dict, theme: str, TOKEN: str
) -> List[Tuple[Any, str]]:
    """
    Fallback sequential component building for when parallel processing fails.
    """
    logger.info(f"🔄 SEQUENTIAL BUILD: Building {len(stored_metadata)} components sequentially")
    children = []

    for child_metadata in stored_metadata:
        try:
            metadata_copy = child_metadata.copy()
            metadata_copy["build_frame"] = True
            metadata_copy["access_token"] = TOKEN

            # Add bulk component data if available
            component_index = metadata_copy.get("index")
            if component_index in bulk_component_data:
                metadata_copy["_bulk_component_data"] = bulk_component_data[component_index]

            child, component_type = await build_component_async(metadata_copy, theme)
            children.append((child, component_type))

        except Exception as e:
            component_index = child_metadata.get("index", "unknown")
            component_type = child_metadata.get("component_type", "unknown")
            logger.error(
                f"❌ SEQUENTIAL BUILD FAILED: Component {component_index} ({component_type}): {e}"
            )

    logger.info(f"✅ SEQUENTIAL COMPLETE: {len(children)} components built")
    return children


def return_interactive_components_dict(dashboard_data):
    # logger.info(f"Dashboard data: {dashboard_data}")

    # logger.debug(f"Dashboard data: {dashboard_data}")
    # logger.debug(f"Dashboard data type: {type(dashboard_data)}")

    interactive_components_dict = collections.defaultdict(dict)

    for e in dashboard_data:
        # logger.debug(f"e: {e}")

        if "component_type" not in e:
            logger.debug(f"Component type not found in e: {e}")
            continue

        if e["component_type"] == "interactive":
            # logger.debug(f"e: {e}")
            # logger.debug(f"e['value']: {e['value']}")
            # logger.debug(f"e['component_type']: {e['component_type']}")
            interactive_components_dict[e["index"]] = {
                "value": e["value"],
                "metadata": e,
            }

    # interactive_components_dict = {e["index"]: {"value": e["value"], "metadata": e} for e in dashboard_data if e["component_type"] == "interactive"}
    # logger.debug(f"Interactive components dict: {interactive_components_dict}")
    return interactive_components_dict


async def render_dashboard(stored_metadata, edit_components_button, dashboard_id, theme, TOKEN):
    logger.info(f"Rendering dashboard with ID: {dashboard_id}")
    from depictio.dash.layouts.draggable import clean_stored_metadata

    logger.info(
        f"📊 RESTORE DEBUG - Raw stored_metadata count: {len(stored_metadata) if stored_metadata else 0}"
    )

    # Log the first few raw metadata entries for debugging
    if stored_metadata:
        for i, elem in enumerate(stored_metadata[:3]):  # Only first 3 to avoid spam
            logger.info(
                f"📊 RESTORE DEBUG - Raw metadata {i}: keys={list(elem.keys()) if elem else 'None'}"
            )
            if elem:
                logger.info(
                    f"📊 RESTORE DEBUG - Raw metadata {i}: dict_kwargs={elem.get('dict_kwargs', 'MISSING')}"
                )
                logger.info(
                    f"📊 RESTORE DEBUG - Raw metadata {i}: wf_id={elem.get('wf_id', 'MISSING')}"
                )
                logger.info(
                    f"📊 RESTORE DEBUG - Raw metadata {i}: dc_id={elem.get('dc_id', 'MISSING')}"
                )

    stored_metadata = clean_stored_metadata(stored_metadata)
    logger.info(
        f"📊 RESTORE DEBUG - After cleaning, metadata count: {len(stored_metadata) if stored_metadata else 0}"
    )

    # PERFORMANCE OPTIMIZATION: Pre-fetch all component data in bulk
    component_ids = [metadata.get("index") for metadata in stored_metadata if metadata.get("index")]
    component_ids = [cid for cid in component_ids if cid is not None]  # Filter out None values

    # CACHE STATUS: Simple check for page refresh monitoring
    try:
        from depictio.api.v1.deltatables_utils import _dataframe_memory_cache

        cache_count = len(_dataframe_memory_cache)
        logger.info(
            f"📊 PAGE REFRESH: {cache_count} DataFrames already cached before loading dashboard {dashboard_id}"
        )
    except Exception:
        pass  # Don't break if cache import fails

    logger.info(
        f"🚀 BULK PRE-FETCH: Loading {len(component_ids)} components in bulk for dashboard {dashboard_id}"
    )
    logger.info(f"📋 COMPONENT IDS: {component_ids}")  # Debug: show which components we're fetching

    # Import bulk function
    from depictio.dash.utils import bulk_get_component_data

    # Pre-fetch all component data in one API call
    bulk_component_data = {}
    if component_ids:
        try:
            logger.info(
                f"🔄 BULK ATTEMPT: About to call bulk_get_component_data with {len(component_ids)} components"
            )
            bulk_component_data = bulk_get_component_data(component_ids, dashboard_id, TOKEN)
            logger.info(f"✅ BULK SUCCESS: Pre-fetched {len(bulk_component_data)} components")
            logger.info(
                f"📊 BULK DATA KEYS: {list(bulk_component_data.keys())}"
            )  # Show what we got back
        except Exception as e:
            logger.error(f"❌ BULK FAILED: {type(e).__name__}: {e}")
            logger.error(
                f"🔍 BULK FAILURE DETAILS: dashboard_id={dashboard_id}, component_count={len(component_ids)}"
            )
            import traceback

            logger.error(f"📚 BULK TRACEBACK: {traceback.format_exc()}")
            bulk_component_data = {}
    else:
        logger.warning("⚠️ NO COMPONENT IDS: Skipping bulk fetch for empty component list")

    # 🚀 ASYNC COMPONENT RENDERING: Use parallel processing for better performance
    logger.info(
        f"📈 ASYNC RENDER: About to build {len(stored_metadata)} components using async parallel processing"
    )
    children = await build_components_parallel(stored_metadata, bulk_component_data, theme, TOKEN)
    logger.info(
        f"📈 ASYNC RENDER: Async parallel processing completed, {len(children)} components built"
    )

    interactive_components_dict = return_interactive_components_dict(stored_metadata)

    # Process children with special handling for text components to avoid circular JSON
    processed_children = []
    for child, component_type in children:
        logger.info(f"Processing child component: {child.id} of type {component_type}")
        # try:
        # if component_type == "text":
        #     # For text components, try to_plotly_json() first, but catch circular reference errors
        #     logger.info(
        #         "Attempting to_plotly_json() for text component with circular reference protection"
        #     )
        #     try:
        #         child_json = child.to_plotly_json()
        #     except (ValueError, TypeError) as e:
        #         if "circular" in str(e).lower() or "json" in str(e).lower():
        #             logger.warning(
        #                 f"Circular reference detected in text component, using fallback approach: {e}"
        #             )
        #             # Create a minimal JSON structure for the text component
        #             # Extract the essential information without the problematic RichTextEditor
        #             child_json = {
        #                 "type": "Div",
        #                 "props": {
        #                     "id": {
        #                         "index": child.id.get("index")
        #                         if hasattr(child, "id") and child.id
        #                         else "unknown"
        #                     },
        #                     "children": "Text Component (Circular Reference Avoided)",
        #                 },
        #             }
        #         else:
        #             raise  # Re-raise if it's not a circular reference issue

        #     processed_child = enable_box_edit_mode(
        #         child_json,
        #         switch_state=edit_components_button,
        #         dashboard_id=dashboard_id,
        #         TOKEN=TOKEN,
        #     )
        # else:
        # For other components, use the standard to_plotly_json() approach
        processed_child = enable_box_edit_mode(
            child.to_plotly_json(),
            switch_state=edit_components_button,
            dashboard_id=dashboard_id,
            TOKEN=TOKEN,
        )
        # if component_type == "text":
        #     logger.info(
        #         f"Processed text component {processed_child.id} with content: {processed_child}"
        #     )
        #     logger.info(f"Processed child: {processed_child}")
        processed_children.append(processed_child)
        # except Exception as e:
        #     logger.error(f"Error processing {component_type} component: {e}")
        #     # Add a fallback component to prevent the entire dashboard from failing
        #     fallback_child = {
        #         "type": "Div",
        #         "props": {
        #             "id": {"index": f"error-{component_type}"},
        #             "children": f"Error loading {component_type} component",
        #         },
        #     }
        #     processed_child = enable_box_edit_mode(
        #         fallback_child,
        #         switch_state=edit_components_button,
        #         dashboard_id=dashboard_id,
        #         TOKEN=TOKEN,
        #     )
        #     processed_children.append(processed_child)

    children = processed_children
    # logger.info(f"Children: {children}")

    # Import here to avoid circular import
    from depictio.dash.layouts.draggable_scenarios.interactive_component_update import (
        update_interactive_component_async,
    )

    children = await update_interactive_component_async(
        stored_metadata,
        interactive_components_dict,
        children,
        switch_state=edit_components_button,
        TOKEN=TOKEN,
        dashboard_id=dashboard_id,
        theme=theme,  # Pass theme to interactive component updates
    )
    # logger.info(f"Updated children after interactive component processing: {children}")

    return children


def render_dashboard_with_skeletons(
    stored_metadata, edit_components_button, dashboard_id, theme, TOKEN
):
    """Render dashboard with skeleton placeholders for progressive loading."""
    logger.info(f"Rendering dashboard with skeletons for ID: {dashboard_id}")
    from depictio.dash.layouts.draggable import clean_stored_metadata

    stored_metadata = clean_stored_metadata(stored_metadata)
    children = []

    for child_metadata in stored_metadata:
        component_type = child_metadata.get("component_type", "card")
        component_uuid = child_metadata.get("index", "unknown")

        logger.info(f"Creating skeleton for {component_type} component {component_uuid}")

        # Create skeleton component
        skeleton_component = create_skeleton_component(component_type)

        # Wrap with DraggableWrapper using enable_box_edit_mode structure
        from dash import html

        # Apply enable_box_edit_mode - wrap skeleton with a content div that can be updated
        skeleton_with_content_id = html.Div(
            [skeleton_component], id={"type": "component-content", "uuid": component_uuid}
        )

        # Create a wrapper div with the expected ID structure for enable_box_edit_mode
        # The enable_box_edit_mode function expects a component with id={"index": component_uuid}
        wrapper_div = html.Div([skeleton_with_content_id], id={"index": component_uuid})

        # Create a proper Dash component for enable_box_edit_mode
        # The enable_box_edit_mode function expects a component's to_plotly_json() output
        wrapped_component = enable_box_edit_mode(
            wrapper_div.to_plotly_json(),
            switch_state=edit_components_button,
            dashboard_id=dashboard_id,
            component_data=child_metadata,
            TOKEN=TOKEN,
        )

        children.append(wrapped_component)

    logger.info(f"Created {len(children)} skeleton components")
    return children


def get_loading_delay_for_component(component_type, index_in_list):
    """Get the loading delay for a component based on its type and position."""
    base_delays = {
        "card": 0.1,  # Fastest - simple components
        "interactive": 0.2,  # Medium - interactive components
        "figure": 0.3,  # Slower - complex visualizations
        "table": 0.4,  # Slowest - data-heavy components
        "jbrowse": 0.5,  # Slowest - genome browser
        "text": 0.1,  # Text components load fast
    }

    base_delay = base_delays.get(component_type, 0.2)
    # Add minimal incremental delay based on position to stagger loading
    positional_delay = index_in_list * 0.05

    return base_delay + positional_delay


async def load_depictio_data(dashboard_id, local_data, theme="light"):
    """Load the dashboard data from the API and render it.
    Args:
        dashboard_id (str): The ID of the dashboard to load.
        local_data (dict): Local data containing access token and other information.
        theme (str): The theme to use for rendering the dashboard.
    Returns:
        dict: The dashboard data with rendered children.
    Raises:
        ValueError: If the dashboard data cannot be fetched or is invalid.
    """
    logger.info(f"Loading Depictio data for dashboard ID: {dashboard_id}")

    # Ensure theme is valid
    if not theme or theme == {} or theme == "{}":
        theme = "light"
    logger.info(f"Using theme: {theme} for dashboard rendering")

    if not local_data["access_token"]:
        logger.warning("Access token not found.")
        return None

    dashboard_data_dict = api_call_get_dashboard(dashboard_id, local_data["access_token"])
    if not dashboard_data_dict:
        logger.error(f"Failed to fetch dashboard data for {dashboard_id}")
        raise ValueError(f"Failed to fetch dashboard data: {dashboard_id}")

    dashboard_data = DashboardData.from_mongo(dashboard_data_dict)

    # logger.info(f"load_depictio_data : {dashboard_data}")

    if dashboard_data:
        if not hasattr(dashboard_data, "buttons_data"):
            dashboard_data.buttons_data = {
                "unified_edit_mode": True,  # Replace separate buttons with unified mode
                "add_button": {"count": 0},
            }

        # buttons = ["edit_components_button", "edit_dashboard_mode_button", "add_button"]
        # for button in buttons:
        #     if button not in dashboard_data["buttons_data"]:
        #         if button == "add_button":
        #             dashboard_data["buttons_data"][button] = {"count": 0}
        #         else:
        #             dashboard_data["buttons_data"][button] = True

        if hasattr(dashboard_data, "stored_metadata"):
            current_user = api_call_fetch_user_from_token(local_data["access_token"])

            # Check if data is available, if not set the buttons to disabled
            owner = (
                True
                if str(current_user.id) in [str(e.id) for e in dashboard_data.permissions.owners]
                else False
            )

            # logger.info(f"Owner: {owner}")
            # logger.info(f"Current user: {current_user.id}")
            # logger.info(
            #     f"Dashboard owners: {[str(e.id) for e in dashboard_data.permissions.owners]}"
            # )

            viewer_ids = [str(e.id) for e in dashboard_data.permissions.viewers]
            is_viewer = str(current_user.id) in viewer_ids
            has_wildcard = "*" in dashboard_data.permissions.viewers
            viewer = is_viewer or has_wildcard

            if not owner and viewer:
                # disabled = True
                # edit_dashboard_mode_button_checked = True
                edit_components_button_checked = False
            else:
                # disabled = False
                # edit_dashboard_mode_button_checked = dashboard_data.buttons_data[
                #     "edit_dashboard_mode_button"
                # ]
                # Try unified edit mode first, fallback to old key for backward compatibility
                edit_components_button_checked = dashboard_data.buttons_data.get(
                    "unified_edit_mode",
                    dashboard_data.buttons_data.get("edit_components_button", False),
                )

            # Disable edit_components_button for anonymous users and temporary users on public dashboards in unauthenticated mode
            if settings.auth.unauthenticated_mode:
                # Disable for anonymous users (non-temporary)
                if (
                    hasattr(current_user, "is_anonymous")
                    and current_user.is_anonymous
                    and not getattr(current_user, "is_temporary", False)
                ):
                    edit_components_button_checked = False
                # Also disable for temporary users viewing public dashboards they don't own
                elif getattr(current_user, "is_temporary", False) and not owner:
                    edit_components_button_checked = False
            else:
                # If not in unauthenticated mode, check if the user is owner or has edit permissions
                if not owner and not viewer:
                    edit_components_button_checked = False

            # Use regular dashboard rendering - progressive loading will be handled at UI level
            logger.info("Rendering dashboard components")
            children = await render_dashboard(
                dashboard_data.stored_metadata,
                edit_components_button_checked,
                dashboard_id,
                theme,
                local_data["access_token"],
            )
            # logger.info(f"Render Children: {children}")

            dashboard_data.stored_children_data = children
        # logger.info(f"Dashboard data RETURN: {dashboard_data}")
        dashboard_data = convert_model_to_dict(dashboard_data)
        # logger.info(f"Dashboard data RETURN to dict: {dashboard_data}")
        return dashboard_data
    else:
        return None


def load_depictio_data_sync(dashboard_id, local_data, theme="light"):
    """
    Synchronous version for load_depictio_data to maintain backward compatibility.
    This is used by non-background callbacks that can't handle async functions directly.
    Uses synchronous build functions to avoid coroutine serialization issues.
    """
    logger.info(f"Loading Depictio data synchronously for dashboard ID: {dashboard_id}")

    # Ensure theme is valid
    if not theme or theme == {} or theme == "{}":
        theme = "light"
    logger.info(f"Using theme: {theme} for synchronous dashboard rendering")

    if not local_data["access_token"]:
        logger.warning("Access token not found.")
        return None

    dashboard_data_dict = api_call_get_dashboard(dashboard_id, local_data["access_token"])
    if not dashboard_data_dict:
        logger.error(f"Failed to fetch dashboard data for {dashboard_id}")
        raise ValueError(f"Failed to fetch dashboard data: {dashboard_id}")

    dashboard_data = DashboardData.from_mongo(dashboard_data_dict)

    if dashboard_data:
        if not hasattr(dashboard_data, "buttons_data"):
            dashboard_data.buttons_data = {
                "unified_edit_mode": True,  # Replace separate buttons with unified mode
                "add_button": {"count": 0},
            }

        if hasattr(dashboard_data, "stored_metadata"):
            current_user = api_call_fetch_user_from_token(local_data["access_token"])

            # Check if data is available, if not set the buttons to disabled
            owner = (
                True
                if str(current_user.id) in [str(e.id) for e in dashboard_data.permissions.owners]
                else False
            )

            viewer_ids = [str(e.id) for e in dashboard_data.permissions.viewers]
            is_viewer = str(current_user.id) in viewer_ids
            has_wildcard = "*" in dashboard_data.permissions.viewers
            viewer = is_viewer or has_wildcard

            if not owner and viewer:
                edit_components_button_checked = False
            else:
                # Try unified edit mode first, fallback to old key for backward compatibility
                edit_components_button_checked = dashboard_data.buttons_data.get(
                    "unified_edit_mode",
                    dashboard_data.buttons_data.get("edit_components_button", False),
                )

            # Disable edit_components_button for anonymous users and temporary users on public dashboards in unauthenticated mode
            if settings.auth.unauthenticated_mode:
                # Disable for anonymous users (non-temporary)
                if (
                    hasattr(current_user, "is_anonymous")
                    and current_user.is_anonymous
                    and not getattr(current_user, "is_temporary", False)
                ):
                    edit_components_button_checked = False
                # Also disable for temporary users viewing public dashboards they don't own
                elif getattr(current_user, "is_temporary", False) and not owner:
                    edit_components_button_checked = False
            else:
                # If not in unauthenticated mode, check if the user is owner or has edit permissions
                if not owner and not viewer:
                    edit_components_button_checked = False

            # Use synchronous dashboard rendering to avoid coroutine serialization issues
            logger.info("Rendering dashboard components synchronously")
            children = render_dashboard_sync(
                dashboard_data.stored_metadata,
                edit_components_button_checked,
                dashboard_id,
                theme,
                local_data["access_token"],
            )

            dashboard_data.stored_children_data = children

        dashboard_data = convert_model_to_dict(dashboard_data)
        return dashboard_data

    return None


def render_dashboard_sync(stored_metadata, edit_components_button, dashboard_id, theme, TOKEN):
    """
    Synchronous version of render_dashboard that uses synchronous build functions.
    This prevents coroutine serialization issues when loading dashboards in non-async contexts.

    Args:
        stored_metadata: List of component metadata
        edit_components_button: Whether edit mode is enabled
        dashboard_id: Dashboard ID
        theme: Theme to use
        TOKEN: Access token

    Returns:
        List of processed children components
    """
    import time

    sync_start_time = time.time()
    logger.info(
        f"🔄 SYNC RENDER: Rendering dashboard synchronously with {len(stored_metadata)} components"
    )

    # Log the component types being built
    component_types_count = {}
    for metadata in stored_metadata:
        comp_type = metadata.get("component_type", "unknown")
        component_types_count[comp_type] = component_types_count.get(comp_type, 0) + 1

    logger.info(f"🎯 SYNC RENDER: Building component types: {dict(component_types_count)}")

    # Import synchronous build functions for sync context
    from depictio.dash.component_metadata import get_build_functions

    build_functions = get_build_functions()

    from depictio.dash.layouts.draggable import clean_stored_metadata

    stored_metadata = clean_stored_metadata(stored_metadata)

    processed_children = []

    for i, child_metadata in enumerate(stored_metadata):
        component_build_start = time.time()
        component_type = child_metadata.get("component_type", None)
        component_index = child_metadata.get("index", "unknown")

        if component_type not in build_functions:
            logger.warning(f"Unsupported child type: {component_type}")
            continue

        # Get the build function (sync wrapper)
        build_function = build_functions[component_type]

        # Prepare metadata
        child_metadata["build_frame"] = True
        child_metadata["access_token"] = TOKEN

        # Add theme for figure components
        if component_type == "figure":
            child_metadata["theme"] = theme
            logger.info(
                f"🎨 SYNC RENDER: Using theme {theme} for figure component {component_index}"
            )

        # Build component synchronously
        logger.info(
            f"🔨 SYNC RENDER: Building {component_type} component {component_index} synchronously ({i + 1}/{len(stored_metadata)})"
        )

        build_start_time = time.time()
        child = build_function(**child_metadata)

        build_end_time = time.time()

        logger.info(
            f"🔨 SYNC RENDER: {component_type} {component_index} build function completed in {(build_end_time - build_start_time) * 1000:.1f}ms"
        )

        # Process child for edit mode
        processed_child = enable_box_edit_mode(
            child.to_plotly_json(),
            switch_state=edit_components_button,
            dashboard_id=dashboard_id,
            TOKEN=TOKEN,
        )

        processed_children.append(processed_child)

        component_build_end = time.time()
        component_total_time = (component_build_end - component_build_start) * 1000
        logger.info(
            f"✅ SYNC RENDER: {component_type} {component_index} TOTAL processing time: {component_total_time:.1f}ms"
        )

    # Handle interactive component updates synchronously
    from depictio.dash.layouts.draggable_scenarios.interactive_component_update import (
        update_interactive_component_sync,
    )

    # Process interactive components synchronously
    processed_children = update_interactive_component_sync(
        stored_metadata,
        {},  # interactive_components_dict (empty for initial load)
        processed_children,
        switch_state=edit_components_button,
        TOKEN=TOKEN,
        dashboard_id=dashboard_id,
        theme=theme,
    )

    sync_end_time = time.time()
    total_sync_time = (sync_end_time - sync_start_time) * 1000

    # Performance summary by component type
    success_by_type = {}
    for metadata in stored_metadata:
        comp_type = metadata.get("component_type", "unknown")
        success_by_type[comp_type] = success_by_type.get(comp_type, 0) + 1

    logger.info(f"🏁 SYNC RENDER: TOTAL synchronous render completed in {total_sync_time:.1f}ms")
    logger.info(
        f"🚀 SYNC RENDER: Average time per component: {total_sync_time / len(stored_metadata) if stored_metadata else 0:.1f}ms"
    )
    logger.info(
        f"✅ SYNC RENDER: Successfully rendered {len(processed_children)} components: {dict(success_by_type)}"
    )

    return processed_children
