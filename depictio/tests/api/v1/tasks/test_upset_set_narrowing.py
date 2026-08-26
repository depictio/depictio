"""Set-column narrowing for the UpSet task.

An UpSet matrix pivots a grouping column into COLUMNS, so a dashboard filter
on that column can never filter rows — the DC has no such column. These tests
pin the mirror-as-a-column-filter behaviour that makes such a filter bite, and
its two guardrails: it must not fire on unrelated filters, and it must work
when the sets were auto-detected rather than declared.
"""

from __future__ import annotations

import polars as pl

from depictio.api.v1.celery_tasks import (
    _detect_upset_set_columns,
    _narrow_wide_matrix_columns,
)


def _matrix() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "taxon": ["a", "b", "c"],
            "Athens": [1, 0, 1],
            "Barcelona": [0, 1, 1],
            "Naples": [1, 1, 0],
            "Phylum": ["P1", "P2", "P1"],
            "prevalence": [12, 4, 30],
        }
    )


def test_detects_binary_columns_only() -> None:
    assert _detect_upset_set_columns(_matrix()) == ["Athens", "Barcelona", "Naples"]


def test_narrows_on_a_filter_carrying_set_values() -> None:
    sets = _detect_upset_set_columns(_matrix())
    filters = [{"column_name": "locality", "value": ["Athens", "Naples"]}]
    assert _narrow_wide_matrix_columns(sets, filters) == ["Athens", "Naples"]


def test_single_value_filter_leaves_one_set() -> None:
    filters = [{"metadata": {"column_name": "locality"}, "value": "Naples"}]
    assert _narrow_wide_matrix_columns(["Athens", "Barcelona", "Naples"], filters) == ["Naples"]


def test_unrelated_filter_leaves_the_sets_alone() -> None:
    # A taxonomy filter narrows ROWS (the DC has a Phylum column); it must not
    # be mistaken for a filter over the sets.
    filters = [{"column_name": "Phylum", "value": ["P1"]}]
    assert _narrow_wide_matrix_columns(["Athens", "Barcelona", "Naples"], filters) is None


def test_selecting_every_set_is_a_no_op() -> None:
    filters = [{"column_name": "locality", "value": ["Athens", "Barcelona", "Naples"]}]
    assert _narrow_wide_matrix_columns(["Athens", "Barcelona", "Naples"], filters) is None


def test_empty_filter_values_are_ignored() -> None:
    filters = [{"column_name": "locality", "value": []}, {"column_name": "x", "value": None}]
    assert _narrow_wide_matrix_columns(["Athens", "Naples"], filters) is None
