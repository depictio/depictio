"""Barcode-rank ("knee") curve from simpleaf/alevin-fry's per-barcode feature dump.

`af_quant/featureDump.txt` is a tab-separated file with one row per barcode
alevin-fry ever quantified (no raw/filtered split the way Cell Ranger has
one): `CB, CorrectedReads, MappedReads, DeduplicatedReads, MappingRate,
DedupRate, MeanByMax, NumGenesExpressed, NumGenesOverMean`. `DeduplicatedReads`
is the UMI count. The barcode carries no sample column (alevin-fry writes one
file per sample under `simpleaf/<sample>/simpleaf_quant/af_quant/`), so the
raw data collection is a **scan** (`include_file_paths`) and the sample is
recovered from the path, same idiom as `cellranger/barcode_rank.py`.

`is_cell` comes from CellBender's own cell-barcode list for the same route
(`cellbender_removebackground/<sample>_cell_barcodes.csv`, no `-1` suffix on
this route, unlike Cell Ranger's), also a raw scan joined in by sample.

A template reusing this recipe declares two raw scan data collections::

    # simpleaf_featuredump_raw
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        separator: "\\t"
        include_file_paths: source_path

    # simpleaf_cellbender_barcodes_raw
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        has_header: false
        new_columns: [barcode]
        include_file_paths: source_path

Output is downsampled to at most `MAX_POINTS_PER_SAMPLE` log-spaced ranks per
sample, matching the canonical `knee_plot` schema plus an `aligner` column so
this output can share a knee_plot tile with the Cell Ranger curve.

Output schema:
    sample : Utf8        sample the barcode was quantified in
    aligner : Utf8        constant "simpleaf"
    rank : Int64          barcode rank within the sample, 1 = highest UMI count
    umi_count : Int64     DeduplicatedReads for that barcode
    is_cell : Boolean     True when CellBender kept this barcode as a cell
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

FEATUREDUMP_DC_TAG = "simpleaf_featuredump_raw"
CELLBENDER_BARCODES_DC_TAG = "simpleaf_cellbender_barcodes_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="featuredump", dc_ref=FEATUREDUMP_DC_TAG),
    RecipeSource(ref="cellbender_barcodes", dc_ref=CELLBENDER_BARCODES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "aligner": pl.Utf8,
    "rank": pl.Int64,
    "umi_count": pl.Int64,
    "is_cell": pl.Boolean,
}

#: log-spaced ranks kept per sample, enough to draw the curve
MAX_POINTS_PER_SAMPLE = 3000

_FEATUREDUMP_SAMPLE_RE = r"simpleaf/([^/]+)/simpleaf_quant/af_quant/featureDump\.txt$"
_CELLBENDER_SAMPLE_RE = r"simpleaf/([^/]+)/cellbender_removebackground/[^/]+_cell_barcodes\.csv$"


def _with_sample(df: pl.DataFrame, pattern: str, dc_name: str) -> pl.DataFrame:
    if "source_path" not in df.columns:
        raise ValueError(
            f"simpleaf_barcode_rank: '{dc_name}' has no 'source_path' column, "
            "it must be scanned with polars_kwargs.include_file_paths"
        )
    out = df.with_columns(pl.col("source_path").str.extract(pattern, 1).alias("sample"))
    if out.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            f"simpleaf_barcode_rank: a row's source_path in '{dc_name}' did not match {pattern!r}"
        )
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    featuredump = _with_sample(sources["featuredump"], _FEATUREDUMP_SAMPLE_RE, "featuredump")
    required = {"CB", "DeduplicatedReads"}
    missing = required - set(featuredump.columns)
    if missing:
        raise ValueError(f"simpleaf_barcode_rank: featuredump is missing columns {sorted(missing)}")

    counts = featuredump.select(
        "sample",
        pl.col("CB").cast(pl.Utf8).alias("barcode"),
        pl.col("DeduplicatedReads").cast(pl.Int64, strict=False).alias("umi_count"),
    )

    cellbender_barcodes = sources.get("cellbender_barcodes")
    if cellbender_barcodes is not None and cellbender_barcodes.height:
        cellbender_barcodes = _with_sample(
            cellbender_barcodes, _CELLBENDER_SAMPLE_RE, "cellbender_barcodes"
        )
        cells = cellbender_barcodes.select(
            "sample", pl.col("barcode").cast(pl.Utf8), pl.lit(True).alias("is_cell")
        ).unique()
        counts = counts.join(cells, on=["sample", "barcode"], how="left")
        counts = counts.with_columns(pl.col("is_cell").fill_null(False))
    else:
        counts = counts.with_columns(pl.lit(False).alias("is_cell"))

    ranked = counts.with_columns(
        pl.col("umi_count")
        .rank(method="ordinal", descending=True)
        .over("sample")
        .cast(pl.Int64)
        .alias("rank")
    )

    max_ranks = ranked.group_by("sample").agg(pl.col("rank").max().alias("max_rank"))
    keep_frames: list[pl.DataFrame] = []
    for row in max_ranks.iter_rows(named=True):
        sample, n = row["sample"], row["max_rank"]
        if n <= MAX_POINTS_PER_SAMPLE:
            target_ranks = list(range(1, n + 1))
        else:
            target_ranks = sorted({int(r) for r in np.geomspace(1, n, num=MAX_POINTS_PER_SAMPLE)})
        keep_frames.append(
            pl.DataFrame({"sample": [sample] * len(target_ranks), "rank": target_ranks})
        )
    keep = pl.concat(keep_frames, how="vertical_relaxed").with_columns(
        pl.col("rank").cast(pl.Int64)
    )

    result = ranked.join(keep, on=["sample", "rank"], how="inner")
    result = result.with_columns(
        pl.col("umi_count").cast(pl.Int64),
        pl.col("is_cell").cast(pl.Boolean),
        pl.lit("simpleaf").alias("aligner"),
    )
    return result.select(list(EXPECTED_SCHEMA)).sort(["sample", "rank"])
