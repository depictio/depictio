"""
Card Component Model.

Represents a metric/KPI card that displays an aggregated value from a data column.
Inherits from CardLiteComponent and adds runtime fields.
"""

import uuid
from typing import Any

from pydantic import Field

from depictio.models.components.lite import CardLiteComponent
from depictio.models.components.types import AggregationFunction, ColumnType


class CardComponent(CardLiteComponent):
    """A metric card component displaying an aggregated value.

    Extends CardLiteComponent with runtime fields for rendering.

    Example YAML:
        - index: card-1
          component_type: card
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          aggregation: average
          column_name: sepal.length
          column_type: float64
    """

    # Override to auto-generate UUID
    index: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Override to be optional (resolved at runtime)
    workflow_tag: str | None = None
    data_collection_tag: str | None = None

    # Override with type alias
    aggregation: AggregationFunction | str
    column_type: ColumnType | str = "float64"

    # Runtime: resolved IDs
    wf_id: str | None = None
    dc_id: str | None = None
    project_id: str | None = None

    # Runtime: full data collection config
    dc_config: dict[str, Any] = Field(default_factory=dict)

    # Runtime: column metadata
    cols_json: dict[str, Any] = Field(default_factory=dict)

    # Runtime: parent reference
    parent_index: str | None = None

    # Runtime: computed value
    value: float | int | str | None = None

    # Panel placement (for dual-panel layouts)
    panel: str | None = Field(default=None, description="Panel placement ('left' or 'right')")

    # Additional styling
    background_color: str | None = Field(default=None, description="Card background color")

    # Trend indicator (optional)
    show_trend: bool = Field(default=False, description="Show trend indicator")
    trend_column: str | None = Field(default=None, description="Column for trend calculation")
    trend_period: str | None = Field(default=None, description="Time period for trend")
