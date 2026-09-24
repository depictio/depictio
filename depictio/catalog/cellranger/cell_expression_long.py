"""A marker-panel slice of `cellranger_cell_expression`, melted: one row per
(cell, gene), so a violin or a box can show the whole per-cell distribution of
one marker across clusters instead of the cluster mean a dot plot draws.

Which genes: resolved by `depictio.recipes.lib.scrnaseq_panels.resolve_marker_panel`,
in this order, and never empty while the wide table has a gene column:

1. the reader's panel, the optional ``MARKER_PANEL`` template variable (a comma
   list of gene symbols, forwarded as the ``marker_panel`` transform param),
   restricted to genes the wide table carries;
2. otherwise the top `TOP_MARKERS_PER_CLUSTER` markers of every graph-based
   cluster from `cellranger_diffexp`, so a mouse run, a non-blood tissue or a
   reference with different symbol casing still gets a panel of its own;
3. otherwise the wide table's first gene columns.

Two caps keep it a frame a plot can draw. At most `MAX_PANEL_GENES` genes are
kept, and at most `MAX_CELLS_PER_CLUSTER` cells of each cluster are carried.
Both matter because `box` is not in the figure service's samplable plot types
(`figure_builder._SAMPLABLE_PLOT_TYPES`): every row it is handed is serialised
into the trace, so the cap has to live here.

The cell cap is the first `MAX_CELLS_PER_CLUSTER` barcodes of the cluster in
barcode order, which is deterministic and, since a 10x barcode is a random
16-mer, independent of anything the plot shows. The wide table keeps every
cell; this one is for the shape of a distribution, not for counting.

Sources: the already-transformed wide table (`dc_ref`), so nothing is re-read
from the matrix, and the marker table for the fallback (optional).

Output schema:
    sample : Utf8
    barcode : Utf8           10x cell barcode
    cluster_label : Utf8      "C<n> top1/top2" graph-based cluster
    qc_status : Utf8          pass | flagged
    gene : Utf8               marker gene symbol, the column to filter on
    expression : Float64      log1p(CP10k) for that (cell, gene); 0 when undetected
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.scrnaseq_panels import resolve_marker_panel

CELL_EXPRESSION_DC_TAG = "cellranger_cell_expression"
DIFFEXP_DC_TAG = "cellranger_diffexp"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="wide", dc_ref=CELL_EXPRESSION_DC_TAG),
    RecipeSource(ref="diffexp", dc_ref=DIFFEXP_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "barcode": pl.Utf8,
    "cluster_label": pl.Utf8,
    "qc_status": pl.Utf8,
    "gene": pl.Utf8,
    "expression": pl.Float64,
}

_INDEX_COLUMNS = ["sample", "barcode", "cluster_label", "qc_status"]
#: non-gene columns of the wide table (index + embedding coordinates)
_NON_GENE_COLUMNS = {*_INDEX_COLUMNS, "umap_1", "umap_2"}

#: cells kept per (sample, cluster) before the melt, see the module docstring
MAX_CELLS_PER_CLUSTER = 150
#: markers per graph-based cluster in the data-derived fallback panel
TOP_MARKERS_PER_CLUSTER = 2
#: genes kept in the long table, whichever source the panel came from
MAX_PANEL_GENES = 24


def _gene_columns(wide: pl.DataFrame) -> list[str]:
    return [
        name
        for name, dtype in wide.schema.items()
        if name not in _NON_GENE_COLUMNS and dtype.is_numeric()
    ]


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    wide = sources["wide"]
    if missing := set(_INDEX_COLUMNS) - set(wide.columns):
        raise ValueError(f"cellranger_cell_expression_long: input lacks {sorted(missing)}")

    genes = resolve_marker_panel(
        params,
        sources.get("diffexp"),
        _gene_columns(wide),
        per_cluster=TOP_MARKERS_PER_CLUSTER,
        cap=MAX_PANEL_GENES,
    )
    if not genes:
        # Only reachable when the wide table carries no gene column at all,
        # which `cellranger/cell_expression.py` never produces.
        return pl.DataFrame(schema=EXPECTED_SCHEMA)

    wide = (
        wide.sort(["sample", "cluster_label", "barcode"])
        .with_columns(
            pl.int_range(pl.len()).over(["sample", "cluster_label"]).alias("_rank_in_cluster")
        )
        .filter(pl.col("_rank_in_cluster") < MAX_CELLS_PER_CLUSTER)
    )

    long = wide.select([*_INDEX_COLUMNS, *genes]).unpivot(
        on=genes,
        index=_INDEX_COLUMNS,
        variable_name="gene",
        value_name="expression",
    )
    long = long.with_columns(
        pl.col("gene").cast(pl.Utf8),
        pl.col("expression").cast(pl.Float64),
    )
    return long.select(list(EXPECTED_SCHEMA)).sort(["sample", "gene", "barcode"])
