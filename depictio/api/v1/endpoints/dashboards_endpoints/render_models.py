"""
Pydantic models for the component render/export API.

Defines request and response schemas for rendering dashboard components
(figures, cards, tables) via API with Celery-backed async execution.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ComponentRenderRequest(BaseModel):
    """Request body for rendering a dashboard component.

    Attributes:
        theme: Plotly theme to apply ('light' or 'dark').
        filters: Optional runtime filter metadata to apply before rendering.
        timeout: Maximum seconds to wait for Celery result before returning 202.
        force_full_data: If True, bypass data sampling limits.
    """

    theme: str = Field(default="light", pattern=r"^(light|dark)$")
    filters: list[dict[str, Any]] | None = None
    timeout: int = Field(default=30, ge=1, le=120)
    force_full_data: bool = False


class FigureRenderData(BaseModel):
    """Rendered Plotly figure data.

    Attributes:
        figure: The Plotly figure spec (data + layout), compatible with any Plotly client.
        data_info: Metadata about the rendering (counts, sampling status).
    """

    figure: dict[str, Any]
    data_info: dict[str, Any]


class CardRenderData(BaseModel):
    """Rendered card component data.

    Attributes:
        value: The computed aggregated value.
        aggregation: The aggregation function used.
        column: The column that was aggregated.
    """

    value: float | int | str | None
    aggregation: str
    column: str


class TableRenderData(BaseModel):
    """Rendered table component data.

    Attributes:
        rows: List of row dictionaries.
        columns: Column names included.
        total_rows: Total row count in source data.
        returned_rows: Number of rows actually returned.
    """

    rows: list[dict[str, Any]]
    columns: list[str]
    total_rows: int
    returned_rows: int


class ComponentRenderResponse(BaseModel):
    """Successful render response for any component type.

    Attributes:
        status: Always 'success' for completed renders.
        component_type: The type of component that was rendered.
        component_tag: The human-readable tag of the component.
        component_index: The UUID index of the component.
        data: The rendered output (structure depends on component_type).
    """

    status: str = "success"
    component_type: str
    component_tag: str | None = None
    component_index: str
    data: FigureRenderData | CardRenderData | TableRenderData | dict[str, Any]


class TaskPendingResponse(BaseModel):
    """Response returned when render exceeds timeout (HTTP 202).

    Attributes:
        status: Always 'pending'.
        task_id: Celery task ID for polling.
        message: Human-readable polling instructions.
    """

    status: str = "pending"
    task_id: str
    message: str = "Rendering in progress. Poll GET /render/tasks/{task_id} for result."


class TaskStatusResponse(BaseModel):
    """Response from the task polling endpoint.

    Attributes:
        status: Task state ('pending', 'success', 'failed').
        task_id: The Celery task ID.
        result: The render result if status is 'success'.
        error: Error message if status is 'failed'.
    """

    status: str
    task_id: str
    result: ComponentRenderResponse | None = None
    error: str | None = None
