"""The 1 Mb mosdepth windows under the column names the locus section shares.

`mosdepth/regions.py` (catalog) names its coordinates `chromosome` /
`position`; the calls in `vcf_variants` are `chrom` / `pos`. A `genome_view`
navigator emits its region as filters on its own column names, and a
`genome_view` that follows it only recognises filters on the names it binds
itself. So the navigator reads this copy, renamed to `chrom` / `pos` like the
calls and the per-target depth, and the three tiles of the section share one
region without a rename in between. The rows are the catalog recipe's rows.

Two columns serve the navigator's lanes and are not in the catalog recipe:

- `sample_id` repeats `sample` under the name the dashboard pins its sample
  colours on (the sample hub's key), so a lane wears the colour the same sample
  has on every other tile;
- `depth_capped` is `depth` held at three times its sample's median window
  depth (at least 40x, so the 20x floor stays on the axis). A few windows over
  repeats or the centromere read ten times the rest, and on a shared axis they
  flatten every other window of the lane into the baseline.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="regions",
        dc_ref="mosdepth_regions",
        input_schema={
            "chromosome": pl.Utf8,
            "position": pl.Int64,
            "end": pl.Int64,
            "value": pl.Float64,
            "sample": pl.Utf8,
            "stage": pl.Utf8,
            "sample_stage": pl.Utf8,
            "n_targets": pl.Int64,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "chrom": pl.Utf8,
    "pos": pl.Int64,  # window start
    "end": pl.Int64,  # window end
    "depth": pl.Float64,  # target-length-weighted mean depth in the window
    "sample": pl.Utf8,
    "stage": pl.Utf8,
    "sample_stage": pl.Utf8,
    "n_targets": pl.Int64,
    "sample_id": pl.Utf8,  # `sample` again, the key the sample colours are pinned on
    "depth_capped": pl.Float64,  # depth, held at 3x the sample's median window depth
}

# The cap, in multiples of the sample's median depth, and its floor in x.
CAP_FACTOR = 3.0
CAP_FLOOR = 40.0


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
            pl.col("sample").alias("sample_id"),
        )
        .with_columns(
            pl.min_horizontal(
                pl.col("depth"),
                pl.max_horizontal(
                    pl.col("depth").filter(pl.col("depth") > 0).median().over("sample")
                    * CAP_FACTOR,
                    pl.lit(CAP_FLOOR),
                ),
            ).alias("depth_capped")
        )
        .select(list(OUTPUT_SCHEMA))
    )
