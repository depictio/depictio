"""Sample hub for nf-core/stableexpression: one row per public sample of the run.

stableexpression takes a species, not a samplesheet: the samples are those of
the public datasets it downloaded. Their design is published as
``merged_data/whole_design.csv`` (``batch`` is the dataset, ``condition`` a
group local to its dataset, ``g1``, ``g2`` ...), which ``METADATA_FILE`` points
at by default; a copy of it with extra columns (tissue, treatment, curated by
hand) can replace it, and every extra column is kept under its own name
(sanitised to ``[0-9A-Za-z_]``) so ``GROUP_COL`` can name it.

Derived, never read from the sample names:

* ``dataset`` (the design's ``batch``), its ``accession`` (``E-GEOD-10070``) and
  ``array_design`` (``A-AFFY-44`` for a microarray dataset);
* ``platform`` (``Microarray``, ``RNA-seq``) and ``normalisation`` (``Normalised``,
  ``Raw counts``), from the dataset's directory under ``datasets/`` (from the
  dataset id when that directory is not there). ``platform`` is the template's
  default ``GROUP_COL``;
* ``condition``, prefixed with the dataset, since ``g1`` of one dataset has
  nothing to do with ``g1`` of the next;
* ``status``: ``Analysed`` for a sample of the merged matrix, ``Filtered out``
  for one the zero or missing-value filter removed (the design keeps them),
  read from ``statistics/ratio_nulls_per_sample.csv``, the per-sample table of
  the merged matrix;
* ``missing_share``: the share of the merged matrix's genes the sample did not
  measure (a microarray covers fewer genes than an RNA-seq library).

Output:
    sample, dataset, accession, array_design, platform, normalisation,
    condition, status, missing_share, <other design columns>
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.stable_expression import (
    TEXT_READ_KWARGS,
    accession_of,
    array_design_of,
    dataset_directories,
    guess_platform,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="design",
        path="merged_data/whole_design.csv",
        format="csv",
        read_kwargs=TEXT_READ_KWARGS,
        input_schema={"batch": pl.Utf8, "sample": pl.Utf8},
    ),
    RecipeSource(
        ref="designs",
        glob_pattern="datasets/*/*/*/*.design.csv",
        format="csv",
        read_kwargs=TEXT_READ_KWARGS,
        source_path="source_path",
    ),
    RecipeSource(
        ref="per_sample",
        path="statistics/ratio_nulls_per_sample.csv",
        format="csv",
        read_kwargs=TEXT_READ_KWARGS,
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "dataset": pl.Utf8,
    "accession": pl.Utf8,
    "array_design": pl.Utf8,
    "platform": pl.Utf8,
    "normalisation": pl.Utf8,
    "condition": pl.Utf8,
    "status": pl.Utf8,
    "missing_share": pl.Float64,
}

_FIXED = {"sample", "batch", "condition"}


def _clean(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", name.strip()).strip("_") or "column"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    design = sources["design"].filter(pl.col("sample").is_not_null())
    extra = [c for c in design.columns if c not in _FIXED]
    renamed = {c: _clean(c) for c in extra}
    extra_out = [renamed[c] for c in extra if renamed[c] not in OUTPUT_SCHEMA]

    dirs = dataset_directories(sources["designs"])
    hub = design.select(
        pl.col("sample"),
        pl.col("batch").alias("dataset"),
        (
            pl.col("condition") if "condition" in design.columns else pl.lit(None, dtype=pl.Utf8)
        ).alias("_condition"),
        *[pl.col(c).alias(renamed[c]) for c in extra if renamed[c] in extra_out],
    ).unique(subset="sample", keep="first")
    hub = hub.join(dirs, on="dataset", how="left").with_columns(
        pl.coalesce(
            pl.col("platform"),
            pl.col("dataset").map_elements(guess_platform, return_dtype=pl.Utf8),
        ).alias("platform"),
        pl.col("dataset").map_elements(accession_of, return_dtype=pl.Utf8).alias("accession"),
        pl.col("dataset").map_elements(array_design_of, return_dtype=pl.Utf8).alias("array_design"),
        pl.when(pl.col("_condition").is_not_null())
        .then(pl.col("dataset") + " " + pl.col("_condition"))
        .otherwise(None)
        .alias("condition"),
    )

    per_sample = sources.get("per_sample")
    if per_sample is not None and {"sample", "ratio"} <= set(per_sample.columns):
        ratios = per_sample.select(
            "sample", pl.col("ratio").cast(pl.Float64, strict=False).alias("missing_share")
        ).unique(subset="sample", keep="last")
        hub = hub.join(ratios, on="sample", how="left").with_columns(
            pl.when(pl.col("sample").is_in(ratios.get_column("sample").implode()))
            .then(pl.lit("Analysed"))
            .otherwise(pl.lit("Filtered out"))
            .alias("status")
        )
    else:
        hub = hub.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("missing_share"),
            pl.lit("Analysed").alias("status"),
        )
    return hub.select(*OUTPUT_SCHEMA, *extra_out).sort("platform", "dataset", "sample")
