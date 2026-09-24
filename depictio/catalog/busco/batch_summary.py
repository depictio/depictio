"""One row per assessed assembly, from BUSCO's `batch_summary.txt`.

BUSCO in batch mode writes one tab-separated summary per run, one row per input
FASTA. nf-core's `busco/busco` module publishes it twice: as
`<prefix>-<lineage>-busco.batch_summary.txt` beside the run directory and as
`<prefix>-<lineage>-busco/batch_summary.txt` inside it. Both carry the same rows,
so the recipe keys each row on the published prefix and keeps one copy.

The prefix is the pipeline's own name for the assessed assembly (for
nf-core/genomeassembler `<sample>_<stage>`), which is what the other QC tools
publish under too; the `Input_file` column is only the FASTA name, which can
differ from it (a renamed or patched FASTA).

Input: the ``busco_batch_raw`` data collection, a recursive Table scan::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '^.+\\.batch_summary\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs: {separator: "\\t", include_file_paths: source_path, infer_schema_length: 0}

Output schema:
    assembly_id : Utf8        the published prefix, lineage and `-busco` suffix removed
    input_file : Utf8         the FASTA BUSCO read
    lineage : Utf8            the lineage dataset the scores are against
    complete_pct : Float64    complete BUSCOs, percent of the lineage set
    single_pct : Float64      complete and single-copy, percent
    duplicated_pct : Float64  complete and duplicated, percent
    fragmented_pct : Float64  fragmented, percent
    missing_pct : Float64     missing, percent
    n_markers : Int64         BUSCO groups in the lineage set
    stop_codon_pct : Float64  complete BUSCOs carrying an internal stop codon, percent (null before BUSCO 6)
    scaffold_n50 : Int64      scaffold N50 BUSCO measured (null when not reported)
    contig_n50 : Int64        contig N50 BUSCO measured (null when not reported)
    percent_gaps : Float64    N bases, percent of the assembly (null when not reported)
    n_scaffolds : Int64       sequences in the assembly (null when not reported)
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "busco_batch_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="summaries", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "input_file": pl.Utf8,
    "lineage": pl.Utf8,
    "complete_pct": pl.Float64,
    "single_pct": pl.Float64,
    "duplicated_pct": pl.Float64,
    "fragmented_pct": pl.Float64,
    "missing_pct": pl.Float64,
    "n_markers": pl.Int64,
    "stop_codon_pct": pl.Float64,
    "scaffold_n50": pl.Int64,
    "contig_n50": pl.Int64,
    "percent_gaps": pl.Float64,
    "n_scaffolds": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

#: `<prefix>-<lineage or auto mode>-busco`, the nf-core module's run name.
_RUN_NAME = re.compile(r"^(?P<prefix>.+?)-[^-]+-busco$")

#: BUSCO column header -> (output column, dtype). Absent headers become nulls.
_COLUMNS: dict[str, tuple[str, type[pl.DataType]]] = {
    "Dataset": ("lineage", pl.Utf8),
    "Complete": ("complete_pct", pl.Float64),
    "Single": ("single_pct", pl.Float64),
    "Duplicated": ("duplicated_pct", pl.Float64),
    "Fragmented": ("fragmented_pct", pl.Float64),
    "Missing": ("missing_pct", pl.Float64),
    "n_markers": ("n_markers", pl.Int64),
    "Internal stop codon percent": ("stop_codon_pct", pl.Float64),
    "Scaffold N50": ("scaffold_n50", pl.Int64),
    "Contigs N50": ("contig_n50", pl.Int64),
    "Percent gaps": ("percent_gaps", pl.Float64),
    "Number of scaffolds": ("n_scaffolds", pl.Int64),
}


def run_label(source_path: str) -> str:
    """The published prefix of a batch summary, from its path."""
    path = PurePosixPath(source_path.replace("\\", "/"))
    name = path.name
    if name == "batch_summary.txt":
        stem = path.parent.name
    else:
        stem = name.removesuffix(".batch_summary.txt")
    match = _RUN_NAME.match(stem)
    return match.group("prefix") if match else stem


def _fasta_stem(name: str) -> str:
    return re.sub(r"\.(fa|fasta|fna)(\.gz)?$", "", PurePosixPath(name).name)


def _cast(column: str, dtype: type[pl.DataType]) -> pl.Expr:
    text = pl.col(column).cast(pl.Utf8).str.strip_chars().str.strip_chars_end("%")
    if dtype == pl.Utf8:
        return text
    as_float = text.cast(pl.Float64, strict=False)
    return as_float.cast(pl.Int64, strict=False) if dtype == pl.Int64 else as_float


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Tidy every scanned batch summary into one row per assessed assembly."""
    raw = sources["summaries"]
    if raw.is_empty():
        raise ValueError("busco_batch_summary: the scanned batch summaries are empty")
    if "Input_file" not in raw.columns:
        raise ValueError(f"busco_batch_summary: no `Input_file` column in {raw.columns}")

    raw = raw.filter(
        pl.col("Input_file").is_not_null() & ~pl.col("Input_file").str.starts_with("#")
    )
    if SOURCE_PATH_COL in raw.columns:
        raw = raw.with_columns(
            pl.col(SOURCE_PATH_COL).map_elements(run_label, return_dtype=pl.Utf8).alias("_label")
        )
    else:
        raw = raw.with_columns(pl.lit(None, dtype=pl.Utf8).alias("_label"))

    stems = pl.col("Input_file").map_elements(_fasta_stem, return_dtype=pl.Utf8)
    # A summary with one input row is keyed on its run name; a multi-FASTA batch
    # falls back to the FASTA names, which are the only thing that tells its rows apart.
    rows_per_label = pl.len().over("_label")
    assembly_id = (
        pl.when(pl.col("_label").is_not_null() & (rows_per_label == 1))
        .then(pl.col("_label"))
        .otherwise(stems)
    )

    selected = [
        assembly_id.alias("assembly_id"),
        pl.col("Input_file").cast(pl.Utf8).alias("input_file"),
    ]
    for header, (name, dtype) in _COLUMNS.items():
        if header in raw.columns:
            selected.append(_cast(header, dtype).alias(name))
        else:
            selected.append(pl.lit(None, dtype=dtype).alias(name))

    out = raw.select(selected).unique(subset=["assembly_id", "lineage"], keep="first")
    if out.is_empty():
        raise ValueError("busco_batch_summary: no batch summary carried a data row")
    return out.select(list(EXPECTED_SCHEMA)).sort(["assembly_id", "lineage"])
