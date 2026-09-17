"""Long region breakdown of Cell Ranger's confidently-mapped-reads accounting,
for a stacked bar.

Sources the same raw `metrics_summary.csv` scan as `cellranger/metrics_summary.py`
(`dc_ref`, independent parse: `mapping_breakdown` only needs the region
columns, not the whole metrics table). A template reusing this recipe
declares one source, the raw text scan already shared with
`cellranger_metrics_summary`::

    transform: {recipe: "cellranger/mapping_breakdown.py"}
    # SOURCES = [RecipeSource(ref="metrics", dc_ref="cellranger_metrics_raw")]

Cell Ranger reports "Reads Mapped Confidently to Genome" as the sum of its
Intergenic + Intronic + Exonic confident-mapping breakdown; "Reads Mapped
Antisense to Gene" is a separate accounting (a subset of exonic/intronic
reads on the wrong strand, not mutually exclusive with them) kept here as
its own bar segment for visibility rather than folded into exonic.
`unmapped` = 1 - "Reads Mapped to Genome". Regions therefore do not sum
to exactly 1 (antisense overlaps exonic/intronic), documented, not a bug.

Output schema:
    sample : Utf8
    region : Utf8      "exonic" | "intronic" | "intergenic" | "antisense" | "unmapped"
    fraction : Float64   0-1
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "cellranger_metrics_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="metrics", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "region": pl.Utf8,
    "fraction": pl.Float64,
}

# region -> raw Cell Ranger column
_REGION_COLUMNS = {
    "exonic": "Reads Mapped Confidently to Exonic Regions",
    "intronic": "Reads Mapped Confidently to Intronic Regions",
    "intergenic": "Reads Mapped Confidently to Intergenic Regions",
    "antisense": "Reads Mapped Antisense to Gene",
}
_MAPPED_TO_GENOME_COLUMN = "Reads Mapped to Genome"

_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/metrics_summary\.csv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["metrics"]
    if "source_path" not in df.columns:
        raise ValueError(
            "cellranger_mapping_breakdown: input has no 'source_path' column, the raw data "
            "collection must be scanned with polars_kwargs.include_file_paths"
        )
    required = set(_REGION_COLUMNS.values()) | {_MAPPED_TO_GENOME_COLUMN}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"cellranger_mapping_breakdown: input lacks columns {sorted(missing)}")

    df = df.with_columns(pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"))
    if df.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            "cellranger_mapping_breakdown: a row's source_path did not match the expected layout"
        )

    def _frac(col: str) -> pl.Expr:
        return pl.col(col).str.replace_all("%", "").cast(pl.Float64, strict=False) / 100

    frames = []
    for region, col in _REGION_COLUMNS.items():
        frames.append(
            df.select("sample", pl.lit(region).alias("region"), _frac(col).alias("fraction"))
        )
    frames.append(
        df.select(
            "sample",
            pl.lit("unmapped").alias("region"),
            (1 - _frac(_MAPPED_TO_GENOME_COLUMN)).alias("fraction"),
        )
    )
    result = pl.concat(frames, how="vertical_relaxed")
    return result.select(list(EXPECTED_SCHEMA)).sort(["sample", "region"])
