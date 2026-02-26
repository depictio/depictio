"""
Celery tasks for rendering dashboard components.

Provides background rendering of figure, card, and table components
so the API endpoint can return results asynchronously without blocking.

All heavy imports are deferred inside the task function to avoid
importing Dash/Plotly at Celery worker startup.
"""

from __future__ import annotations

from typing import Any

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.celery_app import celery_app


def _build_init_data(dc_id_str: str, workflow_id_str: str) -> dict[str, dict[str, Any]]:
    """Build init_data dict for load_deltatable_lite from MongoDB.

    Queries the data collection's delta_table_location and size directly
    from the projects collection, avoiding the deprecated API-call path.

    Args:
        dc_id_str: String ID of the data collection.
        workflow_id_str: String ID of the workflow.

    Returns:
        Dict mapping dc_id to its delta location and metadata.

    Raises:
        ValueError: If the data collection or its delta location cannot be found.
    """
    from bson import ObjectId

    from depictio.api.v1.db import projects_collection

    dc_oid = ObjectId(dc_id_str)

    # Data collections are embedded in project → workflows → data_collections
    project = projects_collection.find_one(
        {"workflows.data_collections._id": dc_oid},
        {
            "workflows.data_collections.$": 1,
        },
    )

    if not project:
        raise ValueError(f"Data collection {dc_id_str} not found in any project")

    # Extract the matching data collection from the nested structure
    dc_config: dict[str, Any] | None = None
    for workflow in project.get("workflows", []):
        for dc in workflow.get("data_collections", []):
            if str(dc.get("_id")) == dc_id_str:
                dc_config = dc
                break
        if dc_config:
            break

    if not dc_config:
        raise ValueError(f"Data collection {dc_id_str} not found in project workflows")

    delta_location = dc_config.get("delta_table_location")
    if not delta_location:
        raise ValueError(f"No delta_table_location for data collection {dc_id_str}")

    return {
        dc_id_str: {
            "delta_location": delta_location,
            "size_bytes": dc_config.get("size_bytes", -1),
            "dc_type": dc_config.get("dc_type"),
        }
    }


def _render_figure_component(
    component: dict[str, Any],
    df: Any,
    theme: str,
    force_full_data: bool,
) -> dict[str, Any]:
    """Render a figure component to Plotly JSON.

    Args:
        component: Component metadata dict from stored_metadata.
        df: Polars DataFrame with the data.
        theme: Theme name ('light' or 'dark').
        force_full_data: Whether to bypass sampling.

    Returns:
        Dict with 'figure' (Plotly spec) and 'data_info'.
    """
    from depictio.dash.modules.figure_component.utils import render_figure

    dict_kwargs = dict(component.get("dict_kwargs", {}))
    visu_type = component.get("visu_type", "scatter")
    mode = component.get("mode", "ui")
    customizations = component.get("customizations")

    fig, data_info = render_figure(
        dict_kwargs=dict_kwargs,
        visu_type=visu_type,
        df=df,
        theme=theme,
        mode=mode,
        force_full_data=force_full_data,
        customizations=customizations,
    )

    # render_figure may return a Dash html.Div on error — detect that
    import plotly.graph_objects as go

    if not isinstance(fig, go.Figure):
        raise RuntimeError("Figure rendering failed — returned non-Figure object")

    return {
        "figure": fig.to_dict(),
        "data_info": data_info,
    }


def _render_card_component(
    component: dict[str, Any],
    df: Any,
) -> dict[str, Any]:
    """Compute a card component's aggregated value.

    Args:
        component: Component metadata dict from stored_metadata.
        df: Polars DataFrame with the data.

    Returns:
        Dict with 'value', 'aggregation', and 'column'.
    """
    from depictio.dash.modules.card_component.utils import compute_value

    column_name = component.get("column_name", "")
    aggregation = component.get("aggregation", "count")
    cols_json = component.get("cols_json")

    value = compute_value(
        data=df,
        column_name=column_name,
        aggregation=aggregation,
        cols_json=cols_json,
        has_filters=False,
    )

    # Ensure value is JSON-serializable
    if value is not None:
        try:
            import math

            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                value = None
            else:
                value = float(value) if isinstance(value, (int, float)) else str(value)
        except (TypeError, ValueError):
            value = str(value)

    return {
        "value": value,
        "aggregation": aggregation,
        "column": column_name,
    }


def _render_table_component(
    component: dict[str, Any],
    df: Any,
) -> dict[str, Any]:
    """Render a table component to JSON rows.

    Args:
        component: Component metadata dict from stored_metadata.
        df: Polars DataFrame with the data.

    Returns:
        Dict with 'rows', 'columns', 'total_rows', 'returned_rows'.
    """
    total_rows = df.height
    columns: list[str] = component.get("columns", [])

    # Select specified columns if any, otherwise return all
    if columns:
        available_cols = [c for c in columns if c in df.columns]
        if available_cols:
            df = df.select(available_cols)

    # Apply page_size limit
    page_size: int = component.get("page_size", 100)
    if page_size and page_size > 0:
        df = df.head(page_size)

    rows = df.to_dicts()

    return {
        "rows": rows,
        "columns": df.columns,
        "total_rows": total_rows,
        "returned_rows": len(rows),
    }


@celery_app.task(bind=True, name="render_component", serializer="json")
def render_component(
    self: Any,
    component_metadata: dict[str, Any],
    workflow_id: str,
    dc_id: str,
    theme: str = "light",
    filters: list[dict[str, Any]] | None = None,
    force_full_data: bool = False,
) -> dict[str, Any]:
    """Celery task: render a dashboard component and return structured JSON.

    Loads data from Delta Lake, then dispatches to the appropriate renderer
    based on component_type (figure, card, table).

    Args:
        self: Celery task instance (bound).
        component_metadata: Component dict from dashboard stored_metadata.
        workflow_id: Workflow ObjectId as string.
        dc_id: Data collection ObjectId as string.
        theme: Plotly theme ('light' or 'dark').
        filters: Optional runtime filter metadata.
        force_full_data: Bypass sampling for figures.

    Returns:
        Dict with 'status', 'component_type', 'component_tag',
        'component_index', and 'data' containing the rendered output.
    """
    from bson import ObjectId

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    component_type: str = component_metadata.get("component_type", "")
    component_tag: str | None = component_metadata.get("tag")
    component_index: str = component_metadata.get("index", "")

    try:
        # Build init_data to avoid deprecated API-call path
        init_data = _build_init_data(dc_id, workflow_id)

        # Determine select_columns for efficiency
        select_columns: list[str] | None = None
        if component_type == "card":
            col = component_metadata.get("column_name")
            if col:
                select_columns = [col]
        elif component_type == "table":
            cols = component_metadata.get("columns")
            if cols:
                select_columns = cols

        # Load data from Delta Lake
        df = load_deltatable_lite(
            workflow_id=ObjectId(workflow_id),
            data_collection_id=ObjectId(dc_id),
            metadata=filters,
            init_data=init_data,
            select_columns=select_columns,
        )

        # Dispatch to type-specific renderer
        if component_type == "figure":
            data = _render_figure_component(component_metadata, df, theme, force_full_data)
        elif component_type == "card":
            data = _render_card_component(component_metadata, df)
        elif component_type == "table":
            data = _render_table_component(component_metadata, df)
        else:
            return {
                "status": "failed",
                "component_type": component_type,
                "component_tag": component_tag,
                "component_index": component_index,
                "error": f"Unsupported component type for rendering: '{component_type}'",
            }

        return {
            "status": "success",
            "component_type": component_type,
            "component_tag": component_tag,
            "component_index": component_index,
            "data": data,
        }

    except Exception as e:
        logger.error(f"render_component task failed for {component_index}: {e}", exc_info=True)
        return {
            "status": "failed",
            "component_type": component_type,
            "component_tag": component_tag,
            "component_index": component_index,
            "error": str(e),
        }
