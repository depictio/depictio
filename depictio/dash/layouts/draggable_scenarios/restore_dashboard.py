from dash import html

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_fetch_project_by_id,
    api_call_fetch_user_from_token,
    api_call_get_dashboard,
)
from depictio.dash.component_metadata import DISPLAY_NAME_TO_TYPE_MAPPING, get_build_functions
from depictio.models.models.dashboards import DashboardData
from depictio.models.utils import convert_model_to_dict

# Get build functions from centralized metadata
build_functions = get_build_functions()


def _fetch_table_columns(child_metadata: dict, token: str) -> dict:
    """Fetch column definitions for a table component from data collection.

    Args:
        child_metadata: Component metadata containing wf_id and dc_id
        token: Access token for API authentication

    Returns:
        Column definitions dict, empty dict on failure
    """
    wf_id = child_metadata.get("wf_id")
    dc_id = child_metadata.get("dc_id")

    if not wf_id or not dc_id:
        return {}

    from depictio.dash.utils import get_columns_from_data_collection

    try:
        cols_json = get_columns_from_data_collection(wf_id, dc_id, token)
        logger.info(f"Fetched {len(cols_json)} columns for table component")
        return cols_json
    except Exception as e:
        logger.error(f"Failed to fetch cols_json for table: {e}")
        return {}


def _fetch_multiqc_metadata_from_dc(
    project_id: str, workflow_id: str, data_collection_id: str, token: str
) -> dict:
    """Fetch MultiQC metadata from data collection's dc_specific_properties.

    Args:
        project_id: Project ID
        workflow_id: Workflow ID
        data_collection_id: Data collection ID
        token: Access token for API authentication

    Returns:
        Dict with s3_locations and metadata fields, empty dict on failure
    """
    if not all([project_id, workflow_id, data_collection_id]):
        return {}

    try:
        # Fetch project data to get dc_specific_properties
        # Use skip_enrichment=True to get simple structure without delta_location aggregation
        project_data = api_call_fetch_project_by_id(project_id, token, skip_enrichment=True)
        if not project_data:
            logger.debug(f"No project data for {project_id}")
            return {}

        # Find the data collection in the project
        workflows = project_data.get("workflows", [])
        logger.debug(
            f"Project workflows type: {type(workflows)}, count: {len(workflows) if isinstance(workflows, list) else 'N/A'}"
        )
        if workflows and len(workflows) > 0:
            logger.debug(f"First workflow type: {type(workflows[0])}")

        for workflow in workflows:
            # Handle both dict and string workflow IDs
            if isinstance(workflow, dict):
                workflow_id_str = (
                    str(workflow.get("_id", {}).get("$oid", ""))
                    if isinstance(workflow.get("_id"), dict)
                    else str(workflow.get("_id", ""))
                )
            elif isinstance(workflow, str):
                workflow_id_str = workflow
                logger.warning(
                    f"Workflow is a string, not a dict. This is unexpected. Value: {workflow}"
                )
                continue  # Skip string workflows as they can't contain data collections
            else:
                logger.warning(f"Unexpected workflow type: {type(workflow)}")
                continue

            if workflow_id_str == str(workflow_id):
                data_collections = workflow.get("data_collections", [])
                logger.debug(
                    f"Found matching workflow, data_collections count: {len(data_collections)}"
                )

                for dc in data_collections:
                    # Handle both dict and string DC IDs
                    if isinstance(dc, dict):
                        dc_id_str = (
                            str(dc.get("_id", {}).get("$oid", ""))
                            if isinstance(dc.get("_id"), dict)
                            else str(dc.get("_id", ""))
                        )
                    else:
                        logger.warning(f"Unexpected DC type: {type(dc)}")
                        continue

                    if dc_id_str == str(data_collection_id):
                        # Extract dc_specific_properties
                        dc_specific_props = dc.get("config", {}).get("dc_specific_properties", {})
                        if not dc_specific_props:
                            logger.debug(f"No dc_specific_properties for DC {data_collection_id}")
                            return {}

                        # Extract MultiQC metadata
                        result = {}

                        # Get s3_location (single location) and convert to list
                        s3_location = dc_specific_props.get("s3_location")
                        if s3_location:
                            result["s3_locations"] = [s3_location]
                            logger.info(
                                f"Found S3 location in dc_specific_properties: {s3_location}"
                            )

                        # Fallback: query multiqc reports API when s3_location is missing from project
                        if not result.get("s3_locations"):
                            try:
                                import httpx

                                api_base_url = settings.fastapi.internal_url
                                reports_response = httpx.get(
                                    f"{api_base_url}/depictio/api/v1/multiqc/reports/data-collection/{data_collection_id}",
                                    headers={"Authorization": f"Bearer {token}"},
                                    timeout=10,
                                )
                                if reports_response.status_code == 200:
                                    reports_data = reports_response.json()
                                    s3_locs = [
                                        r.get("report", {}).get("s3_location")
                                        for r in reports_data.get("reports", [])
                                        if r.get("report", {}).get("s3_location")
                                    ]
                                    if s3_locs:
                                        result["s3_locations"] = s3_locs
                                        logger.info(
                                            f"Found {len(s3_locs)} S3 location(s) from multiqc reports API"
                                        )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to fetch MultiQC reports for DC {data_collection_id}: {e}"
                                )

                        # Get metadata (modules, plots, samples)
                        metadata = {}
                        if dc_specific_props.get("modules"):
                            metadata["modules"] = dc_specific_props["modules"]
                        if dc_specific_props.get("plots"):
                            metadata["plots"] = dc_specific_props["plots"]
                        if dc_specific_props.get("samples"):
                            metadata["samples"] = dc_specific_props["samples"]

                        if metadata:
                            result["metadata"] = metadata
                            logger.info(
                                f"Found MultiQC metadata: {len(metadata.get('modules', []))} modules, "
                                f"{len(metadata.get('samples', []))} samples"
                            )

                        return result

        logger.debug(f"Data collection {data_collection_id} not found in project {project_id}")
        return {}

    except Exception as e:
        logger.error(
            f"Failed to fetch MultiQC metadata from dc_specific_properties: {e}",
            exc_info=True,
        )
        return {}


# DEBUGGING: Test flag to use simple DMC layout instead of draggable grid
# Set to True to test if component disappearance is related to grid layout system
# NOTE: "Simple layout" = NEW dual-panel DashGridLayout system with saved positions
# False = OLD ReactGridLayout single-panel system (deprecated)
USE_SIMPLE_LAYOUT_FOR_TESTING = True  # ENABLED - Use new dual-panel grid system


def render_dashboard(
    stored_metadata,
    edit_components_button,
    dashboard_id,
    theme,
    TOKEN,
    init_data=None,
    project_id=None,
):
    """
    Render dashboard components using build functions.

    Creates UI components with pattern-matching callback IDs for automatic population.
    Build functions create placeholders ("...") - callbacks populate actual values.

    Expected timing: ~150ms for structure, callbacks populate content in parallel

    Args:
        stored_metadata: List of component metadata dicts
        edit_components_button: Edit mode button state
        dashboard_id: Dashboard ObjectId
        theme: Theme name ("light" or "dark")
        TOKEN: Access token
        init_data: Optional consolidated init data for API optimization
        project_id: Optional project ID for cross-DC link resolution

    Returns:
        List of rendered components with callback infrastructure
    """
    from depictio.dash.layouts.draggable import clean_stored_metadata
    from depictio.dash.layouts.edit import enable_box_edit_mode

    stored_metadata = clean_stored_metadata(stored_metadata)

    # Reset build counts at start of dashboard render
    if "_reset_counts" in build_functions:
        build_functions["_reset_counts"]()

    # Extract delta_locations from init_data (contains dc_type for MultiQC detection)
    delta_locations = {}
    if init_data:
        delta_locations = init_data.get("delta_locations", {})

    children = []
    for child_metadata in stored_metadata:
        # Add required fields
        child_metadata["build_frame"] = True
        child_metadata["access_token"] = TOKEN
        child_metadata["theme"] = theme
        # Add project_id for cross-DC link resolution (used by MultiQC and other components)
        if project_id:
            child_metadata["project_id"] = str(project_id)

        # Add component-specific init_data (delta location with dc_type for parquet detection)
        dc_id = child_metadata.get("dc_id")
        if dc_id and delta_locations:
            dc_id_str = str(dc_id)
            component_init_data = {}

            # Add delta location for this component's DC
            if dc_id_str in delta_locations:
                component_init_data[dc_id_str] = delta_locations[dc_id_str]

            # For joined DCs, add individual DC locations
            if isinstance(dc_id, str) and "--" in dc_id:
                for individual_dc_id in dc_id.split("--"):
                    if individual_dc_id in delta_locations:
                        component_init_data[individual_dc_id] = delta_locations[individual_dc_id]

            if component_init_data:
                child_metadata["init_data"] = component_init_data

        # Enrich MultiQC components with metadata from dc_specific_properties
        # This ensures s3_locations and metadata are populated even if dashboard was saved with empty values
        component_type = child_metadata.get("component_type")
        if component_type == "multiqc":
            # Check if metadata is missing or empty
            existing_metadata = child_metadata.get("metadata", {})
            existing_s3_locations = child_metadata.get("s3_locations", [])

            # Determine if we need to fetch from dc_specific_properties
            needs_enrichment = (
                not existing_s3_locations
                or not existing_metadata
                or (
                    isinstance(existing_metadata, dict)
                    and not existing_metadata.get("modules")
                    and not existing_metadata.get("samples")
                )
            )

            if needs_enrichment:
                workflow_id = child_metadata.get("wf_id") or child_metadata.get("workflow_id")
                data_collection_id = child_metadata.get("dc_id") or child_metadata.get(
                    "data_collection_id"
                )

                if project_id and workflow_id and data_collection_id:
                    logger.info(
                        f"Enriching MultiQC component from dc_specific_properties for DC {data_collection_id}"
                    )
                    enriched_data = _fetch_multiqc_metadata_from_dc(
                        str(project_id), str(workflow_id), str(data_collection_id), TOKEN
                    )

                    if enriched_data:
                        # Merge enriched data into child_metadata
                        if "s3_locations" in enriched_data:
                            child_metadata["s3_locations"] = enriched_data["s3_locations"]
                            logger.info(
                                f"✅ Enriched s3_locations: {len(enriched_data['s3_locations'])} locations"
                            )
                        if "metadata" in enriched_data:
                            child_metadata["metadata"] = enriched_data["metadata"]
                            logger.info(
                                f"✅ Enriched metadata: {len(enriched_data['metadata'].get('modules', []))} modules, "
                                f"{len(enriched_data['metadata'].get('samples', []))} samples"
                            )
                    else:
                        logger.warning(
                            f"⚠️  No enriched data found in dc_specific_properties for DC {data_collection_id}"
                        )

        # Get component type
        component_type = child_metadata.get("component_type")

        # Handle legacy type conversion
        if component_type not in build_functions and component_type in DISPLAY_NAME_TO_TYPE_MAPPING:
            component_type = DISPLAY_NAME_TO_TYPE_MAPPING[component_type]
            child_metadata["component_type"] = component_type

        if component_type not in build_functions:
            logger.warning(f"Unsupported component type: {component_type}")
            continue

        # Fetch cols_json for table components if empty
        if component_type == "table" and not child_metadata.get("cols_json"):
            child_metadata["cols_json"] = _fetch_table_columns(child_metadata, TOKEN)

        # Build component (creates placeholder UI with callback IDs)
        build_function = build_functions[component_type]
        child = build_function(**child_metadata)

        # Wrap with edit mode support
        wrapped = enable_box_edit_mode(
            child,
            switch_state=edit_components_button,
            dashboard_id=dashboard_id,
            component_data=child_metadata,
            TOKEN=TOKEN,
        )

        children.append(wrapped)

    return children


# =============================================================================
# RENDER DASHBOARD HELPER FUNCTIONS
# =============================================================================


def _extract_init_data_fields(init_data: dict | None) -> tuple[dict, dict, dict, dict]:
    """Extract fields from init_data for component builders.

    Args:
        init_data: Consolidated dashboard init data.

    Returns:
        Tuple of (delta_locations, column_specs, column_names, join_configs).
    """
    if not init_data:
        return {}, {}, {}, {}

    delta_locations = init_data.get("delta_locations", {})
    column_specs = init_data.get("column_specs", {})
    column_names = init_data.get("column_names", {})
    join_configs = init_data.get("join_configs", {})

    logger.info(
        f"📡 INIT DATA: Using consolidated data with {len(delta_locations)} delta locations, "
        f"{len(column_specs)} column specs"
    )
    return delta_locations, column_specs, column_names, join_configs


def _log_debug_metadata(stored_metadata: list) -> None:
    """Log first few metadata entries for debugging.

    Args:
        stored_metadata: List of component metadata dicts.
    """
    if not stored_metadata:
        return

    for i, elem in enumerate(stored_metadata[:3]):
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


def _enrich_component_metadata(
    child_metadata: dict,
    init_data: dict | None,
    delta_locations: dict,
    column_specs: dict,
    column_names: dict,
    join_configs: dict,
    TOKEN: str,
    theme: str,
) -> None:
    """Enrich component metadata with init_data and required fields.

    Args:
        child_metadata: Component metadata dict to enrich (modified in place).
        init_data: Consolidated init data.
        delta_locations: Delta location mappings.
        column_specs: Column spec mappings.
        column_names: Column name mappings.
        join_configs: Join configuration mappings.
        TOKEN: Access token.
        theme: Theme name.
    """
    child_metadata["build_frame"] = True
    child_metadata["access_token"] = TOKEN
    child_metadata["theme"] = theme

    dc_id = child_metadata.get("dc_id")
    if not init_data or not dc_id:
        return

    dc_id_str = str(dc_id)
    component_init_data = {}

    # Add delta location if available
    if dc_id_str in delta_locations:
        component_init_data[dc_id_str] = delta_locations[dc_id_str]

    # For joined DCs, add individual DC locations
    if isinstance(dc_id, str) and "--" in dc_id:
        for individual_dc_id in dc_id.split("--"):
            if individual_dc_id in delta_locations:
                component_init_data[individual_dc_id] = delta_locations[individual_dc_id]

    child_metadata["init_data"] = component_init_data

    # Add additional enriched fields if available
    if column_specs.get(dc_id_str):
        child_metadata["column_specs"] = column_specs[dc_id_str]
    if column_names.get(dc_id_str):
        child_metadata["column_names"] = column_names[dc_id_str]
    if dc_id_str in join_configs:
        child_metadata["join_config"] = join_configs[dc_id_str]


def _build_component(child_metadata: dict, token: str) -> tuple:
    """Build a single component from metadata.

    Args:
        child_metadata: Component metadata dict.
        token: Access token for API authentication.

    Returns:
        Tuple of (component, component_type, child_metadata).

    Raises:
        ValueError: If component type is unsupported.
    """
    component_type = child_metadata.get("component_type")

    # Log code mode figures for debugging
    if component_type == "figure" and child_metadata.get("mode") == "code":
        logger.info(
            f"🔍 RESTORE: Code mode figure from MongoDB: index={child_metadata.get('index')}"
        )

    # Handle legacy type conversion
    if component_type not in build_functions and component_type in DISPLAY_NAME_TO_TYPE_MAPPING:
        original_type = component_type
        component_type = DISPLAY_NAME_TO_TYPE_MAPPING[component_type]
        logger.debug(f"Converting legacy component type '{original_type}' to '{component_type}'")
        child_metadata["component_type"] = component_type

    if component_type not in build_functions:
        logger.warning(f"Unsupported child type: {component_type}")
        raise ValueError(f"Unsupported child type: {component_type}")

    # Fetch cols_json for table components if empty
    if component_type == "table" and not child_metadata.get("cols_json"):
        child_metadata["cols_json"] = _fetch_table_columns(child_metadata, token)

    build_function = build_functions[component_type]
    child = build_function(**child_metadata)
    return child, component_type, child_metadata


def _add_panel_metadata(children: list) -> None:
    """Add panel metadata to components for layout positioning.

    Args:
        children: List of (component, type, metadata) tuples.
    """
    logger.debug("🧪 PRE-PROCESSING: Adding panel metadata before component wrapping")
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


def _wrap_component_for_edit_mode(
    child, child_metadata: dict, edit_components_button, dashboard_id, TOKEN: str
) -> html.Div:
    """Wrap a component with edit mode controls.

    Args:
        child: The component to wrap.
        child_metadata: Component metadata.
        edit_components_button: Edit mode button state.
        dashboard_id: Dashboard ID.
        TOKEN: Access token.

    Returns:
        Wrapped component div.
    """
    from depictio.dash.layouts.edit import enable_box_edit_mode

    wrapped_component = enable_box_edit_mode(
        child,
        switch_state=edit_components_button,
        dashboard_id=dashboard_id,
        component_data=child_metadata,
        TOKEN=TOKEN,
    )

    return html.Div(
        wrapped_component,
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


def _create_two_panel_layout(children: list, processed_children: list) -> list[html.Div]:
    """Create the two-panel layout for simple layout mode.

    Args:
        children: List of (component, type, metadata) tuples.
        processed_children: List of processed component divs.

    Returns:
        List containing the two-panel layout div.
    """
    import dash_mantine_components as dmc

    logger.info("🧪 TESTING MODE: Using two-panel DMC layout instead of draggable grid")

    # Separate components by type
    interactive_components = []
    card_components = []
    other_components = []

    for i, (child, component_type, child_metadata) in enumerate(children):
        if component_type == "interactive":
            interactive_components.append(processed_children[i])
        elif component_type == "card":
            card_components.append(processed_children[i])
        else:
            other_components.append(processed_children[i])

    logger.info(f"🧪 Left panel (interactive): {len(interactive_components)} components")
    logger.info(f"🧪 Right panel: {len(card_components)} cards + {len(other_components)} other")

    # Create left panel
    left_panel_content = (
        dmc.Stack(interactive_components, gap=0, style={"width": "100%"})
        if interactive_components
        else dmc.Center(
            dmc.Text("No interactive components", size="sm", c="gray", style={"padding": "20px"}),
            style={"width": "100%", "height": "200px"},
        )
    )

    # Create right panel
    right_panel_children = []
    if card_components:
        cards_grid = dmc.SimpleGrid(
            card_components,
            cols=4,
            spacing=2,
            verticalSpacing=2,
            style={"width": "100%", "marginBottom": "2px"},
        )
        right_panel_children.append(cards_grid)
    if other_components:
        right_panel_children.extend(other_components)

    right_panel_content = (
        dmc.Stack(right_panel_children, gap=2, style={"width": "100%"})
        if right_panel_children
        else dmc.Center(
            dmc.Text("No components", size="sm", c="gray", style={"padding": "20px"}),
            style={"width": "100%", "height": "200px"},
        )
    )

    # Assemble two-panel layout
    two_panel_layout = html.Div(
        [
            dmc.Grid(
                [
                    dmc.GridCol(
                        left_panel_content,
                        span=1,
                        style={
                            "backgroundColor": "var(--app-surface-color, #f8f9fa)",
                            "padding": "4px",
                            "borderRadius": "4px",
                        },
                    ),
                    dmc.GridCol(
                        right_panel_content,
                        span=3,
                        style={"padding": "0px"},
                    ),
                ],
                columns=4,
                gutter="sm",
                style={"width": "100%"},
            ),
        ],
        id="simple-test-layout",
        style={
            "padding": "8px",
            "width": "100%",
            "maxWidth": "1920px",
            "margin": "0 auto",
            "backgroundColor": "var(--app-bg-color, #ffffff)",
        },
    )

    return [two_panel_layout]


def render_dashboard_original(
    stored_metadata, edit_components_button, dashboard_id, theme, TOKEN, init_data=None
):
    """Render dashboard components from stored metadata.

    BACKUP: Original full implementation of render_dashboard.

    Args:
        stored_metadata: List of component metadata dicts.
        edit_components_button: Edit mode button state.
        dashboard_id: Dashboard ObjectId.
        theme: Theme name ("light" or "dark").
        TOKEN: Access token.
        init_data: Optional consolidated dashboard init data from /dashboards/init endpoint.

    Returns:
        List of rendered Dash components.
    """
    import time

    from depictio.dash.layouts.draggable import clean_stored_metadata
    from depictio.dash.layouts.edit import enable_box_edit_mode

    start_time_total = time.time()

    # Extract init data fields
    delta_locations, column_specs, column_names, join_configs = _extract_init_data_fields(init_data)

    # Debug logging
    _log_debug_metadata(stored_metadata)

    # Clean metadata
    start_clean = time.time()
    stored_metadata = clean_stored_metadata(stored_metadata)
    logger.info(
        f"⏱️ PROFILING: clean_stored_metadata took {(time.time() - start_clean) * 1000:.1f}ms"
    )
    logger.info(
        f"📊 RESTORE DEBUG - After cleaning, metadata count: {len(stored_metadata) if stored_metadata else 0}"
    )

    # Build components
    children = []
    component_build_times = []

    for child_metadata in stored_metadata:
        start_component = time.time()

        # Enrich metadata
        _enrich_component_metadata(
            child_metadata,
            init_data,
            delta_locations,
            column_specs,
            column_names,
            join_configs,
            TOKEN,
            theme,
        )

        # Build component
        child, component_type, metadata = _build_component(child_metadata, TOKEN)
        children.append((child, component_type, metadata))

        component_build_times.append((time.time() - start_component) * 1000)
        logger.info(f"Using theme: {theme} for component {component_type}")

    # Add panel metadata for simple layout
    if USE_SIMPLE_LAYOUT_FOR_TESTING:
        _add_panel_metadata(children)

    # Process and wrap children
    processed_children = []
    for child, component_type, child_metadata in children:
        logger.debug(f"Processing child component of type {component_type}")

        if USE_SIMPLE_LAYOUT_FOR_TESTING:
            processed_child = _wrap_component_for_edit_mode(
                child, child_metadata, edit_components_button, dashboard_id, TOKEN
            )
        else:
            processed_child = enable_box_edit_mode(
                child,
                switch_state=edit_components_button,
                dashboard_id=dashboard_id,
                component_data=child_metadata,
                TOKEN=TOKEN,
            )
        processed_children.append(processed_child)

    # Log profiling info
    total_duration_ms = (time.time() - start_time_total) * 1000
    avg_time = (
        sum(component_build_times) / len(component_build_times) if component_build_times else 0
    )
    max_time = max(component_build_times) if component_build_times else 0

    logger.info(
        f"⏱️ PROFILING: render_dashboard TOTAL took {total_duration_ms:.1f}ms "
        f"for {len(processed_children)} components "
        f"(avg={avg_time:.1f}ms/component, max={max_time:.1f}ms)"
    )
    logger.info(
        f"✅ Dashboard restored with {len(processed_children)} components - "
        f"pattern-matching callbacks will populate values"
    )

    # Return appropriate layout
    if USE_SIMPLE_LAYOUT_FOR_TESTING:
        return _create_two_panel_layout(children, processed_children)

    return processed_children


def load_depictio_data(
    dashboard_id: str,
    local_data: dict,
    theme: str = "light",
    cached_user_data: dict | None = None,
    init_data: dict | None = None,
) -> dict | None:
    """Load the dashboard data from the API and render it.

    PERFORMANCE OPTIMIZATION (Phase 5A):
    - Added cached_user_data parameter to avoid redundant API call
    - User data already fetched by consolidated API callback

    PERFORMANCE OPTIMIZATION (API Consolidation):
    - Added init_data parameter from /dashboards/init endpoint
    - Contains enriched metadata, column specs, delta locations
    - Passed to render_dashboard to eliminate component-level API calls

    Args:
        dashboard_id (str): The ID of the dashboard to load.
        local_data (dict): Local data containing access token and other information.
        theme (str): The theme to use for rendering the dashboard.
        cached_user_data: Cached user data from consolidated API (avoids redundant fetch)
        init_data: Consolidated dashboard init data (enriched metadata, column specs, etc.)
    Returns:
        dict: The dashboard data with rendered children.
    Raises:
        ValueError: If the dashboard data cannot be fetched or is invalid.
    """
    # Ensure theme is valid
    if not theme or theme == {} or theme == "{}":
        theme = "light"

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

        # buttons = ["edit_components_button", "edit_dashboard_mode_button", "add_button"]
        # for button in buttons:
        #     if button not in dashboard_data["buttons_data"]:
        #         if button == "add_button":
        #             dashboard_data["buttons_data"][button] = {"count": 0}
        #         else:
        #             dashboard_data["buttons_data"][button] = True

        if hasattr(dashboard_data, "stored_metadata"):
            # PERFORMANCE OPTIMIZATION (Phase 5A): Use cached user data
            if cached_user_data:
                current_user = cached_user_data
            else:
                current_user = api_call_fetch_user_from_token(
                    local_data["access_token"]
                )  # Fallback only

            # Check if data is available, if not set the buttons to disabled
            # Note: current_user can be either a dict (from cache), User object (from API), or None
            # Handle all cases defensively
            if current_user is None:
                logger.warning("current_user is None - treating as non-owner viewer")
                current_user_id = ""
            else:
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
            children = render_dashboard(
                dashboard_data.stored_metadata,
                edit_components_button_checked,
                dashboard_id,
                theme,
                local_data["access_token"],
                init_data=init_data,  # Pass consolidated init data to components
                project_id=dashboard_data.project_id,  # Pass project_id for cross-DC link resolution
            )

            dashboard_data.stored_children_data = children

        dashboard_data = convert_model_to_dict(dashboard_data)

        return dashboard_data
    else:
        return None
