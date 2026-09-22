"""One row per sarek sample, from the samplesheet the pipeline validated.

The megatest samplesheet already has one row per sample (no multi-lane
merging in this run: `lane` is always 1), so this recipe is mostly about
deriving the two columns no other collection carries: the read-depth
condition the megatest name encodes (`<patient>_<depth>M`) and a
human-readable status label. It still `group_by`s on `sample_id` rather than
assuming one row per sample, so a samplesheet with real multi-lane merging
(this run has none) still collapses correctly.

Output schema:
    sample_id            : Utf8   samplesheet `sample` column, the key every
                                   other collection is linked on
    patient               : Utf8   samplesheet `patient` column
    status                : Int64  0 = normal, 1 = tumor (sarek convention;
                                    this run is germline-only, always 0)
    status_label           : Utf8   "Normal" or "Tumor"
    read_depth_millions    : Int64  approximate input read depth, parsed off
                                    the sample name (NA12878_75M -> 75)
    read_depth_label       : Utf8   the same depth as a label ("75M reads"), so
                                    the run's one real factor can drive a
                                    MultiSelect: an Int64 column only takes a
                                    slider
    n_lanes                : Int64  sequencing lanes merged into the sample
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/NA12878_Agilent_full_test.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "patient": pl.Utf8,
    "status": pl.Int64,
    "status_label": pl.Utf8,
    "read_depth_millions": pl.Int64,
    "read_depth_label": pl.Utf8,
    "n_lanes": pl.Int64,
}

_REQUIRED = ["patient", "status", "sample"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Collapse the samplesheet's lane rows to one row per sample."""
    df = sources["samplesheet"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"sarek samples: samplesheet lacks columns {missing}")

    df = df.with_columns(
        pl.col("sample").cast(pl.Utf8).alias("sample_id"),
        pl.col("patient").cast(pl.Utf8).alias("patient"),
        pl.col("status").cast(pl.Int64, strict=False).alias("status"),
    )

    samples = df.group_by("sample_id").agg(
        pl.col("patient").first(),
        pl.col("status").first(),
        pl.len().cast(pl.Int64).alias("n_lanes"),
    )

    samples = samples.with_columns(
        pl.col("sample_id")
        .str.extract(r"_(\d+)M$", 1)
        .cast(pl.Int64, strict=False)
        .alias("read_depth_millions"),
        pl.when(pl.col("status") == 0)
        .then(pl.lit("Normal"))
        .otherwise(pl.lit("Tumor"))
        .alias("status_label"),
    ).with_columns(
        pl.when(pl.col("read_depth_millions").is_not_null())
        .then(pl.concat_str([pl.col("read_depth_millions").cast(pl.Utf8), pl.lit("M reads")]))
        .otherwise(pl.lit("unknown depth"))
        .alias("read_depth_label"),
    )

    return samples.select(list(EXPECTED_SCHEMA)).sort("sample_id")
