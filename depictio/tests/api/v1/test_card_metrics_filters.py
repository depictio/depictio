"""Card preview under active dashboard filters (#329).

``hero_value`` computes a card's hero scalar live on a (possibly filtered)
frame using the exact expression + coercion pair the saved-card pushdown path
uses, so the builder preview and the saved card cannot disagree. The other
tests pin that the numeric-strip and breakdown helpers, fed a pre-filtered
scan (as the filtered ``card_metric`` / ``breakdown`` endpoints now do),
return the filtered distribution rather than the whole collection's.

Style matches ``test_card_breakdown.py``: in-memory Polars frames, no HTTP.
"""

import polars as pl
import pytest

from depictio.api.v1.deltatables_utils import apply_filters_to_scan
from depictio.api.v1.services.card_breakdown import compute_breakdown
from depictio.api.v1.services.card_metrics import hero_value, numeric_layout_payload


@pytest.fixture
def frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "variety": ["Setosa"] * 4 + ["Versicolor"] * 4 + ["Virginica"] * 2,
            "petal_length": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        }
    )


SETOSA_FILTER = [
    {
        "interactive_component_type": "MultiSelect",
        "column_name": "variety",
        "value": ["Setosa"],
    }
]


class TestHeroValue:
    @pytest.mark.parametrize(
        ("aggregation", "expected"),
        [
            ("count", 10),
            ("sum", 55.0),
            ("mean", 5.5),
            ("average", 5.5),
            ("min", 1.0),
            ("max", 10.0),
            ("median", 5.5),
            ("nunique", 10),
        ],
    )
    def test_unfiltered(self, frame, aggregation, expected):
        assert hero_value(frame.lazy(), "petal_length", aggregation) == expected

    def test_filtered_scan(self, frame):
        filtered = apply_filters_to_scan(frame.lazy(), SETOSA_FILTER)
        assert hero_value(filtered, "petal_length", "count") == 4
        assert hero_value(filtered, "petal_length", "sum") == 10.0
        assert hero_value(filtered, "petal_length", "mean") == 2.5

    def test_missing_column(self, frame):
        assert hero_value(frame.lazy(), "nope", "count") is None

    def test_expressionless_aggregation(self, frame):
        # ``mode`` deliberately has no lazy expression form (tie-order isn't
        # guaranteed); the preview returns None rather than approximating.
        assert hero_value(frame.lazy(), "petal_length", "mode") is None

    def test_eager_frame_accepted(self, frame):
        assert hero_value(frame, "petal_length", "count") == 10


class TestFilteredStripHelpers:
    def test_histogram_differs_under_filter(self, frame):
        full = numeric_layout_payload(frame.lazy(), {}, "petal_length", "histogram")
        filtered = numeric_layout_payload(
            apply_filters_to_scan(frame.lazy(), SETOSA_FILTER), {}, "petal_length", "histogram"
        )
        assert full is not None and filtered is not None
        assert full["total"] == 10
        assert sum(full["bins"]) == 10
        assert filtered["total"] == 4
        assert sum(filtered["bins"]) == 4

    def test_breakdown_reflects_filter(self, frame):
        filtered = compute_breakdown(
            apply_filters_to_scan(frame.lazy(), SETOSA_FILTER),
            column="petal_length",
            breakdown_col="variety",
            aggregation="count",
            top_n_count=3,
        )
        assert filtered is not None
        assert filtered["total"] == 4
        assert [g["name"] for g in filtered["top"]] == ["Setosa"]
