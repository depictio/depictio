"""One row per metagenome-assembled genome, with CheckM2's verdict on it.

`checkm2 predict` writes a `quality_report.tsv` per run and nf-core/mag
republishes it as `<assembler>-<binner>-<refinement>-<sample>_checkm2_report.tsv`.
Both spellings are the same fourteen-column table: the bin name, the predicted
completeness and contamination, and the assembly statistics CheckM2 measured on
the way (coding density, contig N50, genome size, GC, gene count).

The three facts a reader filters on (sample, assembler, binner) are in the
file name and in the bin name, never in a column, so they are recovered by
`depictio/recipes/lib/mag_bins.py` and added here. The file name carries them
only on nf-core/mag's spelling; on CheckM2's own (`quality_report.tsv`) the
bin name is the only place they are written, so it is the fallback.

Two derived columns are added because every downstream tile wants them and
computing them per tile would let two tiles disagree:

``quality_score``
    ``completeness - 5 * contamination``, the score dRep and DAS Tool rank bins
    by. It is what "the best bin" means when one bin is more complete and
    another is cleaner.
``quality_tier``
    the MIMAG completeness / contamination band. NOT the full MIMAG tier: a
    high-quality MIMAG draft also needs the 5S / 16S / 23S rRNAs and 18 tRNAs,
    which CheckM2 does not count. `mag/bin_summary` adds those from Prokka and
    publishes the full `mimag_tier` beside this one.

Input: the ``checkm2_quality_raw`` data collection, a recursive Table scan of
the per-run report files, declared with::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*(_checkm2_report|quality_report)\\.tsv$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          include_file_paths: source_path   # carries assembler / binner / sample
          infer_schema_length: 0            # every column Utf8; recast here

Output schema:
    bin_id : Utf8                   bin name as the binner wrote it
    sample : Utf8                   sample the assembly was built from
    assembler : Utf8                FLYE, MEGAHIT, METAMDBG, SPAdes, ...
    binner : Utf8                   MetaBAT2, MaxBin2, MetaBinner, SemiBin2, COMEBin
    completeness : Float64          percent of the expected genome recovered
    contamination : Float64         percent of the bin that belongs elsewhere
    quality_score : Float64         completeness - 5 * contamination
    quality_tier : Utf8             High / Medium / Low quality, or Contaminated
    coding_density : Float64        fraction of the bin covered by coding sequence
    contig_n50 : Int64              N50 of the contigs in the bin
    genome_size : Int64             total bases in the bin
    gc_content : Float64            fraction G+C
    total_coding_sequences : Int64  genes CheckM2 called
    total_contigs : Int64           contigs in the bin
    max_contig_length : Int64       longest contig in the bin
    completeness_model : Utf8       which CheckM2 model produced the estimate
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mag_bins import (
    RUN_FIELDS,
    bin_id_lookup,
    file_stem_expr,
    label_lookup,
    quality_tier,
)

#: Data-collection tag the recipe reads. A template reusing this recipe must
#: scan its CheckM2 reports into a DC with this tag (see module docstring).
RAW_DC_TAG = "checkm2_quality_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="reports", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "bin_id": pl.Utf8,
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "binner": pl.Utf8,
    "completeness": pl.Float64,
    "contamination": pl.Float64,
    "quality_score": pl.Float64,
    "quality_tier": pl.Utf8,
    "coding_density": pl.Float64,
    "contig_n50": pl.Int64,
    "genome_size": pl.Int64,
    "gc_content": pl.Float64,
    "total_coding_sequences": pl.Int64,
    "total_contigs": pl.Int64,
    "max_contig_length": pl.Int64,
    "completeness_model": pl.Utf8,
}

SOURCE_PATH_COL = "source_path"

#: Suffixes nf-core/mag and CheckM2 put after the run label.
_LABEL_SUFFIXES = ("_checkm2_report.tsv", ".tsv")

#: Output column -> its dtype. The CheckM2 column of the same name is matched
#: case-insensitively and with non-alphanumerics folded, so `GC_Content`,
#: `GC content` and `gc_content` all land on `gc_content`.
_NUMERIC_COLUMNS: dict[str, type[pl.DataType]] = {
    "completeness": pl.Float64,
    "contamination": pl.Float64,
    "coding_density": pl.Float64,
    "contig_n50": pl.Int64,
    "genome_size": pl.Int64,
    "gc_content": pl.Float64,
    "total_coding_sequences": pl.Int64,
    "total_contigs": pl.Int64,
    "max_contig_length": pl.Int64,
}


def _norm(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(name).strip().lower()).strip("_")


def _column(raw: pl.DataFrame, wanted: str) -> str | None:
    for column in raw.columns:
        if _norm(column) == wanted:
            return column
    return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Label every CheckM2 row with its run, recast it, and add the two verdicts."""
    raw = sources["reports"]
    if raw.is_empty():
        raise ValueError("checkm2_quality_report: the scanned CheckM2 reports are empty")

    name_column = _column(raw, "name")
    if name_column is None:
        raise ValueError(
            f"checkm2_quality_report: no bin-name column in {raw.columns}; "
            "expected CheckM2's `Name`"
        )

    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "checkm2_quality_report: the scan must set "
            f"`include_file_paths: {SOURCE_PATH_COL}`; the run label lives only in the file name"
        )

    labelled = raw.with_columns(
        file_stem_expr(pl.col(SOURCE_PATH_COL), *_LABEL_SUFFIXES).alias("run_label"),
        pl.col(name_column).cast(pl.Utf8).alias("bin_id"),
    )
    by_label = label_lookup(labelled["run_label"].to_list())
    by_bin = bin_id_lookup(labelled["bin_id"].to_list()).select(
        "bin_id", *[pl.col(field).alias(f"_bin_{field}") for field in RUN_FIELDS]
    )
    labelled = labelled.join(by_label, on="run_label", how="left").join(
        by_bin, on="bin_id", how="left"
    )

    selected: list[pl.Expr] = [
        pl.col("bin_id"),
        # nf-core/mag's report name carries the ids; CheckM2's own
        # (`quality_report.tsv`) does not, and then only the bin name does.
        *[pl.coalesce(pl.col(field), pl.col(f"_bin_{field}")).alias(field) for field in RUN_FIELDS],
    ]
    for wanted, dtype in _NUMERIC_COLUMNS.items():
        original = _column(labelled, wanted)
        if original is None:
            selected.append(pl.lit(None, dtype=dtype).alias(wanted))
        else:
            selected.append(
                pl.col(original)
                .cast(pl.Float64, strict=False)
                .cast(dtype, strict=False)
                .alias(wanted)
            )

    model_column = _column(labelled, "completeness_model_used")
    selected.append(
        pl.col(model_column).cast(pl.Utf8).alias("completeness_model")
        if model_column
        else pl.lit(None, dtype=pl.Utf8).alias("completeness_model")
    )

    frame = labelled.select(selected).drop_nulls(["bin_id"])
    if frame.is_empty():
        raise ValueError("checkm2_quality_report: no row carried a bin name")

    scored = frame.with_columns(
        (pl.col("completeness") - 5.0 * pl.col("contamination")).alias("quality_score"),
        quality_tier(pl.col("completeness"), pl.col("contamination")).alias("quality_tier"),
    )
    return scored.select(list(EXPECTED_SCHEMA)).sort(["assembler", "binner", "sample", "bin_id"])
