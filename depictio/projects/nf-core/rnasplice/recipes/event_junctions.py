"""STAR splice junctions around the called rMATS events, per gene and condition.

A sashimi plot draws the splice junctions of a locus as arcs, each labelled
with the reads that cross it. nf-core/rnasplice publishes what the arcs need
but no sashimi of its own: STAR writes every junction it saw in a sample
(``star_salmon/log/<sample>.SJ.out.tab``) and rMATS says which events change.
This recipe keeps the junctions that touch or span the alternative region of a
called rMATS event, averages their uniquely mapped reads over the replicates of
each condition the event's contrast compares, and writes one row per gene,
condition and junction. A gene pick then draws that gene's event junctions in
one lane per condition.

Rows are per gene, not per event: the events of one gene often share a
flanking exon, and with it a junction, and a row per event would draw every
shared arc twice. A gene called in several contrasts carries the conditions of
each, once.

STAR columns (no header): chromosome, first and last intronic base (1-based),
strand (0 undefined, 1 +, 2 -), intron motif, annotated (1 when the GTF has
the junction), uniquely mapped reads, multi-mapped reads, maximum overhang.
A junction runs from its donor (the last exonic base before the intron) to its
acceptor (the first exonic base after it), the coordinates a sashimi draws.
The annotated flag is not carried: rnasplice runs STAR in two-pass mode, which
marks every junction of the first pass as annotated, so it no longer tells a
known junction from a novel one.

A junction belongs to an event when its intron overlaps or abuts the event's
alternative region (the skipped exon, the retained intron, the pair of
mutually exclusive exons, the long form of an alternative splice site): that
is every inclusion and skipping junction of the event, plus any longer
junction that spans it. On an unstranded library STAR infers the strand from
the intron motif; a junction on the other strand than the gene is left out.

Sources:
    junctions  every ``*.SJ.out.tab`` under the run root (STAR, one per sample)
    events     the ``rmats_events`` collection (dc_ref): the called events
    sheet      ``pipeline_info/samplesheet.valid.csv``: each sample's condition,
               in the labels the contrasts use (a design table may relabel
               the hub's condition, never the contrasts)
    contrasts  the ``contrasts`` collection (dc_ref): treatment and control

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_STAR_COLUMNS = [
    "chrom",
    "intron_start",
    "intron_end",
    "strand",
    "motif",
    "annotated",
    "unique_reads",
    "multi_reads",
    "max_overhang",
]

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="junctions",
        glob_pattern="**/*.SJ.out.tab",
        format="tsv",
        input_schema={
            "chrom": pl.Utf8,
            "intron_start": pl.Utf8,
            "intron_end": pl.Utf8,
            "strand": pl.Utf8,
            "unique_reads": pl.Utf8,
            "source_path": pl.Utf8,
        },
        # Headerless; read as text, since chromosome names mix digits and letters.
        read_kwargs={"has_header": False, "new_columns": _STAR_COLUMNS, "infer_schema_length": 0},
        source_path="source_path",
    ),
    RecipeSource(
        ref="events",
        dc_ref="rmats_events",
        input_schema={
            "contrast": pl.Utf8,
            "gene_id": pl.Utf8,
            "gene_name": pl.Utf8,
            "chrom": pl.Utf8,
            "strand": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
            "significant": pl.Boolean,
        },
    ),
    RecipeSource(
        ref="sheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="csv",
        input_schema={"sample": pl.Utf8, "condition": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(
        ref="contrasts",
        dc_ref="contrasts",
        input_schema={"contrast": pl.Utf8, "treatment": pl.Utf8, "control": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "condition": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "reads": pl.Int64,
}

_SAMPLE = r"([^/]+)\.SJ\.out\.tab$"
_RUN_SUFFIX = r"_T\d+$"
# Puts every chromosome on one axis, so an overlap join on two inequalities
# never pairs a junction with a region of another chromosome.
_CHROM_STRIDE = 10_000_000_000
_STRAND = {"1": "+", "2": "-"}


def _chrom_key(col: str) -> pl.Expr:
    """Chromosome name without the ``chr`` prefix: rMATS writes chr1, STAR 1."""
    return pl.col(col).cast(pl.Utf8).str.replace(r"(?i)^chr", "")


def _regions(events: pl.DataFrame, contrasts: pl.DataFrame) -> pl.DataFrame:
    """One row per called event: its gene, the region's ends and the conditions compared."""
    called = events.filter(pl.col("significant").fill_null(False)).drop_nulls(["start", "end"])
    return called.join(contrasts.select("contrast", "treatment", "control"), on="contrast").select(
        "gene_id",
        "gene_name",
        pl.col("chrom").alias("event_chrom"),
        _chrom_key("chrom").alias("chrom_key"),
        pl.col("strand").alias("gene_strand"),
        pl.col("start").cast(pl.Int64),
        pl.col("end").cast(pl.Int64),
        pl.concat_list("treatment", "control").alias("conditions"),
    )


def _per_sample(junctions: pl.DataFrame, sheet: pl.DataFrame) -> pl.DataFrame:
    """Every junction of every sample with its condition and read count."""
    # The sheet lists a sample once per sequencing run (_T1, _T2...); STAR
    # names its outputs after the merged sample.
    conditions = sheet.select(
        pl.col("sample").cast(pl.Utf8).str.replace(_RUN_SUFFIX, ""), pl.col("condition")
    ).unique(subset="sample")
    return (
        junctions.select(
            pl.col("source_path")
            .str.extract(_SAMPLE, 1)
            .str.replace(_RUN_SUFFIX, "")
            .alias("sample"),
            _chrom_key("chrom").alias("chrom_key"),
            pl.col("intron_start").cast(pl.Int64, strict=False),
            pl.col("intron_end").cast(pl.Int64, strict=False),
            pl.col("strand").cast(pl.Utf8).replace_strict(_STRAND, default=None).alias("jx_strand"),
            pl.col("unique_reads").cast(pl.Int64, strict=False).fill_null(0).alias("reads"),
        )
        .drop_nulls(["intron_start", "intron_end"])
        .filter(pl.col("reads") > 0)
        .join(conditions, on="sample", how="inner")
    )


def _gene_junctions(per_sample: pl.DataFrame, regions: pl.DataFrame) -> pl.DataFrame:
    """Each distinct junction paired with the genes whose called events it touches."""
    chroms = (
        pl.concat([per_sample.select("chrom_key"), regions.select("chrom_key")])
        .unique()
        .sort("chrom_key")
        .with_row_index("chrom_idx")
        .with_columns((pl.col("chrom_idx").cast(pl.Int64) * _CHROM_STRIDE).alias("offset"))
        .drop("chrom_idx")
    )
    distinct = (
        per_sample.select("chrom_key", "intron_start", "intron_end", "jx_strand")
        .unique(subset=["chrom_key", "intron_start", "intron_end"], keep="first")
        .join(chroms, on="chrom_key")
        .with_columns(
            (pl.col("offset") + pl.col("intron_start")).alias("g_start"),
            (pl.col("offset") + pl.col("intron_end")).alias("g_end"),
        )
        .drop("offset")
    )
    spans = regions.join(chroms, on="chrom_key").select(
        "gene_id",
        "gene_name",
        "event_chrom",
        pl.col("chrom_key").alias("event_key"),
        "gene_strand",
        "conditions",
        # Abutting counts: an inclusion junction ends on the exon it includes.
        (pl.col("offset") + pl.col("start") - 1).alias("g_region_start"),
        (pl.col("offset") + pl.col("end") + 1).alias("g_region_end"),
    )
    pairs = distinct.join_where(
        spans,
        pl.col("g_start") <= pl.col("g_region_end"),
        pl.col("g_end") >= pl.col("g_region_start"),
    ).filter(
        (pl.col("chrom_key") == pl.col("event_key"))
        & (pl.col("jx_strand").is_null() | (pl.col("jx_strand") == pl.col("gene_strand")))
    )
    return (
        pairs.explode("conditions")
        .rename({"conditions": "condition"})
        .group_by("gene_id", "condition", "chrom_key", "intron_start", "intron_end")
        .agg(
            pl.col("gene_name").first(),
            pl.col("event_chrom").first(),
            pl.col("gene_strand").first(),
        )
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per gene, condition and junction around the gene's called events."""
    regions = _regions(sources["events"], sources["contrasts"])
    if regions.is_empty():
        raise ValueError("rnasplice event_junctions: no called rMATS event to draw")
    per_sample = _per_sample(sources["junctions"], sources["sheet"])
    if per_sample.is_empty():
        raise ValueError("rnasplice event_junctions: no STAR junction matches a sample")
    replicates = per_sample.group_by("condition").agg(pl.col("sample").n_unique().alias("n"))
    pairs = _gene_junctions(per_sample, regions)
    reads = per_sample.group_by("condition", "chrom_key", "intron_start", "intron_end").agg(
        pl.col("reads").sum().alias("total")
    )
    out = (
        pairs.join(reads, on=["condition", "chrom_key", "intron_start", "intron_end"], how="left")
        .join(replicates, on="condition", how="left")
        .with_columns(
            (pl.col("total").fill_null(0) / pl.col("n")).round(0).cast(pl.Int64).alias("reads")
        )
        .filter(pl.col("reads") >= 1)
    )
    out = out.select(
        "gene_id",
        pl.col("gene_name").fill_null(pl.col("gene_id")),
        "condition",
        pl.col("event_chrom").alias("chrom"),
        (pl.col("intron_start") - 1).alias("start"),
        (pl.col("intron_end") + 1).alias("end"),
        pl.col("gene_strand").alias("strand"),
        "reads",
    )
    return out.select(list(OUTPUT_SCHEMA)).sort(["gene_id", "start", "end", "condition"])
