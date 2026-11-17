"""featureCounts count matrix as a long table, one row per feature per library.

``featureCounts -o <name>.featureCounts.txt a.bam b.bam ...`` writes a comment
line (``# Program:featureCounts v2.0.1; Command:...``), then a header
``Geneid Chr Start End Strand Length <bam> <bam> ...`` and one row per feature.
A meta-feature (a gene, counted over its exons) carries one value per exon in
``Chr``, ``Start``, ``End`` and ``Strand``, joined by ``;``; it is collapsed here
to its first contig and strand and to the span from its first start to its last
end, which is what a locus table and a genome axis need.

Library columns are named after the BAM path the pipeline passed. The sample is
that file name with its stage and format suffixes stripped
(``GM_30min.sorted.bam`` -> ``GM_30min``), through
``depictio/recipes/lib/sample_ids.py``, the rule every alignment-named output
already follows, plus the ``umi_dedup`` token of a UMI run.

Counts are kept raw and normalised to counts per million of the library's
counted reads (``cpm``), with ``log2_cpm = log2(cpm + 1)``, the scale every
correlation, PCA and fold change downstream reads. Features with no read in any
library are dropped: they carry no information and, on a full GTF, are a third
of the rows.

Output schema:
    gene_id : Utf8       feature id (the GTF gene id or name featureCounts used)
    chromosome : Utf8    first contig of the feature
    start : Int64        first start of the feature (1-based, as featureCounts writes it)
    end : Int64          last end of the feature
    strand : Utf8        first strand of the feature
    length : Int64       feature length, the union of its exons
    sample : Utf8        library
    counts : Int64       reads counted over the feature
    cpm : Float64        counts per million counted reads of the library
    log2_cpm : Float64   log2(cpm + 1)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="matrix",
        glob_pattern="**/*.featureCounts.txt",
        format="TSV",
        read_kwargs={"comment_prefix": "#", "infer_schema_length": 0, "quote_char": None},
        input_schema={
            "Geneid": pl.Utf8,
            "Chr": pl.Utf8,
            "Start": pl.Utf8,
            "End": pl.Utf8,
            "Strand": pl.Utf8,
            "Length": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "chromosome": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "length": pl.Int64,
    "sample": pl.Utf8,
    "counts": pl.Int64,
    "cpm": pl.Float64,
    "log2_cpm": pl.Float64,
}

ANNOTATION_COLUMNS = ("Geneid", "Chr", "Start", "End", "Strand", "Length")


def library_name(column: str) -> str:
    """The sample a featureCounts library column counts: the BAM name, unsuffixed."""
    stem = strip_stage_suffixes(column)
    for token in (".umi_dedup", "_umi_dedup", ".umi"):
        if stem.endswith(token):
            stem = stem[: -len(token)]
    return stem or column


def _first(column: str) -> pl.Expr:
    return pl.col(column).str.split(";").list.first().str.strip_chars()


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Collapse each feature's exon lists and melt the libraries into rows."""
    raw = sources["matrix"]
    libraries = [c for c in raw.columns if c not in ANNOTATION_COLUMNS]
    if not libraries:
        raise ValueError("subread_gene_counts: the matrix has no library column")
    renamed = {c: library_name(c) for c in libraries}
    if len(set(renamed.values())) != len(renamed):
        # Two BAMs that strip to one sample would be summed into one library.
        renamed = {c: c for c in libraries}

    features = raw.select(
        pl.col("Geneid").cast(pl.Utf8).alias("gene_id"),
        _first("Chr").alias("chromosome"),
        pl.col("Start")
        .str.split(";")
        .list.eval(pl.element().cast(pl.Int64, strict=False))
        .list.min()
        .alias("start"),
        pl.col("End")
        .str.split(";")
        .list.eval(pl.element().cast(pl.Int64, strict=False))
        .list.max()
        .alias("end"),
        _first("Strand").alias("strand"),
        pl.col("Length").cast(pl.Int64, strict=False).alias("length"),
        *[pl.col(c).cast(pl.Int64, strict=False).fill_null(0).alias(renamed[c]) for c in libraries],
    )
    long = features.unpivot(
        index=["gene_id", "chromosome", "start", "end", "strand", "length"],
        on=list(renamed.values()),
        variable_name="sample",
        value_name="counts",
    )
    # A feature with no read anywhere says nothing about any library.
    seen = long.group_by("gene_id").agg(pl.col("counts").sum().alias("_total"))
    long = long.join(seen.filter(pl.col("_total") > 0).select("gene_id"), on="gene_id")
    library_total = pl.col("counts").sum().over("sample").cast(pl.Float64)
    return (
        long.with_columns(
            (pl.col("counts") / library_total.replace(0.0, None) * 1e6).alias("cpm"),
        )
        .with_columns((pl.col("cpm") + 1.0).log(2).alias("log2_cpm"))
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["gene_id", "sample"])
    )
