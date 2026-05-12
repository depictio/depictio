"""AdvancedViz component model (lite + full).

Lite is YAML-friendly. Full adds runtime fields (resolved IDs, dc_config,
cached columns). Both store the per-kind config in a discriminated-union
field; ``viz_kind`` at the top level mirrors ``config.viz_kind`` and is
enforced consistent by a validator.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field, model_validator

from depictio.models.components.advanced_viz.configs import VizConfig
from depictio.models.components.lite import BaseLiteComponent
from depictio.models.components.types import AdvancedVizKind


class AdvancedVizLiteComponent(BaseLiteComponent):
    """User-definable advanced visualisation component.

    Example YAML:
        - tag: volcano-1
          component_type: advanced_viz
          workflow_tag: nf-core/ampliseq
          data_collection_tag: ancombc_volcano
          viz_kind: volcano
          config:
            viz_kind: volcano
            feature_id_col: feature_id
            effect_size_col: effect_size
            significance_col: significance
            significance_threshold: 0.05
            effect_threshold: 1.0
    """

    component_type: Literal["advanced_viz"] = "advanced_viz"

    # Top-level viz_kind mirrors config.viz_kind. Convenient for lookups and
    # for the outer dispatch in the React renderer without unwrapping config.
    viz_kind: AdvancedVizKind = Field(..., description="Advanced viz kind")

    # Per-kind configuration. Pydantic discriminates by config.viz_kind.
    config: VizConfig = Field(
        ..., description="Per-kind configuration (column bindings + display defaults)"
    )

    @model_validator(mode="after")
    def _kind_matches_config(self) -> "AdvancedVizLiteComponent":
        if self.viz_kind != self.config.viz_kind:
            raise ValueError(
                f"viz_kind={self.viz_kind!r} does not match config.viz_kind={self.config.viz_kind!r}"
            )
        return self


class AdvancedVizComponent(AdvancedVizLiteComponent):
    """Runtime advanced viz component with resolved data-source IDs."""

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

    # Runtime: column metadata (column_name -> polars dtype string)
    cols_json: dict[str, Any] = Field(default_factory=dict)

    # Runtime: parent reference (unused today but kept for parity with siblings)
    parent_index: str | None = None
