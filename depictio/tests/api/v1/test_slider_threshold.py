"""P19: a single-value Slider is a threshold (``>=``), not an equality filter."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1.deltatables_utils import (
    add_filter,
    convert_filter_model_to_metadata,
    process_metadata_and_filter,
)

DF = pl.DataFrame({"min_contig_length": [0, 1000, 2500, 5000, 10000]})


def _rows(slider_mode: str | None, value: int) -> list[int]:
    filters: list = []
    add_filter(filters, "Slider", "min_contig_length", value, slider_mode=slider_mode)
    return DF.filter(filters[0])["min_contig_length"].to_list()


def test_default_is_threshold() -> None:
    assert _rows(None, 2500) == [2500, 5000, 10000]


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("eq", [2500]),
        ("ne", [0, 1000, 5000, 10000]),
        ("gt", [5000, 10000]),
        ("lte", [0, 1000, 2500]),
        ("lt", [0, 1000]),
        ("bogus", [2500, 5000, 10000]),
    ],
)
def test_explicit_modes(mode: str, expected: list[int]) -> None:
    assert _rows(mode, 2500) == expected


def test_zero_is_a_real_value() -> None:
    assert _rows("eq", 0) == [0]


def test_slider_mode_read_from_component_metadata() -> None:
    metadata = [
        {
            "metadata": {
                "interactive_component_type": "Slider",
                "column_name": "min_contig_length",
                "slider_mode": "eq",
            },
            "value": 5000,
        }
    ]
    [expr] = process_metadata_and_filter(metadata)
    assert DF.filter(expr)["min_contig_length"].to_list() == [5000]


def test_grid_number_filters_keep_their_operator() -> None:
    [entry] = convert_filter_model_to_metadata(
        {"min_contig_length": {"filterType": "number", "type": "equals", "filter": 1000}}
    )
    [expr] = process_metadata_and_filter([entry])
    assert DF.filter(expr)["min_contig_length"].to_list() == [1000]
