"""Read pairs per sample at each preprocessing stage, long, for the read funnel figure.

The sample hub holds the stages side by side (raw, trimmed, host removed); a
grouped bar of the funnel needs one row per sample and stage, in pipeline
order. A stage the run skipped (``--skip_trimming``, ``--skip_hostremoval``)
has no rows. The design columns of the hub follow ``sample``.

Sources:
    samples   ``samples``, the sample hub

Output schema:
    sample : Utf8          sample id
    stage : Utf8           Raw, Trimmed or Host removed
    stage_order : Int64    1 to 3, the pipeline order
    read_pairs : Int64     read pairs at the stage
    pct_of_raw : Float64   read pairs over the raw read pairs, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={
            "sample": pl.Utf8,
            "raw_read_pairs": pl.Int64,
            "trimmed_read_pairs": pl.Int64,
            "host_filtered_read_pairs": pl.Int64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "stage": pl.Utf8,
    "stage_order": pl.Int64,
    "read_pairs": pl.Int64,
    "pct_of_raw": pl.Float64,
}

STAGES = {
    "raw_read_pairs": "Raw",
    "trimmed_read_pairs": "Trimmed",
    "host_filtered_read_pairs": "Host removed",
}
#: Hub columns that are measures, not design columns.
_MEASURE_PREFIXES = (
    "raw_",
    "trimmed_",
    "host_",
    "q30",
    "fastp_",
    "adapter",
    "retained",
    "assembly_",
)
_MEASURES = {"clusters", "removed_clusters", "mean_cluster_size", "singletons", "denovo_consensus"}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    hub = sources["samples"]
    design = [
        c
        for c in hub.columns
        if c != "sample" and c not in _MEASURES and not c.startswith(_MEASURE_PREFIXES)
    ]
    long = (
        hub.select("sample", *design, *STAGES)
        .unpivot(
            index=["sample", *design],
            on=list(STAGES),
            variable_name="_col",
            value_name="read_pairs",
        )
        .filter(pl.col("read_pairs").is_not_null())
        .with_columns(
            pl.col("_col").replace_strict(STAGES).alias("stage"),
            pl.col("_col")
            .replace_strict({c: i for i, c in enumerate(STAGES, 1)}, return_dtype=pl.Int64)
            .alias("stage_order"),
        )
    )
    raw = hub.select("sample", pl.col("raw_read_pairs").alias("_raw"))
    long = long.join(raw, on="sample", how="left").with_columns(
        pl.when(pl.col("_raw") > 0)
        .then((pl.col("read_pairs") * 100.0 / pl.col("_raw")).round(2))
        .otherwise(None)
        .alias("pct_of_raw")
    )
    return long.select(*[pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()], *design).sort(
        "sample", "stage_order"
    )
