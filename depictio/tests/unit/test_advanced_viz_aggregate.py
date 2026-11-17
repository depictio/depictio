"""`/advanced_viz/data` can sum a column per group on the server.

The sunburst adds abundances up a lineage, so one row per lineage carries the
same information as one row per lineage and sample, in far fewer bytes.
"""

from __future__ import annotations

import polars as pl
import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import _aggregate_frame


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "Kingdom": ["Bacteria", "Bacteria", "Eukaryota", "Eukaryota", "Eukaryota"],
            "Phylum": ["Pseudo", "Pseudo", "Arthro", None, None],
            "abundance": [1.0, 2.0, 4.0, 8.0, 16.0],
        }
    )


def test_sums_per_group_and_keeps_the_totals() -> None:
    out = _aggregate_frame(_frame(), {"group_by": ["Kingdom", "Phylum"], "sum": "abundance"})
    assert out.height == 3
    assert out["abundance"].sum() == _frame()["abundance"].sum()
    got = {(r["Kingdom"], r["Phylum"]): r["abundance"] for r in out.to_dicts()}
    assert got == {
        ("Bacteria", "Pseudo"): 3.0,
        ("Eukaryota", "Arthro"): 4.0,
        ("Eukaryota", None): 24.0,
    }


def test_null_keys_stay_a_group_of_their_own() -> None:
    out = _aggregate_frame(_frame(), {"group_by": ["Phylum"], "sum": "abundance"})
    assert out.filter(pl.col("Phylum").is_null())["abundance"].to_list() == [24.0]


@pytest.mark.parametrize(
    "bad",
    [
        {"group_by": [], "sum": "abundance"},
        {"group_by": ["Kingdom"]},
        {"group_by": "Kingdom", "sum": "abundance"},
        {"group_by": ["Kingdom"], "sum": "missing"},
        {"group_by": ["nope"], "sum": "abundance"},
        "Kingdom",
    ],
)
def test_malformed_requests_are_a_400(bad: object) -> None:
    with pytest.raises(HTTPException) as err:
        _aggregate_frame(_frame(), bad)
    assert err.value.status_code == 400
