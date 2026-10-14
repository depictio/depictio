"""`qiime2/alpha_rarefaction_summary.py`: the system columns ingestion adds are not metrics.

Every Delta table carries `depictio_run_id`, so the `dc_ref` read hands it to the
recipe. Treating every non-key column as a metric sent that string column into
`quantile()`, which failed with "sub operation not supported for dtypes str and
str" (#1171).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

RECIPE = "qiime2/alpha_rarefaction_summary.py"


def _rarefaction() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": ["s1", "s1", "s1", "s2", "s2", "s2"],
            "depth": [10, 10, 10, 10, 10, 10],
            "iter": [1, 2, 3, 1, 2, 3],
            "faith_pd": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "depictio_run_id": ["run-1"] * 6,
        }
    )


def _metadata() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ID": ["s1", "s2"],
            "habitat": ["soil", "water"],
            "depictio_run_id": ["run-1", "run-1"],
        }
    )


def test_run_id_is_neither_summarised_nor_failing(tmp_path: Path) -> None:
    out = execute_recipe(
        RECIPE, tmp_path, extra_sources={"rarefaction": _rarefaction(), "metadata": None}
    )
    assert "depictio_run_id" not in out.columns
    assert "depictio_run_id_iqr" not in out.columns
    assert out.sort("sample")["faith_pd"].to_list() == [2.0, 5.0]
    assert out.sort("sample")["faith_pd_iqr"].to_list() == [1.0, 1.0]


def test_run_id_is_not_joined_as_an_annotation(tmp_path: Path) -> None:
    out = execute_recipe(
        RECIPE, tmp_path, extra_sources={"rarefaction": _rarefaction(), "metadata": _metadata()}
    )
    assert "depictio_run_id" not in out.columns
    assert dict(zip(out["sample"], out["habitat"], strict=True)) == {"s1": "soil", "s2": "water"}


def test_non_numeric_columns_are_not_metrics(tmp_path: Path) -> None:
    df = _rarefaction().with_columns(pl.lit("qiime2").alias("tool"))
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"rarefaction": df, "metadata": None})
    assert "tool_iqr" not in out.columns
    assert "faith_pd_iqr" in out.columns
