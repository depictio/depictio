"""isomiR composition of each sample, in four exclusive partitions.

Most reads assigned to a miRNA do not match its reference mature sequence
exactly: Dicer and Drosha cut with some slack, exonucleases trim the 3' end,
and terminal nucleotidyl transferases add untemplated nucleotides (mostly A or
U) to it. mirtop describes every read sequence against the reference, and this
recipe partitions each sample's miRNA reads four ways, each partition summing
to all of the sample's miRNA reads:

``3' end``
    Reference 3' end, 3' trimmed (shorter than the reference), 3' templated
    extension (longer, matching the genome), or non-templated 3' addition
    (whatever the templated end, the read carries added nucleotides).
``5' end``
    Reference 5' end, or shifted by 1 nt, or by 2 nt or more. A 5' shift moves
    the seed, and with it the targets.
``3' addition``
    No addition, a single added A, U, C or G, or 2 nt or more. Adenylation and
    uridylation are the two modifications with known effects on stability.
``Nucleotide change``
    No change, a change in the seed (nt 2 to 8), a central change, or another
    change. mirtop cannot tell an editing event or a SNP from a sequencing
    error; a change seen in one sample only is most likely the latter.

The shape is the stacked-composition contract (``sample``, ``rank``,
``taxon``, ``abundance``) with ``rank`` naming the partition, so one tile
switches between the four.

Source: ``**/mirtop/joined_samples_mirtop.tsv``.

Output schema:
    sample : Utf8
    rank : Utf8        partition: 3' end, 5' end, 3' addition, Nucleotide change
    taxon : Utf8       class within the partition
    abundance : Float64  reads in the class
    percent : Float64  of the sample's miRNA reads, %
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
    "sample": pl.Utf8,
    "rank": pl.Utf8,
    "taxon": pl.Utf8,
    "abundance": pl.Float64,
    "percent": pl.Float64,
}

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


def classify(joined: pl.DataFrame) -> pl.DataFrame:
    """Add one class column per partition to the isomiR rows."""
    five, three = _signed("iso_5p"), _signed("iso_3p")
    added = pl.col("iso_add3p").cast(pl.Int64, strict=False).fill_null(0)
    added_nt = pl.col("iso_add3p_nt").cast(pl.Utf8).fill_null("").str.replace_all("T", "U")
    variant = pl.col("Variant").cast(pl.Utf8).fill_null("")
    changes = pl.col("iso_snp").cast(pl.Int64, strict=False).fill_null(0)
    return joined.with_columns(
        pl.when(added > 0)
        .then(pl.lit("Non-templated 3' addition"))
        .when(three < 0)
        .then(pl.lit("3' trimmed"))
        .when(three > 0)
        .then(pl.lit("3' templated extension"))
        .otherwise(pl.lit("Reference 3' end"))
        .alias("_c_3' end"),
        pl.when(five == 0)
        .then(pl.lit("Reference 5' end"))
        .when(five.abs() == 1)
        .then(pl.lit("5' shift, 1 nt"))
        .otherwise(pl.lit("5' shift, 2 nt or more"))
        .alias("_c_5' end"),
        pl.when(added <= 0)
        .then(pl.lit("No addition"))
        .when(added_nt.str.len_chars() == 1)
        .then(pl.lit("+") + added_nt)
        .otherwise(pl.lit("+2 nt or more"))
        .alias("_c_3' addition"),
        pl.when(variant.str.contains("iso_snv_seed"))
        .then(pl.lit("Seed change"))
        .when(variant.str.contains("iso_snv_central"))
        .then(pl.lit("Central change"))
        .when((changes > 0) | variant.str.contains("iso_snv"))
        .then(pl.lit("Other change"))
        .otherwise(pl.lit("No change"))
        .alias("_c_Nucleotide change"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Reads per class and sample, for each partition."""
    joined = sources["joined"]
    samples = [
        c for c in joined.columns if c not in ANNOTATION_COLUMNS and joined[c].dtype.is_numeric()
    ]
    if not samples:
        raise ValueError("mirtop isomir_composition: no per-sample count columns")
    classed = classify(joined)
    parts = []
    for column in [c for c in classed.columns if c.startswith("_c_")]:
        per_class = classed.group_by(column).agg([pl.col(s).sum() for s in samples])
        parts.append(
            per_class.unpivot(index=column, variable_name="sample", value_name="abundance")
            .rename({column: "taxon"})
            .with_columns(pl.lit(column[3:]).alias("rank"))
        )
    long = pl.concat(parts).with_columns(pl.col("abundance").cast(pl.Float64))
    long = long.with_columns(
        (pl.col("abundance") * 100.0 / pl.col("abundance").sum().over(["sample", "rank"]))
        .fill_nan(None)
        .alias("percent")
    )
    return long.select(list(EXPECTED_SCHEMA)).sort(
        ["sample", "rank", "abundance"], descending=[False, False, True]
    )
