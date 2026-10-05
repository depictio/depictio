"""Barcode-rank ("knee") curve from the raw feature-barcode matrix.

Cell Ranger's `raw_feature_bc_matrix/` carries every barcode the run ever saw
(background droplets included), as a MatrixMarket sparse matrix: three header
lines (`%%MatrixMarket ...`, `%metadata_json: ...`, `<n_genes> <n_barcodes>
<n_entries>`) followed by one `<gene_idx> <barcode_idx> <count>` triplet per
non-zero entry, tens of millions of rows. This recipe never materialises a
dense matrix: the raw data collection is a **streaming** column scan
(`pl.scan_csv`, `skip_rows: 3` to drop the three header lines) that sums UMI
counts per barcode with a columnar `group_by`, and the barcode order (also a
scan, `row_index_name`/`row_index_offset` recovering the 1-based MatrixMarket
index) is joined in only to translate an index back to a barcode string. The
`filtered_feature_bc_matrix/` barcode list says which of those barcodes Cell
Ranger called a cell.

A template reusing this recipe declares three raw scan data collections::

    # cellranger_raw_matrix_raw: skip the 3 MatrixMarket header lines
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        separator: " "
        has_header: false
        skip_rows: 3
        new_columns: [gene_idx, barcode_idx, count]
        include_file_paths: source_path

    # cellranger_raw_barcodes_raw: 1-based row position == MatrixMarket barcode_idx
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        has_header: false
        new_columns: [barcode]
        include_file_paths: source_path
        row_index_name: barcode_idx
        row_index_offset: 1

    # cellranger_filtered_barcodes_raw: same shape as the raw barcode list,
    # only the barcode string is used (Cell Ranger's own cell-calling index
    # numbering is unrelated to the raw matrix's)
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        has_header: false
        new_columns: [barcode]
        include_file_paths: source_path

The output is deliberately small: at most `MAX_POINTS_PER_SAMPLE` log-spaced
ranks per sample (a knee curve needs the shape, not every barcode), matching
the canonical `knee_plot` schema.

Output schema:
    sample : Utf8       sample the barcode was sequenced in
    rank : Int64         barcode rank within the sample, 1 = highest UMI count
    umi_count : Int64    total UMI count summed across every gene for that barcode
    is_cell : Boolean    True when Cell Ranger kept this barcode in the filtered matrix
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_MATRIX_DC_TAG = "cellranger_raw_matrix_raw"
RAW_BARCODES_DC_TAG = "cellranger_raw_barcodes_raw"
FILTERED_BARCODES_DC_TAG = "cellranger_filtered_barcodes_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="raw_counts", dc_ref=RAW_MATRIX_DC_TAG),
    RecipeSource(ref="raw_barcodes", dc_ref=RAW_BARCODES_DC_TAG),
    RecipeSource(ref="filtered_barcodes", dc_ref=FILTERED_BARCODES_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "rank": pl.Int64,
    "umi_count": pl.Int64,
    "is_cell": pl.Boolean,
}

#: log-spaced ranks kept per sample, enough to draw the curve, far from "every barcode"
MAX_POINTS_PER_SAMPLE = 3000

_RAW_MATRIX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/raw_feature_bc_matrix/"
_RAW_BARCODES_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/raw_feature_bc_matrix/"
_FILTERED_BARCODES_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"


def _with_sample(df: pl.DataFrame, pattern: str, dc_name: str) -> pl.DataFrame:
    if "source_path" not in df.columns:
        raise ValueError(
            f"cellranger_barcode_rank: '{dc_name}' has no 'source_path' column, "
            "it must be scanned with polars_kwargs.include_file_paths"
        )
    out = df.with_columns(pl.col("source_path").str.extract(pattern, 1).alias("sample"))
    if out.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            f"cellranger_barcode_rank: a row's source_path in '{dc_name}' did not match {pattern!r}"
        )
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw_counts = _with_sample(sources["raw_counts"], _RAW_MATRIX_SAMPLE_RE, "raw_counts")
    raw_barcodes = _with_sample(sources["raw_barcodes"], _RAW_BARCODES_SAMPLE_RE, "raw_barcodes")
    filtered_barcodes = _with_sample(
        sources["filtered_barcodes"], _FILTERED_BARCODES_SAMPLE_RE, "filtered_barcodes"
    )

    # 1. Sum UMI counts per (sample, barcode index), the streaming aggregation.
    umi_per_index = raw_counts.group_by(["sample", "barcode_idx"]).agg(
        pl.col("count").cast(pl.Int64, strict=False).sum().alias("umi_count")
    )

    # 2. Translate the index back to the barcode string.
    barcode_lookup = raw_barcodes.select(
        "sample",
        pl.col("barcode_idx").cast(pl.Int64),
        pl.col("barcode").cast(pl.Utf8),
    )
    umi_per_barcode = umi_per_index.join(
        barcode_lookup, on=["sample", "barcode_idx"], how="inner"
    ).select("sample", "barcode", "umi_count")

    # 3. Flag the barcodes Cell Ranger kept as cells.
    cells = filtered_barcodes.select(
        "sample", pl.col("barcode").cast(pl.Utf8), pl.lit(True).alias("is_cell")
    ).unique()
    umi_per_barcode = umi_per_barcode.join(cells, on=["sample", "barcode"], how="left")
    umi_per_barcode = umi_per_barcode.with_columns(pl.col("is_cell").fill_null(False))

    # 4. Rank within each sample, highest UMI count first.
    ranked = umi_per_barcode.with_columns(
        pl.col("umi_count")
        .rank(method="ordinal", descending=True)
        .over("sample")
        .cast(pl.Int64)
        .alias("rank")
    )

    # 5. Downsample to log-spaced ranks per sample so the output stays small.
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
        pl.col("umi_count").cast(pl.Int64), pl.col("is_cell").cast(pl.Boolean)
    )
    return result.select(list(EXPECTED_SCHEMA)).sort(["sample", "rank"])
