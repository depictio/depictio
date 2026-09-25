"""miRNA expression per sample, aggregated from the mirtop isomiR table.

nf-core/smrnaseq exports mirtop's annotation of every sample as one joined
table, ``mirna_quant/mirtop/joined_samples_mirtop.tsv``: one row per distinct
read sequence (an isomiR), its miRNA, its variant description, and one count
column per sample. A miRNA's expression is the sum over all its isomiRs; that
is the count the downstream views read, and it is what mirtop's own ``counts``
command and the pipeline's edgeR input are built from.

Counts are normalised to counts per million miRNA-assigned reads (CPM) within
each sample. That is a library-size normalisation only; it does not correct
for composition the way TMM or DESeq2 size factors do, so it is the scale for
exploring and ranking, not for a formal test.

Two isomiR summaries ride along per (sample, miRNA): how many distinct isomiR
sequences carried reads, and the share of reads that match the reference
mature sequence exactly (mirtop writes ``NA`` as the variant of those rows).

When a design table is declared (the ``metadata`` data collection: sample id in
its first column, or in a column named ``sample``), its other columns are
joined on as text, under their own names, so a figure can colour or split by
the run's design factor. Without one the output carries no design columns.

Sources:
    joined    ``**/mirtop/joined_samples_mirtop.tsv``
    metadata  optional design table

Output schema:
    sample : Utf8
    mirna : Utf8            mature miRNA name
    reads : Int64           reads assigned to the miRNA, all isomiRs
    cpm : Float64           reads per million miRNA-assigned reads of the sample
    log2_cpm : Float64      log2(CPM + 1)
    isomirs : Int64         distinct isomiR sequences with at least one read
    reference_pct : Float64 reads matching the reference mature sequence, % (null at 0 reads)
    <design columns> : Utf8 one per metadata column, when a design table is given
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="joined",
        glob_pattern="**/mirtop/joined_samples_mirtop.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA"]},
    ),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "mirna": pl.Utf8,
    "reads": pl.Int64,
    "cpm": pl.Float64,
    "log2_cpm": pl.Float64,
    "isomirs": pl.Int64,
    "reference_pct": pl.Float64,
}
# Design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: The annotation columns mirtop writes before the per-sample counts.
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


def sample_columns(joined: pl.DataFrame) -> list[str]:
    """The per-sample count columns: every numeric column after the annotations."""
    cols = [
        c for c in joined.columns if c not in ANNOTATION_COLUMNS and joined[c].dtype.is_numeric()
    ]
    if not cols:
        raise ValueError("mirtop: no per-sample count columns in the joined table")
    if "miRNA" not in joined.columns:
        raise ValueError("mirtop: the joined table has no miRNA column")
    return cols


def design_columns(metadata: pl.DataFrame | None, reserved: set[str]) -> pl.DataFrame | None:
    """The design table keyed on ``sample``, every other column as text.

    The sample id is the column named ``sample`` when there is one, else the
    first column (the convention the template's METADATA_ID_COL follows).
    Column names are made Delta-safe; one that collides with an output column
    is dropped rather than allowed to overwrite it.
    """
    if metadata is None or metadata.is_empty() or metadata.width < 2:
        return None
    id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    keep: dict[str, str] = {}
    for col in metadata.columns:
        if col == id_col:
            continue
        safe = re.sub(r"[^0-9A-Za-z]+", "_", col.strip()).strip("_") or "column"
        if safe in reserved or safe in keep.values():
            continue
        keep[col] = safe
    if not keep:
        return None
    return (
        metadata.select(
            pl.col(id_col).cast(pl.Utf8).alias("sample"),
            *[pl.col(c).cast(pl.Utf8).alias(s) for c, s in keep.items()],
        )
        .filter(pl.col("sample").is_not_null())
        .unique(subset="sample", keep="first")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Sum isomiRs per miRNA and sample, normalise to CPM, join the design."""
    joined = sources["joined"]
    samples = sample_columns(joined)
    is_reference = pl.col("Variant").is_null() | (pl.col("Variant") == "NA")

    per_mirna = joined.group_by("miRNA").agg(
        *[pl.col(s).sum().alias(f"reads::{s}") for s in samples],
        *[(pl.col(s) > 0).sum().alias(f"isomirs::{s}") for s in samples],
        *[pl.col(s).filter(is_reference).sum().alias(f"ref::{s}") for s in samples],
    )
    long = (
        per_mirna.unpivot(index="miRNA", variable_name="_key", value_name="_value")
        .with_columns(pl.col("_key").str.split_exact("::", 1).alias("_parts"))
        .unnest("_parts")
        .rename({"field_0": "_what", "field_1": "sample", "miRNA": "mirna"})
        .pivot(on="_what", index=["sample", "mirna"], values="_value")
    )
    # Keep the miRNAs seen in at least one sample; a miRNA absent everywhere
    # carries no information and would only pad every downstream matrix.
    seen = long.group_by("mirna").agg(pl.col("reads").sum().alias("_total"))
    long = long.join(seen.filter(pl.col("_total") > 0).select("mirna"), on="mirna")

    totals = long.group_by("sample").agg(pl.col("reads").sum().alias("_library"))
    out = (
        long.join(totals, on="sample")
        .with_columns(
            pl.col("reads").cast(pl.Int64),
            pl.col("isomirs").cast(pl.Int64),
            pl.when(pl.col("_library") > 0)
            .then(pl.col("reads") * 1e6 / pl.col("_library"))
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("cpm"),
            pl.when(pl.col("reads") > 0)
            .then(pl.col("ref") * 100.0 / pl.col("reads"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("reference_pct"),
        )
        .with_columns((pl.col("cpm") + 1.0).log(2).alias("log2_cpm"))
    )
    out = out.select(list(EXPECTED_SCHEMA))

    design = design_columns(sources.get("metadata"), set(EXPECTED_SCHEMA))
    if design is not None:
        out = out.join(design, on="sample", how="left")
    return out.sort(["sample", "mirna"])
