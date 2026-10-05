"""One row per sample from a Qualimap BamQC `genome_results.txt` report.

Qualimap writes `genome_results.txt` under a per-sample directory
(`<sample>_stats/genome_results.txt`, `<sample>_rmdup_stats/genome_results.txt`
after deduplication, ...) and the sample name lives only in that directory, not
in the report itself, which is titled `BamQC report` regardless of input.  So
this is the raw-scan-plus-`dc_ref` idiom `preseq/complexity_curve.py`
documents: the DC declared under `RAW_DC_TAG` reads every matched file one LINE
per row (a separator the report cannot contain, so nothing splits) with
`include_file_paths: source_path`, and only here, with the path in hand, is the
sample recovered and the `key = value` lines parsed.

Input: the `qualimap_bamqc_genome_results_raw` data collection, declared by the
template as::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*/genome_results\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\x1f"
          has_header: false
          new_columns: ["raw"]
          include_file_paths: "source_path"
          infer_schema_length: 0

Output schema:
    sample : Utf8                    library Qualimap ran on
    total_reads : Int64               reads Qualimap was given
    mapped_reads : Int64               reads it placed
    percentage_aligned : Float64       mapped_reads / total_reads, Qualimap's own number
    mean_coverage : Float64            mean depth over the reference, X
    mean_mapping_quality : Float64     mean MAPQ of mapped reads
    general_error_rate : Float64       mismatches / mapped bases
    gc_percentage : Float64            GC content of mapped bases
    duplication_rate : Float64         Qualimap's own duplicate estimate, percent
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan the raw reports into (see module
#: docstring). Any pipeline reusing this recipe declares a DC with this tag.
RAW_DC_TAG = "qualimap_bamqc_genome_results_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lines", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_reads": pl.Int64,
    "mapped_reads": pl.Int64,
    "percentage_aligned": pl.Float64,
    "mean_coverage": pl.Float64,
    "mean_mapping_quality": pl.Float64,
    "general_error_rate": pl.Float64,
    "gc_percentage": pl.Float64,
    "duplication_rate": pl.Float64,
}

SOURCE_PATH_COL = "source_path"

# Trailing directory tokens that describe a processing stage rather than the
# sample: Qualimap's own `_stats` suffix, plus the dedupper stage a pipeline
# ran before BamQC (Picard MarkDuplicates -> `_rmdup`, DeDup -> `_dedup`).
_DIR_STAGE_TOKENS = ("stats", "rmdup", "dedup", "results")


def _sample_from_dir(source_path: str) -> str:
    dirname = Path(source_path).parent.name
    tokens = dirname.split("_")
    while len(tokens) > 1 and tokens[-1].lower() in _DIR_STAGE_TOKENS:
        tokens.pop()
    return "_".join(tokens)


def _number(text: str, pattern: str) -> float:
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        raise ValueError(f"qualimap_bamqc_genome_results: pattern not found: {pattern!r}")
    return float(m.group(1).replace(",", ""))


def _parse_report(source_path: str, text: str) -> dict:
    return {
        "sample": _sample_from_dir(source_path),
        "total_reads": int(_number(text, r"number of reads = ([\d,]+)")),
        "mapped_reads": int(_number(text, r"number of mapped reads = ([\d,]+)")),
        "percentage_aligned": _number(text, r"number of mapped reads = [\d,]+ \(([\d.]+)%\)"),
        "mean_coverage": _number(text, r"mean coverageData = ([\d.]+)X"),
        "mean_mapping_quality": _number(text, r"mean mapping quality = ([\d.]+)"),
        "general_error_rate": _number(text, r"general error rate = ([\d.]+)"),
        "gc_percentage": _number(text, r"GC percentage = ([\d.]+)%"),
        "duplication_rate": _number(text, r"duplication rate = ([\d.]+)%"),
    }


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Reassemble every matched genome_results.txt from its lines and parse it."""
    raw = sources["lines"]
    if raw.is_empty():
        raise ValueError("qualimap_bamqc_genome_results: the scanned reports are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "qualimap_bamqc_genome_results: no source_path column, the DC must "
            "scan with include_file_paths: source_path"
        )

    records = [
        _parse_report(str(path), "\n".join(line or "" for line in group["raw"].to_list()))
        for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True)
    ]
    if not records:
        raise ValueError("qualimap_bamqc_genome_results: no report parsed")

    return pl.DataFrame(records, schema=EXPECTED_SCHEMA).sort("sample")
