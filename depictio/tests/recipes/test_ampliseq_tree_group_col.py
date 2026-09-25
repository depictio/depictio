"""`nf-core/ampliseq/tree_metadata_canonical.py`: the dominant group follows GROUP_COL.

The template passes `GROUP_COL` as the `group_col` param; without it (or with
the CLI's `__no_group__` sentinel) the recipe falls back to the second metadata
column, the CLI's own GROUP_COL convention. No column name is special-cased.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

RECIPE = "nf-core/ampliseq/tree_metadata_canonical.py"


def _asv_table() -> pl.DataFrame:
    # asv1 lives in s1/s2, asv2 in s3/s4, asv3 is split evenly across all four.
    return pl.DataFrame(
        {
            "ID": ["asv1", "asv2", "asv3"],
            "Kingdom": ["Bacteria"] * 3,
            "Phylum": ["P1", "P2", "P3"],
            "confidence": ["0.9", "0.9", "0.9"],
            "s1": ["0.5", "0.0", "0.1"],
            "s2": ["0.5", "0.0", "0.1"],
            "s3": ["0.0", "0.5", "0.1"],
            "s4": ["0.0", "0.5", "0.1"],
        }
    ).cast(pl.Utf8)


def _metadata() -> pl.DataFrame:
    # `site` splits s1/s2 against s3/s4; `season` splits s1/s3 against s2/s4.
    return pl.DataFrame(
        {
            "sample": ["s1", "s2", "s3", "s4"],
            "season": ["dry", "wet", "dry", "wet"],
            "site": ["upstream", "upstream", "downstream", "downstream"],
        }
    )


def _run(tmp_path: Path, params: dict[str, str] | None) -> dict[str, str]:
    out = execute_recipe(
        RECIPE,
        tmp_path,
        extra_sources={"asv_tax": _asv_table(), "taxonomy": None, "metadata": _metadata()},
        params=params,
    )
    return dict(zip(out["taxon"], out["dominant_habitat"], strict=True))


def test_group_col_param_picks_the_factor(tmp_path: Path) -> None:
    by_site = _run(tmp_path, {"group_col": "site", "id_col": "sample"})
    assert by_site == {"asv1": "upstream", "asv2": "downstream", "asv3": "Mixed"}


def test_no_group_col_falls_back_to_the_second_column(tmp_path: Path) -> None:
    """Sentinel, unresolved placeholder, unknown column and no params all fall back."""
    expected = {"asv1": "Mixed", "asv2": "Mixed", "asv3": "Mixed"}  # `season` splits evenly
    for params in (
        None,
        {"group_col": "__no_group__"},
        {"group_col": "{GROUP_COL}"},
        {"group_col": "not_a_column"},
    ):
        assert _run(tmp_path, params) == expected
