"""kallisto | bustools (kb count) run headline numbers, one row per sample.

`run_info.json` (kallisto bus: `n_processed`, `n_pseudoaligned`,
`p_pseudoaligned`) and `inspect.json` (bustools inspect, post barcode
correction: `numBarcodes`) are small pretty-printed JSON objects with no
sample field (kb writes one pair per sample under `kallisto/<sample>.count/`).
Both are read the `ataqv/metrics.py` way: a one-column CSV with a separator
that cannot occur in JSON text (`\\x1f`, no quote char) so every physical
line arrives verbatim; grouping by `source_path` reconstructs one file at a
time and `json.loads` parses it directly (single object, not an array).

The number of cells `kb count --filter` called is not in either JSON: it is
the row count of `counts_filtered/cells_x_genes.barcodes.txt`, a third raw
scan (headerless, one barcode per line, `include_file_paths`).

A template reusing this recipe declares three raw scan data collections::

    # kallisto_run_info_raw / kallisto_inspect_raw
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        has_header: false
        separator: "\\x1f"
        quote_char: null
        new_columns: [raw]
        include_file_paths: source_path
        infer_schema_length: 0

    # kallisto_barcodes_raw
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        has_header: false
        new_columns: [barcode]
        include_file_paths: source_path

Output schema:
    sample : Utf8            sample kb count ran on
    n_processed : Int64        run_info.json n_processed
    n_pseudoaligned : Int64    run_info.json n_pseudoaligned
    p_pseudoaligned : Float64  run_info.json p_pseudoaligned / 100
    n_barcodes : Int64         inspect.json numBarcodes (barcodes on the whitelist after correction)
    cells_called : Int64       rows in counts_filtered/cells_x_genes.barcodes.txt (kb's own knee filter)
"""

from __future__ import annotations

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

RUN_INFO_DC_TAG = "kallisto_run_info_raw"
INSPECT_DC_TAG = "kallisto_inspect_raw"
BARCODES_DC_TAG = "kallisto_barcodes_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="run_info", dc_ref=RUN_INFO_DC_TAG),
    RecipeSource(ref="inspect", dc_ref=INSPECT_DC_TAG),
    RecipeSource(ref="barcodes", dc_ref=BARCODES_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "n_processed": pl.Int64,
    "n_pseudoaligned": pl.Int64,
    "p_pseudoaligned": pl.Float64,
    "n_barcodes": pl.Int64,
    "cells_called": pl.Int64,
}

_RUN_INFO_SAMPLE_RE = r"kallisto/([^/]+)\.count/run_info\.json$"
_INSPECT_SAMPLE_RE = r"kallisto/([^/]+)\.count/inspect\.json$"
_BARCODES_SAMPLE_RE = r"kallisto/([^/]+)\.count/counts_filtered/cells_x_genes\.barcodes\.txt$"


def _decode_per_sample(df: pl.DataFrame, pattern: str, dc_name: str) -> dict[str, dict]:
    if not {"raw", "source_path"}.issubset(df.columns):
        raise ValueError(
            f"kallisto_run_metrics: '{dc_name}' must be scanned as a one-column "
            "text CSV with include_file_paths"
        )
    out: dict[str, dict] = {}
    for source_path, group in df.group_by("source_path"):
        path = source_path[0] if isinstance(source_path, tuple) else source_path
        m = pl.Series([path]).str.extract(pattern, 1)[0]
        if m is None:
            raise ValueError(
                f"kallisto_run_metrics: source_path {path!r} in '{dc_name}' did not match {pattern!r}"
            )
        text = "\n".join(group["raw"].to_list())
        out[m] = json.loads(text)
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    run_info = _decode_per_sample(sources["run_info"], _RUN_INFO_SAMPLE_RE, "run_info")
    inspect = _decode_per_sample(sources["inspect"], _INSPECT_SAMPLE_RE, "inspect")

    barcodes = sources["barcodes"]
    if "source_path" not in barcodes.columns:
        raise ValueError(
            "kallisto_run_metrics: 'barcodes' has no 'source_path' column, "
            "it must be scanned with polars_kwargs.include_file_paths"
        )
    barcodes = barcodes.with_columns(
        pl.col("source_path").str.extract(_BARCODES_SAMPLE_RE, 1).alias("sample")
    )
    if barcodes.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            f"kallisto_run_metrics: a row's source_path in 'barcodes' did not match "
            f"{_BARCODES_SAMPLE_RE!r}"
        )
    cells_called = barcodes.group_by("sample").agg(pl.len().cast(pl.Int64).alias("cells_called"))

    samples = sorted(set(run_info) | set(inspect) | set(cells_called["sample"].to_list()))
    cells_called_map = dict(
        zip(cells_called["sample"].to_list(), cells_called["cells_called"].to_list())
    )

    rows: list[dict] = []
    for sample in samples:
        ri = run_info.get(sample, {})
        insp = inspect.get(sample, {})
        p_pseudoaligned = ri.get("p_pseudoaligned")
        rows.append(
            {
                "sample": sample,
                "n_processed": ri.get("n_processed"),
                "n_pseudoaligned": ri.get("n_pseudoaligned"),
                "p_pseudoaligned": (
                    (p_pseudoaligned / 100.0) if p_pseudoaligned is not None else None
                ),
                "n_barcodes": insp.get("numBarcodes"),
                "cells_called": cells_called_map.get(sample),
            }
        )

    df = pl.DataFrame(rows, infer_schema_length=None)
    for column, dtype in EXPECTED_SCHEMA.items():
        if column not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=dtype).alias(column))
    return df.select(
        [pl.col(column).cast(dtype, strict=False) for column, dtype in EXPECTED_SCHEMA.items()]
    ).sort("sample")
