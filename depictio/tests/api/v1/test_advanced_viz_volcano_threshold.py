"""The volcano's significance threshold is a p-value whatever its column holds.

`VolcanoConfig.significance_threshold` is documented as the p/padj cut-off, and
the browser renderer converts it to -log10 when the column already holds
-log10 values (`significancePredicate` in deViews.ts). The server-side builder
used the raw number on such a column, so a 0.05 cut-off drew its line at
y = 0.05 and called almost every point significant: the two renders of one
tile disagreed.
"""

from __future__ import annotations

import math

from depictio.api.v1.services.advanced_viz.kinds import volcano


def _tiers(sig: list[float], neg_log10: bool) -> list[str]:
    fig = volcano.build(
        rows={"effect_size": [2.0, 2.0, -2.0], "significance": sig, "feature_id": ["a", "b", "c"]},
        config={"significance_is_neg_log10": neg_log10, "significance_threshold": 0.05},
        controls={},
        theme="light",
    )
    return [row[2] for row in fig["data"][0]["customdata"]]


def test_raw_p_values_are_called_at_the_cutoff():
    assert _tiers([0.01, 0.2, 0.001], neg_log10=False) == ["UP", "NS", "DN"]


def test_neg_log10_column_is_called_at_the_same_p_value_cutoff():
    sig = [-math.log10(p) for p in (0.01, 0.2, 0.001)]
    assert _tiers(sig, neg_log10=True) == ["UP", "NS", "DN"]
