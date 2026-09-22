"""Per-sample, per-context methylation summary, long format (one row per
sample x context).

``bismark_methylation_extractor`` writes one
``<sample>_bismark_bt2_pe.deduplicated_splitting_report.txt`` per library,
whose "Final Cytosine Methylation Report" block gives the post-deduplication,
post-extraction methylated/unmethylated cytosine counts for the CpG, CHG and
CHH contexts. This is the canonical per-context number nf-core reports (the
alignment report has the same block, but computed before deduplication) and
the one MultiQC's ``bismark-methylation-dp`` table draws from, this recipe
keeps it queryable directly, without going through the report.

Input: the ``bismark_splitting_raw`` data collection, a recursive Table scan of
the per-sample splitting reports read one LINE per row (prose plus
`Key:\\tValue` lines, see ``alignment_summary.py``). The DC must be declared
with::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*_splitting_report\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "|"
          has_header: false
          new_columns: ["line"]
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8               library the extraction ran on
    context : Utf8               CpG, CHG or CHH
    methylated_c : Int64         methylated cytosines seen in this context
    unmethylated_c : Int64       unmethylated cytosines (C->T conversions) in this context
    pct_methylated : Float64     methylated_c / (methylated_c + unmethylated_c) * 100,
                                  as Bismark reports it
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bismark_reports import report_lines

RAW_DC_TAG = "bismark_splitting_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lines", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "context": pl.Utf8,
    "methylated_c": pl.Int64,
    "unmethylated_c": pl.Int64,
    "pct_methylated": pl.Float64,
}

# `bismark_[a-z0-9]+`: the bismark_hisat route writes `_bismark_hisat2_`.
_SUFFIX_RE = re.compile(
    r"(_\d+)?(_val_\d+)?_bismark_[a-z0-9]+_(pe|se)(\.deduplicated)?_splitting_report\.txt$"
)

_CONTEXTS = ("CpG", "CHG", "CHH")


def _parse_report(sample: str, text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for context in _CONTEXTS:
        meth = re.search(rf"Total methylated C's in {context} context:\t(\d+)", text)
        unmeth = re.search(rf"Total C to T conversions in {context} context:\t(\d+)", text)
        pct = re.search(rf"C methylated in {context} context:\t([\d.]+)\s*%", text)
        rows.append(
            {
                "sample": sample,
                "context": context,
                "methylated_c": int(meth.group(1)) if meth else None,
                "unmethylated_c": int(unmeth.group(1)) if unmeth else None,
                "pct_methylated": float(pct.group(1)) if pct else None,
            }
        )
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Re-assemble each report from its lines, then split it into 3 context rows."""
    rows: list[dict[str, object]] = []
    for sample, lines in report_lines(
        sources["lines"], "bismark_methylation_context_summary", _SUFFIX_RE
    ):
        rows.extend(_parse_report(sample, "\n".join(lines)))

    frame = pl.DataFrame(rows, infer_schema_length=None)
    return frame.select(
        pl.col("sample"),
        pl.col("context"),
        pl.col("methylated_c").cast(pl.Int64, strict=False),
        pl.col("unmethylated_c").cast(pl.Int64, strict=False),
        pl.col("pct_methylated").cast(pl.Float64, strict=False),
    ).sort(["sample", "context"])
