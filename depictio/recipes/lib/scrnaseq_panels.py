"""Gene panels and marker-panel resolution the single-cell recipes share.

Two things live here because several recipes read them:

* the reader's marker panel. It is never hardcoded: a run passes it as the
  optional ``MARKER_PANEL`` template variable (a comma-separated list of gene
  symbols, forwarded to the recipes as the ``marker_panel`` transform param),
  and when it is absent, or none of its genes is in the run's reference, the
  recipes fall back to the top markers of every graph-based cluster from
  ``cellranger_diffexp``. The wide cell x gene table
  (``cellranger/cell_expression.py``) and its melted companion
  (``cellranger/cell_expression_long.py``) both resolve the panel through
  :func:`resolve_marker_panel`, so a mouse or a non-blood run gets a panel built
  from its own clusters instead of an empty one.
* the two Tirosh cell-cycle sets the cell-cycle scorer
  (``cellranger/cell_cycle.py``) reads. They are human gene symbols; on another
  organism the intersection is empty and every cell's phase degrades to NA.

Gene names are SYMBOLS, matched against the filtered matrix's ``features.tsv.gz``
second column. Nothing here is required to be present: a recipe intersects a
list with the features the run actually carries and works with what is left.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import polars as pl

#: transform param carrying the ``MARKER_PANEL`` template variable
MARKER_PANEL_PARAM = "marker_panel"

#: the clustering the data-derived fallback reads its markers from
GRAPHCLUST_RESOLUTION = "graphclust"


def parse_marker_panel(value: str | None) -> tuple[str, ...]:
    """Split a ``MARKER_PANEL`` value into gene symbols, in order, deduplicated.

    Accepts commas, semicolons or whitespace as separators. An unset variable
    reaches a recipe either as ``None``, an empty string or the literal
    ``{MARKER_PANEL}`` placeholder the template engine leaves behind; all three
    mean "no panel".
    """
    if not value:
        return ()
    tokens = value.replace(";", ",").replace("\n", ",").replace("\t", ",").split(",")
    genes: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        for gene in token.split():
            gene = gene.strip().strip("'\"")
            if not gene or "{" in gene or "}" in gene or gene in seen:
                continue
            seen.add(gene)
            genes.append(gene)
    return tuple(genes)


def marker_panel_from_params(params: Mapping[str, str] | None) -> tuple[str, ...]:
    """The reader's panel from a recipe's transform params, empty when unset."""
    if not params:
        return ()
    return parse_marker_panel(params.get(MARKER_PANEL_PARAM))


def top_markers_per_cluster(diffexp: pl.DataFrame | None, per_cluster: int) -> list[str]:
    """The ``per_cluster`` best-ranked markers of every graph-based cluster.

    Ordered by rank first, then cluster, so a cap applied by the caller keeps
    the top marker of every cluster before the second marker of any. Empty when
    the diffexp table is missing or lacks the expected columns.
    """
    if diffexp is None or diffexp.is_empty():
        return []
    if not {"gene", "rank_in_cluster", "cluster"} <= set(diffexp.columns):
        return []
    markers = diffexp
    if "resolution" in markers.columns:
        graph = markers.filter(pl.col("resolution") == GRAPHCLUST_RESOLUTION)
        if not graph.is_empty():
            markers = graph
    markers = markers.filter(pl.col("rank_in_cluster") <= per_cluster).sort(
        ["rank_in_cluster", "cluster"]
    )
    return _dedupe(markers["gene"].cast(pl.Utf8).to_list())


def resolve_marker_panel(
    params: Mapping[str, str] | None,
    diffexp: pl.DataFrame | None,
    available: Iterable[str],
    per_cluster: int,
    cap: int,
) -> list[str]:
    """The genes a per-cell marker tile shows, never empty when ``available`` is not.

    1. the reader's ``MARKER_PANEL``, restricted to genes the run carries;
    2. otherwise the top ``per_cluster`` markers of each graph-based cluster;
    3. otherwise the first ``cap`` available genes, in their given order.
    """
    available_list = [gene for gene in available if gene]
    available_set = set(available_list)
    panel = [gene for gene in marker_panel_from_params(params) if gene in available_set]
    if not panel:
        panel = [
            gene for gene in top_markers_per_cluster(diffexp, per_cluster) if gene in available_set
        ]
    if not panel:
        panel = available_list
    return panel[:cap]


def _dedupe(names: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


#: Tirosh et al. 2016 S-phase set (the list Seurat's `cc.genes` ships), with the
#: two renamed symbols spelled both ways so an older and a newer reference both hit.
TIROSH_S_GENES: tuple[str, ...] = (
    "MCM5",
    "PCNA",
    "TYMS",
    "FEN1",
    "MCM2",
    "MCM4",
    "RRM1",
    "UNG",
    "GINS2",
    "MCM6",
    "CDCA7",
    "DTL",
    "PRIM1",
    "UHRF1",
    "MLF1IP",
    "CENPU",
    "HELLS",
    "RFC2",
    "RPA2",
    "NASP",
    "RAD51AP1",
    "GMNN",
    "WDR76",
    "SLBP",
    "CCNE2",
    "UBR7",
    "POLD3",
    "MSH2",
    "ATAD2",
    "RAD51",
    "RRM2",
    "CDC45",
    "CDC6",
    "EXO1",
    "TIPIN",
    "DSCC1",
    "BLM",
    "CASP8AP2",
    "USP1",
    "CLSPN",
    "POLA1",
    "CHAF1B",
    "BRIP1",
    "E2F8",
)

#: Tirosh et al. 2016 G2/M set, same convention.
TIROSH_G2M_GENES: tuple[str, ...] = (
    "HMGB2",
    "CDK1",
    "NUSAP1",
    "UBE2C",
    "BIRC5",
    "TPX2",
    "TOP2A",
    "NDC80",
    "CKS2",
    "NUF2",
    "CKS1B",
    "MKI67",
    "TMPO",
    "CENPF",
    "TACC3",
    "FAM64A",
    "PIMREG",
    "SMC4",
    "CCNB2",
    "CKAP2L",
    "CKAP2",
    "AURKB",
    "BUB1",
    "KIF11",
    "ANP32E",
    "TUBB4B",
    "GTSE1",
    "KIF20B",
    "HJURP",
    "CDCA3",
    "HN1",
    "JPT1",
    "CDC20",
    "TTK",
    "CDC25C",
    "KIF2C",
    "RANGAP1",
    "NCAPD2",
    "DLGAP5",
    "CDCA2",
    "CDCA8",
    "ECT2",
    "KIF23",
    "HMMR",
    "AURKA",
    "PSRC1",
    "ANLN",
    "LBR",
    "CKAP5",
    "CENPE",
    "CTCF",
    "NEK2",
    "G2E3",
    "GAS2L3",
    "CBX5",
    "CENPA",
)
