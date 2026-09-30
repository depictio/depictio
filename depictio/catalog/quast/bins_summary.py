"""One row per recovered bin, from the QUAST summary of a binning run.

nf-core/mag runs QUAST over every bin a binner produced and aggregates the
per-bin reports into `<assembler>-<binner>-<refinement>-<sample>-quast_summary.tsv`,
which is a QUAST transposed report whose `Assembly` column holds the bin's FASTA
name rather than an assembly name.

This is the assembly-statistics half of a bin's identity: CheckM2 says how
complete a bin is, QUAST says whether that completeness sits in one contig or in
four hundred. A 95%-complete bin made of 400 contigs is a different object from
a 95%-complete bin made of three, and only QUAST can tell them apart.

Input: the ``quast_bins_raw`` data collection, a recursive Table scan::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*-quast_summary\\.tsv$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs: {separator: "\\t", include_file_paths: source_path, infer_schema_length: 0}

Output schema:
    bin_id : Utf8              bin name, FASTA suffixes removed
    sample : Utf8              sample the assembly was built from
    assembler : Utf8           FLYE, MEGAHIT, METAMDBG, SPAdes, ...
    binner : Utf8              MetaBAT2, MaxBin2, MetaBinner, SemiBin2, COMEBin
    n_contigs : Int64          contigs in the bin
    total_length : Int64       bases in the bin
    largest_contig : Int64     longest contig in the bin
    n50 : Int64                half the bin sits in contigs at least this long
    l50 : Int64                how many contigs make up that half
    gc_percent : Float64       percent G+C
    predicted_rrna_genes : Utf8  QUAST's rRNA count, kept as text ("3 + 1 part")
    contigs_over_10kb : Int64  contigs at least 10 kbp long
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mag_bins import file_stem, label_lookup
from depictio.recipes.lib.quast_report import column_map, scalar_expressions, threshold_columns

RAW_DC_TAG = "quast_bins_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="summaries", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "bin_id": pl.Utf8,
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "binner": pl.Utf8,
    "n_contigs": pl.Int64,
    "total_length": pl.Int64,
    "largest_contig": pl.Int64,
    "n50": pl.Int64,
    "l50": pl.Int64,
    "gc_percent": pl.Float64,
    "predicted_rrna_genes": pl.Utf8,
    "contigs_over_10kb": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

#: Suffixes nf-core/mag puts after the run label in the summary file name.
_LABEL_SUFFIXES = ("-quast_summary.tsv", ".tsv")

#: FASTA suffixes QUAST keeps on the bin name it was handed.
_FASTA_SUFFIXES = (".fa.gz", ".fasta.gz", ".fna.gz", ".fa", ".fasta", ".fna")

#: Threshold reported as `contigs_over_10kb`. 10 kbp is where a contig starts
#: carrying enough genes for a taxonomic call of its own.
LONG_CONTIG_THRESHOLD_BP = 10000


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Name every QUAST bin row after its bin and its binning run."""
    raw = sources["summaries"]
    if raw.is_empty():
        raise ValueError("quast_bins_summary: the scanned QUAST bin summaries are empty")

    mapping = column_map(raw.columns)
    assembly_column = mapping.get("assembly")
    if assembly_column is None:
        raise ValueError(f"quast_bins_summary: no `Assembly` column in {raw.columns}")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "quast_bins_summary: the scan must set "
            f"`include_file_paths: {SOURCE_PATH_COL}`; the binning run lives only in the file name"
        )

    steps = {bp: (count, length) for bp, count, length in threshold_columns(raw.columns)}
    count_column, _ = steps.get(LONG_CONTIG_THRESHOLD_BP, (None, None))

    labelled = raw.with_columns(
        pl.col(SOURCE_PATH_COL)
        .map_elements(lambda path: file_stem(path, *_LABEL_SUFFIXES), return_dtype=pl.Utf8)
        .alias("run_label"),
        pl.col(assembly_column)
        .map_elements(lambda name: file_stem(name, *_FASTA_SUFFIXES), return_dtype=pl.Utf8)
        .alias("bin_id"),
    )
    labelled = labelled.join(
        label_lookup(labelled["run_label"].to_list()), on="run_label", how="left"
    )

    frame = labelled.select(
        pl.col("bin_id"),
        pl.col("sample"),
        pl.col("assembler"),
        pl.col("binner"),
        *scalar_expressions(raw.columns),
        (
            pl.col(count_column).cast(pl.Float64, strict=False).cast(pl.Int64, strict=False)
            if count_column
            else pl.lit(None, dtype=pl.Int64)
        ).alias("contigs_over_10kb"),
    ).drop_nulls(["bin_id"])

    if frame.is_empty():
        raise ValueError("quast_bins_summary: no row carried a bin name")

    return (
        frame.unique(subset=["bin_id"], keep="first", maintain_order=True)
        .select(list(EXPECTED_SCHEMA))
        .sort(["assembler", "binner", "sample", "bin_id"])
    )
