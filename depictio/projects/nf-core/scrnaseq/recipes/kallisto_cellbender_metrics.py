"""CellBender's per-sample metrics on the kallisto route.

The catalog recipe `cellbender/metrics.py` reads its raw scan through a fixed
`dc_ref` (`cellbender_metrics_raw`, the Cell Ranger route). Reusing it for the
kallisto route as-is made `kallisto_cellbender_metrics` a copy of the Cell Ranger
numbers, so this recipe keeps the catalog transform and only repoints the
source at the kallisto route's own raw scan, `kallisto_cellbender_metrics_raw`.

Output schema: identical to `cellbender/metrics.py`.
"""

from __future__ import annotations

from depictio.catalog.cellbender.metrics import EXPECTED_SCHEMA, transform
from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="metrics", dc_ref="kallisto_cellbender_metrics_raw"),
]

__all__ = ["EXPECTED_SCHEMA", "SOURCES", "transform"]
