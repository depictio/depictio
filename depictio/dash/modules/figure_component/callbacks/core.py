"""
Figure Component - Core Rendering Callbacks

This module contains callbacks essential for rendering figures in view mode.
These callbacks are always loaded at app startup.

Phase 1: View mode only
- render_figures_batch: Batch rendering of all figures (ALL pattern)
- Theme-aware Plotly figure generation
- Filter integration via interactive-values-store
- Parallel data loading with deduplication

Callbacks:
- render_figures_batch: Compute and render all figures in single callback (batch optimization)
"""

import concurrent.futures
import hashlib
import json
import time
import uuid
from typing import Any

import dash
import plotly.express as px
import plotly.graph_objects as go
from bson import ObjectId
from dash import ALL, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.background_callback_helpers import (
    log_background_callback_status,
    should_use_background_for_component,
)
from depictio.dash.modules.figure_component.utils import _get_theme_template
from depictio.dash.utils import (
    extend_filters_via_links,
)

USE_BACKGROUND_CALLBACKS = should_use_background_for_component("figure")

LoadKey = tuple[str, str, str]  # (wf_id, dc_id, filters_hash)
LoadKeyExtended = tuple[str, str, str, str]  # (wf_id, dc_id, filters_hash, columns_hash)


def _build_metadata_index(
    interactive_metadata_list: list | None,
    interactive_metadata_ids: list | None,
) -> dict[str, dict]:
    """
    Build a mapping from component index to full metadata.

    Args:
        interactive_metadata_list: List of metadata dictionaries for interactive components
        interactive_metadata_ids: List of component IDs with index keys

    Returns:
        Dictionary mapping component index strings to their metadata
    """
    metadata_by_index: dict[str, dict] = {}
    if not interactive_metadata_list or not interactive_metadata_ids:
        return metadata_by_index

    for idx, meta_id in enumerate(interactive_metadata_ids):
        if idx < len(interactive_metadata_list):
            index = meta_id["index"]
            metadata_by_index[index] = interactive_metadata_list[idx]

    return metadata_by_index


def _enrich_filter_components(
    lightweight_components: list[dict],
    metadata_by_index: dict[str, dict],
) -> list[dict]:
    """
    Enrich lightweight filter components with full metadata.

    Handles both regular interactive components (metadata from stores) and
    selection sources (scatter_selection, table_selection) which have metadata
    embedded in the store entry itself.

    Args:
        lightweight_components: List of filter components with index and value
        metadata_by_index: Mapping from index to full metadata

    Returns:
        List of enriched components with full metadata attached
    """
    enriched_components = []
    for comp in lightweight_components:
        comp_index = comp.get("index")
        source = comp.get("source")

        # Handle selection sources (scatter_selection, table_selection)
        # These have metadata embedded directly in the store entry
        if source in ("scatter_selection", "table_selection"):
            selection_metadata = {
                "dc_id": comp.get("dc_id"),
                "column_name": comp.get("column_name"),
                "interactive_component_type": "MultiSelect",
                "source": source,
            }
            enriched_comp = {**comp, "metadata": selection_metadata}
            enriched_components.append(enriched_comp)
        else:
            # Regular interactive components need metadata lookup
            if comp_index is None:
                full_metadata: dict = {}
            else:
                full_metadata = metadata_by_index.get(str(comp_index), {})

            # Special handling for DateRangePicker values
            if full_metadata.get("interactive_component_type") == "DateRangePicker":
                value = comp.get("value")
                # Ensure value is a list of 2 string dates
                if value and not isinstance(value, list):
                    value = [value]
                if value and len(value) == 2:
                    # Skip if either value is None (incomplete selection)
                    if value[0] is None or value[1] is None:
                        # Keep original value to mark as inactive later
                        pass
                    else:
                        # Normalize to strings in YYYY-MM-DD format
                        normalized_value = []
                        for v in value:
                            # Handle ISO datetime strings (e.g., "2023-01-01T00:00:00")
                            if isinstance(v, str) and "T" in v:
                                normalized_value.append(v.split("T")[0])
                            else:
                                normalized_value.append(str(v))
                        comp = {**comp, "value": normalized_value}

            enriched_comp = {**comp, "metadata": full_metadata}
            enriched_components.append(enriched_comp)
    return enriched_components


def _group_filters_by_dc(components: list[dict]) -> dict[str, list[dict]]:
    """
    Group filter components by their data collection ID.

    Args:
        components: List of enriched filter components

    Returns:
        Dictionary mapping DC IDs to lists of filter components
    """
    filters_by_dc: dict[str, list[dict]] = {}
    for component in components:
        component_dc = str(component.get("metadata", {}).get("dc_id", ""))
        if component_dc:
            if component_dc not in filters_by_dc:
                filters_by_dc[component_dc] = []
            filters_by_dc[component_dc].append(component)
    return filters_by_dc


def _filter_active_components(components: list[dict]) -> list[dict]:
    """
    Filter out components with empty or null values.

    Args:
        components: List of filter components

    Returns:
        List of components with active (non-empty) values
    """
    active = []
    for c in components:
        value = c.get("value")
        metadata = c.get("metadata", {})

        # Special case: DateRangePicker with valid date range is active
        if metadata.get("interactive_component_type") == "DateRangePicker":
            # DateRangePicker is active if value exists and is a valid list of 2 non-None dates
            if (
                value
                and isinstance(value, list)
                and len(value) == 2
                and value[0] is not None
                and value[1] is not None
            ):
                active.append(c)
        # Generic case for other components
        elif value not in [None, [], "", False]:
            active.append(c)

    return active


def _extract_filters_for_figure(
    dc_id: str,
    filters_data: dict | None,
    interactive_metadata_list: list | None,
    interactive_metadata_ids: list | None,
    project_metadata: dict | None,
    batch_task_id: str,
    access_token: str | None = None,
) -> list[dict]:
    """
    Extract active filters for a specific figure's data collection.

    This function handles the complete filter extraction process including:
    - Building metadata index from interactive components
    - Enriching lightweight filter data with full metadata
    - Grouping filters by data collection
    - Including filters from source DCs for joined data collections
    - Including filters resolved via DC links (cross-DC filtering)

    Args:
        dc_id: The data collection ID for the figure
        filters_data: Filter state from interactive-values-store
        interactive_metadata_list: Full metadata for interactive components
        interactive_metadata_ids: IDs of interactive components
        project_metadata: Project metadata with join definitions and links
        batch_task_id: Task ID for logging
        access_token: Authentication token for link resolution API calls

    Returns:
        List of active filter components for this figure
    """
    if not filters_data or not filters_data.get("interactive_components_values"):
        return []

    metadata_by_index = _build_metadata_index(interactive_metadata_list, interactive_metadata_ids)

    lightweight_components = filters_data.get("interactive_components_values", [])

    enriched_components = _enrich_filter_components(lightweight_components, metadata_by_index)

    filters_by_dc = _group_filters_by_dc(enriched_components)

    card_dc_str = str(dc_id)
    relevant_filters = filters_by_dc.get(card_dc_str, [])

    # Include filters from source DCs if this figure uses a joined DC
    relevant_filters = _extend_filters_for_joined_dc(
        relevant_filters,
        card_dc_str,
        filters_by_dc,
        project_metadata,
        batch_task_id,
    )

    # Include filters resolved via DC links (cross-DC filtering without joins)
    link_resolved_filters = extend_filters_via_links(
        target_dc_id=card_dc_str,
        filters_by_dc=filters_by_dc,
        project_metadata=project_metadata,
        access_token=access_token,
        component_type="figure",
    )
    if link_resolved_filters:
        relevant_filters.extend(link_resolved_filters)

    active_filters = _filter_active_components(relevant_filters)

    return active_filters


def _compute_filters_hash(metadata_to_pass: list[dict]) -> str:
    """
    Compute a hash for a list of filter metadata.

    Args:
        metadata_to_pass: List of filter metadata dictionaries

    Returns:
        Short hash string for the filters, or 'nofilter' if empty
    """
    if not metadata_to_pass:
        return "nofilter"

    return hashlib.md5(
        json.dumps(metadata_to_pass, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]


def _build_dc_load_registry(
    trigger_data_list: list[dict | None],
    filters_data: dict | None,
    interactive_metadata_list: list | None,
    interactive_metadata_ids: list | None,
    project_metadata: dict | None,
    batch_task_id: str,
    access_token: str | None = None,
) -> tuple[dict[LoadKey, tuple[list[dict], list[str]]], dict[int, LoadKey | None]]:
    """
    Build registry of unique DC loads and map figures to their load keys.

    This function scans all figures to identify unique data load requirements,
    enabling deduplication and parallel loading optimization.

    Args:
        trigger_data_list: List of trigger data for each figure
        filters_data: Filter state from interactive-values-store
        interactive_metadata_list: Full metadata for interactive components
        interactive_metadata_ids: IDs of interactive components
        project_metadata: Project metadata with workflows, DCs, and links
        batch_task_id: Task ID for logging
        access_token: Authentication token for link resolution API calls

    Returns:
        Tuple of:
        - dc_load_registry: Dict mapping load keys to (filters, columns) tuples
        - figure_to_load_key: Dict mapping figure indices to their load keys
    """
    dc_load_registry: dict[LoadKey, tuple[list[dict], list[str]]] = {}
    figure_to_load_key: dict[int, LoadKey | None] = {}

    for i, trigger_data in enumerate(trigger_data_list):
        if not trigger_data or not isinstance(trigger_data, dict):
            figure_to_load_key[i] = None
            continue

        wf_id = trigger_data.get("wf_id")
        dc_id = trigger_data.get("dc_id")
        visu_type = trigger_data.get("visu_type", "scatter")
        dict_kwargs = trigger_data.get("dict_kwargs", {})

        if not wf_id or not dc_id:
            figure_to_load_key[i] = None
            continue

        # At this point wf_id and dc_id are guaranteed to be non-None
        wf_id_str = str(wf_id)
        dc_id_str = str(dc_id)

        required_columns = _extract_required_columns(dict_kwargs, visu_type)

        metadata_to_pass = _extract_filters_for_figure(
            dc_id_str,
            filters_data,
            interactive_metadata_list,
            interactive_metadata_ids,
            project_metadata,
            batch_task_id,
            access_token=access_token,
        )

        filters_hash = _compute_filters_hash(metadata_to_pass)
        load_key: LoadKey = (wf_id_str, dc_id_str, filters_hash)

        if load_key not in dc_load_registry:
            dc_load_registry[load_key] = (metadata_to_pass, required_columns)

        figure_to_load_key[i] = load_key

    return dc_load_registry, figure_to_load_key


def _load_dcs_parallel(
    dc_load_registry: dict[LoadKey, tuple[list[dict], list[str]]],
    access_token: str,
    batch_task_id: str,
) -> dict[LoadKey, Any]:
    """
    Load data collections in parallel using ThreadPoolExecutor.

    Args:
        dc_load_registry: Registry of unique DC loads with (filters, columns) tuples
        access_token: Authentication token for API calls
        batch_task_id: Task ID for logging

    Returns:
        Dictionary mapping load keys to loaded DataFrames
    """
    dc_cache: dict[LoadKey, Any] = {}

    def load_single_dc(
        load_key: LoadKey,
        metadata_to_pass: list[dict],
        required_columns: list[str],
    ) -> tuple[LoadKey, Any]:
        """Load a single DC with optional filters (thread-safe operation)."""
        wf_id, dc_id, filters_hash = load_key
        try:
            # NOTE: select_columns disabled - causes hang in ThreadPoolExecutor context
            data = load_deltatable_lite(
                ObjectId(wf_id),
                ObjectId(dc_id),
                metadata=metadata_to_pass,
                TOKEN=access_token,
            )
            return load_key, data
        except Exception as e:
            logger.error(f"   Parallel load failed: {dc_id[:8]}: {e}", exc_info=True)
            return load_key, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_key = {
            executor.submit(load_single_dc, load_key, metadata, columns): load_key
            for load_key, (metadata, columns) in dc_load_registry.items()
        }

        for future in concurrent.futures.as_completed(future_to_key):
            load_key, data = future.result()
            if data is not None:
                dc_cache[load_key] = data

    return dc_cache


def _process_code_mode_figure(
    code_content: str,
    df: Any,
    current_theme: str,
    task_id: str,
) -> tuple[bool, go.Figure | None, str | None]:
    """
    Process a figure in code mode by executing user-provided code.

    Args:
        code_content: User-provided Python code to execute
        df: DataFrame to pass to the code execution
        current_theme: Current theme name for styling
        task_id: Task ID for logging

    Returns:
        Tuple of (success, figure, visu_type):
        - success: Whether code execution succeeded
        - figure: The generated figure (or None on failure)
        - visu_type: Detected visualization type (or None on failure)
    """
    if not code_content:
        logger.error(f"[{task_id}] Code mode but no code_content")
        return False, None, None

    from depictio.dash.modules.figure_component.code_mode import (
        extract_visualization_type_from_code,
    )
    from depictio.dash.modules.figure_component.simple_code_executor import (
        SimpleCodeExecutor,
    )

    executor = SimpleCodeExecutor()
    success, fig, message = executor.execute_code(code_content, df)

    if not success:
        logger.error(f"[{task_id}] Code execution failed: {message}")
        return False, _create_error_figure(f"Code execution error: {message}", current_theme), None

    detected_visu_type = extract_visualization_type_from_code(code_content)

    if "template=" not in code_content:
        theme_template = f"mantine_{current_theme}"
        fig.update_layout(template=theme_template)

    return True, fig, detected_visu_type


def _process_single_figure(
    trigger_data: dict | None,
    trigger_id: dict,
    figure_index: int,
    dc_cache: dict[LoadKey, Any],
    figure_to_load_key: dict[int, LoadKey | None],
    current_theme: str,
    batch_task_id: str,
    stored_metadata: dict | None = None,
) -> tuple[dict | go.Figure, dict]:
    """
    Process a single figure and return the figure and metadata.

    Args:
        trigger_data: Trigger data containing figure parameters
        trigger_id: Component ID for the figure
        figure_index: Index of the figure in the batch
        dc_cache: Cache of loaded DataFrames keyed by load key
        figure_to_load_key: Mapping from figure index to load key
        current_theme: Current theme name
        batch_task_id: Task ID for logging
        stored_metadata: Stored component metadata (includes customizations)

    Returns:
        Tuple of (figure, metadata) where figure is a Plotly figure dict
        and metadata contains rendering information
    """
    task_id = f"{batch_task_id}-{figure_index}"
    component_id = trigger_id.get("index", "unknown")[:8] if trigger_id else "unknown"

    try:
        if not trigger_data or not isinstance(trigger_data, dict):
            logger.warning(f"[{task_id}] Invalid trigger data for figure {component_id}")
            return _create_error_figure("Invalid trigger data", current_theme), {}

        mode = trigger_data.get("mode", "ui")
        visu_type = trigger_data.get("visu_type", "scatter")
        dict_kwargs = trigger_data.get("dict_kwargs", {})
        code_content = trigger_data.get("code_content", "")

        # Extract customizations - PRIORITY ORDER:
        # 1. From trigger_data (guaranteed fresh from slider callback, bypasses State race condition)
        # 2. From stored_metadata (fallback for non-slider triggers)
        customizations = None

        # PRIORITY 1: Use customizations from trigger (guaranteed fresh from slider callback)
        if trigger_data.get("customizations"):
            customizations = trigger_data["customizations"]
            logger.warning(
                f"[{task_id}] 🔥 RENDER: Got customizations from TRIGGER "
                f"({len(customizations.get('highlights', []))} highlights)"
            )

        # PRIORITY 2: Fall back to stored metadata
        if not customizations and stored_metadata and isinstance(stored_metadata, dict):
            customizations = stored_metadata.get("customizations")
            if customizations:
                logger.debug(f"[{task_id}] Got customizations from stored_metadata")

        load_key = figure_to_load_key.get(figure_index)
        if not load_key or load_key not in dc_cache:
            logger.warning(f"[{task_id}] No cached data for figure {component_id}")
            return _create_error_figure("Data not available", current_theme), {}

        df = dc_cache[load_key]

        # Extract selection configuration
        selection_enabled = trigger_data.get("selection_enabled", False)
        selection_column = trigger_data.get("selection_column")

        if mode == "code":
            success, fig, detected_visu_type = _process_code_mode_figure(
                code_content, df, current_theme, task_id
            )
            if not success:
                return fig, {}
            if detected_visu_type:
                visu_type = detected_visu_type
            # Apply selection mode to code-generated figures if enabled
            if selection_enabled and isinstance(fig, go.Figure):
                fig.update_layout(
                    clickmode="event+select",
                    dragmode="lasso",
                )
        else:
            fig = _create_figure_from_data(
                df=df,
                visu_type=visu_type,
                dict_kwargs=dict_kwargs,
                theme=current_theme,
                selection_enabled=selection_enabled,
                selection_column=selection_column,
                customizations=customizations,
            )

        if isinstance(fig, go.Figure):
            fig_dict = json.loads(fig.to_json())
        else:
            fig_dict = fig

        metadata = {
            "index": component_id,
            "visu_type": visu_type,
            "rendered_at": time.time(),
        }

        return fig_dict, metadata

    except Exception as e:
        logger.error(f"[{task_id}] Figure rendering failed: {e}", exc_info=True)
        return _create_error_figure(f"Error: {str(e)}", current_theme), {}


def _extend_filters_for_joined_dc(
    relevant_filters: list,
    card_dc_str: str,
    filters_by_dc: dict,
    project_metadata: dict | None,
    batch_task_id: str,
) -> list:
    """
    Extend filters to include source DC filters when figure uses a joined DC.

    For joined data collections, filters from the source DCs (left and right)
    should also apply to the joined result.

    Args:
        relevant_filters: Initial list of filters for the figure's DC
        card_dc_str: The figure's data collection ID as string
        filters_by_dc: Dictionary mapping DC IDs to their filters
        project_metadata: Project metadata containing join definitions
        batch_task_id: Task ID for logging

    Returns:
        Extended list of filters including source DC filters
    """
    if not project_metadata:
        return relevant_filters

    project_data = project_metadata.get("project", {})
    project_joins = project_data.get("joins", [])

    for join_def in project_joins:
        result_dc_id = join_def.get("result_dc_id")
        if str(result_dc_id) != card_dc_str:
            continue

        # This figure uses a joined DC - include filters from source DCs
        source_dc_tags = [join_def.get("left_dc", ""), join_def.get("right_dc", "")]

        for dc_tag in source_dc_tags:
            if not dc_tag:
                continue

            # Find DC IDs matching this tag and include their filters
            for wf in project_data.get("workflows", []):
                for dc in wf.get("data_collections", []):
                    if dc.get("data_collection_tag") == dc_tag:
                        source_dc_id = str(dc.get("_id", ""))
                        source_filters = filters_by_dc.get(source_dc_id, [])
                        if source_filters:
                            relevant_filters.extend(source_filters)

        break  # Found the join definition

    return relevant_filters


def register_core_callbacks(app):
    """Register core rendering callbacks for figure component."""

    log_background_callback_status("figure", "render_figures_batch")

    @app.callback(
        Output({"type": "figure-graph", "index": ALL}, "figure"),
        Output({"type": "figure-metadata", "index": ALL}, "data"),
        Input({"type": "figure-trigger", "index": ALL}, "data"),
        Input("interactive-values-store", "data"),
        State({"type": "figure-trigger", "index": ALL}, "id"),
        State({"type": "figure-metadata", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        State("project-metadata-store", "data"),
        State("local-store", "data"),
        State("theme-store", "data"),
        prevent_initial_call=False,
        background=USE_BACKGROUND_CALLBACKS,
    )
    def render_figures_batch(
        trigger_data_list,
        filters_data,
        trigger_ids,
        existing_metadata_list,
        stored_metadata_list,
        interactive_metadata_list,
        interactive_metadata_ids,
        project_metadata,
        local_data,
        theme_data,
    ):
        """
        UNIFIED BATCH RENDERING: Process ALL figures with optional filter application.

        This single callback handles BOTH initial rendering and filter updates, avoiding
        the race condition and duplicate Output issues from having separate callbacks.

        The callback implements a three-phase optimization strategy:
        1. Build DC load registry - scan figures to identify unique data load requirements
        2. Parallel data loading - load unique DC+filter combinations concurrently
        3. Figure processing - render each figure using cached data

        Args:
            trigger_data_list: List of trigger data for each figure containing:
                - wf_id: Workflow ID
                - dc_id: Data collection ID
                - visu_type: Visualization type (scatter, line, bar, etc.)
                - dict_kwargs: Figure parameters (x, y, color, etc.)
                - mode: 'ui' or 'code'
                - code_content: User code for code mode
            filters_data: Filter state from interactive-values-store (None on initial load)
            trigger_ids: List of component IDs for pattern matching
            existing_metadata_list: List of existing metadata stores (unused, for state)
            stored_metadata_list: List of stored component metadata (unused, for state)
            interactive_metadata_list: Full metadata for interactive filter components
            interactive_metadata_ids: IDs of interactive filter components
            project_metadata: Dashboard metadata with workflows/DCs and join definitions
            local_data: User/token data containing access_token
            theme_data: Theme state ('light' or 'dark')

        Returns:
            Tuple of (all_figures, all_metadata) where:
            - all_figures: List of Plotly figure dicts for each figure component
            - all_metadata: List of metadata dicts with index, visu_type, rendered_at
        """
        batch_task_id = str(uuid.uuid4())[:8]

        # Handle empty dashboard
        if not trigger_data_list or not trigger_ids:
            raise dash.exceptions.PreventUpdate

        current_theme = theme_data if theme_data else "light"

        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access_token available in local-store")
            num_figures = len(trigger_ids)
            empty_fig = {"data": [], "layout": {"title": "Auth Error"}}
            return [empty_fig] * num_figures, [{}] * num_figures

        # Phase 1: Build DC load registry
        dc_load_registry, figure_to_load_key = _build_dc_load_registry(
            trigger_data_list,
            filters_data,
            interactive_metadata_list,
            interactive_metadata_ids,
            project_metadata,
            batch_task_id,
            access_token=access_token,
        )

        # Phase 2: Load DCs in parallel
        dc_cache = _load_dcs_parallel(dc_load_registry, access_token, batch_task_id)

        # Phase 3: Process each figure
        all_figures = []
        all_metadata = []

        for i, (trigger_data, trigger_id) in enumerate(zip(trigger_data_list, trigger_ids)):
            # Get stored metadata for this component to extract customizations
            stored_metadata = None
            if stored_metadata_list and i < len(stored_metadata_list):
                stored_metadata = stored_metadata_list[i]

            fig_dict, metadata = _process_single_figure(
                trigger_data,
                trigger_id,
                i,
                dc_cache,
                figure_to_load_key,
                current_theme,
                batch_task_id,
                stored_metadata=stored_metadata,
            )
            all_figures.append(fig_dict)
            all_metadata.append(metadata)

        return all_figures, all_metadata


def _extract_required_columns(dict_kwargs: dict, visu_type: str) -> list[str]:
    """
    Extract required columns from figure parameters for column projection.

    This enables performance optimization by loading only needed columns from delta tables.

    Args:
        dict_kwargs: Figure parameters (x, y, color, size, etc.)
        visu_type: Visualization type

    Returns:
        List of column names required for the figure
    """
    columns = []

    # Common column parameters across visualization types
    common_params = [
        "x",
        "y",
        "color",
        "size",
        "hover_name",
        "hover_data",
        "facet_row",
        "facet_col",
    ]

    for param in common_params:
        value = dict_kwargs.get(param)
        if value and isinstance(value, str):
            columns.append(value)
        elif value and isinstance(value, list):
            # hover_data can be a list of column names
            columns.extend([v for v in value if isinstance(v, str)])

    # Remove duplicates and return
    return list(set(columns))


def _create_figure_from_data(
    df: Any,
    visu_type: str,
    dict_kwargs: dict,
    theme: str = "light",
    selection_enabled: bool = False,
    selection_column: str | None = None,
    customizations: dict | None = None,
) -> go.Figure:
    """
    Create Plotly figure from DataFrame and parameters.

    Args:
        df: Polars DataFrame with data
        visu_type: Visualization type (scatter, line, bar, box)
        dict_kwargs: Figure parameters
        theme: Theme name (light or dark)
        selection_enabled: Whether to enable scatter selection filtering
        selection_column: Column to include in customdata for selection extraction
        customizations: Optional customizations dict (axes, reference_lines, highlights)

    Returns:
        Plotly Figure object
    """
    try:
        if hasattr(df, "to_pandas"):
            pandas_df = df.to_pandas()
        else:
            pandas_df = df

        template = _get_theme_template(theme)

        keep_empty_string_params = {
            "parents",
            "names",
            "ids",
            "hover_name",
            "hover_data",
            "custom_data",
        }

        json_parseable_params = {
            "color_discrete_map",
            "color_continuous_scale",
            "category_orders",
            "labels",
            "hover_data",
            "custom_data",
            "line_dash_map",
            "symbol_map",
            "pattern_shape_map",
            "size_map",
        }

        cleaned_kwargs = {}
        for k, v in dict_kwargs.items():
            if v is None:
                continue

            if k in json_parseable_params and isinstance(v, str) and v.strip():
                try:
                    v = json.loads(v)
                except (json.JSONDecodeError, ValueError):
                    logger.warning(f"Failed to parse {k} as JSON: {v}, skipping")
                    continue

            if isinstance(v, bool):
                cleaned_kwargs[k] = v
            elif v != "" and v != [] or (k in keep_empty_string_params and v == ""):
                cleaned_kwargs[k] = v

        cleaned_kwargs["template"] = template

        if selection_enabled and selection_column and selection_column in pandas_df.columns:
            existing_custom_data = cleaned_kwargs.get("custom_data", [])
            if isinstance(existing_custom_data, str):
                # If it's a single column name, convert to list
                existing_custom_data = [existing_custom_data]
            elif not isinstance(existing_custom_data, list):
                existing_custom_data = []

            if selection_column not in existing_custom_data:
                cleaned_kwargs["custom_data"] = [selection_column] + list(existing_custom_data)

        if visu_type not in ["scatter", "line", "bar", "box", "histogram"]:
            logger.warning(f"Unsupported visualization type: {visu_type}, defaulting to scatter")
            visu_type = "scatter"

        plot_func = getattr(px, visu_type)
        fig = plot_func(pandas_df, **cleaned_kwargs)

        # Apply customizations if provided
        if customizations:
            from depictio.dash.modules.figure_component.customizations import apply_customizations

            # Pass DataFrame to enable highlight evaluation
            fig = apply_customizations(fig, customizations, df=pandas_df)

        layout_updates = {
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
        }

        if selection_enabled:
            layout_updates["clickmode"] = "event+select"
            layout_updates["dragmode"] = "lasso"

        fig.update_layout(**layout_updates)

        return fig

    except Exception as e:
        logger.error(f"Figure creation failed: {e}", exc_info=True)
        return _create_error_figure(f"Error: {str(e)}", theme)


def _create_error_figure(error_message: str, theme: str = "light") -> go.Figure:
    """
    Create error figure with message.

    Args:
        error_message: Error message to display
        theme: Theme name

    Returns:
        Plotly Figure object with error message
    """
    template = _get_theme_template(theme)

    fig = px.scatter(template=template, title="")
    fig.add_annotation(
        text=f"⚠️ {error_message}",
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        xanchor="center",
        yanchor="middle",
        showarrow=False,
        font={"size": 16, "color": "red"},
        bgcolor="rgba(255,255,255,0.8)" if theme == "light" else "rgba(0,0,0,0.8)",
        bordercolor="red",
        borderwidth=2,
        borderpad=10,
    )

    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
    )

    return fig
