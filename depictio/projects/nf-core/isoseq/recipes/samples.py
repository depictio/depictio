"""Sample hub for nf-core/isoseq: one row per sample, the read funnel and the transcriptome.

nf-core/isoseq does not publish the samplesheet it ran on, and the one thing
every output agrees on is the sample name (TAMA merge writes one annotation per
sample; the per-chunk CCS and refine reports carry it in their file prefix).
So the hub is built from the outputs: the CCS yield, the refine yield, the FLNC
insert length and the TAMA merge transcriptome, each summed per sample. A
source a run did not write (a run started from ``lima``, ``refine`` or
``mapping`` has no CCS reports) leaves its columns null rather than failing the
collection. The design table, when the template declares one
(``METADATA_FILE``: sample id in the column named ``sample`` or in the first
column, every other column a factor), is joined on the sample, so the hub
carries the run's factors under their own names and ``{GROUP_COL}`` resolves
against it.

The funnel columns, in pipeline order, are what the attrition card reads:
zmw_input (subread ZMWs) -> ccs_reads -> fl_reads (both primers found by lima)
-> flnc_reads (non-chimeric, kept by refine) -> collapsed_reads (FLNC reads TAMA
collapsed into a final isoform, i.e. mapped and kept).

Sources:
    ccs          ``pbccs_zmw_yield`` (catalog ``pbccs/zmw_yield``), optional
    refine       ``isoseq_refine_summary`` (catalog ``isoseq/refine_summary``), optional
    insert       ``isoseq_insert_length`` (catalog ``isoseq/insert_length``), optional
    transcripts  ``tama_transcripts`` (catalog ``tama/transcripts``)
    metadata     ``metadata``, the design table, optional

Output schema:
    sample : Utf8                  sample
    libraries : Int64              samplesheet rows (SMRT cells) of the sample
    zmw_input : Int64              ZMWs read by CCS
    ccs_reads : Int64              ZMWs that produced a CCS read
    ccs_pass_pct : Float64         ccs_reads over zmw_input, percent (every percent 2 decimals)
    fl_reads : Int64               full-length reads (both primers)
    flnc_reads : Int64             full-length non-chimeric reads
    flnc_pct : Float64             flnc_reads over fl_reads, percent
    collapsed_reads : Int64        FLNC reads collapsed into a final isoform
    collapsed_pct : Float64        collapsed_reads over flnc_reads, percent
    median_insert_bp : Int64       median FLNC insert length (100 bp bins)
    isoforms : Int64               final isoforms (TAMA merge)
    genes : Int64                  genes they belong to
    annotated_genes : Int64        of which reference genes
    fsm_pct : Float64              isoforms matching a reference intron chain, percent
    novel_isoform_pct : Float64    NIC plus NNC isoforms, percent
    novel_read_pct : Float64       FLNC reads on NIC plus NNC isoforms, percent
    <design columns> : Utf8        one per design table column, when one is given,
                                   placed right after ``sample``
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="ccs", dc_ref="pbccs_zmw_yield", optional=True),
    RecipeSource(ref="refine", dc_ref="isoseq_refine_summary", optional=True),
    RecipeSource(ref="insert", dc_ref="isoseq_insert_length", optional=True),
    RecipeSource(ref="transcripts", dc_ref="tama_transcripts"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "libraries": pl.Int64,
    "zmw_input": pl.Int64,
    "ccs_reads": pl.Int64,
    "ccs_pass_pct": pl.Float64,
    "fl_reads": pl.Int64,
    "flnc_reads": pl.Int64,
    "flnc_pct": pl.Float64,
    "collapsed_reads": pl.Int64,
    "collapsed_pct": pl.Float64,
    "median_insert_bp": pl.Int64,
    "isoforms": pl.Int64,
    "genes": pl.Int64,
    "annotated_genes": pl.Int64,
    "fsm_pct": pl.Float64,
    "novel_isoform_pct": pl.Float64,
    "novel_read_pct": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_NOVEL = ["NIC", "NNC"]


def _present(frame: pl.DataFrame | None, *cols: str) -> bool:
    return frame is not None and not frame.is_empty() and all(c in frame.columns for c in cols)


def _pct(num: str, den: str) -> pl.Expr:
    return (
        pl.when(pl.col(den) > 0)
        .then(pl.col(num) * 100.0 / pl.col(den))
        .otherwise(None)
        .cast(pl.Float64)
        .round(2)
    )


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
        .unique(subset="sample", keep="first")
    )


def _median_insert(insert: pl.DataFrame) -> pl.DataFrame:
    """First bin where the cumulative share reaches half of the sample's reads."""
    return (
        insert.filter(pl.col("cumulative_pct") >= 50.0)
        .group_by("sample")
        .agg(pl.col("length_bp").min().cast(pl.Int64).alias("median_insert_bp"))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    tx = sources["transcripts"]
    if tx.is_empty():
        raise ValueError("isoseq samples: the transcripts collection is empty")
    parts: list[pl.DataFrame] = []
    libraries: list[pl.DataFrame] = []

    ccs = sources.get("ccs")
    if _present(ccs, "sample", "library", "zmw_input", "zmw_passed"):
        parts.append(
            ccs.group_by("sample").agg(
                pl.col("zmw_input").sum().cast(pl.Int64),
                pl.col("zmw_passed").sum().cast(pl.Int64).alias("ccs_reads"),
            )
        )
        libraries.append(ccs.select("sample", "library"))

    refine = sources.get("refine")
    if _present(refine, "sample", "library", "fl_reads", "flnc_reads"):
        parts.append(
            refine.group_by("sample").agg(
                pl.col("fl_reads").sum().cast(pl.Int64),
                pl.col("flnc_reads").sum().cast(pl.Int64),
            )
        )
        libraries.append(refine.select("sample", "library"))

    insert = sources.get("insert")
    if _present(insert, "sample", "length_bp", "cumulative_pct"):
        parts.append(_median_insert(insert))

    novel = pl.col("structural_category").is_in(_NOVEL)
    parts.append(
        tx.group_by("sample").agg(
            pl.col("read_support").sum().cast(pl.Int64).alias("collapsed_reads"),
            pl.len().cast(pl.Int64).alias("isoforms"),
            pl.col("gene_id").n_unique().cast(pl.Int64).alias("genes"),
            pl.col("gene_id")
            .filter(pl.col("gene_id") != pl.col("sample") + ":" + pl.col("tama_gene_id"))
            .n_unique()
            .cast(pl.Int64)
            .alias("annotated_genes"),
            ((pl.col("structural_category") == "FSM").mean() * 100.0)
            .cast(pl.Float64)
            .round(2)
            .alias("fsm_pct"),
            (novel.mean() * 100.0).cast(pl.Float64).round(2).alias("novel_isoform_pct"),
            pl.col("read_support").filter(novel).sum().alias("_novel_reads"),
        )
    )

    hub = pl.concat([p.select("sample") for p in parts]).unique()
    for part in parts:
        hub = hub.join(part, on="sample", how="left")
    if libraries:
        lib = (
            pl.concat(libraries)
            .unique()
            .group_by("sample")
            .agg(pl.len().cast(pl.Int64).alias("libraries"))
        )
        hub = hub.join(lib, on="sample", how="left")

    for col, dtype in EXPECTED_SCHEMA.items():
        if col not in hub.columns and col not in {
            "ccs_pass_pct",
            "flnc_pct",
            "collapsed_pct",
            "novel_read_pct",
        }:
            hub = hub.with_columns(pl.lit(None, dtype=dtype).alias(col))
    hub = hub.with_columns(
        _pct("ccs_reads", "zmw_input").alias("ccs_pass_pct"),
        _pct("flnc_reads", "fl_reads").alias("flnc_pct"),
        _pct("collapsed_reads", "flnc_reads").alias("collapsed_pct"),
        _pct("_novel_reads", "collapsed_reads").alias("novel_read_pct"),
    )
    out = hub.select([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()])
    design = design_columns(sources.get("metadata"), set(EXPECTED_SCHEMA))
    if design is not None:
        # The factors right after the sample, so the summary table opens on
        # who the sample is before what it yielded.
        out = out.join(design, on="sample", how="left").select(
            "sample", *design.columns[1:], *list(EXPECTED_SCHEMA)[1:]
        )
    return out.sort("sample")
