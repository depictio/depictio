from dash import dcc, html

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token, api_call_get_dashboard
from depictio.dash.component_metadata import DISPLAY_NAME_TO_TYPE_MAPPING, get_build_functions
from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
    create_card_placeholder,
    create_figure_placeholder,
    create_interactive_placeholder,
    create_skeleton_component,
)
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.models.models.dashboards import DashboardData
from depictio.models.utils import convert_model_to_dict

# Get build functions from centralized metadata
build_functions = get_build_functions()

# PERFORMANCE OPTIMIZATION (Phase 5B): Enable progressive loading for multiple component types
# Set to True to reduce initial render from 378 DOM mutations to smaller chunks
PROGRESSIVE_LOADING_ENABLED = False  # DISABLED FOR DEBUGGING

# Component types that should use progressive loading
# Priority order: card (fastest) < interactive < figure (slowest)
PROGRESSIVE_LOADING_TYPES = ["figure", "card", "interactive"]

# DEBUGGING: Test flag to use simple DMC layout instead of draggable grid
# Set to True to test if component disappearance is related to grid layout system
USE_SIMPLE_LAYOUT_FOR_TESTING = True  # ENABLED FOR DEBUGGING

# Base delays for each component type (in milliseconds)
COMPONENT_BASE_DELAYS = {
    "card": 300,  # Lightest - simple metric cards
    "interactive": 400,  # Medium - filters and controls
    "figure": 500,  # Heaviest - complex visualizations
}

# Placeholder creation functions for each type
PLACEHOLDER_FUNCTIONS = {
    "figure": create_figure_placeholder,
    "card": create_card_placeholder,
    "interactive": create_interactive_placeholder,
}


def render_dashboard(stored_metadata, edit_components_button, dashboard_id, theme, TOKEN):
    import time

    start_time_total = time.time()
    logger.info(f"⏱️ PROFILING: Starting render_dashboard for {dashboard_id}")
    from depictio.dash.layouts.draggable import clean_stored_metadata

    num_components = len(stored_metadata) if stored_metadata else 0
    logger.info(f"📊 RESTORE DEBUG - Raw stored_metadata count: {num_components}")

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

    start_clean = time.time()
    stored_metadata = clean_stored_metadata(stored_metadata)
    clean_duration_ms = (time.time() - start_clean) * 1000
    logger.info(f"⏱️ PROFILING: clean_stored_metadata took {clean_duration_ms:.1f}ms")
    logger.info(
        f"📊 RESTORE DEBUG - After cleaning, metadata count: {len(stored_metadata) if stored_metadata else 0}"
    )

    children = list()
    component_build_times = []
    components_pending_load = {}  # Track components for progressive loading by type

    for child_metadata in stored_metadata:
        start_component = time.time()
        child_metadata["build_frame"] = True
        child_metadata["access_token"] = TOKEN
        # logger.info(child_metadata)
        # logger.info(f"type of child_metadata : {type(child_metadata)}")

        # Extract the type of the child (assuming there is a type key in the metadata)
        component_type = child_metadata.get("component_type", None)

        # Handle legacy case conversion for existing components (e.g., "MultiQC" -> "multiqc")
        if component_type not in build_functions and component_type in DISPLAY_NAME_TO_TYPE_MAPPING:
            original_type = component_type
            component_type = DISPLAY_NAME_TO_TYPE_MAPPING[component_type]
            logger.info(f"Converting legacy component type '{original_type}' to '{component_type}'")
            # Update the metadata to use the correct type for consistency
            child_metadata["component_type"] = component_type

        # logger.info(f"component_type : {component_type}")
        if component_type not in build_functions:
            logger.warning(f"Unsupported child type: {component_type}")
            raise ValueError(f"Unsupported child type: {component_type}")

        # Add theme to child metadata for figure generation
        child_metadata["theme"] = theme
        logger.info(f"Using theme: {theme} for component {component_type}")

        # PERFORMANCE OPTIMIZATION (Phase 5B): Return lightweight placeholders for heavy components
        # This reduces initial React render from 378 DOM mutations to much smaller chunks
        # Actual components will be loaded via dcc.Interval triggered callbacks
        if PROGRESSIVE_LOADING_ENABLED and component_type in PROGRESSIVE_LOADING_TYPES:
            component_uuid = child_metadata.get("index", "unknown")
            logger.info(
                f"⚡ PROGRESSIVE LOADING: Creating placeholder for {component_type} {component_uuid}"
            )

            # Initialize tracking list for this component type if needed
            if component_type not in components_pending_load:
                components_pending_load[component_type] = []

            # Get placeholder creation function
            placeholder_func = PLACEHOLDER_FUNCTIONS.get(component_type)
            if not placeholder_func:
                logger.warning(
                    f"⚠️  No placeholder function for {component_type}, building normally"
                )
                # Fall through to normal build
                build_function = build_functions[component_type]
                child = build_function(**child_metadata)
            else:
                # Create lightweight placeholder with dcc.Interval to trigger loading
                # Calculate stagger delay based on component type and count
                base_delay = COMPONENT_BASE_DELAYS.get(component_type, 400)
                stagger_delay = len(components_pending_load[component_type]) * 100

                # CRITICAL FIX: Progressive loading placeholders must NOT be wrapped by enable_box_edit_mode
                # The progressive loading callback will build the component and wrap it itself
                # The container needs pattern-matching ID for the callback to target it
                # But we wrap it in an outer div with simple ID for enable_box_edit_mode to process later

                # Inner container - targeted by progressive loading callback
                inner_container = html.Div(
                    [
                        placeholder_func(component_uuid),
                        # Interval fires once after delay to trigger server callback
                        dcc.Interval(
                            id={
                                "type": f"{component_type}-load-trigger",
                                "index": component_uuid,
                            },
                            interval=base_delay + stagger_delay,
                            n_intervals=0,
                            max_intervals=1,  # Fire only once
                        ),
                        # Store to hold loaded component
                        dcc.Store(
                            id={
                                "type": f"{component_type}-metadata-store",
                                "index": component_uuid,
                            },
                            data=child_metadata,  # Store metadata for callback
                        ),
                    ],
                    id={
                        "type": f"{component_type}-container",
                        "index": component_uuid,
                    },
                )

                # Outer wrapper - has simple ID structure expected by draggable grid
                # Progressive loading callback will replace inner_container children with wrapped component
                # This outer wrapper ensures the grid item has the correct ID (box-{index})
                child = html.Div(
                    inner_container,
                    id=f"box-{component_uuid}",  # Grid item ID - must match draggable layout "i" field
                    className="responsive-wrapper",
                    style={
                        "position": "relative",
                        "width": "100%",
                        "height": "100%",
                        "display": "flex",
                        "flexDirection": "column",
                        "flex": "1",
                    },
                )
                components_pending_load[component_type].append(child_metadata)
        else:
            # Build other components normally (text, table, jbrowse, multiqc)
            # Get the build function based on the type
            build_function = build_functions[component_type]
            # logger.info(f"build_function : {build_function.__name__}")

            # Build the child using the appropriate function and kwargs
            child = build_function(**child_metadata)

        component_build_time_ms = (time.time() - start_component) * 1000
        component_build_times.append(component_build_time_ms)
        # logger.debug(f"child : ")
        # Store child with its component type and metadata for later processing
        children.append((child, component_type, child_metadata))
    # logger.info(f"Children: {children}")

    # PRE-PROCESS: Add panel metadata before wrapping components
    # This is needed so position menus can access panel/row/col data during creation
    if USE_SIMPLE_LAYOUT_FOR_TESTING:
        logger.info("🧪 PRE-PROCESSING: Adding panel metadata before component wrapping")
        interactive_count = 0
        card_count = 0
        other_count = 0

        for child, component_type, child_metadata in children:
            if component_type == "interactive":
                child_metadata["panel"] = "left"
                child_metadata["panel_position"] = interactive_count
                interactive_count += 1
            elif component_type == "card":
                child_metadata["panel"] = "right"
                child_metadata["component_section"] = "cards"
                child_metadata["panel_position"] = card_count
                child_metadata["row"] = card_count // 4
                child_metadata["col"] = card_count % 4
                card_count += 1
            else:
                child_metadata["panel"] = "right"
                child_metadata["component_section"] = "other"
                child_metadata["panel_position"] = other_count
                other_count += 1

    # Process children with special handling for text components to avoid circular JSON
    processed_children = []
    for child, component_type, child_metadata in children:
        logger.info(f"Processing child component of type {component_type}")

        # DEBUGGING: Use enable_box_edit_mode but extract only the content div without DraggableWrapper
        if USE_SIMPLE_LAYOUT_FOR_TESTING:
            logger.info(f"🧪 TESTING MODE: Using simplified button wrapper for {component_type}")
            # Call enable_box_edit_mode to get buttons, but we'll extract the content div
            wrapped_component = enable_box_edit_mode(
                child,
                switch_state=edit_components_button,
                dashboard_id=dashboard_id,
                component_data=child_metadata,
                TOKEN=TOKEN,
            )

            # The wrapped_component structure is: html.Div(children=[DraggableWrapper(children=[content_div])])
            # For simple layout, we just want the content_div with buttons, not the DraggableWrapper
            # Since extracting from DraggableWrapper is complex, let's just use the wrapped_component as-is
            # The buttons are already in there, we just need to strip the draggable functionality

            # Simply use the wrapped component but give it a simpler styling for stack layout
            content_div = wrapped_component

            # Wrap the content div in a simple container for the layout
            processed_child = html.Div(
                content_div,
                id=f"box-{child_metadata.get('index')}",
                className="dashboard-component-hover",
                style={
                    "position": "relative",
                    "width": "100%",
                    "minHeight": "auto",
                    "margin": "0",
                    "padding": "0",
                },
            )
        # CRITICAL FIX: Skip enable_box_edit_mode for progressive loading placeholders
        # They're already wrapped with the correct box-{index} ID and structure
        # Progressive loading callback will handle wrapping the actual component
        elif PROGRESSIVE_LOADING_ENABLED and component_type in PROGRESSIVE_LOADING_TYPES:
            logger.info(
                f"⚡ PROGRESSIVE LOADING: Skipping enable_box_edit_mode for {component_type} placeholder"
            )
            processed_child = child  # Already wrapped, use as-is
        else:
            processed_child = enable_box_edit_mode(
                child,  # Pass native Dash component directly
                switch_state=edit_components_button,
                dashboard_id=dashboard_id,
                component_data=child_metadata,  # Pass component metadata to help with ID extraction
                TOKEN=TOKEN,
            )
        processed_children.append(processed_child)

    # Pattern-matching callbacks handle initial value population (prevent_initial_call=False)
    # No need for sync rebuild - cards, figures, tables all self-initialize

    total_duration_ms = (time.time() - start_time_total) * 1000
    avg_component_time = (
        sum(component_build_times) / len(component_build_times) if component_build_times else 0
    )
    max_component_time = max(component_build_times) if component_build_times else 0

    logger.info(
        f"⏱️ PROFILING: render_dashboard TOTAL took {total_duration_ms:.1f}ms "
        f"for {len(processed_children)} components "
        f"(avg={avg_component_time:.1f}ms/component, max={max_component_time:.1f}ms)"
    )

    # Log progressive loading summary
    if PROGRESSIVE_LOADING_ENABLED and components_pending_load:
        total_pending = sum(len(comps) for comps in components_pending_load.values())
        logger.info(f"⚡ PROGRESSIVE LOADING: {total_pending} components will load incrementally:")
        for comp_type, comps in components_pending_load.items():
            base_delay = COMPONENT_BASE_DELAYS.get(comp_type, 400)
            logger.info(
                f"  - {len(comps)} {comp_type} component(s) "
                f"(base delay: {base_delay}ms, stagger: 100ms)"
            )

    logger.info(
        f"✅ Dashboard restored with {len(processed_children)} components - pattern-matching callbacks will populate values"
    )

    # DEBUGGING: Return simple DMC two-panel layout instead of draggable grid items
    if USE_SIMPLE_LAYOUT_FOR_TESTING:
        import dash_mantine_components as dmc

        logger.info("🧪 TESTING MODE: Using two-panel DMC layout instead of draggable grid")
        logger.info(f"🧪 Number of processed children: {len(processed_children)}")

        # Log each child type for debugging
        for i, child in enumerate(processed_children):
            child_type = type(child).__name__
            logger.info(f"🧪 Child {i}: {child_type}")
            if hasattr(child, "id"):
                logger.info(f"🧪 Child {i} ID: {child.id}")

        # Add a debug header to confirm the layout is being used
        debug_header = dmc.Alert(
            title="🧪 Testing Mode Active",
            children=f"Two-panel layout: Interactive (25%) | Cards+Other (75%) - {len(processed_children)} components total",
            color="blue",
            style={"marginBottom": "20px"},
        )

        # Separate components into two panels: interactive (left), everything else (right)
        interactive_components = []  # Left panel - vertical stack

        # Track card and non-card components separately for right panel layout
        card_components = []  # Cards will be in a 4-column grid
        other_components = []  # Other components in vertical stack below cards

        # Need to match processed_children with original metadata to get component_type
        # The children list was built in the same order as stored_metadata
        # Panel metadata was already set in pre-processing step
        for i, (child, component_type, child_metadata) in enumerate(children):
            if component_type == "interactive":
                interactive_components.append(processed_children[i])
                logger.info(
                    f"🎛️ Adding interactive component to left panel: {child_metadata.get('index')} (position={child_metadata.get('panel_position')})"
                )
            elif component_type == "card":
                card_components.append(processed_children[i])
                logger.info(
                    f"📊 Adding card to right panel cards section: {child_metadata.get('index')} (row={child_metadata.get('row')}, col={child_metadata.get('col')})"
                )
            else:
                other_components.append(processed_children[i])
                logger.info(
                    f"📈 Adding {component_type} to right panel other section: {child_metadata.get('index')} (position={child_metadata.get('panel_position')})"
                )

        logger.info(f"🧪 Left panel (interactive): {len(interactive_components)} components")
        logger.info(
            f"🧪 Right panel: {len(card_components)} cards + {len(other_components)} other = {len(card_components) + len(other_components)} total"
        )

        # Create left panel (25% width) - Interactive components
        if interactive_components:
            left_panel_content = dmc.Stack(
                interactive_components,
                gap=0,  # No gap between interactive components
                style={"width": "100%"},
            )
        else:
            left_panel_content = dmc.Center(
                dmc.Text(
                    "No interactive components",
                    size="sm",
                    c="gray",
                    style={"padding": "20px"},
                ),
                style={"width": "100%", "height": "200px"},
            )

        # Create right panel (75% width) - Cards in grid + Other components in stack
        right_panel_children = []

        # Add cards section with 4-column grid if cards exist
        if card_components:
            cards_grid = dmc.SimpleGrid(
                card_components,
                cols=4,  # 4 cards per row
                spacing=2,  # 2px horizontal gap
                verticalSpacing=2,  # 2px vertical gap
                style={"width": "100%", "marginBottom": "2px"},
            )
            right_panel_children.append(cards_grid)

        # Add other components section as vertical stack
        if other_components:
            right_panel_children.extend(other_components)

        # If no components at all, show placeholder
        if not right_panel_children:
            right_panel_content = dmc.Center(
                dmc.Text(
                    "No components",
                    size="sm",
                    c="gray",
                    style={"padding": "20px"},
                ),
                style={"width": "100%", "height": "200px"},
            )
        else:
            # Wrap all right panel components in a Stack
            right_panel_content = dmc.Stack(
                right_panel_children,
                gap=2,  # Minimal 2px gap between sections/components
                style={"width": "100%"},
            )

        # Create two-panel layout using dmc.Grid
        two_panel_layout = html.Div(
            [
                debug_header,
                dmc.Grid(
                    [
                        # Left panel - 1/4 width (span=1 out of 4 columns) - Interactive
                        dmc.GridCol(
                            left_panel_content,
                            span=1,
                            style={
                                "backgroundColor": "var(--app-surface-color, #f8f9fa)",
                                "padding": "4px",  # Minimal padding
                                "borderRadius": "4px",
                            },
                        ),
                        # Right panel - 3/4 width (span=3 out of 4 columns) - Cards + Other
                        dmc.GridCol(
                            right_panel_content,
                            span=3,
                            style={
                                "padding": "0px",  # No padding for maximum compression
                            },
                        ),
                    ],
                    columns=4,  # Total columns for 1/4 - 3/4 split
                    gutter="sm",  # 8px gap between panels
                    style={"width": "100%"},
                ),
            ],
            id="simple-test-layout",  # Add ID for debugging
            style={
                "padding": "8px",  # Reduced outer padding
                "width": "100%",
                "maxWidth": "1920px",  # Wider max width to accommodate two panels
                "margin": "0 auto",  # Center the content
                "backgroundColor": "var(--app-bg-color, #ffffff)",
            },
        )

        logger.info(f"🧪 Returning two-panel layout with {len(processed_children)} components")
        # Return wrapped in a container that the draggable callback can handle
        # This prevents callback errors while we test
        return [two_panel_layout]

    return processed_children


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


def load_depictio_data_sync(
    dashboard_id: str,
    local_data: dict,
    theme: str = "light",
    cached_user_data: dict | None = None,
) -> dict | None:
    """Load the dashboard data from the API and render it.

    PERFORMANCE OPTIMIZATION (Phase 5A):
    - Added cached_user_data parameter to avoid redundant API call
    - User data already fetched by consolidated API callback

    Args:
        dashboard_id (str): The ID of the dashboard to load.
        local_data (dict): Local data containing access token and other information.
        theme (str): The theme to use for rendering the dashboard.
        cached_user_data: Cached user data from consolidated API (avoids redundant fetch)
    Returns:
        dict: The dashboard data with rendered children.
    Raises:
        ValueError: If the dashboard data cannot be fetched or is invalid.
    """
    import time

    start_time_total = time.time()
    logger.info(f"⏱️ PROFILING: Starting load_depictio_data_sync for dashboard {dashboard_id}")

    # Ensure theme is valid
    if not theme or theme == {} or theme == "{}":
        theme = "light"
    logger.info(f"Using theme: {theme} for dashboard rendering")

    if not local_data["access_token"]:
        logger.warning("Access token not found.")
        return None

    # PROFILING: Measure dashboard metadata fetch
    start_fetch = time.time()
    dashboard_data_dict = api_call_get_dashboard(dashboard_id, local_data["access_token"])
    fetch_duration_ms = (time.time() - start_fetch) * 1000
    logger.info(f"⏱️ PROFILING: api_call_get_dashboard took {fetch_duration_ms:.1f}ms")
    if not dashboard_data_dict:
        logger.error(f"Failed to fetch dashboard data for {dashboard_id}")
        raise ValueError(f"Failed to fetch dashboard data: {dashboard_id}")

    # PROFILING: Measure Pydantic parsing
    start_parsing = time.time()
    dashboard_data = DashboardData.from_mongo(dashboard_data_dict)
    parsing_duration_ms = (time.time() - start_parsing) * 1000
    logger.info(f"⏱️ PROFILING: DashboardData.from_mongo took {parsing_duration_ms:.1f}ms")

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
            # PERFORMANCE OPTIMIZATION (Phase 5A): Use cached user data
            start_user_fetch = time.time()
            if cached_user_data:
                current_user = cached_user_data
                logger.info("⏱️ PROFILING: Using cached user data (0ms)")
            else:
                current_user = api_call_fetch_user_from_token(
                    local_data["access_token"]
                )  # Fallback only
                user_fetch_duration_ms = (time.time() - start_user_fetch) * 1000
                logger.info(
                    f"⏱️ PROFILING: api_call_fetch_user_from_token took {user_fetch_duration_ms:.1f}ms"
                )

            # Check if data is available, if not set the buttons to disabled
            # Note: current_user can be either a dict (from cache) or User object (from API)
            # Handle both cases defensively
            current_user_id = str(
                current_user.get("id") if isinstance(current_user, dict) else current_user.id
            )

            # Note: dashboard_data.permissions.owners can be either dicts or UserBase objects
            # Handle both cases defensively
            owner_ids = [
                str(e.get("id") if isinstance(e, dict) else e.id)
                for e in dashboard_data.permissions.owners
            ]
            owner = current_user_id in owner_ids

            # logger.info(f"Owner: {owner}")
            # logger.info(f"Current user: {current_user_id}")
            # logger.info(f"Dashboard owners: {owner_ids}")

            # Note: dashboard_data.permissions.viewers can be either dicts or UserBase objects
            viewer_ids = [
                str(e.get("id") if isinstance(e, dict) else e.id)
                for e in dashboard_data.permissions.viewers
            ]
            is_viewer = current_user_id in viewer_ids
            has_wildcard = "*" in viewer_ids  # Check if wildcard "*" is in the list of IDs
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
            # PROFILING: Measure component rendering
            start_render = time.time()
            children = render_dashboard(
                dashboard_data.stored_metadata,
                edit_components_button_checked,
                dashboard_id,
                theme,
                local_data["access_token"],
            )
            render_duration_ms = (time.time() - start_render) * 1000
            logger.info(f"⏱️ PROFILING: render_dashboard took {render_duration_ms:.1f}ms")

            dashboard_data.stored_children_data = children

        # PROFILING: Measure model conversion
        start_convert = time.time()
        dashboard_data = convert_model_to_dict(dashboard_data)
        convert_duration_ms = (time.time() - start_convert) * 1000
        logger.info(f"⏱️ PROFILING: convert_model_to_dict took {convert_duration_ms:.1f}ms")

        total_duration_ms = (time.time() - start_time_total) * 1000
        logger.info(
            f"⏱️ PROFILING: load_depictio_data_sync TOTAL took {total_duration_ms:.1f}ms "
            f"(fetch={fetch_duration_ms:.1f}ms, parse={parsing_duration_ms:.1f}ms, "
            f"render={render_duration_ms:.1f}ms, convert={convert_duration_ms:.1f}ms)"
        )

        return dashboard_data
    else:
        return None
