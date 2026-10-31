"""nf-core/raredisease mean depth per contig and sample, from the mosdepth summary.

mosdepth runs on the duplicate-marked alignment of every sample and writes one
summary row per contig (length, bases, mean, min, max) and a ``total`` row.
This recipe keeps the contig rows, classes them (autosome, X, Y, mitochondrion,
other for alt, unplaced and decoy contigs) and adds each contig's depth relative
to the sample's autosomal mean. That ratio is what tells the sex and the
mitochondrial copy number apart from sequencing depth: an autosome sits at 1, X
at 1 in a female and 0.5 in a male, Y near 0 in a female, the mitochondrion at
hundreds.

Sources:
    summary  every ``qc_bam/*_mosdepth.mosdepth.summary.txt``, the sample in
             ``source_path``

Output schema:
    sample : Utf8          sample id (the file name before ``_mosdepth``)
    contig : Utf8          contig name as the reference spells it
    contig_class : Utf8    autosome / X / Y / mitochondrion / other
    class_order : Int64    1 to 5, the order above
    length : Int64         contig length
    bases : Int64          bases covered by reads, summed over positions
    mean_depth : Float64   mosdepth's mean depth of the contig
    min_depth : Int64
    max_depth : Int64
    relative_depth : Float64   mean depth over the sample's autosomal mean, null without autosomes
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        glob_pattern="qc_bam/*_mosdepth.mosdepth.summary.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
        input_schema={
            "chrom": pl.Utf8,
            "length": pl.Utf8,
            "bases": pl.Utf8,
            "mean": pl.Utf8,
            "min": pl.Utf8,
            "max": pl.Utf8,
            "source_path": pl.Utf8,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "contig": pl.Utf8,
    "contig_class": pl.Utf8,
    "class_order": pl.Int64,
    "length": pl.Int64,
    "bases": pl.Int64,
    "mean_depth": pl.Float64,
    "min_depth": pl.Int64,
    "max_depth": pl.Int64,
    "relative_depth": pl.Float64,
}

_SAMPLE_RE = r"([^/]+)_mosdepth\.mosdepth\.summary\.txt$"
_AUTOSOME = r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2])$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per contig of every sample's mosdepth summary."""
    contig = pl.col("chrom")
    frame = (
        sources["summary"]
        .filter(contig.is_not_null() & (contig != "total") & (contig != "chrom"))
        .with_columns(
            pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
            contig.alias("contig"),
            pl.col("length").cast(pl.Int64, strict=False),
            pl.col("bases").cast(pl.Int64, strict=False),
            pl.col("mean").cast(pl.Float64, strict=False).alias("mean_depth"),
            pl.col("min").cast(pl.Int64, strict=False).alias("min_depth"),
            pl.col("max").cast(pl.Int64, strict=False).alias("max_depth"),
        )
        .with_columns(
            pl.when(contig.str.contains(_AUTOSOME))
            .then(pl.lit("autosome"))
            .when(contig.is_in(["X", "chrX"]))
            .then(pl.lit("X"))
            .when(contig.is_in(["Y", "chrY"]))
            .then(pl.lit("Y"))
            .when(contig.is_in(["MT", "M", "chrM", "chrMT"]))
            .then(pl.lit("mitochondrion"))
            .otherwise(pl.lit("other"))
            .alias("contig_class")
        )
    )
    # Length-weighted autosomal mean depth per sample (bases over length).
    autosomal = (
        frame.filter(pl.col("contig_class") == "autosome")
        .group_by("sample")
        .agg((pl.col("bases").sum() / pl.col("length").sum()).alias("_auto_mean"))
    )
    order = {"autosome": 1, "X": 2, "Y": 3, "mitochondrion": 4, "other": 5}
    return (
        frame.join(autosomal, on="sample", how="left")
        .with_columns(
            pl.col("contig_class").replace_strict(order, default=5).alias("class_order"),
            pl.when(pl.col("_auto_mean") > 0)
            .then(pl.col("mean_depth") / pl.col("_auto_mean"))
            .otherwise(None)
            .alias("relative_depth"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "class_order", "contig"])
    )
