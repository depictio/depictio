"""One row per assembly, from QUAST's transposed report.

QUAST writes `report.tsv` (metrics down the page) and `transposed_report.tsv`
(one row per assembly) side by side. This recipe reads the transposed one,
because a dashboard compares assemblies and a table with assemblies as columns
cannot be filtered.

The assembly is named in the `Assembly` column the way the pipeline labelled
it, `<assembler>-<sample>` for nf-core/mag; when that shape is recognised the
assembler and the sample are split out so both become filters. A label that
does not carry a `-` is kept whole as the assembly id with a null assembler.

Input: the ``quast_assembly_raw`` data collection, a recursive Table scan::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '^transposed_report\\.tsv$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs: {separator: "\\t", include_file_paths: source_path, infer_schema_length: 0}

Output schema:
    assembly_id : Utf8            assembly as QUAST labelled it
    assembler : Utf8              assembler part of the label, null if unrecognised
    sample : Utf8                 sample part of the label, null if unrecognised
    n_contigs : Int64             contigs past QUAST's minimum length
    total_length : Int64          assembled bases
    largest_contig : Int64        longest contig
    n50 : Int64                   half the assembly sits in contigs at least this long
    n75 : Int64                   the same at 75%
    l50 : Int64                   how many contigs make up that half
    l75 : Int64                   the same at 75%
    gc_percent : Float64          percent G+C
    ns_per_100_kbp : Float64      ambiguous bases per 100 kbp
    predicted_rrna_genes : Utf8   QUAST's rRNA count, kept as text ("23 + 20 part")
    contigs_over_1kb : Int64      contigs at least 1 kbp long, the binnable fraction
    length_over_1kb : Int64       bases held by those contigs
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.quast_report import (
    column_map,
    label_parts,
    scalar_expressions,
    threshold_columns,
)

RAW_DC_TAG = "quast_assembly_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="reports", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "assembler": pl.Utf8,
    "sample": pl.Utf8,
    "n_contigs": pl.Int64,
    "total_length": pl.Int64,
    "largest_contig": pl.Int64,
    "n50": pl.Int64,
    "n75": pl.Int64,
    "l50": pl.Int64,
    "l75": pl.Int64,
    "gc_percent": pl.Float64,
    "ns_per_100_kbp": pl.Float64,
    "predicted_rrna_genes": pl.Utf8,
    "contigs_over_1kb": pl.Int64,
    "length_over_1kb": pl.Int64,
}

#: The threshold the "binnable fraction" columns report on. 1 kbp is QUAST's
#: own first step and the floor every binner applies before it starts.
BINNABLE_THRESHOLD_BP = 1000


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Recast one QUAST row per assembly and split the assembler out of its label."""
    raw = sources["reports"]
    if raw.is_empty():
        raise ValueError("quast_assembly_report: the scanned QUAST reports are empty")

    mapping = column_map(raw.columns)
    assembly_column = mapping.get("assembly")
    if assembly_column is None:
        raise ValueError(f"quast_assembly_report: no `Assembly` column in {raw.columns}")

    steps = {bp: (count, length) for bp, count, length in threshold_columns(raw.columns)}
    count_column, length_column = steps.get(BINNABLE_THRESHOLD_BP, (None, None))

    def _threshold(original: str | None) -> pl.Expr:
        if original is None:
            return pl.lit(None, dtype=pl.Int64)
        return pl.col(original).cast(pl.Float64, strict=False).cast(pl.Int64, strict=False)

    frame = raw.select(
        pl.col(assembly_column).cast(pl.Utf8).alias("assembly_id"),
        *scalar_expressions(raw.columns),
        _threshold(count_column).alias("contigs_over_1kb"),
        _threshold(length_column).alias("length_over_1kb"),
    ).drop_nulls(["assembly_id"])

    if frame.is_empty():
        raise ValueError("quast_assembly_report: no row carried an assembly name")

    assembler, sample = label_parts(pl.col("assembly_id"))
    return (
        frame.with_columns(assembler.alias("assembler"), sample.alias("sample"))
        .unique(subset=["assembly_id"], keep="first", maintain_order=True)
        .select(list(EXPECTED_SCHEMA))
        .sort(["assembler", "sample"])
    )
