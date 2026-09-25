"""One row per barcode called a cell by ANY method, across all three aligner routes.

nf-core/scrnaseq's `--aligner` routes (Cell Ranger, simpleaf/alevin-fry,
kallisto|bustools) each write their own cell-barcode list, and CellBender
writes a second, ambient-RNA-aware list for the routes it ran on. Cell
Ranger's own barcodes (both raw and CellBender's) carry a 10x `-1` GEM-well
suffix that the other two routes do not, so every barcode is normalised to
its bare 16-mer (`barcode_core`) before the union, this is the whole point
of the table: it lets `cellranger`/`cellranger_cellbender` rows line up with
`simpleaf_cellbender`/`kallisto`/`kallisto_cellbender` rows for the SAME
physical barcode.

The table has NO `sample` dimension: the union runs over every barcode list
the scan matched, whatever sample directory it sits in. On a one-sample run
(the layout this recipe was built on) that is exact; on a multi-sample run a
16-mer shared by two samples' droplets collapses onto one row, so the
concordance it reports is over the run, not per sample.

Every source but the plain Cell Ranger cell list is `optional=True`: a
Cell Ranger-only megatest run (the default `--aligner`, no CellBender) still
produces a one-column table, and the aligner-concordance dashboard tab reads
that as "no comparison available" rather than failing.

A template reusing this recipe declares raw scans for each cell-barcode list
(headerless, one barcode per line, `include_file_paths: source_path`); see
`cellranger/barcode_rank.py`, `simpleaf/barcode_rank.py` and
`kallisto/run_metrics.py` for the shared `cellranger_filtered_barcodes_raw`,
`simpleaf_cellbender_barcodes_raw` and `kallisto_barcodes_raw` scans this
recipe reuses, plus two scans it is the only consumer of:
`cellranger_cellbender_barcodes_raw` and `kallisto_cellbender_barcodes_raw`
(same shape, CellBender's own `*_cell_barcodes.csv` for those two routes).

Output schema:
    barcode_core : Utf8              16-mer 10x barcode, GEM-well suffix stripped
    cellranger : Boolean              Cell Ranger's own filtered-matrix cell call
    cellranger_cellbender : Boolean   CellBender kept this barcode on the Cell Ranger route
    simpleaf_cellbender : Boolean     CellBender kept this barcode on the simpleaf route
    kallisto : Boolean                kb count --filter's own knee-based cell call
    kallisto_cellbender : Boolean     CellBender kept this barcode on the kallisto route
    n_callers : Int64                 how many of the 5 boolean columns are True
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

CELLRANGER_DC_TAG = "cellranger_filtered_barcodes_raw"
CELLRANGER_CELLBENDER_DC_TAG = "cellranger_cellbender_barcodes_raw"
SIMPLEAF_CELLBENDER_DC_TAG = "simpleaf_cellbender_barcodes_raw"
KALLISTO_DC_TAG = "kallisto_barcodes_raw"
KALLISTO_CELLBENDER_DC_TAG = "kallisto_cellbender_barcodes_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="cellranger", dc_ref=CELLRANGER_DC_TAG),
    RecipeSource(ref="cellranger_cellbender", dc_ref=CELLRANGER_CELLBENDER_DC_TAG, optional=True),
    RecipeSource(ref="simpleaf_cellbender", dc_ref=SIMPLEAF_CELLBENDER_DC_TAG, optional=True),
    RecipeSource(ref="kallisto", dc_ref=KALLISTO_DC_TAG, optional=True),
    RecipeSource(ref="kallisto_cellbender", dc_ref=KALLISTO_CELLBENDER_DC_TAG, optional=True),
]

_CALLER_COLUMNS = [
    "cellranger",
    "cellranger_cellbender",
    "simpleaf_cellbender",
    "kallisto",
    "kallisto_cellbender",
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "barcode_core": pl.Utf8,
    "cellranger": pl.Boolean,
    "cellranger_cellbender": pl.Boolean,
    "simpleaf_cellbender": pl.Boolean,
    "kallisto": pl.Boolean,
    "kallisto_cellbender": pl.Boolean,
    "n_callers": pl.Int64,
}

#: 10x GEM-well suffix Cell Ranger (and CellBender on its route) appends, e.g. "-1"
_GEM_SUFFIX_RE = r"-\d+$"


def _barcode_core_set(df: pl.DataFrame | None, dc_name: str) -> set[str]:
    if df is None or df.height == 0:
        return set()
    if "barcode" not in df.columns:
        raise ValueError(f"cell_calls_by_method: '{dc_name}' has no 'barcode' column")
    cores = (
        df.select(
            pl.col("barcode").cast(pl.Utf8).str.replace(_GEM_SUFFIX_RE, "").alias("barcode_core")
        )
        .drop_nulls()
        .unique()
    )
    return set(cores["barcode_core"].to_list())


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    # The source refs and the output columns carry the same names, one per caller.
    caller_sets = {
        caller: _barcode_core_set(sources.get(caller), caller) for caller in _CALLER_COLUMNS
    }

    if not caller_sets["cellranger"]:
        raise ValueError("cell_calls_by_method: 'cellranger' source produced no barcodes")

    df = pl.DataFrame({"barcode_core": sorted(set().union(*caller_sets.values()))})
    for col in _CALLER_COLUMNS:
        members = caller_sets[col]
        df = df.with_columns(pl.col("barcode_core").is_in(members).alias(col))

    df = df.with_columns(
        pl.sum_horizontal([pl.col(c).cast(pl.Int64) for c in _CALLER_COLUMNS]).alias("n_callers")
    )
    return df.select(list(EXPECTED_SCHEMA)).sort("barcode_core")
