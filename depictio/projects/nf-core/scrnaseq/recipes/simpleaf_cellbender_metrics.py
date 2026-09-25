"""CellBender's per-sample metrics on the simpleaf route.

The catalog recipe `cellbender/metrics.py` reads its raw scan through a fixed
`dc_ref` (`cellbender_metrics_raw`, the Cell Ranger route). Reusing it for the
simpleaf route as-is made `simpleaf_cellbender_metrics` a copy of the Cell Ranger
numbers, so this recipe keeps the catalog transform and only repoints the
source at the simpleaf route's own raw scan, `simpleaf_cellbender_metrics_raw`.

Output schema: identical to `cellbender/metrics.py`.
"""

from __future__ import annotations

from depictio.catalog.cellbender.metrics import EXPECTED_SCHEMA, transform
from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="metrics", dc_ref="simpleaf_cellbender_metrics_raw"),
]

__all__ = ["EXPECTED_SCHEMA", "SOURCES", "transform"]
