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
    enrich_interactive_components_with_metadata,
    group_filters_by_dc,
    resolve_link_values,
)

# Use centralized background callback configuration
USE_BACKGROUND_CALLBACKS = should_use_background_for_component("figure")


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
        logger.info(
            f"[{batch_task_id}] Figure uses joined DC {card_dc_str[:8]}, "
            f"including filters from source DCs: {source_dc_tags}"
        )

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
                            logger.info(
                                f"[{batch_task_id}] Including {len(source_filters)} "
                                f"filters from source DC {dc_tag} ({source_dc_id[:8]})"
                            )
                            relevant_filters.extend(source_filters)

        break  # Found the join definition

    return relevant_filters


def _extend_filters_via_links(
    target_dc_id: str,
    filters_by_dc: dict,
    project_metadata: dict | None,
    access_token: str | None,
    batch_task_id: str,
) -> list:
    """
    Extend filters using DC links for cross-DC filtering.

    When a filter is on a source DC that has a link to the target DC,
    resolve the filter values through the link.

    Args:
        target_dc_id: The figure's data collection ID
        filters_by_dc: Dictionary mapping DC IDs to their filters
        project_metadata: Project metadata containing link definitions
        access_token: Authentication token for API calls
        batch_task_id: Task ID for logging

    Returns:
        List of filters to apply (resolved via links)
    """
    link_filters = []

    if not project_metadata or not access_token:
        return link_filters

    project_data = project_metadata.get("project", {})
    project_id = str(project_data.get("_id", ""))
    project_links = project_data.get("links", [])

    if not project_id or not project_links:
        return link_filters

    # Find links where target_dc_id is the target
    for link in project_links:
        if not link.get("enabled", True):
            continue

        link_target_dc = str(link.get("target_dc_id", ""))
        link_source_dc = str(link.get("source_dc_id", ""))

        if link_target_dc != target_dc_id:
            continue

        # Check if we have filters for the source DC
        source_filters = filters_by_dc.get(link_source_dc, [])
        active_source_filters = [
            f for f in source_filters if f.get("value") not in [None, [], "", False]
        ]

        if not active_source_filters:
            continue

        # Get filter values from source DC
        for source_filter in active_source_filters:
            filter_value = source_filter.get("value", [])
            source_column = source_filter.get("metadata", {}).get("column_name", "")

            if not filter_value:
                continue

            filter_values = filter_value if isinstance(filter_value, list) else [filter_value]

            # Resolve through link
            resolved = resolve_link_values(
                project_id=project_id,
                source_dc_id=link_source_dc,
                source_column=source_column,
                filter_values=filter_values,
                target_dc_id=target_dc_id,
                token=access_token,
            )

            if resolved and resolved.get("resolved_values"):
                resolved_values = resolved["resolved_values"]
                target_column = link.get("link_config", {}).get("target_field", source_column)

                # Create a synthetic filter for the target DC
                # Use MultiSelect type so load_deltatable_lite applies is_in() filter
                link_filter = {
                    "index": f"link_{link.get('id', 'unknown')}",
                    "value": resolved_values,
                    "metadata": {
                        "dc_id": target_dc_id,
                        "column_name": target_column,
                        "interactive_component_type": "MultiSelect",
                    },
                }
                link_filters.append(link_filter)

                logger.info(
                    f"[{batch_task_id}] 🔗 Link resolution: {len(filter_values)} values from "
                    f"{link_source_dc[:8]} → {len(resolved_values)} values for {target_dc_id[:8]} "
                    f"(column: {target_column})"
                )

    return link_filters


def register_core_callbacks(app):
    """Register core rendering callbacks for figure component."""

    # Log background callback status for figure component
    log_background_callback_status("figure", "render_figures_batch")

    # ============================================================================
    # CALLBACK 1: Initial Figure Rendering (NO filter listening)
    # ============================================================================
    # UNIFIED CALLBACK: Handles both initial render AND filter updates
    # ============================================================================
    @app.callback(
        Output({"type": "figure-graph", "index": ALL}, "figure"),
        Output({"type": "figure-metadata", "index": ALL}, "data"),
        Input({"type": "figure-trigger", "index": ALL}, "data"),
        Input("interactive-values-store", "data"),  # Also listen to filters!
        State({"type": "figure-trigger", "index": ALL}, "id"),
        State({"type": "figure-metadata", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State(
            {"type": "interactive-stored-metadata", "index": ALL}, "data"
        ),  # Full filter metadata!
        State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        State("project-metadata-store", "data"),
        State("local-store", "data"),
        State("theme-store", "data"),
        prevent_initial_call=False,
        background=USE_BACKGROUND_CALLBACKS,  # Use centralized background callback config
    )
    def render_figures_batch(
        trigger_data_list,
        filters_data,  # NEW: Filter state from interactive-values-store
        trigger_ids,
        existing_metadata_list,
        stored_metadata_list,
        interactive_metadata_list,  # Full metadata for filters
        interactive_metadata_ids,
        project_metadata,
        local_data,
        theme_data,
    ):
        """
        UNIFIED BATCH RENDERING: Process ALL figures with optional filter application.

        This single callback handles BOTH initial rendering and filter updates, avoiding
        the race condition and duplicate Output issues from having separate callbacks.

        Args:
            trigger_data_list: List of trigger data for each figure
            filters_data: Filter state from interactive-values-store (None on initial load)
            trigger_ids: List of component IDs
            existing_metadata_list: List of existing metadata stores
            stored_metadata_list: List of stored component metadata
            project_metadata: Dashboard metadata with workflows/DCs
            local_data: User/token data
            theme_data: Theme state (light/dark)

        Returns:
            Tuple of (all_figures, all_metadata)
        """
        # Generate batch task correlation ID and start timing
        batch_task_id = str(uuid.uuid4())[:8]
        batch_start_time = time.time()

        logger.info(f"[{batch_task_id}] 🎨 FIGURE INITIAL RENDER - {len(trigger_ids)} figures")

        # Handle empty dashboard (no figures)
        if not trigger_data_list or not trigger_ids:
            logger.debug("No figures to render - preventing update")
            raise dash.exceptions.PreventUpdate

        # Extract theme from store (theme-store stores theme string directly, not dict)
        current_theme = theme_data if theme_data else "light"
        logger.debug(f"Current theme: {current_theme}")

        # Extract access token from local-store
        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access_token available in local-store")
            # Return empty figures for all components
            num_figures = len(trigger_ids)
            empty_fig = {"data": [], "layout": {"title": "Auth Error"}}
            return [empty_fig] * num_figures, [{}] * num_figures

        # Initialize result lists for batch processing
        all_figures = []
        all_metadata = []

        # ⭐ OPTIMIZATION: Pre-load unique DC+filter combinations in parallel
        # Scan all figures to identify unique data loads, then execute in parallel
        logger.info(
            f"[{batch_task_id}] 📊 Analyzing {len(trigger_ids)} figures for parallel loading"
        )

        # Step 1: Build index of unique DC loads
        dc_load_registry = {}  # Key: (wf_id, dc_id, filters_hash) -> (filters_metadata, required_columns)
        figure_to_load_key = {}  # Map: figure_index -> load_key

        for i, trigger_data in enumerate(trigger_data_list):
            if not trigger_data or not isinstance(trigger_data, dict):
                figure_to_load_key[i] = None
                continue

            wf_id = trigger_data.get("wf_id")
            dc_id = trigger_data.get("dc_id")
            visu_type = trigger_data.get("visu_type", "scatter")
            dict_kwargs = trigger_data.get("dict_kwargs", {})

            if not all([wf_id, dc_id]):
                figure_to_load_key[i] = None
                continue

            # Extract required columns from parameters
            required_columns = _extract_required_columns(dict_kwargs, visu_type)

            # Extract filters for this figure's DC (if filters exist)
            metadata_to_pass = []
            if filters_data and filters_data.get("interactive_components_values"):
                # Enrich lightweight filter data with full metadata using shared utility
                enriched_components = enrich_interactive_components_with_metadata(
                    filters_data,
                    interactive_metadata_list,
                    interactive_metadata_ids,
                )

                # Group filters by DC using shared utility
                card_dc_str = str(dc_id)
                filters_by_dc = group_filters_by_dc(enriched_components)

                # Get relevant filters for this figure's DC
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
                link_resolved_filters = _extend_filters_via_links(
                    target_dc_id=card_dc_str,
                    filters_by_dc=filters_by_dc,
                    project_metadata=project_metadata,
                    access_token=access_token,
                    batch_task_id=batch_task_id,
                )
                if link_resolved_filters:
                    relevant_filters.extend(link_resolved_filters)

                active_filters = [
                    c for c in relevant_filters if c.get("value") not in [None, [], "", False]
                ]
                metadata_to_pass = active_filters

            # Create load key: (wf_id, dc_id, filters_hash)
            filters_hash = (
                hashlib.md5(
                    json.dumps(metadata_to_pass, sort_keys=True, default=str).encode()
                ).hexdigest()[:8]
                if metadata_to_pass
                else "nofilter"
            )

            load_key = (str(wf_id), str(dc_id), filters_hash)

            # Register this unique load
            if load_key not in dc_load_registry:
                dc_load_registry[load_key] = (metadata_to_pass, required_columns)

            # Map figure to its load key
            figure_to_load_key[i] = load_key

        logger.info(
            f"[{batch_task_id}] 📊 Found {len(dc_load_registry)} unique DC loads "
            f"for {len(figure_to_load_key)} figures"
        )

        # Step 2: Load all unique DCs in parallel
        dc_cache = {}  # Cache: load_key -> DataFrame

        def load_single_dc(load_key, metadata_to_pass, required_columns):
            """Load a single DC with optional filters (thread-safe operation)."""
            wf_id, dc_id, filters_hash = load_key
            try:
                # Load with column projection for performance
                # NOTE: select_columns disabled - causes hang in ThreadPoolExecutor context
                data = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id),
                    metadata=metadata_to_pass,
                    TOKEN=access_token,
                    # select_columns=required_columns if required_columns else None,  # DISABLED - causes hang
                )
                logger.debug(
                    f"   ✅ Parallel load: {dc_id[:8]} "
                    f"({data.height:,} rows × {data.width} cols, projected: {len(required_columns)} cols)"
                )
                return load_key, data
            except Exception as e:
                logger.error(f"   ❌ Parallel load failed: {dc_id[:8]}: {e}", exc_info=True)
                return load_key, None

        # Execute parallel loads (max 4 concurrent workers)
        parallel_start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            # Submit all load tasks
            future_to_key = {
                executor.submit(load_single_dc, load_key, metadata, columns): load_key
                for load_key, (metadata, columns) in dc_load_registry.items()
            }

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_key):
                load_key, data = future.result()
                if data is not None:
                    dc_cache[load_key] = data
        parallel_duration = (time.time() - parallel_start) * 1000
        cache_hit_rate = len(dc_cache) / len(dc_load_registry) * 100 if dc_load_registry else 0
        dedup_ratio = len(figure_to_load_key) / len(dc_load_registry) if dc_load_registry else 1
        logger.info(
            f"[{batch_task_id}] ⚡ Parallel loading complete: "
            f"{len(dc_cache)}/{len(dc_load_registry)} DCs loaded in {parallel_duration:.1f}ms "
            f"(dedup: {dedup_ratio:.1f}x, success: {cache_hit_rate:.0f}%)"
        )

        # Step 3: Process each figure using cached data
        for i, (trigger_data, trigger_id) in enumerate(zip(trigger_data_list, trigger_ids)):
            # Generate per-figure task ID
            task_id = f"{batch_task_id}-{i}"
            component_id = trigger_id.get("index", "unknown")[:8] if trigger_id else "unknown"
            figure_start_time = time.time()

            try:
                logger.debug(
                    f"[{task_id}] Processing figure {i + 1}/{len(trigger_ids)}: {component_id}"
                )

                # Validate trigger data
                if not trigger_data or not isinstance(trigger_data, dict):
                    logger.warning(f"[{task_id}] Invalid trigger data for figure {component_id}")
                    all_figures.append(_create_error_figure("Invalid trigger data", current_theme))
                    all_metadata.append({})
                    continue

                # Extract figure parameters
                mode = trigger_data.get("mode", "ui")
                visu_type = trigger_data.get("visu_type", "scatter")
                dict_kwargs = trigger_data.get("dict_kwargs", {})
                code_content = trigger_data.get("code_content", "")

                logger.debug(
                    f"[{task_id}] Figure params: mode={mode}, visu_type={visu_type}, dict_kwargs={dict_kwargs}"
                )

                # CRITICAL DEBUG: Log full trigger_data for code mode figures
                if mode == "code":
                    logger.info(f"🔍 RENDER: Code mode figure {component_id}")
                    logger.info(f"   code_content length: {len(code_content)}")
                    logger.info(
                        f"   code_content present in trigger_data: {'code_content' in trigger_data}"
                    )
                    logger.info(f"   Full trigger_data keys: {trigger_data.keys()}")
                    logger.info(f"   Full trigger_data: {trigger_data}")

                # Get cached data
                load_key = figure_to_load_key.get(i)
                if not load_key or load_key not in dc_cache:
                    logger.warning(f"[{task_id}] No cached data for figure {component_id}")
                    all_figures.append(_create_error_figure("Data not available", current_theme))
                    all_metadata.append({})
                    continue

                df = dc_cache[load_key]

                # Create figure - branch on mode
                if mode == "code":
                    # CODE MODE: Execute user code
                    if not code_content:
                        logger.error(f"[{task_id}] Code mode but no code_content")
                        all_figures.append(
                            _create_error_figure("No code content provided", current_theme)
                        )
                        all_metadata.append({})
                        continue

                    from depictio.dash.modules.figure_component.code_mode import (
                        extract_visualization_type_from_code,
                    )
                    from depictio.dash.modules.figure_component.simple_code_executor import (
                        SimpleCodeExecutor,
                    )

                    executor = SimpleCodeExecutor()
                    success, fig, message = executor.execute_code(code_content, df)

                    if success:
                        # Extract visu_type dynamically from code
                        detected_visu_type = extract_visualization_type_from_code(code_content)
                        if detected_visu_type:
                            visu_type = detected_visu_type

                        # Apply theme template if not in code
                        if "template=" not in code_content:
                            theme_template = f"mantine_{current_theme}"
                            fig.update_layout(template=theme_template)

                        logger.debug(
                            f"[{task_id}] ✅ Code execution successful (visu_type: {visu_type})"
                        )
                    else:
                        logger.error(f"[{task_id}] Code execution failed: {message}")
                        all_figures.append(
                            _create_error_figure(f"Code execution error: {message}", current_theme)
                        )
                        all_metadata.append({})
                        continue
                else:
                    # UI MODE: Existing logic
                    fig = _create_figure_from_data(
                        df=df,
                        visu_type=visu_type,
                        dict_kwargs=dict_kwargs,
                        theme=current_theme,
                    )

                figure_duration = (time.time() - figure_start_time) * 1000
                logger.debug(f"[{task_id}] ✅ Figure rendered in {figure_duration:.1f}ms")

                # Convert to JSON-serializable dict (handles NumPy arrays)
                if isinstance(fig, go.Figure):
                    fig_dict = json.loads(fig.to_json())  # Plotly's to_json() handles ndarrays
                    all_figures.append(fig_dict)
                else:
                    all_figures.append(fig)
                all_metadata.append(
                    {
                        "index": component_id,
                        "visu_type": visu_type,
                        "rendered_at": time.time(),
                    }
                )

            except Exception as e:
                logger.error(f"[{task_id}] ❌ Figure rendering failed: {e}", exc_info=True)
                all_figures.append(_create_error_figure(f"Error: {str(e)}", current_theme))
                all_metadata.append({})

        # Log batch completion
        batch_duration = (time.time() - batch_start_time) * 1000
        logger.info(
            f"[{batch_task_id}] 🎨 FIGURE BATCH COMPLETE - "
            f"{len(all_figures)} figures rendered in {batch_duration:.1f}ms "
            f"(avg: {batch_duration / len(all_figures):.1f}ms/figure)"
        )

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
    df: Any, visu_type: str, dict_kwargs: dict, theme: str = "light"
) -> go.Figure:
    """
    Create Plotly figure from DataFrame and parameters.

    Args:
        df: Polars DataFrame with data
        visu_type: Visualization type (scatter, line, bar, box)
        dict_kwargs: Figure parameters
        theme: Theme name (light or dark)

    Returns:
        Plotly Figure object
    """
    try:
        # Convert Polars to Pandas for Plotly Express compatibility
        if hasattr(df, "to_pandas"):
            pandas_df = df.to_pandas()
        else:
            pandas_df = df

        # Get theme template
        template = _get_theme_template(theme)

        # Prepare parameters (clean None values, validate types)
        # Keep certain parameters that can legitimately be empty strings
        keep_empty_string_params = {
            "parents",
            "names",
            "ids",
            "hover_name",
            "hover_data",
            "custom_data",
        }
        cleaned_kwargs = {}
        for k, v in dict_kwargs.items():
            if v is None:
                continue

            # Skip *_map parameters that are strings (malformed data) - Plotly expects dicts
            if k.endswith("_map") and isinstance(v, str):
                logger.debug(f"Skipping malformed parameter {k}='{v}' (expected dict, got string)")
                continue

            # Keep boolean parameters (including False values)
            if isinstance(v, bool):
                cleaned_kwargs[k] = v
            # Keep the parameter if it's not empty, or if it's in the allowed empty string list
            elif v != "" and v != [] or (k in keep_empty_string_params and v == ""):
                cleaned_kwargs[k] = v

        # Add template to parameters
        cleaned_kwargs["template"] = template

        # Get Plotly Express function dynamically
        if visu_type not in ["scatter", "line", "bar", "box", "histogram"]:
            logger.warning(f"Unsupported visualization type: {visu_type}, defaulting to scatter")
            visu_type = "scatter"

        plot_func = getattr(px, visu_type)

        # Create figure
        fig = plot_func(pandas_df, **cleaned_kwargs)

        # Apply additional theme-aware styling
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",  # Transparent background
            plot_bgcolor="rgba(0,0,0,0)",  # Transparent plot area
            margin={"l": 50, "r": 20, "t": 40, "b": 40},  # Reasonable margins
        )

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

    # Add error annotation
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

    # Remove axes
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)

    # Transparent background
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
    )

    return fig
