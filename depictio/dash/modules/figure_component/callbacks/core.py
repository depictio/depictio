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
from depictio.dash.modules.figure_component.utils import _get_theme_template


def register_core_callbacks(app):
    """Register core rendering callbacks for figure component."""

    # ============================================================================
    # CALLBACK 1: Initial Figure Rendering (NO filter listening)
    # ============================================================================
    @app.callback(
        Output({"type": "figure-graph", "index": ALL}, "figure"),
        Output({"type": "figure-metadata", "index": ALL}, "data"),
        Input({"type": "figure-trigger", "index": ALL}, "data"),
        State({"type": "figure-trigger", "index": ALL}, "id"),
        State({"type": "figure-metadata", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State("project-metadata-store", "data"),
        State("local-store", "data"),
        State("theme-store", "data"),
        prevent_initial_call=False,
    )
    def render_figures_batch(
        trigger_data_list,
        trigger_ids,
        existing_metadata_list,
        stored_metadata_list,
        project_metadata,
        local_data,
        theme_data,
    ):
        """
        INITIAL BATCH RENDERING: Process ALL figures in single callback (no filters).

        This callback handles the initial rendering of figures when they are first created.
        It does NOT respond to filter changes - that is handled by patch_figures_with_filters.

        Args:
            trigger_data_list: List of trigger data for each figure
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

            # No filters on initial render - load full dataset
            metadata_to_pass = []

            # Create load key: (wf_id, dc_id, columns_hash)
            # No filters_hash needed for initial render
            columns_hash = hashlib.md5(
                json.dumps(sorted(required_columns), sort_keys=True).encode()
            ).hexdigest()[:8]
            load_key = (str(wf_id), str(dc_id), columns_hash)

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
            """Load a single DC with column projection (thread-safe operation, no filters)."""
            wf_id, dc_id, columns_hash = load_key
            try:
                # Load with column projection for performance
                data = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id),
                    metadata=metadata_to_pass,
                    TOKEN=access_token,
                    select_columns=required_columns if required_columns else None,
                )
                logger.debug(
                    f"   ✅ Parallel load: {dc_id[:8]} "
                    f"({data.height:,} rows × {data.width} cols, projected: {len(required_columns)} cols)"
                )
                return load_key, data
            except Exception as e:
                logger.error(f"   ❌ Parallel load failed: {dc_id[:8]}: {e}")
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
                visu_type = trigger_data.get("visu_type", "scatter")
                dict_kwargs = trigger_data.get("dict_kwargs", {})

                # Get cached data
                load_key = figure_to_load_key.get(i)
                if not load_key or load_key not in dc_cache:
                    logger.warning(f"[{task_id}] No cached data for figure {component_id}")
                    all_figures.append(_create_error_figure("Data not available", current_theme))
                    all_metadata.append({})
                    continue

                df = dc_cache[load_key]

                # Create figure from data
                fig = _create_figure_from_data(
                    df=df,
                    visu_type=visu_type,
                    dict_kwargs=dict_kwargs,
                    theme=current_theme,
                )

                figure_duration = (time.time() - figure_start_time) * 1000
                logger.debug(f"[{task_id}] ✅ Figure rendered in {figure_duration:.1f}ms")

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

    # ============================================================================
    # CALLBACK 2: Patch Figures with Filters (responds to interactive changes)
    # ============================================================================
    @app.callback(
        Output({"type": "figure-graph", "index": ALL}, "figure", allow_duplicate=True),
        Input("interactive-values-store", "data"),
        State({"type": "figure-trigger", "index": ALL}, "data"),
        State({"type": "figure-trigger", "index": ALL}, "id"),
        State("project-metadata-store", "data"),
        State("local-store", "data"),
        State("theme-store", "data"),
        prevent_initial_call=True,
    )
    def patch_figures_with_filters(
        filters_data,
        trigger_data_list,
        trigger_ids,
        project_metadata,
        local_data,
        theme_data,
    ):
        """
        FILTER PATCH: Update ALL figures when filters change.

        This callback is triggered ONLY when interactive components change.
        It applies filters to the data and re-renders all figures with the filtered data.

        Args:
            filters_data: Filter state from interactive-values-store
            trigger_data_list: List of trigger data for each figure
            trigger_ids: List of component IDs
            project_metadata: Dashboard metadata
            local_data: User/token data
            theme_data: Theme state

        Returns:
            List of updated figures
        """
        # Generate batch task correlation ID
        batch_task_id = str(uuid.uuid4())[:8]
        batch_start_time = time.time()

        # Extract filter count for logging
        filter_count = (
            len(filters_data.get("interactive_components_values", [])) if filters_data else 0
        )

        logger.info(
            f"[{batch_task_id}] 🔄 FIGURE FILTER PATCH - {len(trigger_ids)} figures, "
            f"{filter_count} active filters"
        )

        # Handle empty dashboard
        if not trigger_data_list or not trigger_ids:
            raise dash.exceptions.PreventUpdate

        # Extract theme
        current_theme = theme_data if theme_data else "light"

        # Extract access token
        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access_token available")
            empty_fig = {"data": [], "layout": {"title": "Auth Error"}}
            return [empty_fig] * len(trigger_ids)

        # Process figures with filters
        all_figures = []

        # Build DC load registry with filters
        dc_load_registry = {}
        figure_to_load_key = {}

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

            # Extract columns
            required_columns = _extract_required_columns(dict_kwargs, visu_type)

            # Get filters for this figure's DC
            card_dc_str = str(dc_id)
            metadata_list = (
                filters_data.get("interactive_components_values", []) if filters_data else []
            )

            # Group filters by DC
            filters_by_dc = {}
            if metadata_list:
                for component in metadata_list:
                    component_dc = str(component.get("metadata", {}).get("dc_id"))
                    if component_dc not in filters_by_dc:
                        filters_by_dc[component_dc] = []
                    filters_by_dc[component_dc].append(component)

            # Get relevant filters
            relevant_filters = filters_by_dc.get(card_dc_str, [])

            # Determine if filters are active
            has_active_filters = any(
                c.get("value") not in [None, [], "", False] for c in relevant_filters
            )

            if has_active_filters:
                active_filters = [
                    c for c in relevant_filters if c.get("value") not in [None, [], "", False]
                ]
                metadata_to_pass = active_filters
            else:
                metadata_to_pass = []

            # Create load key with filters
            filter_signature = sorted(
                [
                    (c.get("metadata", {}).get("column_name"), str(c.get("value")))
                    for c in metadata_to_pass
                ]
            )
            filters_hash = hashlib.md5(
                json.dumps(filter_signature, sort_keys=True).encode()
            ).hexdigest()[:8]

            columns_hash = hashlib.md5(
                json.dumps(sorted(required_columns), sort_keys=True).encode()
            ).hexdigest()[:8]

            load_key = (str(wf_id), str(dc_id), filters_hash, columns_hash)

            # Log filter application
            if metadata_to_pass:
                filter_summary = ", ".join(
                    [
                        f"{c.get('metadata', {}).get('column_name')}={c.get('value')}"
                        for c in metadata_to_pass
                    ]
                )
                logger.debug(
                    f"   📊 Figure {i}: Applying {len(metadata_to_pass)} filters to DC {dc_id[:8]} "
                    f"({filter_summary})"
                )

            # Register unique load
            if load_key not in dc_load_registry:
                dc_load_registry[load_key] = (metadata_to_pass, required_columns)

            figure_to_load_key[i] = load_key

        # Load all unique DCs with filters in parallel
        dc_cache = {}

        def load_single_dc_with_filters(load_key, metadata_to_pass, required_columns):
            """Load a single DC with filters and column projection."""
            wf_id, dc_id, filters_hash, columns_hash = load_key
            try:
                data = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id),
                    metadata=metadata_to_pass,
                    TOKEN=access_token,
                    select_columns=required_columns if required_columns else None,
                )
                logger.debug(
                    f"   ✅ Filtered load: {dc_id[:8]}...{filters_hash} "
                    f"({data.height:,} rows × {data.width} cols)"
                )
                return load_key, data
            except Exception as e:
                logger.error(f"   ❌ Filtered load failed: {dc_id[:8]}...{filters_hash}: {e}")
                return load_key, None

        # Execute parallel loads
        parallel_start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_key = {
                executor.submit(load_single_dc_with_filters, load_key, metadata, columns): load_key
                for load_key, (metadata, columns) in dc_load_registry.items()
            }

            for future in concurrent.futures.as_completed(future_to_key):
                load_key, data = future.result()
                if data is not None:
                    dc_cache[load_key] = data

        parallel_duration = (time.time() - parallel_start) * 1000
        logger.info(
            f"[{batch_task_id}] ⚡ Parallel loading complete: "
            f"{len(dc_cache)}/{len(dc_load_registry)} DCs loaded in {parallel_duration:.1f}ms"
        )

        # Generate figures using cached filtered data
        for i, (trigger_data, trigger_id) in enumerate(zip(trigger_data_list, trigger_ids)):
            try:
                if not trigger_data or not isinstance(trigger_data, dict):
                    all_figures.append(_create_error_figure("Invalid trigger data", current_theme))
                    continue

                visu_type = trigger_data.get("visu_type", "scatter")
                dict_kwargs = trigger_data.get("dict_kwargs", {})

                load_key = figure_to_load_key.get(i)
                if not load_key or load_key not in dc_cache:
                    all_figures.append(_create_error_figure("Data not available", current_theme))
                    continue

                df = dc_cache[load_key]

                # Create figure with filtered data
                fig = _create_figure_from_data(
                    df=df,
                    visu_type=visu_type,
                    dict_kwargs=dict_kwargs,
                    theme=current_theme,
                )

                all_figures.append(fig)

            except Exception as e:
                logger.error(f"Figure patch failed: {e}", exc_info=True)
                all_figures.append(_create_error_figure(f"Error: {str(e)}", current_theme))

        # Log completion
        batch_duration = (time.time() - batch_start_time) * 1000
        logger.info(
            f"[{batch_task_id}] 🔄 FIGURE FILTER PATCH COMPLETE - "
            f"{len(all_figures)} figures updated in {batch_duration:.1f}ms"
        )

        return all_figures


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
