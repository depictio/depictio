"""Samples x miRNAs CPM matrix, the input of the two-group comparison.

``group_compare`` tests every numeric column of a wide frame between two groups
of rows. For miRNA expression the rows are the samples and the numeric columns
are the miRNAs, on the CPM scale (the comparison applies its own log1p before
testing and reports fold changes on the frame's scale). Design columns stay as
text columns, so they can define the two groups without being tested.

The matrix keeps the ``MAX_MIRNAS`` miRNAs with the highest mean CPM. The
long tail below that is mostly miRNAs seen in a handful of reads in a few
samples, which no test on a handful of samples can call, and each extra column
costs the comparison time.

Source: the ``mirtop_mirna_counts`` collection (``mirtop/mirna_counts.py``).

Output: ``sample`` (Utf8), the design columns (Utf8) when a design table was
given, then one Float64 CPM column per miRNA, named after it, by decreasing
mean CPM.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="counts", dc_ref="mirtop_mirna_counts"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
}
# miRNA and design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

MAX_MIRNAS = 1000

#: Columns of mirna_counts that are measurements, not design.
_MEASURES = ("mirna", "reads", "cpm", "log2_cpm", "isomirs", "reference_pct")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot the top miRNAs by mean CPM to one column each."""
    counts = sources["counts"]
    design = [c for c in counts.columns if c not in _MEASURES and c != "sample"]
    top = (
        counts.group_by("mirna")
        .agg(pl.col("cpm").mean().alias("_mean"))
        .sort(["_mean", "mirna"], descending=[True, False])
        .head(MAX_MIRNAS)["mirna"]
        .to_list()
    )
    wide = (
        counts.filter(pl.col("mirna").is_in(top))
        .pivot(on="mirna", index="sample", values="cpm")
        .fill_null(0.0)
    )
    wide = wide.select("sample", *[pl.col(m).cast(pl.Float64) for m in top if m in wide.columns])
    if design:
        wide = wide.join(counts.select("sample", *design).unique(subset="sample"), on="sample")
        wide = wide.select("sample", *design, *[m for m in top if m in wide.columns])
    return wide.sort("sample")
