"""CellBender's per-sample metrics on the simpleaf route.

The catalog recipe `cellbender/metrics.py` reads its raw scan through a fixed
`dc_ref` (`cellbender_metrics_raw`, the Cell Ranger route). Reusing it for the
simpleaf route as-is made `simpleaf_cellbender_metrics` a copy of the Cell Ranger
numbers, so this recipe keeps the catalog transform and only repoints the
source at the simpleaf route's own raw scan, `simpleaf_cellbender_metrics_raw`.

Output schema: identical to `cellbender/metrics.py`.
"""

from __future__ import annotations

import polars as pl

from depictio.catalog.cellbender.metrics import OUTPUT_SCHEMA, transform
from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="metrics",
        input_schema={
            "source_path": pl.Utf8,
            "metric": pl.Utf8,
            "value": pl.Utf8,
        },
        dc_ref="simpleaf_cellbender_metrics_raw",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
# OUTPUT_SCHEMA and transform() are the catalog cellbender/metrics.py ones.
__all__ = ["OUTPUT_SCHEMA", "SOURCES", "transform"]
