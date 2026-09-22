"""Gene panels the single-cell recipes share.

Three lists, kept here rather than inside one recipe because three of them read
the same names: the wide cell x gene expression table
(``cellranger/cell_expression.py``) seeds its gene panel with the PBMC markers,
its melted companion (``cellranger/cell_expression_long.py``) keeps only those
columns so a violin stays readable, and the cell-cycle scorer
(``cellranger/cell_cycle.py``) reads the two Tirosh sets.

The lists are gene SYMBOLS, matched against the filtered matrix's
``features.tsv.gz`` second column. Nothing here is required to be present: a
recipe intersects the list with the features the run actually carries and works
with what is left, so a non-human reference simply contributes no panel genes
(the marker-derived and dispersion-derived parts of the panel still do).
"""

from __future__ import annotations

#: Canonical 10x / Seurat PBMC lineage markers. Present on any human reference,
#: and the set a reader of a PBMC run types into a gene box first.
CURATED_PBMC_PANEL: tuple[str, ...] = (
    # T cells
    "CD3D",
    "CD3E",
    "CD3G",
    "IL7R",
    "CCR7",
    "SELL",
    "S100A4",
    # cytotoxic T
    "CD8A",
    "CD8B",
    "GZMK",
    # NK
    "GNLY",
    "NKG7",
    "KLRD1",
    "PRF1",
    # B
    "MS4A1",
    "CD79A",
    "CD79B",
    "TCL1A",
    # monocytes
    "CD14",
    "LYZ",
    "S100A8",
    "S100A9",
    "FCN1",
    "FCGR3A",
    "MS4A7",
    # dendritic cells
    "FCER1A",
    "CST3",
    "CLEC9A",
    "LILRA4",
    # platelets
    "PPBP",
    "PF4",
    # progenitors, erythroid, proliferation
    "CD34",
    "HBB",
    "MKI67",
)

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
