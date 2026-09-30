"""Indel alleles per library, relative to the cut site.

``cigar/<sample>_indels.csv`` has one row per indel read that passed the CIGAR
parser's filters: the modification (``del``, ``ins`` or ``delin``), its start
and length on the amplicon, whether it sits above the sequencing error rate and
inside the library's main indel peak (``in_pick``), the cut site, and the
library's wild-type and template-based read counts. This recipe collapses the
reads to one row per distinct allele (type, start, length) and expresses each
as a share of the library's classified reads (wild type + template-based +
indel reads), the same denominator as the edit outcome table.

Only the columns the recipe needs are read: the per-read tables of a large run
add up to gigabytes of text.

Output: one row per library and allele (see EXPECTED_SCHEMA). ``size`` is signed
(insertions positive, deletions and deletion-insertions negative) and
``offset`` is ``start - cut_site`` on the amplicon.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_COLUMNS = [
    "Modification",
    "Start",
    "Length",
    "in_pick",
    "sample",
    "cut_site",
    "wt_reads",
    "t_reads",
]

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="indels",
        glob_pattern="**/*_indels.csv",
        format="csv",
        read_kwargs={
            "columns": _COLUMNS,
            "schema_overrides": {
                "Modification": pl.Utf8,
                "Start": pl.Int64,
                "Length": pl.Int64,
                "in_pick": pl.Utf8,
                "sample": pl.Utf8,
                "cut_site": pl.Int64,
                "wt_reads": pl.Int64,
                "t_reads": pl.Int64,
            },
            "null_values": ["NA", ""],
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "allele": pl.Utf8,
    "indel_type": pl.Utf8,
    "start": pl.Int64,
    "length": pl.Int64,
    "size": pl.Int64,
    "offset": pl.Int64,
    "frame": pl.Utf8,
    "peak": pl.Utf8,
    "reads": pl.Int64,
    "pct_reads": pl.Float64,
    "pct_indel_reads": pl.Float64,
    "rank": pl.Int64,
    "cut_site": pl.Int64,
}

_TYPES = {"del": "Deletion", "ins": "Insertion", "delin": "Deletion-insertion"}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["indels"].filter(pl.col("Start").is_not_null() & pl.col("Length").is_not_null())
    per_lib = df.group_by("sample").agg(
        pl.len().cast(pl.Int64).alias("_indel_reads"),
        (pl.col("wt_reads").first().fill_null(0) + pl.col("t_reads").first().fill_null(0)).alias(
            "_other_reads"
        ),
        pl.col("cut_site").first().alias("cut_site"),
    )
    alleles = (
        df.group_by("sample", "Modification", "Start", "Length")
        .agg(
            pl.len().cast(pl.Int64).alias("reads"),
            (pl.col("in_pick").str.to_uppercase() == "TRUE").any().alias("_in_peak"),
        )
        .join(per_lib, on="sample", how="left")
    )
    total = pl.col("_indel_reads") + pl.col("_other_reads")
    is_ins = pl.col("Modification") == "ins"
    out = alleles.with_columns(
        pl.col("Modification").replace_strict(_TYPES, default="Other").alias("indel_type"),
        pl.col("Start").alias("start"),
        pl.col("Length").alias("length"),
        pl.when(is_ins).then(pl.col("Length")).otherwise(-pl.col("Length")).alias("size"),
        (pl.col("Start") - pl.col("cut_site")).alias("offset"),
        pl.when(pl.col("Length") % 3 == 0)
        .then(pl.lit("In-frame"))
        .otherwise(pl.lit("Frameshift"))
        .alias("frame"),
        pl.when(pl.col("_in_peak"))
        .then(pl.lit("Main peak"))
        .otherwise(pl.lit("Outside the main peak"))
        .alias("peak"),
        (pl.col("reads") * 100.0 / total).alias("pct_reads"),
        (pl.col("reads") * 100.0 / pl.col("_indel_reads")).alias("pct_indel_reads"),
    ).with_columns(
        pl.format(
            "{} {} bp at {}",
            pl.col("indel_type"),
            pl.col("length"),
            pl.when(pl.col("offset") >= 0)
            .then(pl.format("+{}", pl.col("offset")))
            .otherwise(pl.col("offset").cast(pl.Utf8)),
        ).alias("allele"),
        pl.col("reads")
        .rank(method="ordinal", descending=True)
        .over("sample")
        .cast(pl.Int64)
        .alias("rank"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort("sample", "rank")
