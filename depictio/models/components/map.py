"""
Map Component Model.

Represents a geospatial map visualization component (scatter_map, density_map, choropleth_map).
Inherits from MapLiteComponent and adds runtime fields.
"""

import uuid
from typing import Any

from pydantic import Field

from depictio.models.components.lite import MapLiteComponent


class MapComponent(MapLiteComponent):
    """A map component for geospatial data visualization.

    Extends MapLiteComponent with runtime fields for rendering.

    Example YAML:
        - tag: sample-locations
          component_type: map
          workflow_tag: nfcore/ampliseq
          data_collection_tag: sample_metadata
          lat_column: latitude
          lon_column: longitude
          color_column: biome
          map_style: carto-positron
    """

    # Override to auto-generate UUID
    index: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Override to be optional (resolved at runtime)
    workflow_tag: str | None = None
    data_collection_tag: str | None = None

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

    # Panel placement (for dual-panel layouts)
    panel: str | None = Field(default=None, description="Panel placement ('left' or 'right')")

    # Timestamp for caching/updates
    last_updated: str | None = Field(default=None, description="Last update timestamp")

    # Rendering state (populated at render time)
    displayed_data_count: int = Field(default=0, description="Number of data points displayed")
    total_data_count: int = Field(default=0, description="Total data points available")
    was_sampled: bool = Field(default=False, description="Whether data was sampled")
    filter_applied: bool = Field(default=False, description="Whether filter was applied")
