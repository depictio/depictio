"""Which isomiR classes each of the most expressed miRNAs carries.

For the ``MAX_MIRNAS`` miRNAs with the most reads, and for each isomiR class,
two numbers over the samples where the miRNA has at least ``MIN_READS`` reads:
the mean share of the miRNA's reads in that class, and the fraction of those
samples in which the class holds at least ``PRESENT_PCT`` percent of them. On a
dot plot (miRNA x class, colour = mean share, size = fraction of samples) that
reads as "this miRNA is mostly 3' trimmed, everywhere" or "this one carries an
untemplated addition in only part of the cohort".

The classes are not exclusive: a read can be 3' trimmed and carry an addition.
They are:

- Reference: the exact reference mature sequence.
- 3' trimmed / 3' extended: the templated 3' end is shorter / longer.
- 3' addition: non-templated nucleotides added at the 3' end.
- 5' shift: the 5' end, and so the seed, moved.
- Seed change / central change: a nucleotide differs from the reference.

Source: ``**/mirtop/joined_samples_mirtop.tsv``.

Output schema:
    mirna : Utf8
    variant_class : Utf8
    mean_share_pct : Float64   mean share of the miRNA's reads in the class, %
    samples_fraction : Float64 samples where the class holds at least PRESENT_PCT %, 0 to 1
    class_reads : Int64        reads in the class, all samples
    mirna_rank : Int64         1 = the miRNA with the most reads
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="joined",
        glob_pattern="**/mirtop/joined_samples_mirtop.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA"]},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "mirna": pl.Utf8,
    "variant_class": pl.Utf8,
    "mean_share_pct": pl.Float64,
    "samples_fraction": pl.Float64,
    "class_reads": pl.Int64,
    "mirna_rank": pl.Int64,
}

MAX_MIRNAS = 40
MIN_READS = 10
PRESENT_PCT = 5.0

ANNOTATION_COLUMNS = (
    "UID",
    "Read",
    "miRNA",
    "Variant",
    "iso_5p",
    "iso_3p",
    "iso_add3p",
    "iso_snp",
    "iso_5p_nt",
    "iso_3p_nt",
    "iso_add3p_nt",
    "iso_snp_nt",
)


def _signed(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .str.replace(r"^\+", "")
        .cast(pl.Int64, strict=False)
        .fill_null(0)
    )


def _flags() -> dict[str, pl.Expr]:
    variant = pl.col("Variant").cast(pl.Utf8).fill_null("")
    three = _signed("iso_3p")
    return {
        "Reference": variant == "",
        "3' trimmed": three < 0,
        "3' extended": three > 0,
        "3' addition": pl.col("iso_add3p").cast(pl.Int64, strict=False).fill_null(0) > 0,
        "5' shift": _signed("iso_5p") != 0,
        "Seed change": variant.str.contains("iso_snv_seed"),
        "Central change": variant.str.contains("iso_snv_central"),
    }


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Per-class share of the top miRNAs, summarised over samples."""
    joined = sources["joined"]
    samples = [
        c for c in joined.columns if c not in ANNOTATION_COLUMNS and joined[c].dtype.is_numeric()
    ]
    if not samples:
        raise ValueError("mirtop isomir_landscape: no per-sample count columns")
    totals = (
        joined.group_by("miRNA")
        .agg(pl.sum_horizontal(samples).sum().alias("_total"))
        .sort(["_total", "miRNA"], descending=[True, False])
        .head(MAX_MIRNAS)
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("mirna_rank"))
    )
    top = joined.filter(pl.col("miRNA").is_in(totals["miRNA"].to_list()))
    mirna_reads = (
        top.group_by("miRNA")
        .agg([pl.col(s).sum() for s in samples])
        .unpivot(index="miRNA", variable_name="sample", value_name="_mirna_reads")
    )
    parts = []
    for name, flag in _flags().items():
        per = (
            top.filter(flag)
            .group_by("miRNA")
            .agg([pl.col(s).sum() for s in samples])
            .unpivot(index="miRNA", variable_name="sample", value_name="_class_reads")
            .with_columns(pl.lit(name).alias("variant_class"))
        )
        full = mirna_reads.join(per, on=["miRNA", "sample"], how="left").with_columns(
            pl.col("_class_reads").fill_null(0),
            pl.col("variant_class").fill_null(name),
        )
        parts.append(full)
    long = pl.concat(parts).filter(pl.col("_mirna_reads") >= MIN_READS)
    long = long.with_columns(
        (pl.col("_class_reads") * 100.0 / pl.col("_mirna_reads")).alias("_share")
    )
    out = long.group_by(["miRNA", "variant_class"]).agg(
        pl.col("_share").mean().alias("mean_share_pct"),
        (pl.col("_share") >= PRESENT_PCT).mean().cast(pl.Float64).alias("samples_fraction"),
        pl.col("_class_reads").sum().cast(pl.Int64).alias("class_reads"),
    )
    out = out.join(totals.select("miRNA", "mirna_rank"), on="miRNA").rename({"miRNA": "mirna"})
    order = {name: i for i, name in enumerate(_flags())}
    out = out.with_columns(
        pl.col("variant_class").replace_strict(order, return_dtype=pl.Int64).alias("_order")
    )
    return out.sort(["mirna_rank", "_order"]).select(list(EXPECTED_SCHEMA))
