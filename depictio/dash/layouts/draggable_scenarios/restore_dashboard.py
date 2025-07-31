import collections

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token, api_call_get_dashboard
from depictio.dash.component_metadata import get_build_functions
from depictio.dash.layouts.draggable_scenarios.interactive_component_update import (
    update_interactive_component,
)
from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
    create_skeleton_component,
)
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.models.models.dashboards import DashboardData
from depictio.models.utils import convert_model_to_dict

# Get build functions from centralized metadata
build_functions = get_build_functions()


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


def render_dashboard(stored_metadata, edit_components_button, dashboard_id, theme, TOKEN):
    logger.info(f"Rendering dashboard with ID: {dashboard_id}")
    from depictio.dash.layouts.draggable import clean_stored_metadata

    stored_metadata = clean_stored_metadata(stored_metadata)
    # logger.info(f"Stored metadata: {stored_metadata}")

    children = list()

    for child_metadata in stored_metadata:
        child_metadata["build_frame"] = True
        child_metadata["access_token"] = TOKEN
        # logger.info(child_metadata)
        # logger.info(f"type of child_metadata : {type(child_metadata)}")

        # Extract the type of the child (assuming there is a type key in the metadata)
        component_type = child_metadata.get("component_type", None)
        # logger.info(f"component_type : {component_type}")
        if component_type not in build_functions:
            logger.warning(f"Unsupported child type: {component_type}")
            raise ValueError(f"Unsupported child type: {component_type}")

        # Get the build function based on the type
        build_function = build_functions[component_type]
        # logger.info(f"build_function : {build_function.__name__}")

        # Add theme to child metadata for figure generation
        if component_type == "figure":
            child_metadata["theme"] = theme
            logger.info(f"Using theme: {theme} for figure component")

        # Build the child using the appropriate function and kwargs
        child = build_function(**child_metadata)
        # logger.debug(f"child : ")
        # Store child with its component type for later processing
        children.append((child, component_type))
    # logger.info(f"Children: {children}")

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

    children = update_interactive_component(
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


def load_depictio_data(dashboard_id, local_data, theme="light"):
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
            children = render_dashboard(
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
