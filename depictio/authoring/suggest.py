"""Viz suggestions for a schema (right column, "suggested" tab).

Thin wrapper over ``suggest_viz_kinds`` (``depictio.models.components.advanced_viz.schemas``),
serialising each ``VizSuggestion`` dataclass for the JSON API.
"""

from __future__ import annotations

import dataclasses
from typing import Any


def suggest_for_schema(
    schema: dict[str, str],
    dc_type: str | None = None,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    """Rank every viz kind for ``schema`` (column → polars dtype name)."""
    from depictio.models.components.advanced_viz.schemas import suggest_viz_kinds

    return [
        dataclasses.asdict(s)
        for s in suggest_viz_kinds(schema, min_confidence=min_confidence, dc_type=dc_type)
    ]
