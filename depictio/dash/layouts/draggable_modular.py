"""
Modular Draggable Layout System

This module provides a refactored approach to the draggable layout management
with separated callbacks for different operations to reduce complexity and
improve maintainability.

Key principles:
- Single responsibility per callback
- One output per callback to reduce callback tree complexity
- Independent operations that can be composed
- Compatible with future background/progress callbacks
- Synchronous operations for now (async-ready design)
"""

import time

import dash
from dash import ALL, MATCH, Input, Output, State, dcc, html

from depictio.api.v1.configs.logging_init import logger

# Removed unused imports


def _load_dashboard_data_lightweight(dashboard_id: str, access_token: str):
    """
    Lightweight dashboard data loader - extracts only essential data without rendering.

    This replaces the heavy load_depictio_data_sync approach with a focused data extraction
    that only gets what the modular system needs.
    """
    from depictio.dash.api_calls import api_call_get_dashboard
    from depictio.models.models.dashboards import DashboardData

    logger.info(f"🔄 Loading dashboard data (lightweight) for {dashboard_id}")

    if not access_token:
        logger.warning("No access token provided for dashboard data loading")
        return None

    # Fetch dashboard data from API
    dashboard_data_dict = api_call_get_dashboard(dashboard_id, access_token)
    if not dashboard_data_dict:
        logger.warning(f"Failed to fetch dashboard data for {dashboard_id}")
        return None

    # Convert to dashboard model
    dashboard_data = DashboardData.from_mongo(dashboard_data_dict)
    logger.info(f"DashboardData: {dashboard_data}")
    if not dashboard_data:
        logger.warning(f"Failed to parse dashboard data for {dashboard_id}")
        return None

    logger.info(f"✅ Dashboard data loaded successfully for {dashboard_id}")
    return dashboard_data


# ============================================================================
# TRIGGER SYSTEM - Light callbacks for coordination
# ============================================================================


def register_trigger_callbacks(app):
    """Register minimal trigger callback - just URL for now."""

    @app.callback(
        Output({"type": "component-render-trigger", "index": ALL}, "data"),
        [
            Input("url", "pathname"),
            Input("stored-component-metadata", "data"),
        ],
        prevent_initial_call=False,
    )
    def trigger_component_updates(pathname, stored_component_metadata):
        """Minimal trigger callback - updates all component triggers on URL change."""
        logger.info(f"🔥 TRIGGER_COMPONENT_UPDATES - URL changed: {pathname}")

        if not stored_component_metadata:
            logger.info("🔥 No metadata available, returning empty list")
            return []

        # Extract current dashboard metadata to determine number of components
        current_pathname = pathname.split("/")[-1] if pathname else "default"
        current_dashboard_metadata = stored_component_metadata.get(current_pathname, {})
        num_components = len(current_dashboard_metadata)

        if num_components == 0:
            logger.info("🔥 No components found, returning empty list")
            return []

        trigger_data = {
            "pathname": pathname,
            "timestamp": time.time(),
            "needs_update": True,
        }

        logger.info(f"🔥 Sending trigger to {num_components} components: {trigger_data}")
        return [trigger_data] * num_components


def register_metadata_callbacks(app):
    """Register callbacks for component metadata management (add/edit/remove)."""

    @app.callback(
        Output("stored-component-metadata", "data", allow_duplicate=True),
        [
            Input({"type": "btn-done", "index": ALL}, "n_clicks"),
            Input({"type": "btn-done-edit", "index": ALL}, "n_clicks"),
            Input({"type": "duplicate-box-button", "index": ALL}, "n_clicks"),
            Input({"type": "remove-box-button", "index": ALL}, "n_clicks"),
        ],
        [
            State("stored-component-metadata", "data"),
            Input("url", "pathname"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_component_metadata(
        btn_done_clicks,
        btn_edit_clicks,
        duplicate_clicks,
        remove_clicks,
        stored_metadata,
        pathname,
        local_data,
    ):
        """Handle component metadata operations - simplified version."""
        if not local_data:
            return dash.no_update

        # TODO: Implement basic metadata operations
        # For now, just log the operation
        logger.info("🔄 Component metadata operation detected")
        logger.info(f"   Dashboard: {pathname}")
        logger.info(
            f"   Current metadata keys: {list(stored_metadata.keys()) if stored_metadata else 'None'}"
        )

        # Return unchanged for now - will implement operations as needed
        return stored_metadata or {}

    @app.callback(
        Output("stored-component-metadata", "data", allow_duplicate=True),
        Input("url", "pathname"),
        [
            State("local-store", "data"),
            State("stored-component-metadata", "data"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def load_metadata_from_database(pathname, local_data, current_stored_metadata):
        """Load component metadata from database on dashboard navigation."""
        if not pathname or not local_data:
            return dash.no_update

        dashboard_id = pathname.split("/")[-1] if "/" in pathname else pathname

        # Skip if not a dashboard URL
        if not dashboard_id or dashboard_id == "dashboard":
            return dash.no_update

        # Skip if we already have metadata for this dashboard
        if current_stored_metadata and dashboard_id in current_stored_metadata:
            current_metadata = current_stored_metadata.get(dashboard_id, {})
            if isinstance(current_metadata, dict) and len(current_metadata) > 0:
                logger.info(
                    f"🔍 Already have {len(current_metadata)} components for {dashboard_id}"
                )
                return dash.no_update

        # Load from database
        try:
            TOKEN = local_data.get("access_token")
            if not TOKEN:
                logger.warning("No access token for metadata loading")
                return dash.no_update

            dashboard_data = _load_dashboard_data_lightweight(dashboard_id, TOKEN)
            if not dashboard_data:
                return dash.no_update

            logger.info(f"Loaded dashboard data: {dashboard_data}")
            logger.info(f"Loaded metadata: {dashboard_data}")

            stored_metadata = getattr(dashboard_data, "stored_metadata", [])
            if not stored_metadata:
                logger.info(f"No metadata in database for {dashboard_id}")
                return dash.no_update

            # Convert list to dict format {component_uuid: metadata}
            metadata_dict = {}
            for metadata_item in stored_metadata:
                if hasattr(metadata_item, "model_dump"):
                    metadata_dict_item = metadata_item.model_dump()
                elif isinstance(metadata_item, dict):
                    metadata_dict_item = metadata_item
                else:
                    continue

                if "index" in metadata_dict_item:
                    component_uuid = metadata_dict_item["index"]
                    metadata_dict[component_uuid] = metadata_dict_item

            logger.info(f"✅ Loaded {len(metadata_dict)} components for {dashboard_id}")

            # Update session store
            updated_stored_metadata = (
                current_stored_metadata.copy() if current_stored_metadata else {}
            )
            updated_stored_metadata[dashboard_id] = metadata_dict
            return updated_stored_metadata

        except Exception as e:
            logger.error(f"❌ Failed to load metadata: {e}")
            return dash.no_update


# ============================================================================
# MAIN REGISTRATION FUNCTION
# ============================================================================


def create_modular_dashboard_layout(dashboard_id, local_data=None, theme="light"):
    """Create minimal dashboard layout."""
    logger.info(f"🏗️ Creating minimal modular dashboard layout for {dashboard_id}")

    import dash_dynamic_grid_layout as dgl

    draggable = dgl.DashGridLayout(
        id="draggable",
        items=[
            # dgl.DraggableWrapper(
            #     html.Div("TEST", id="test")
            # )
        ],
        itemLayout=[],
        # itemLayout=[{"i": "test", "x": 0, "y": 0, "w": 1, "h": 1}],
        rowHeight=50,  # Larger row height for better component display
        cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
        showRemoveButton=False,  # Keep consistent - CSS handles visibility
        showResizeHandles=True,  # Enable resize functionality for vertical growing behavior
        className="draggable-grid-container",  # CSS class for styling
        allowOverlap=False,
        # Additional parameters to try to disable responsive scaling
        autoSize=True,  # Let grid auto-size instead of using responsive breakpoints
        style={
            # "display": display_style,
            "flex-grow": 1,
            "width": "100%",
            "height": "auto",
        },
    )

    # Minimal layout components
    layout_components = [
        # Essential stores only
        dcc.Store(id="local-store", data=local_data or {}),
        dcc.Store(id="stored-component-metadata", data={}),
        # Main dashboard content area
        html.Div(
            id="page-content",
            children=draggable,
            # children=[
            #     html.Div(
            #         id="draggable",
            #         children=[],  # Component containers will be added here
            #         style={"min-height": "400px", "padding": "10px"},
            #     )
            # ],
        ),
    ]

    return html.Div(layout_components)


def create_component_containers_from_metadata(stored_metadata, local_data):
    """Create empty component containers for modular rendering with ResponsiveWrapper."""
    logger.info(f"🏗️ Creating {len(stored_metadata)} component containers with ResponsiveWrapper")

    containers = []
    for metadata in stored_metadata:
        component_uuid = metadata.get("index", "unknown")
        # component_type = metadata.get("component_type", "unknown")  # Unused for now
        box_uuid = f"box-{component_uuid}"

        # Create metadata store for this component (required by callbacks)
        # This ensures the store exists before individual callbacks try to access it
        metadata_store = dcc.Store(
            id={"type": "stored-metadata-component", "index": component_uuid},
            data=metadata,
            storage_type="memory",
        )

        # Create component-specific render trigger store
        component_trigger_store = dcc.Store(
            id={"type": "component-render-trigger", "index": component_uuid},
            data={},
            storage_type="memory",
        )
        logger.info(f"Created component trigger store for {component_uuid}")

        # Create inner component container
        component_container = html.Div(
            id={"type": "component", "index": component_uuid},
            # children=f"Loading {component_type} component...",
            style={"width": "100%", "height": "100%"},
        )

        # Create content div with proper responsive-content class
        content_div = html.Div(
            # [component_container],
            [component_container, metadata_store, component_trigger_store],
            id=f"content-{box_uuid}",
            # className="dashboard-component-hover responsive-content",
            # style={
            #     "overflow": "visible",
            #     "width": "100%",
            #     "height": "100%",
            #     "boxSizing": "border-box",
            #     "padding": "5px",
            #     "border": "1px solid transparent",
            #     "borderRadius": "8px",
            #     "position": "relative",
            #     "minHeight": "100px",
            #     "transition": "all 0.3s ease",
            #     "display": "flex",
            #     "flexDirection": "column",
            # },
        )

        # Import DraggableWrapper
        # import dash_dynamic_grid_layout as dgl

        # Create DraggableWrapper with the UUID as ID (like in edit.py)
        # draggable_wrapper = dgl.DraggableWrapper(
        #     id=box_uuid,  # Use UUID as ID for layout tracking
        #     children=[content_div],
        #     handleText="Drag",  # Handle text for dragging
        # )
        from depictio.dash.layouts.edit import enable_box_edit_mode

        draggable_wrapper = enable_box_edit_mode(
            box=content_div,
            dashboard_id=box_uuid,
            component_data=metadata,
            TOKEN=local_data.get("access_token") if local_data else None,
        )

        # Wrap with ResponsiveWrapperadmin for dash-dynamic-grid-layout compatibility
        # responsive_wrapper = html.Div(
        #     draggable_wrapper,
        #     id=box_uuid,  # This is the ID that grid layout uses - CRITICAL: Same ID as DraggableWrapper
        #     className="responsive-wrapper",  # Critical: This class makes it work!
        #     style={
        #         "position": "relative",
        #         "width": "100%",
        #         "height": "100%",
        #         "display": "flex",
        #         "flexDirection": "column",
        #         "flex": "1",  # Critical: Allow vertical growing
        #     },
        # )

        # NOTE: Don't create metadata_store here - component build functions create them
        # to avoid duplicate stores error

        containers.append(draggable_wrapper)

    logger.info(f"✅ Created {len(containers)} component containers with ResponsiveWrapper")
    return containers


def register_modular_draggable_callbacks(app):
    """
    Register minimal modular draggable callbacks.

    Minimal structure:
    - Central trigger callback (URL-based)
    - Component metadata management (add/edit/remove)
    - Component container creation
    - Individual component callbacks (registered separately)
    """
    logger.info("🔧 Registering minimal modular callback system")

    # Register minimal callback groups
    register_trigger_callbacks(app)  # Central trigger with component-specific outputs
    register_metadata_callbacks(app)  # Component metadata operations
    _register_component_container_callback(app)  # Container creation
    _register_centralized_component_callback(app)  # MATCH-based component rendering

    logger.info("✅ Minimal modular callback system registered")


def _register_centralized_component_callback(app):
    """Register MATCH-based callback for component rendering with enable_box_edit_mode."""

    @app.callback(
        [
            Output({"type": "component", "index": MATCH}, "children", allow_duplicate=True),
            Output(
                {"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True
            ),
        ],
        Input({"type": "component-render-trigger", "index": MATCH}, "data"),
        [
            State("local-store", "data"),
            State(
                {"type": "stored-metadata-component", "index": MATCH}, "data", allow_optional=True
            ),
            State("url", "pathname"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def update_component_and_metadata(trigger, local_data, metadata, pathname):
        """Handle component rendering using MATCH pattern with enable_box_edit_mode integration."""

        logger.info("🎯 MATCH CALLBACK: Component update triggered")
        logger.info(f"Trigger data: {trigger}")
        logger.info(f"Metadata available: {metadata is not None}")

        if not trigger or not local_data or not metadata:
            logger.info("🎯 MATCH CALLBACK: Missing data, skipping")
            return dash.no_update, dash.no_update

        # Only handle card and interactive components for now
        component_type = metadata.get("component_type")
        if component_type not in ["card", "interactive"]:
            logger.info(f"🎯 MATCH CALLBACK: Skipping {component_type} component")
            return dash.no_update, dash.no_update

        # Extract component info
        dashboard_id = pathname.split("/")[-1] if pathname else "default"
        TOKEN = local_data.get("access_token")
        meta_index = metadata.get("index")

        logger.info(f"🎯 MATCH CALLBACK: Updating {component_type} component {meta_index}")

        try:
            # Extract interactive filters from trigger data (for future use)
            interactive_filters = None
            if trigger and isinstance(trigger, dict):
                interactive_filters = trigger.get("interactive_filters", {})
                if interactive_filters:
                    logger.info(f"🎯 Received {len(interactive_filters)} interactive filters")

            # Route to appropriate build function based on component type
            if component_type == "card":
                from depictio.dash.modules.card_component.utils import build_card

                updated_component, store_component = build_card(
                    index=meta_index,
                    title=metadata.get("title"),
                    wf_id=metadata.get("wf_id"),
                    dc_id=metadata.get("dc_id"),
                    dc_config=metadata.get("dc_config"),
                    column_name=metadata.get("column_name"),
                    column_type=metadata.get("column_type"),
                    aggregation=metadata.get("aggregation"),
                    v=metadata.get("value", metadata.get("v")),
                    color=metadata.get("color"),
                    cols_json=metadata.get("cols_json", {}),
                    interactive_filters=interactive_filters,  # Pass interactive filters
                    access_token=TOKEN,
                    dashboard_id=dashboard_id,
                )

            elif component_type == "interactive":
                from depictio.dash.modules.interactive_component.utils import build_interactive

                updated_component, store_component = build_interactive(
                    index=meta_index,
                    title=metadata.get("title"),
                    wf_id=metadata.get("wf_id"),
                    dc_id=metadata.get("dc_id"),
                    column_name=metadata.get("column_name"),
                    interactive_component_type=metadata.get("interactive_component_type"),
                    access_token=TOKEN,
                    build_frame=False,
                )

            else:
                logger.warning(f"🎯 Unsupported component type: {component_type}")
                return dash.no_update, dash.no_update

            # Apply enable_box_edit_mode integration
            # if updated_component:
            #     try:
            #         from depictio.dash.layouts.edit import enable_box_edit_mode

            #         updated_component = enable_box_edit_mode(
            #             box=updated_component,
            #             dashboard_id=dashboard_id,
            #             component_data=metadata,
            #             TOKEN=TOKEN,
            #         )
            #         # import dash_dynamic_grid_layout as dgl

            #         # updated_component = dgl.DraggableWrapper(
            #         #     children=updated_component,
            #         #     id=f"draggable-{component_type}-{meta_index}"
            #         # )
            #         logger.info(f"✅ {component_type} component {meta_index} updated with edit mode")
            #     except ImportError as ie:
            #         logger.warning(f"⚠️ Could not import enable_box_edit_mode: {ie}")
            #         logger.info(f"✅ {component_type} component {meta_index} updated without edit mode")

            return updated_component, store_component.data if hasattr(
                store_component, "data"
            ) else store_component
            # else:
            #     logger.warning(f"⚠️ Failed to build {component_type} component {meta_index}")
            #     return dash.no_update, dash.no_update

        except Exception as e:
            logger.error(f"❌ Error updating {component_type} component {meta_index}: {e}")
            return dash.no_update, dash.no_update

    # @app.callback(
    #     # [
    #     #     Output({"type": "component", "index": MATCH}, "children"),
    #     #     Output(
    #     #         {"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True
    #     #     ),
    #     # ],
    #     Input("component-render-trigger", "data"),
    #     State({"type": "stored-metadata-component", "index": MATCH}, "data"),
    #     State("local-store", "data"),
    #     State("url", "pathname"),
    #     # prevent_initial_call=True,
    # )
    # def update_component_and_metadata(trigger, all_metadata, local_data, pathname):
    #     """Handle both component rendering and metadata updates in single callback."""

    #     logger.info("🎯 CENTRALIZED CALLBACK: Triggered for component update")
    #     logger.info(f"Trigger data: {trigger}")
    #     logger.info(f"All metadata: {all_metadata}")

    #     if not trigger or not all_metadata:
    #         logger.info("🎯 CENTRALIZED CALLBACK: No trigger or metadata, skipping")
    #         return [dash.no_update] * len(all_metadata), [dash.no_update] * len(all_metadata)

    #     components = []
    #     metadata_updates = []

    #     for metadata in all_metadata:
    #         if not metadata:
    #             components.append(dash.no_update)
    #             metadata_updates.append(dash.no_update)
    #             continue

    #     component_type = metadata.get("component_type")
    #     meta_index = metadata.get("index", "unknown")

    #     logger.info(f"🎯 CENTRALIZED CALLBACK: Updating {component_type} component {meta_index}")

    #     # Route to appropriate build function based on component type
    #     if component_type == "card":
    #         from depictio.dash.modules.card_component.utils import build_card

    #         component, store = build_card(
    #             index=meta_index,
    #             title=metadata.get("title"),
    #             wf_id=metadata.get("wf_id"),
    #             dc_id=metadata.get("dc_id"),
    #             dc_config=metadata.get("dc_config"),
    #             column_name=metadata.get("column_name"),
    #             column_type=metadata.get("column_type"),
    #             aggregation=metadata.get("aggregation"),
    #             v=metadata.get("value"),
    #             access_token=local_data.get("access_token") if local_data else None,
    #             build_frame=False,
    #         )
    #         return component, store.data

    #     elif component_type == "figure":
    #         from depictio.dash.modules.figure_component.utils import build_figure

    #         component, store = build_figure(
    #             index=meta_index,
    #             title=metadata.get("title"),
    #             wf_id=metadata.get("wf_id"),
    #             dc_id=metadata.get("dc_id"),
    #             figure_config=metadata.get("figure_config", {}),
    #             access_token=local_data.get("access_token") if local_data else None,
    #             build_frame=False,
    #         )
    #         return component, store.data

    #     elif component_type == "table":
    #         from depictio.dash.modules.table_component.utils import build_table

    #         component, store = build_table(
    #             index=meta_index,
    #             title=metadata.get("title"),
    #             wf_id=metadata.get("wf_id"),
    #             dc_id=metadata.get("dc_id"),
    #             cols_json=metadata.get("cols_json", {}),
    #             access_token=local_data.get("access_token") if local_data else None,
    #             build_frame=False,
    #         )
    #         return component, store.data

    #     elif component_type == "interactive":
    #         from depictio.dash.modules.interactive_component.utils import build_interactive

    #         component, store = build_interactive(
    #             index=meta_index,
    #             title=metadata.get("title"),
    #             wf_id=metadata.get("wf_id"),
    #             dc_id=metadata.get("dc_id"),
    #             column_name=metadata.get("column_name"),
    #             interactive_component_type=metadata.get("interactive_component_type"),
    #             access_token=local_data.get("access_token") if local_data else None,
    #             build_frame=False,
    #         )
    #         return component, store.data

    #     elif component_type == "text":
    #         from depictio.dash.modules.text_component.utils import build_text

    #         component, store = build_text(
    #             index=meta_index,
    #             title=metadata.get("title"),
    #             content=metadata.get("content", ""),
    #             build_frame=False,
    #         )
    #         return component, store.data

    #     elif component_type == "jbrowse":
    #         from depictio.dash.modules.jbrowse_component.utils import build_jbrowse

    #         component, store = build_jbrowse(
    #             index=meta_index,
    #             title=metadata.get("title"),
    #             wf_id=metadata.get("wf_id"),
    #             dc_id=metadata.get("dc_id"),
    #             access_token=local_data.get("access_token") if local_data else None,
    #             build_frame=False,
    #         )
    #         return component, store.data

    #     else:
    #         logger.warning(f"Unknown component type: {component_type}")
    #         return f"Unknown component type: {component_type}", metadata


def _register_component_container_callback(app):
    """Register callback to create component containers when metadata is loaded."""

    @app.callback(
        [Output("draggable", "items"), Output("draggable", "layouts")],
        [Input("stored-component-metadata", "data")],
        [Input("url", "pathname"), Input("local-store", "data")],
        prevent_initial_call=False,
    )
    def update_draggable_containers(metadata_dict, pathname, local_data):
        """Create component containers when metadata is available."""
        logger.info("🏗️ Updating draggable containers from metadata")
        logger.info(f"Pathname: {pathname}")
        logger.info(f"Metadata : {metadata_dict}")

        if not metadata_dict or not pathname:
            logger.info("No metadata or pathname available, returning empty containers")
            return [], []

        dashboard_id = pathname.split("/")[-1]
        stored_metadata = (
            list(metadata_dict[dashboard_id].values()) if dashboard_id in metadata_dict else []
        )

        if not stored_metadata:
            logger.info("No valid metadata found, returning empty containers")
            return []

        logger.info(f"Creating containers for {len(stored_metadata)} components")
        containers = create_component_containers_from_metadata(stored_metadata, local_data)
        logger.info(f"Containers created: {containers}")
        layouts = [
            {
                "i": f"box-{metadata.get('index', 'unknown')}",
                "x": metadata.get("x", 0),
                "y": metadata.get("y", 0),
                "w": metadata.get("w", 2),
                "h": metadata.get("h", 2),
            }
            for metadata in stored_metadata
        ]

        # import dash_dynamic_grid_layout as dgl
        # containers = [dgl.DraggableWrapper(html.Div("TEST", id="test"))]

        # layouts = [{ "id": "test", "x": 0, "y": 0, "w": 1, "h": 1 }]
        # logger.info(f"Layouts created: {layouts}")
        # logger.info(f"Containers created: {containers}")
        return containers, layouts


# ============================================================================
# MIGRATION UTILITIES
# ============================================================================


def create_hidden_stores_for_triggers():
    """Create the hidden stores needed for the trigger system."""
    return [
        dcc.Store(id="component-render-trigger", data={}),
        dcc.Store(id="layout-update-trigger", data={}),
    ]
