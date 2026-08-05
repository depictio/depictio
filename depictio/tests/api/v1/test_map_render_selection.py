"""The wire contract between ``render_map`` and the viewer's selection highlight.

``MapRenderer`` decides which points to dim by reading ``customdata`` straight
off each trace and comparing it to the selection values in the filter list. That
only works while ``customdata`` arrives as a plain nested list.

plotly.py >= 6 serialises a *numeric* ``custom_data`` column as a base64 typed
array instead (``{"dtype": ..., "bdata": ..., "shape": ...}``), which the client
cannot read — so a map whose ``selection_column`` was numeric lassoed correctly
but showed no highlight at all. ``render_map`` therefore stringifies the column
before handing it to Plotly Express, and this pins that down.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from depictio.api.v1.services.map.render import render_map


def _trigger(selection_column: str) -> dict:
    return {
        "map_type": "scatter_map",
        "lat_column": "lat",
        "lon_column": "lon",
        "selection_enabled": True,
        "selection_column": selection_column,
    }


def _customdata(selection_column: str, values: list) -> object:
    df = pd.DataFrame({"lat": [48.85, 52.52], "lon": [2.35, 13.40], selection_column: values})
    fig, _ = render_map(df=df, trigger_data=_trigger(selection_column))
    # Round-trip through to_json exactly as the endpoint does — the typed-array
    # encoding only appears at serialisation time.
    return json.loads(fig.to_json())["data"][0]["customdata"]


@pytest.mark.parametrize(
    ("column", "values", "expected"),
    [
        ("sample", ["s1", "s2"], [["s1"], ["s2"]]),
        ("run_number", [10, 20], [["10"], ["20"]]),
        ("score", [1.5, 2.5], [["1.5"], ["2.5"]]),
    ],
    ids=["string", "int", "float"],
)
def test_customdata_is_a_nested_list_of_strings(column, values, expected) -> None:
    assert _customdata(column, values) == expected


def test_numeric_selection_column_is_not_a_typed_array() -> None:
    """The specific regression: a dict here means the client sees no highlight."""
    customdata = _customdata("run_number", [10, 20])
    assert isinstance(customdata, list), (
        f"customdata must be a nested list, got {type(customdata).__name__}: {customdata!r}"
    )
