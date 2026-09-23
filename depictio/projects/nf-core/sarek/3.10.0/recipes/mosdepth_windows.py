"""The 1 Mb mosdepth windows under the column names the locus section shares.

`mosdepth/regions.py` (catalog) names its coordinates `chromosome` /
`position`; the calls in `vcf_variants` are `chrom` / `pos`. A `genome_view`
navigator emits its region as filters on its own column names, and a
`genome_view` that follows it only recognises filters on the names it binds
itself. So the navigator reads this copy, renamed to `chrom` / `pos` like the
calls and the per-target depth, and the three tiles of the section share one
region without a rename in between. The rows are the catalog recipe's rows.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="regions", dc_ref="mosdepth_regions")]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chrom": pl.Utf8,
    "pos": pl.Int64,  # window start
    "end": pl.Int64,  # window end
    "depth": pl.Float64,  # target-length-weighted mean depth in the window
    "sample": pl.Utf8,
    "stage": pl.Utf8,
    "sample_stage": pl.Utf8,
    "n_targets": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename the catalog windows onto the section's shared coordinate names."""
    return (
        sources["regions"]
        .rename({"chromosome": "chrom", "position": "pos", "value": "depth"})
        .with_columns(
            pl.col("pos").cast(pl.Int64),
            pl.col("end").cast(pl.Int64),
            pl.col("depth").cast(pl.Float64),
            pl.col("n_targets").cast(pl.Int64),
        )
        .select(list(EXPECTED_SCHEMA))
    )
