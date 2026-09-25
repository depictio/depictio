"""Endogenous DNA percentage per library, from endorS.py's MultiQC custom content.

endorS.py divides a library's mapped read count by the reads it was given and
writes the result as a MultiQC custom-content JSON, one file per library::

    {"id": "endorSpy", "plot_type": "generalstats",
     "pconfig": {"endogenous_dna": {...}, "endogenous_dna_post": {...}},
     "data": {"COD076E1bL1": {"endogenous_dna": 35.235273,
                              "endogenous_dna_post": 23.535004}}}

This is the headline number of an ancient-DNA screen: it says what share of an
extract is the target organism rather than the soil, the excavator and the lab.
It reaches MultiQC's general-statistics table and, before this output existed,
lived nowhere a card or a figure could read.

``endogenous_dna`` is computed on the raw alignment, ``endogenous_dna_post``
after the quality filter and deduplication the pipeline applied; the gap between
them is how much of the on-target signal survives filtering, and is derived here
as ``endogenous_dna_loss``. The off-target share is derived too, because that is
the fraction a metagenomic screen would work on.

The file is read one LINE per row (a separator it cannot contain) rather than as
JSON, so the same scan idiom as every other text report applies and no JSON
reader has to be declared on the collection::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*_endogenous_dna_mqc\\.json$'}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\x1f"
          has_header: false
          new_columns: ["raw"]
          include_file_paths: "source_path"
          infer_schema_length: 0

Output schema:
    sample : Utf8                  library endorS.py ran on
    endogenous_dna : Float64       on-target share of the raw alignment, percent
    endogenous_dna_post : Float64  same after filtering and deduplication, percent
    endogenous_dna_loss : Float64  the drop between the two, percentage points
    off_target_pct : Float64       100 minus endogenous_dna, percent
"""

from __future__ import annotations

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan the JSON files into.
RAW_DC_TAG = "endorspy_endogenous_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="reports", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "endogenous_dna": pl.Float64,
    "endogenous_dna_post": pl.Float64,
    "endogenous_dna_loss": pl.Float64,
    "off_target_pct": pl.Float64,
}

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library, read off each report's ``data`` block."""
    raw = sources["reports"]
    if raw.is_empty():
        raise ValueError("endorspy_endogenous: the scanned reports are empty")
    for column in (RAW_LINE_COL, SOURCE_PATH_COL):
        if column not in raw.columns:
            raise ValueError(
                f"endorspy_endogenous: no {column} column, the data collection must "
                f"scan one line per row with include_file_paths: source_path"
            )

    records: list[dict] = []
    for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        text = "\n".join(line or "" for line in group[RAW_LINE_COL].to_list())
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"endorspy_endogenous: {path} is not valid JSON: {exc}") from exc
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"endorspy_endogenous: {path} has no 'data' object")
        for sample, metrics in data.items():
            if not isinstance(metrics, dict):
                continue
            records.append(
                {
                    "sample": str(sample),
                    "endogenous_dna": _as_float(metrics.get("endogenous_dna")),
                    "endogenous_dna_post": _as_float(metrics.get("endogenous_dna_post")),
                }
            )

    if not records:
        raise ValueError("endorspy_endogenous: no report carried a library")

    return (
        pl.DataFrame(
            records,
            schema={
                "sample": pl.Utf8,
                "endogenous_dna": pl.Float64,
                "endogenous_dna_post": pl.Float64,
            },
        )
        .with_columns(
            (pl.col("endogenous_dna") - pl.col("endogenous_dna_post")).alias("endogenous_dna_loss"),
            (100.0 - pl.col("endogenous_dna")).alias("off_target_pct"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort("sample")
    )
