"""Tidy HOMER ``annotatePeaks.pl`` output into a per-peak annotation table.

``<sample>_peaks.annotatePeaks.txt`` is a tab-separated table whose first header
cell embeds the command line (``PeakID (cmd=annotatePeaks.pl <peaks> ...)``) and
therefore differs per file; when several files are concatenated each such column
is coalesced into ``peak_id``. The sample is read off the MACS2 peak name
(``<sample>_peak_12``); consensus-level tables, whose ids are ``Interval_12``,
fall back to ``consensus``.

``annotation_class`` is the coarse HOMER class (``promoter-TSS``, ``intron``,
``exon``, ``Intergenic``, ``TTS``, ``5' UTR``, ``3' UTR``, ``non-coding``) taken
from the ``Annotation`` column before its parenthesised detail, so peaks group
by feature type without the transcript-level noise.

Columns HOMER fills only for some annotation sources are kept but may be
entirely null: ``gene_type`` is empty when the run annotated against a plain
GTF rather than a HOMER genome package, and ``strand`` is ``+`` for every row
when the peaks came from MACS2 (which calls peaks strandlessly).

Output schema:
    sample : Utf8               sample the peak was called in
    peak_id : Utf8              HOMER/MACS2 peak identifier
    chr : Utf8                  chromosome
    start : Int64               peak start (1-based, as HOMER reports it)
    end : Int64                 peak end
    strand : Utf8               peak strand as HOMER reports it
    peak_score : Float64        score carried over from the peak caller
    annotation_class : Utf8     coarse genomic feature class
    annotation : Utf8           full HOMER annotation string
    distance_to_tss : Int64     signed distance to the nearest TSS (bp)
    nearest_promoter_id : Utf8  identifier of the nearest promoter
    gene_name : Utf8            symbol of the nearest gene
    gene_type : Utf8            biotype of the nearest gene, when annotated
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="annotation",
        glob_pattern="**/*.annotatePeaks.txt",
        format="TSV",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA"]},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "peak_id": pl.Utf8,
    "chr": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "peak_score": pl.Float64,
    "annotation_class": pl.Utf8,
    "annotation": pl.Utf8,
    "distance_to_tss": pl.Int64,
    "nearest_promoter_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "gene_type": pl.Utf8,
}

# HOMER header cell -> output column. Every one of these is written by
# `annotatePeaks.pl` whatever the annotation source, except `Gene Type`, which
# only a HOMER genome package fills in (declared optional below).
_RENAMES = {
    "Chr": "chr",
    "Start": "start",
    "End": "end",
    "Strand": "strand",
    "Peak Score": "peak_score",
    "Annotation": "annotation",
    "Distance to TSS": "distance_to_tss",
    "Nearest PromoterID": "nearest_promoter_id",
    "Gene Name": "gene_name",
}
_OPTIONAL_RENAMES = {"Gene Type": "gene_type"}

_PEAK_SAMPLE = r"^(.+)_peak_\d+[a-z]*$"
_CONSENSUS_LABEL = "consensus"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Coalesce the per-file PeakID columns, rename and type the HOMER columns."""
    df = sources["annotation"]
    id_cols = [c for c in df.columns if c.startswith("PeakID")]
    if not id_cols:
        raise ValueError("homer_annotate_peaks: no `PeakID` column found")
    missing = [c for c in _RENAMES if c not in df.columns]
    if missing:
        raise ValueError(f"homer_annotate_peaks: input lacks columns {missing}")

    for header, column in _OPTIONAL_RENAMES.items():
        if header not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(header))

    df = df.with_columns(pl.coalesce([pl.col(c) for c in id_cols]).cast(pl.Utf8).alias("peak_id"))
    df = df.drop(id_cols).rename({**_RENAMES, **_OPTIONAL_RENAMES})
    df = df.with_columns(
        pl.col("peak_id").str.extract(_PEAK_SAMPLE, 1).fill_null(_CONSENSUS_LABEL).alias("sample"),
        pl.col("chr").cast(pl.Utf8),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        pl.col("strand").cast(pl.Utf8),
        pl.col("peak_score").cast(pl.Float64, strict=False),
        pl.col("annotation").cast(pl.Utf8),
        pl.col("annotation")
        .cast(pl.Utf8)
        .str.replace(r"\s*\(.*$", "")
        .str.strip_chars()
        .alias("annotation_class"),
        # HOMER writes the distance as an integer, but a concatenated frame read
        # as text can carry `12345.0` from another producer: parse as float first.
        pl.col("distance_to_tss").cast(pl.Float64, strict=False).round(0).cast(pl.Int64),
        pl.col("nearest_promoter_id").cast(pl.Utf8),
        pl.col("gene_name").cast(pl.Utf8),
        pl.col("gene_type").cast(pl.Utf8),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["sample", "chr", "start"])
