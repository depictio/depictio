"""Enriched gene sets, from the GSEA report tables a pre-ranked run publishes.

GSEA writes one report per phenotype per contrast, under
``tables/gsea/<contrast>/<contrast>.gsea_report_for_<phenotype>.tsv``. Each file
holds the sets enriched at one POLE of that contrast, which is why a run with two
contrasts publishes four of them, and why neither the contrast nor the pole is a
column of any of them: both live only in the file name.

So this is the raw-scan two-step. A recursive scan collection reads every report
with ``include_file_paths``, and this recipe recovers the contrast and the
phenotype from the path, stacks the four tables into one frame and normalises the
column names GSEA writes for a human reader:

* ``GS<br> follow link to MSigDB`` and ``GS DETAILS`` are HTML for the report
  page and carry nothing the dashboard can use, so they are dropped. The file
  also ends every line with a tab, which gives an unnamed twelfth column.
* ``NOM p-val``, ``FDR q-val`` and ``FWER p-val`` become ``nom_pvalue``,
  ``fdr_qvalue`` and ``fwer_pvalue``.
* ``LEADING EDGE`` is one string, ``tags=51%, list=30%, signal=72%``. The tags
  percentage is the share of the set that sits in the leading edge, which is the
  number a reader uses to tell a broad shift from a handful of genes carrying the
  set, so it is parsed out into ``leading_edge_percent``.

``neg_log10_fdr`` is added because an FDR q-value of 0 is what GSEA writes for
anything below its resolution, and a dot plot sized on the raw q-value collapses
those to a point. It is clipped at the smallest non-zero q-value in the run.

Output:
    contrast : Utf8              the contrast directory, e.g. Condition_genotype_WT_KO
    phenotype : Utf8             the pole this report is for, e.g. KO
    term : Utf8                  the gene set name
    size : Int64                 genes of the set found in the ranked list
    es, nes : Float64            enrichment score, and the size-normalised one
    nom_pvalue : Float64         nominal p-value
    fdr_qvalue : Float64         FDR q-value across the sets of this report
    fwer_pvalue : Float64        family-wise error rate
    neg_log10_fdr : Float64      -log10(fdr_qvalue), clipped at the run's floor
    rank_at_max : Int64          where in the ranked list the score peaked
    leading_edge_percent : Float64   share of the set in the leading edge
    leading_edge : Utf8          the original string, kept for the table
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# The contrast and the phenotype live only in the file name, and `pl.read_csv`
# (what a recipe glob source goes through) has no `include_file_paths`.
RAW_DC_TAG = "gsea_report_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="report", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "phenotype": pl.Utf8,
    "term": pl.Utf8,
    "size": pl.Int64,
    "es": pl.Float64,
    "nes": pl.Float64,
    "nom_pvalue": pl.Float64,
    "fdr_qvalue": pl.Float64,
    "fwer_pvalue": pl.Float64,
    "neg_log10_fdr": pl.Float64,
    "rank_at_max": pl.Int64,
    "leading_edge_percent": pl.Float64,
    "leading_edge": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# `<contrast>.gsea_report_for_<phenotype>[_<timestamp>].tsv`
_NAME = re.compile(r"^(?P<contrast>.+?)\.gsea_report_for_(?P<phenotype>.+?)(?:_\d{10,})?\.tsv$")
_TAGS = re.compile(r"tags=(\d+(?:\.\d+)?)%")

_RENAME = {
    "NAME": "term",
    "SIZE": "size",
    "ES": "es",
    "NES": "nes",
    "NOM p-val": "nom_pvalue",
    "FDR q-val": "fdr_qvalue",
    "FWER p-val": "fwer_pvalue",
    "RANK AT MAX": "rank_at_max",
    "LEADING EDGE": "leading_edge",
}
_FLOATS = ("es", "nes", "nom_pvalue", "fdr_qvalue", "fwer_pvalue")


def _from_path(source_path: str) -> tuple[str, str]:
    """Recover (contrast, phenotype) from the report's file name."""
    parts = str(source_path).split("/")
    name = parts[-1]
    match = _NAME.match(name)
    if match:
        return match.group("contrast"), match.group("phenotype")
    # The directory is the contrast even when the file name is not the usual one.
    contrast = parts[-2] if len(parts) > 1 else "contrast"
    return contrast, name.removesuffix(".tsv")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Stack every report, label it with its contrast and pole, and rename."""
    df = sources["report"]
    if df.is_empty():
        return pl.DataFrame(schema=EXPECTED_SCHEMA)

    labels = [_from_path(p) for p in df.get_column("source_path").to_list()]
    df = df.with_columns(
        pl.Series("contrast", [c for c, _ in labels], dtype=pl.Utf8),
        pl.Series("phenotype", [p for _, p in labels], dtype=pl.Utf8),
    )
    present = {old: new for old, new in _RENAME.items() if old in df.columns}
    df = df.rename(present)

    out = df.select(
        pl.col("contrast"),
        pl.col("phenotype"),
        pl.col("term").cast(pl.Utf8),
        pl.col("size").cast(pl.Float64, strict=False).cast(pl.Int64, strict=False),
        *[pl.col(col).cast(pl.Float64, strict=False) for col in _FLOATS],
        pl.col("rank_at_max").cast(pl.Float64, strict=False).cast(pl.Int64, strict=False),
        pl.col("leading_edge").cast(pl.Utf8),
    ).drop_nulls("term")

    out = out.with_columns(
        pl.col("leading_edge")
        .str.extract(_TAGS.pattern, 1)
        .cast(pl.Float64, strict=False)
        .alias("leading_edge_percent")
    )

    # GSEA writes 0 for any q-value below its resolution, which a -log10 turns
    # into an infinity. Clipping at the smallest q-value the run actually
    # resolved keeps those sets at the top of the axis without breaking it. A
    # q-value GSEA left as NA stays null: max_horizontal would otherwise clip
    # it to the floor and score an unknown as the most significant.
    resolved = out.filter(pl.col("fdr_qvalue") > 0).get_column("fdr_qvalue")
    floor = resolved.min() if resolved.len() else 1e-3
    out = out.with_columns(
        pl.when(pl.col("fdr_qvalue").is_null())
        .then(None)
        .otherwise(-pl.max_horizontal(pl.col("fdr_qvalue"), pl.lit(float(floor))).log10())
        .cast(pl.Float64)
        .alias("neg_log10_fdr")
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(
        ["contrast", "phenotype", "nes"], descending=[False, False, True]
    )
