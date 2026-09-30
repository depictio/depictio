"""simpleaf/alevin-fry mapping headline numbers, one row per sample.

`af_map/map_info.json` (piscem/alevin-fry mapping: `num_reads`, `num_mapped`,
`percent_mapped`) and `af_quant/quant.json` (alevin-fry quant:
`num_quantified_cells`) are both small pretty-printed JSON objects with no
sample field of their own (alevin-fry writes one pair per sample under
`simpleaf/<sample>/simpleaf_quant/...`). Neither format is polars-native, so
each is read the way `ataqv/metrics.py` reads its JSON reports: as a
one-column CSV with a separator that cannot occur in JSON text (`\\x1f`, no
quote char), so every physical line of every matched file arrives verbatim;
grouping by `source_path` reconstructs one file at a time and `json.loads`
parses it directly (these files hold a single object, not an array of
records, so no streaming decoder is needed).

A template reusing this recipe declares two raw scan data collections::

    # simpleaf_mapinfo_raw / simpleaf_quantjson_raw
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        has_header: false
        separator: "\\x1f"
        quote_char: null
        new_columns: [raw]
        include_file_paths: source_path
        infer_schema_length: 0

Output schema:
    sample : Utf8          sample simpleaf/alevin-fry ran on
    num_processed : Int64   map_info.json num_reads
    num_mapped : Int64      map_info.json num_mapped
    mapping_rate : Float64  map_info.json percent_mapped / 100
    num_cells : Int64       quant.json num_quantified_cells (barcodes alevin-fry quantified,
                             not a final cell call; see qcatch_metrics_summary.retained_cells
                             or aligner_summary.cells_called for that)
"""

from __future__ import annotations

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

MAPINFO_DC_TAG = "simpleaf_mapinfo_raw"
QUANTJSON_DC_TAG = "simpleaf_quantjson_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="map_info", dc_ref=MAPINFO_DC_TAG),
    RecipeSource(ref="quant_json", dc_ref=QUANTJSON_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "num_processed": pl.Int64,
    "num_mapped": pl.Int64,
    "mapping_rate": pl.Float64,
    "num_cells": pl.Int64,
}

_MAPINFO_SAMPLE_RE = r"simpleaf/([^/]+)/simpleaf_quant/af_map/map_info\.json$"
_QUANTJSON_SAMPLE_RE = r"simpleaf/([^/]+)/simpleaf_quant/af_quant/quant\.json$"


def _decode_per_sample(df: pl.DataFrame, pattern: str, dc_name: str) -> dict[str, dict]:
    if not {"raw", "source_path"}.issubset(df.columns):
        raise ValueError(
            f"simpleaf_mapping_metrics: '{dc_name}' must be scanned as a one-column "
            "text CSV with include_file_paths"
        )
    out: dict[str, dict] = {}
    for source_path, group in df.group_by("source_path"):
        path = source_path[0] if isinstance(source_path, tuple) else source_path
        m = pl.Series([path]).str.extract(pattern, 1)[0]
        if m is None:
            raise ValueError(
                f"simpleaf_mapping_metrics: source_path {path!r} in '{dc_name}' "
                f"did not match {pattern!r}"
            )
        text = "\n".join(group["raw"].to_list())
        out[m] = json.loads(text)
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    map_info = _decode_per_sample(sources["map_info"], _MAPINFO_SAMPLE_RE, "map_info")
    quant_json = _decode_per_sample(sources["quant_json"], _QUANTJSON_SAMPLE_RE, "quant_json")

    samples = sorted(set(map_info) | set(quant_json))
    rows: list[dict] = []
    for sample in samples:
        mi = map_info.get(sample, {})
        qj = quant_json.get(sample, {})
        percent_mapped = mi.get("percent_mapped")
        rows.append(
            {
                "sample": sample,
                "num_processed": mi.get("num_reads"),
                "num_mapped": mi.get("num_mapped"),
                "mapping_rate": (percent_mapped / 100.0) if percent_mapped is not None else None,
                "num_cells": qj.get("num_quantified_cells"),
            }
        )

    df = pl.DataFrame(rows, infer_schema_length=None)
    for column, dtype in EXPECTED_SCHEMA.items():
        if column not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=dtype).alias(column))
    return df.select(
        [pl.col(column).cast(dtype, strict=False) for column, dtype in EXPECTED_SCHEMA.items()]
    ).sort("sample")
