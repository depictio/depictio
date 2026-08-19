"""Filter support for the builder-preview endpoints (#329 / #196).

Covers the pure helpers the filtered previews are built on —
``clean_filter_payload`` (React ``InteractiveFilter`` payload → cleaned
``filter_metadata``) and ``apply_filters_to_scan`` (schema-guarded filter
application on a lazy frame) — plus the ``preview_deltatable`` Celery task
against a local Delta table.

Style matches ``test_card_breakdown.py`` / ``test_deltatables_utils.py``:
in-memory Polars frames, no HTTP client, no database.
"""

from unittest.mock import patch

import polars as pl
import pytest

from depictio.api.v1.deltatables_utils import apply_filters_to_scan, clean_filter_payload


@pytest.fixture
def iris_like() -> pl.DataFrame:
    """A small frame shaped like the seeded Iris DC: one categorical column
    with three balanced groups, one numeric column."""
    return pl.DataFrame(
        {
            "variety": ["Setosa"] * 3 + ["Versicolor"] * 3 + ["Virginica"] * 3,
            "petal_length": [1.4, 1.3, 1.5, 4.5, 4.7, 4.4, 6.0, 5.8, 6.1],
        }
    )


class TestCleanFilterPayload:
    def test_flat_shape(self):
        filters = [
            {
                "interactive_component_type": "MultiSelect",
                "column_name": "variety",
                "value": ["Setosa"],
            }
        ]
        assert clean_filter_payload(filters) == [
            {
                "interactive_component_type": "MultiSelect",
                "column_name": "variety",
                "value": ["Setosa"],
            }
        ]

    def test_nested_metadata_shape(self):
        """The React payload keeps column/type under ``metadata`` — the shape
        every interactive component emits at runtime."""
        filters = [
            {
                "index": "abc-123",
                "value": ["Setosa"],
                "metadata": {
                    "interactive_component_type": "MultiSelect",
                    "column_name": "variety",
                    "dc_id": "000000000000000000000001",
                },
            }
        ]
        out = clean_filter_payload(filters)
        assert out == [
            {
                "interactive_component_type": "MultiSelect",
                "column_name": "variety",
                "value": ["Setosa"],
            }
        ]

    @pytest.mark.parametrize("empty", [None, [], ""])
    def test_empty_values_dropped(self, empty):
        filters = [
            {"column_name": "variety", "interactive_component_type": "MultiSelect", "value": empty}
        ]
        assert clean_filter_payload(filters) == []

    def test_missing_column_dropped(self):
        assert clean_filter_payload([{"value": ["Setosa"], "metadata": {}}]) == []

    def test_filter_expr_carried_through(self):
        filters = [
            {
                "column_name": "variety",
                "interactive_component_type": "MultiSelect",
                "value": ["Setosa"],
                "metadata": {"filter_expr": "col('petal_length') > 1.0"},
            }
        ]
        assert clean_filter_payload(filters)[0]["filter_expr"] == "col('petal_length') > 1.0"

    def test_none_input(self):
        assert clean_filter_payload(None) == []


class TestApplyFiltersToScan:
    def test_multiselect_narrows(self, iris_like):
        out = apply_filters_to_scan(
            iris_like.lazy(),
            [
                {
                    "interactive_component_type": "MultiSelect",
                    "column_name": "variety",
                    "value": ["Setosa"],
                }
            ],
        ).collect()
        assert out.height == 3
        assert set(out["variety"].to_list()) == {"Setosa"}

    def test_rangeslider_narrows(self, iris_like):
        out = apply_filters_to_scan(
            iris_like.lazy(),
            [
                {
                    "interactive_component_type": "RangeSlider",
                    "column_name": "petal_length",
                    "value": [4.0, 5.0],
                }
            ],
        ).collect()
        assert out.height == 3
        assert set(out["variety"].to_list()) == {"Versicolor"}

    def test_filters_and_together(self, iris_like):
        out = apply_filters_to_scan(
            iris_like.lazy(),
            [
                {
                    "interactive_component_type": "MultiSelect",
                    "column_name": "variety",
                    "value": ["Setosa", "Virginica"],
                },
                {
                    "interactive_component_type": "RangeSlider",
                    "column_name": "petal_length",
                    "value": [5.9, 7.0],
                },
            ],
        ).collect()
        assert out.height == 2
        assert set(out["variety"].to_list()) == {"Virginica"}

    def test_absent_column_skipped_valid_cofilter_applies(self, iris_like):
        """The cross-DC contract: a filter on a column this frame doesn't have
        is skipped rather than raising ColumnNotFoundError, while the valid
        co-supplied filter still narrows the frame."""
        out = apply_filters_to_scan(
            iris_like.lazy(),
            [
                {
                    "interactive_component_type": "MultiSelect",
                    "column_name": "habitat",  # not in this DC
                    "value": ["marine"],
                },
                {
                    "interactive_component_type": "MultiSelect",
                    "column_name": "variety",
                    "value": ["Setosa"],
                },
            ],
        ).collect()
        assert out.height == 3
        assert set(out["variety"].to_list()) == {"Setosa"}

    @pytest.mark.parametrize("metadata", [None, []])
    def test_no_filters_is_noop(self, iris_like, metadata):
        out = apply_filters_to_scan(iris_like.lazy(), metadata).collect()
        assert out.equals(iris_like)

    def test_nested_metadata_shape(self, iris_like):
        """Entries can also arrive in the nested runtime shape (column under
        ``metadata``) — ``process_metadata_and_filter`` handles both."""
        out = apply_filters_to_scan(
            iris_like.lazy(),
            [
                {
                    "value": ["Versicolor"],
                    "metadata": {
                        "interactive_component_type": "MultiSelect",
                        "column_name": "variety",
                    },
                }
            ],
        ).collect()
        assert set(out["variety"].to_list()) == {"Versicolor"}


class TestPreviewDeltatableTask:
    """End-to-end through the Celery task body against a local Delta table."""

    @pytest.fixture
    def delta_location(self, tmp_path, iris_like) -> str:
        loc = str(tmp_path / "iris_delta")
        iris_like.write_delta(loc)
        return loc

    def _run(self, delta_location: str, **payload):
        from depictio.api.v1.celery_tasks import preview_deltatable

        # Local paths take no S3 storage options.
        with patch("depictio.api.v1.s3.polars_s3_config", {}):
            return preview_deltatable({"delta_table_location": delta_location, **payload})

    def test_unfiltered(self, delta_location):
        out = self._run(delta_location, limit=5)
        assert out["total_rows"] == 9
        assert len(out["rows"]) == 5
        assert out["filter_applied"] is False

    def test_filtered_rows_and_total(self, delta_location):
        out = self._run(
            delta_location,
            limit=100,
            filter_metadata=[
                {
                    "interactive_component_type": "MultiSelect",
                    "column_name": "variety",
                    "value": ["Setosa"],
                }
            ],
        )
        # Both the page and the "of N rows" total reflect the filtered frame.
        assert out["total_rows"] == 3
        assert len(out["rows"]) == 3
        assert {r["variety"] for r in out["rows"]} == {"Setosa"}
        assert out["filter_applied"] is True
