"""CpG M-bias curve, one row per sample x read x position.

``bismark_methylation_extractor --mbias_only`` writes one
``<sample>_bismark_bt2_pe.deduplicated.M-bias.txt`` per library: six
tab-separated tables in one file (CpG / CHG / CHH, each for read 1 and read
2), each row giving the % methylation and coverage observed at one read
position. A read-position bias that does not flatten out is Bismark's own
advice to add an `--ignore` / `--ignore_r2` trim before re-extracting.

MultiQC's own ``bismark_mbias`` panel draws the same curve per context/read,
but as a picture with no cross-tile selection; this recipe keeps the CpG
context (the context nf-core/methylseq's default human/mouse references
report on) queryable and linkable through `selection_column: sample`. CHG and
CHH are not extracted here, the MultiQC panel (`multiqc/bismark`, section
`bismark`) already surfaces those for the samples that need them.

Input: the ``bismark_mbias_raw`` data collection, a recursive Table scan of the
per-sample M-bias files read one LINE per row (six tables share one file with
no shared column count, so no single tabular read fits it, see
``alignment_summary.py``). The DC must be declared with::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*\\.M-bias\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "|"
          has_header: false
          new_columns: ["line"]
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8                library Bismark ran on
    read : Utf8                  R1 or R2
    series : Utf8                "<sample> R<read>", the profile kind's series role
    position : Int64             base position inside the read
    pct_methylation : Float64    % methylated calls at this position, CpG context
    coverage : Int64             calls (methylated + unmethylated) behind the percentage
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "bismark_mbias_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lines", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "read": pl.Utf8,
    "series": pl.Utf8,
    "position": pl.Int64,
    "pct_methylation": pl.Float64,
    "coverage": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

_SUFFIX_RE = re.compile(r"(_\d+)?_val_\d+_bismark_bt2_(pe|se)\.deduplicated\.M-bias\.txt$")

# "CpG context (R1)" / "CHG context (R2)" / ..., the section header Bismark
# writes before each of the six tables.
_SECTION_RE = re.compile(r"^(CpG|CHG|CHH) context \((R[12])\)$")

# Data rows: "<position>\t<count methylated>\t<count unmethylated>\t<% methylation>\t<coverage>"
_ROW_RE = re.compile(r"^(\d+)\t(\d+)\t(\d+)\t([\d.]+)\t(\d+)$")


def _sample_id(path: str) -> str:
    name = Path(str(path)).name
    return _SUFFIX_RE.sub("", name)


def _parse_cpg_rows(sample: str, lines: list[str]) -> list[dict[str, object]]:
    """Walk the file's six sections, keeping only the two CpG ones."""
    rows: list[dict[str, object]] = []
    current_context: str | None = None
    current_read: str | None = None
    for line in lines:
        section = _SECTION_RE.match(line.strip())
        if section:
            current_context, current_read = section.group(1), section.group(2)
            continue
        if current_context != "CpG":
            continue
        data = _ROW_RE.match(line.strip())
        if not data:
            continue
        position, methylated, unmethylated, pct, coverage = data.groups()
        rows.append(
            {
                "sample": sample,
                "read": current_read,
                "series": f"{sample} {current_read}",
                "position": int(position),
                "pct_methylation": float(pct),
                "coverage": int(coverage),
            }
        )
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Re-assemble each M-bias file from its lines, keep the CpG sections."""
    raw = sources["lines"]
    if raw.is_empty():
        raise ValueError("bismark_mbias_curve: the scanned M-bias files are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "bismark_mbias_curve: the raw scan must carry include_file_paths=source_path"
        )

    rows: list[dict[str, object]] = []
    for (source_path,), part in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        sample = _sample_id(source_path)
        rows.extend(
            _parse_cpg_rows(sample, [line or "" for line in part.get_column("line").to_list()])
        )

    if not rows:
        raise ValueError("bismark_mbias_curve: no CpG row was parsed from any M-bias file")

    frame = pl.DataFrame(rows, infer_schema_length=None)
    return frame.select(
        pl.col("sample"),
        pl.col("read"),
        pl.col("series"),
        pl.col("position").cast(pl.Int64, strict=False),
        pl.col("pct_methylation").cast(pl.Float64, strict=False),
        pl.col("coverage").cast(pl.Int64, strict=False),
    ).sort(["sample", "read", "position"])
