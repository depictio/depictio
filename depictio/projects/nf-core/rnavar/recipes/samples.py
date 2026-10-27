"""nf-core/rnavar sample hub: one row per sample, from the reads to the calls.

rnavar does not publish the samplesheet it ran on, and the samplesheet carries
no design column anyway. The one thing every output agrees on is the sample id
(STAR, Picard, samtools and HaplotypeCaller all prefix their files with it), so
the hub is built from the outputs: the samples STAR aligned or HaplotypeCaller
called (a run started from BAM, CRAM or VCF skips STAR, one that stops before
calling has no callset), enriched with what a run may write. A missing source
leaves its columns null rather than failing the collection.

* ``star``: input reads and the read fate (catalog ``star/log_final``);
* ``junctions``: the share of novel splice junctions (``star/junctions``);
* ``dups``: Picard's duplication rate (``picard/markduplicates_metrics``),
  as a percentage;
* ``stats``: from ``samtools stats`` (``samtools/stats_sections``), the share of
  covered bases at 10x or more, read off the coverage histogram, which is the
  part of the transcriptome deep enough to call on;
* ``idxstats``: the mitochondrial, chrY and alt / unplaced contig shares of the
  mapped reads (``samtools/idxstats``);
* ``callset``: the PASS calls, SNVs, indels, Ts/Tv, het/hom ratio and median
  depth of the sample's callset (``vcf/callset_summary``, one caller in rnavar).

The design table, when the template declares one (``METADATA_FILE``: sample id
in the column named ``sample`` or in the first column, every other column a
factor), is joined on the sample, so the hub carries the run's factors under
their own names and ``{GROUP_COL}`` resolves against it. Without one the hub
carries a constant ``__no_group__`` column, the value ``GROUP_COL`` falls back
to, so the group filter and the tiles grouped by it still resolve on one group.
Nothing is parsed out of sample names.

Output schema (the design columns right after ``sample``):
    sample : Utf8
    input_reads : Int64                 reads given to STAR
    uniquely_mapped_pct : Float64       percent of the input
    multimapped_pct : Float64           percent of the input
    unmapped_pct : Float64              percent of the input
    mismatch_rate_pct : Float64         STAR mismatches per aligned base, percent
    splices_annotated_pct : Float64     splices on an annotated junction, percent
    novel_junction_pct : Float64        junctions absent from the annotation, percent
    duplication_pct : Float64           Picard PERCENT_DUPLICATION x 100
    bases_10x_pct : Float64             covered bases at depth 10 or more, percent
    mito_reads_pct : Float64            mapped reads on the mitochondrion, percent
    chry_reads_pct : Float64            mapped reads on chrY, percent
    other_contig_reads_pct : Float64    mapped reads on alt, unplaced and decoy contigs, percent;
                                        on GRCh38 the rDNA repeats sit there, so this is
                                        mostly ribosomal RNA the library kept
    pass_calls : Int64                  PASS calls of the sample's callset
    snvs : Int64                        PASS SNVs
    indels : Int64                      PASS indels
    pass_pct : Float64                  PASS calls over all calls, percent
    ts_tv : Float64                     transitions over transversions, PASS SNVs
    het_hom_ratio : Float64             heterozygous over homozygous-alternate PASS calls
    median_dp : Float64                 median read depth at the PASS calls
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="star",
        dc_ref="star_log_final",
        optional=True,
        input_schema={
            "sample": pl.Utf8,
            "input_reads": pl.Int64,
            "uniquely_mapped_pct": pl.Float64,
            "multimapped_pct": pl.Float64,
            "unmapped_pct": pl.Float64,
            "mismatch_rate_pct": pl.Float64,
            "splices_annotated_pct": pl.Float64,
        },
    ),
    RecipeSource(
        ref="junctions",
        dc_ref="star_junctions",
        optional=True,
        input_schema={"sample": pl.Utf8, "annotation": pl.Utf8, "junctions": pl.Int64},
    ),
    RecipeSource(
        ref="dups",
        dc_ref="picard_markduplicates_metrics",
        optional=True,
        input_schema={"sample": pl.Utf8, "percent_duplication": pl.Float64},
    ),
    RecipeSource(
        ref="stats",
        dc_ref="samtools_stats_sections",
        optional=True,
        input_schema={
            "sample": pl.Utf8,
            "section": pl.Utf8,
            "bin": pl.Float64,
            "n_bases": pl.Float64,
        },
    ),
    RecipeSource(
        ref="idxstats",
        dc_ref="samtools_idxstats",
        optional=True,
        input_schema={"sample": pl.Utf8, "contig_class": pl.Utf8, "mapped_pct": pl.Float64},
    ),
    RecipeSource(
        ref="callset",
        dc_ref="vcf_callset_summary",
        optional=True,
        input_schema={
            "sample": pl.Utf8,
            "pass_calls": pl.Int64,
            "snvs": pl.Int64,
            "indels": pl.Int64,
            "pass_pct": pl.Float64,
            "ts_tv": pl.Float64,
            "het_hom_ratio": pl.Float64,
            "median_dp": pl.Float64,
        },
    ),
    # No input_schema on the design table: its columns are the user's factors, and
    # the sample id sits in the column named `sample` or, failing that, the first one.
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "input_reads": pl.Int64,
    "uniquely_mapped_pct": pl.Float64,
    "multimapped_pct": pl.Float64,
    "unmapped_pct": pl.Float64,
    "mismatch_rate_pct": pl.Float64,
    "splices_annotated_pct": pl.Float64,
    "novel_junction_pct": pl.Float64,
    "duplication_pct": pl.Float64,
    "bases_10x_pct": pl.Float64,
    "mito_reads_pct": pl.Float64,
    "chry_reads_pct": pl.Float64,
    "other_contig_reads_pct": pl.Float64,
    "pass_calls": pl.Int64,
    "snvs": pl.Int64,
    "indels": pl.Int64,
    "pass_pct": pl.Float64,
    "ts_tv": pl.Float64,
    "het_hom_ratio": pl.Float64,
    "median_dp": pl.Float64,
}
# Design columns are run-dependent and pass through unvalidated.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Column ``GROUP_COL`` resolves to when the run gives no design table.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All samples"
#: Depth a call is usually trusted at; the coverage share is counted from here.
CALLABLE_DEPTH = 10.0


def _present(frame: pl.DataFrame | None, *cols: str) -> bool:
    return frame is not None and not frame.is_empty() and all(c in frame.columns for c in cols)


def design_columns(metadata: pl.DataFrame | None, reserved: set[str]) -> pl.DataFrame | None:
    """The design table keyed on ``sample``, every other column as Delta-safe text."""
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
            pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("sample"),
            *[pl.col(c).cast(pl.Utf8).alias(s) for c, s in keep.items()],
        )
        .filter(pl.col("sample").is_not_null())
        .unique(subset="sample", keep="first", maintain_order=True)
    )


def _novel_junctions(junctions: pl.DataFrame) -> pl.DataFrame:
    total = pl.col("junctions").sum()
    novel = pl.col("junctions").filter(pl.col("annotation") == "novel").sum()
    return junctions.group_by("sample").agg(
        pl.when(total > 0)
        .then(novel * 100.0 / total)
        .otherwise(None)
        .round(2)
        .alias("novel_junction_pct")
    )


def _callable_bases(stats: pl.DataFrame) -> pl.DataFrame:
    cov = stats.filter((pl.col("section") == "COV") & pl.col("bin").is_not_null())
    covered = pl.col("n_bases").filter(pl.col("bin") >= 1.0).sum()
    deep = pl.col("n_bases").filter(pl.col("bin") >= CALLABLE_DEPTH).sum()
    return cov.group_by("sample").agg(
        pl.when(covered > 0)
        .then(deep * 100.0 / covered)
        .otherwise(None)
        .round(2)
        .alias("bases_10x_pct")
    )


def _contig_shares(idx: pl.DataFrame) -> pl.DataFrame:
    return idx.group_by("sample").agg(
        pl.col("mapped_pct")
        .filter(pl.col("contig_class") == "mitochondrion")
        .sum()
        .round(3)
        .alias("mito_reads_pct"),
        pl.col("mapped_pct")
        .filter(pl.col("contig_class") == "Y")
        .sum()
        .round(4)
        .alias("chry_reads_pct"),
        pl.col("mapped_pct")
        .filter(pl.col("contig_class") == "other")
        .sum()
        .round(3)
        .alias("other_contig_reads_pct"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join every per-sample summary onto the sample list, then the design."""
    star_cols = [
        "sample",
        "input_reads",
        "uniquely_mapped_pct",
        "multimapped_pct",
        "unmapped_pct",
        "mismatch_rate_pct",
        "splices_annotated_pct",
    ]
    star = sources.get("star")
    callset = sources.get("callset")
    ids = [
        frame.select(pl.col("sample").cast(pl.Utf8))
        for frame in (star, callset)
        if _present(frame, "sample")
    ]
    if not ids:
        raise ValueError(
            "rnavar samples: neither the STAR alignment summary nor the callset summary "
            "holds a sample"
        )
    hub = pl.concat(ids).unique()
    if _present(star, *star_cols):
        hub = hub.join(
            star.select(star_cols).unique(subset="sample", keep="first"), on="sample", how="left"
        )

    parts: list[pl.DataFrame] = []
    junctions = sources.get("junctions")
    if _present(junctions, "sample", "annotation", "junctions"):
        parts.append(_novel_junctions(junctions))
    dups = sources.get("dups")
    if _present(dups, "sample", "percent_duplication"):
        parts.append(
            dups.group_by("sample").agg(
                (pl.col("percent_duplication").max() * 100.0).round(2).alias("duplication_pct")
            )
        )
    stats = sources.get("stats")
    if _present(stats, "sample", "section", "bin", "n_bases"):
        parts.append(_callable_bases(stats))
    idx = sources.get("idxstats")
    if _present(idx, "sample", "contig_class", "mapped_pct"):
        parts.append(_contig_shares(idx))
    if _present(callset, "sample", "pass_calls"):
        cols = ["pass_calls", "snvs", "indels", "pass_pct", "ts_tv", "het_hom_ratio", "median_dp"]
        # rnavar runs one caller; should a callset carry several, the first one wins.
        parts.append(callset.unique(subset="sample", keep="first").select("sample", *cols))

    for part in parts:
        hub = hub.join(part, on="sample", how="left")
    for col, dtype in OUTPUT_SCHEMA.items():
        if col not in hub.columns:
            hub = hub.with_columns(pl.lit(None, dtype=dtype).alias(col))
    out = hub.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])

    design = design_columns(sources.get("metadata"), set(OUTPUT_SCHEMA))
    if design is not None:
        out = out.join(design, on="sample", how="left").select(
            "sample", *design.columns[1:], *list(OUTPUT_SCHEMA)[1:]
        )
    else:
        out = out.with_columns(pl.lit(NO_GROUP_VALUE).alias(NO_GROUP_COL)).select(
            "sample", NO_GROUP_COL, *list(OUTPUT_SCHEMA)[1:]
        )
    return out.sort("sample")
