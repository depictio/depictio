"""One row per bin, joining everything four tools know about it.

nf-core/mag's BIN_SUMMARY process writes exactly this table, and some megatest
runs publish it while others do not. This recipe rebuilds it from the four tool
outputs every run publishes, so the headline per-bin table does not depend on
one optional file:

    QUAST      contigs, N50, length, GC             (quast/bins_summary)
    CheckM2    completeness, contamination          (checkm2/quality_report)
    GTDB-Tk    the lineage                          (gtdbtk/summary)
    Prokka     CDS, tRNA, rRNA                      (prokka/summary)

The four tools do not see the same bins. QUAST runs on every bin a binner
wrote; CheckM2 runs on the ones that survived the pipeline's bin filter;
GTDB-Tk only on the ones that passed its completeness and contamination
thresholds; Prokka on the ones that were annotated. The join is therefore a
full outer join over the union of bin ids, and `sources_present` counts how
many of the four contributed to each row: a bin with a taxon but no CheckM2
row, or the reverse, is a real state of the run and must not be dropped.

`mimag_tier` is the MIMAG standard applied in full, which is why it belongs
here and not in `checkm2/quality_report`: a high-quality draft needs 90%
completeness, under 5% contamination AND the 5S / 16S / 23S rRNAs plus at least
18 tRNAs, and only Prokka can answer the second half. The CheckM2-only
`quality_tier` is carried beside it on purpose, because the gap between the two
counts is the number of bins that look finished and are not.

Output schema:
    bin_id : Utf8            bin name as the binner wrote it
    sample : Utf8            sample the assembly was built from
    assembler : Utf8         FLYE, MEGAHIT, METAMDBG, SPAdes, ...
    binner : Utf8            MetaBAT2, MaxBin2, MetaBinner, SemiBin2, COMEBin
    completeness : Float64   CheckM2 completeness, percent
    contamination : Float64  CheckM2 contamination, percent
    quality_score : Float64  completeness - 5 * contamination
    quality_tier : Utf8      CheckM2-only band
    mimag_tier : Utf8        the MIMAG tier, rRNA and tRNA included
    total_length : Int64     bases in the bin
    n_contigs : Int64        contigs in the bin
    n50 : Int64              contig N50 of the bin
    gc_percent : Float64     percent G+C
    cds : Int64              coding sequences Prokka called
    trna : Int64             transfer RNAs
    rrna : Int64             ribosomal RNAs
    cds_per_mbp : Float64    coding sequences per megabase
    meets_mimag_rna : Boolean  at least 3 rRNAs and 18 tRNAs
    domain, phylum, class_name, order, family, genus, species : Utf8
    rank_assigned : Utf8     deepest rank GTDB-Tk named
    classified : Boolean     GTDB-Tk placed this bin at all
    sources_present : Int64  how many of the four tools reported on this bin
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mag_bins import bin_id_lookup

#: Tags of the four transformed collections this recipe joins. They must be
#: declared BEFORE this one in the workflow: a `dc_ref` reads the referenced
#: collection's Delta table, which only exists once it has been processed.
QUAST_DC_TAG = "quast_bins_summary"
CHECKM2_DC_TAG = "checkm2_quality_report"
GTDBTK_DC_TAG = "gtdbtk_summary"
PROKKA_DC_TAG = "prokka_summary"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="quast", dc_ref=QUAST_DC_TAG, optional=True),
    RecipeSource(ref="checkm2", dc_ref=CHECKM2_DC_TAG, optional=True),
    RecipeSource(ref="gtdbtk", dc_ref=GTDBTK_DC_TAG, optional=True),
    RecipeSource(ref="prokka", dc_ref=PROKKA_DC_TAG, optional=True),
]

_RANK_COLUMNS = ("domain", "phylum", "class_name", "order", "family", "genus", "species")

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "bin_id": pl.Utf8,
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "binner": pl.Utf8,
    "completeness": pl.Float64,
    "contamination": pl.Float64,
    "quality_score": pl.Float64,
    "quality_tier": pl.Utf8,
    "mimag_tier": pl.Utf8,
    "total_length": pl.Int64,
    "n_contigs": pl.Int64,
    "n50": pl.Int64,
    "gc_percent": pl.Float64,
    "cds": pl.Int64,
    "trna": pl.Int64,
    "rrna": pl.Int64,
    "cds_per_mbp": pl.Float64,
    "meets_mimag_rna": pl.Boolean,
    "domain": pl.Utf8,
    "phylum": pl.Utf8,
    "class_name": pl.Utf8,
    "order": pl.Utf8,
    "family": pl.Utf8,
    "genus": pl.Utf8,
    "species": pl.Utf8,
    "rank_assigned": pl.Utf8,
    "classified": pl.Boolean,
    "sources_present": pl.Int64,
}

#: MIMAG thresholds. The RNA half arrives already evaluated as
#: `meets_mimag_rna` from `prokka/summary`.
HIGH_COMPLETENESS = 90.0
HIGH_CONTAMINATION = 5.0
MEDIUM_COMPLETENESS = 50.0
MAX_CONTAMINATION = 10.0


def _take(frame: pl.DataFrame | None, columns: dict[str, type[pl.DataType]]) -> pl.DataFrame | None:
    """`bin_id` plus the wanted columns, nulled when the source lacks one."""
    if frame is None or frame.is_empty() or "bin_id" not in frame.columns:
        return None
    selected = [pl.col("bin_id").cast(pl.Utf8)]
    for name, dtype in columns.items():
        if name in frame.columns:
            selected.append(pl.col(name).cast(dtype, strict=False).alias(name))
        else:
            selected.append(pl.lit(None, dtype=dtype).alias(name))
    return frame.select(selected).unique(subset=["bin_id"], keep="first")


def _mimag_tier(
    completeness: float | None, contamination: float | None, rna_ok: bool | None
) -> str:
    if completeness is None or contamination is None:
        return "Unknown"
    if contamination > MAX_CONTAMINATION:
        return "Contaminated"
    if completeness >= HIGH_COMPLETENESS and contamination <= HIGH_CONTAMINATION and bool(rna_ok):
        return "High quality draft"
    if completeness >= MEDIUM_COMPLETENESS:
        return "Medium quality draft"
    return "Low quality draft"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Outer-join the four per-bin tables and apply the MIMAG standard in full."""
    quast = _take(
        sources.get("quast"),
        {
            "total_length": pl.Int64,
            "n_contigs": pl.Int64,
            "n50": pl.Int64,
            "gc_percent": pl.Float64,
        },
    )
    checkm2 = _take(
        sources.get("checkm2"),
        {
            "completeness": pl.Float64,
            "contamination": pl.Float64,
            "quality_score": pl.Float64,
            "quality_tier": pl.Utf8,
            "genome_size": pl.Int64,
        },
    )
    gtdbtk = _take(
        sources.get("gtdbtk"),
        {
            **{column: pl.Utf8 for column in _RANK_COLUMNS},
            "rank_assigned": pl.Utf8,
        },
    )
    prokka = _take(
        sources.get("prokka"),
        {
            "cds": pl.Int64,
            "trna": pl.Int64,
            "rrna": pl.Int64,
            "cds_per_mbp": pl.Float64,
            "meets_mimag_rna": pl.Boolean,
        },
    )

    present = [frame for frame in (quast, checkm2, gtdbtk, prokka) if frame is not None]
    if not present:
        raise ValueError(
            "mag_bin_summary: none of the four per-bin collections "
            f"({QUAST_DC_TAG}, {CHECKM2_DC_TAG}, {GTDBTK_DC_TAG}, {PROKKA_DC_TAG}) had rows"
        )

    bin_ids = sorted({value for frame in present for value in frame["bin_id"].to_list()})
    joined = bin_id_lookup(bin_ids).drop("bin_index")
    for frame in (quast, checkm2, gtdbtk, prokka):
        if frame is None:
            continue
        joined = joined.join(frame, on="bin_id", how="left")

    counted = joined.with_columns(
        sum(
            (
                pl.col(marker).is_not_null().cast(pl.Int64)
                for marker, frame in (
                    ("total_length", quast),
                    ("completeness", checkm2),
                    ("rank_assigned", gtdbtk),
                    ("cds", prokka),
                )
                if frame is not None
            ),
            pl.lit(0, dtype=pl.Int64),
        ).alias("sources_present")
    )

    # A source that did not run at all still has to leave its columns behind,
    # so every missing one is materialised as a typed null column.
    for name, dtype in EXPECTED_SCHEMA.items():
        if name not in counted.columns:
            counted = counted.with_columns(pl.lit(None, dtype=dtype).alias(name))

    scored = counted.with_columns(
        # QUAST measures the bin's FASTA, CheckM2 re-measures it; prefer QUAST
        # and fall back so a bin QUAST skipped still carries a size.
        pl.coalesce([pl.col("total_length"), pl.col("genome_size")])
        .cast(pl.Int64)
        .alias("total_length")
        if "genome_size" in counted.columns
        else pl.col("total_length"),
        pl.col("rank_assigned").is_not_null().alias("classified"),
        pl.struct(["completeness", "contamination", "meets_mimag_rna"])
        .map_elements(
            lambda row: _mimag_tier(
                row["completeness"], row["contamination"], row["meets_mimag_rna"]
            ),
            return_dtype=pl.Utf8,
        )
        .alias("mimag_tier"),
    )
    return scored.select(list(EXPECTED_SCHEMA)).sort(["assembler", "binner", "sample", "bin_id"])
