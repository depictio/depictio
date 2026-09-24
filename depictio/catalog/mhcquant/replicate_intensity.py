"""Peptide intensity per raw replicate, long format.

When a run quantifies (``--quantify``), mhcquant links the features of a
sample's raw replicates and the per-sample peptide table ``<sample>.tsv`` gains
one ``intensity_<k>`` column per replicate (``nan`` where the peptide was not
found in that file) next to the consensus ``intensity_cf``. ``k`` counts from 0
in the order the files were linked, which is their samplesheet ``ID`` order
within the sample, so ``replicate`` here is ``k + 1`` and joins the sample
sheet's ``replicate`` column.

One row per sample, peptidoform and replicate the sample has (charge states
summed), with the
intensity on a log10 scale and a detected flag, which is what the
reproducibility views (replicate scatter, replicate UpSet, correlation cards)
are built from. A run without quantification has no replicate columns and this
recipe fails, so its data collection is optional.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="peptides",
        glob_pattern="*.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "peptide": pl.Utf8,
    "sequence": pl.Utf8,
    "replicate": pl.Int64,
    "replicate_label": pl.Utf8,
    "detected": pl.Int64,
    "log10_intensity": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_OUTPUT_SUFFIXES = ("_pin", "_speclib", "_matching_ions", "_all_peaks")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["peptides"]
    rep_cols = [c for c in raw.columns if c.startswith("intensity_") and c[10:].isdigit()]
    if "sequence" not in raw.columns or not rep_cols:
        raise ValueError(
            "mhcquant replicate intensities: no intensity_<k> columns; the run did not quantify"
        )
    raw = raw.with_columns(
        pl.col("source_path").str.split("/").list.last().str.replace(r"\.tsv$", "").alias("sample")
    ).filter(
        pl.col("sequence").is_not_null()
        & ~pl.col("sample").str.contains("(" + "|".join(_OUTPUT_SUFFIXES) + ")$")
    )
    peptide = (
        pl.coalesce(pl.col("peptidoform"), pl.col("sequence"))
        if "peptidoform" in raw.columns
        else pl.col("sequence")
    )
    long = (
        raw.select(pl.col("sample"), peptide.alias("peptide"), pl.col("sequence"), *rep_cols)
        .unpivot(index=["sample", "peptide", "sequence"], variable_name="_col", value_name="_v")
        # A column the sample never wrote (fewer replicates than the widest
        # sample) is all-null after the concat; drop it rather than call it a miss.
        .filter(pl.col("_v").is_not_null().any().over("sample", "_col"))
        .with_columns(
            (pl.col("_col").str.extract(r"(\d+)$", 1).cast(pl.Int64) + 1).alias("replicate"),
            pl.col("_v").replace("nan", None).cast(pl.Float64, strict=False).alias("_i"),
        )
    )
    # The table has one row per precursor, so a peptidoform seen at two charge
    # states has two rows: sum their intensities per replicate.
    long = long.group_by("sample", "peptide", "sequence", "replicate").agg(pl.col("_i").sum())
    return (
        long.with_columns(
            ("Replicate " + pl.col("replicate").cast(pl.Utf8)).alias("replicate_label"),
            (pl.col("_i") > 0).fill_null(False).cast(pl.Int64).alias("detected"),
            pl.when(pl.col("_i") > 0).then(pl.col("_i").log10()).alias("log10_intensity"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "peptide", "replicate"])
    )
