"""Arriba breakpoint pairs with the fusion-report index and a rank the browser opens on.

The catalog recipe ``arriba/fusion_links.py`` turns each Arriba call into a link
between its two breakpoints (``chrom_a`` / ``pos_a`` / ``chrom_b`` / ``pos_b``,
the summed read ``weight``, the event class and Arriba's confidence). This recipe
keeps that transform and adds the two columns the breakpoint browser orders its
calls by:

* ``fii``: the Fusion Indication Index of the call's fusion in the same sample,
  read from the fusion-report consensus (0 for a call the consensus does not
  list). It is the score the ranked bars of the Caller Agreement tab sort by;
* ``rank_score``: one number that orders the calls the way those bars do. The
  browser's ``sort_by`` takes a single column and most fusions of a run tie on
  the index, so it folds three levels into one integer: the index (in
  thousandths), then the reads every caller found for the fusion
  (``caller_evidence``, the bars' tie-break), then this call's own ``weight``
  (which separates two breakpoints of one fusion). The highest index comes
  first, and among equal indices the fusion with the most reads.

Sources: Arriba's ``*.arriba.fusions.tsv`` files (the catalog's), and the
``fusion_consensus`` and ``caller_evidence`` collections of the template.

Output schema: the catalog's columns, then ``fii`` and ``rank_score``.
"""

from __future__ import annotations

import polars as pl

from depictio.catalog.arriba.fusion_links import OUTPUT_SCHEMA as _CATALOG_SCHEMA
from depictio.catalog.arriba.fusion_links import SOURCES as _CATALOG_SOURCES
from depictio.catalog.arriba.fusion_links import transform as _links
from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    *_CATALOG_SOURCES,
    RecipeSource(
        ref="consensus",
        dc_ref="fusion_consensus",
        optional=True,
        input_schema={"sample": pl.Utf8, "fusion": pl.Utf8, "fii": pl.Float64},
    ),
    RecipeSource(
        ref="evidence",
        dc_ref="caller_evidence",
        optional=True,
        input_schema={"sample": pl.Utf8, "fusion": pl.Utf8, "supporting_reads": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    **_CATALOG_SCHEMA,
    "fii": pl.Float64,
    "rank_score": pl.Int64,
}

#: Each level of ``rank_score`` is six digits wide: the index in thousandths sits
#: above the fusion's reads, which sit above the call's own weight.
_LEVEL = 1_000_000
_CAP = _LEVEL - 1


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """The catalog's breakpoint pairs, with the call's index and its browser rank."""
    links = _links({"fusions": sources["fusions"]})
    consensus = sources.get("consensus")
    if consensus is not None and consensus.height:
        index = consensus.group_by(["sample", "fusion"]).agg(pl.col("fii").max().alias("fii"))
        links = links.join(index.rename({"fusion": "label"}), on=["sample", "label"], how="left")
    else:
        links = links.with_columns(pl.lit(None, dtype=pl.Float64).alias("fii"))
    evidence = sources.get("evidence")
    if evidence is not None and evidence.height:
        reads = evidence.group_by(["sample", "fusion"]).agg(
            pl.col("supporting_reads").sum().alias("_fusion_reads")
        )
        links = links.join(reads.rename({"fusion": "label"}), on=["sample", "label"], how="left")
    else:
        links = links.with_columns(pl.lit(None, dtype=pl.Int64).alias("_fusion_reads"))
    links = links.with_columns(
        pl.col("fii").fill_null(0.0).cast(pl.Float64),
        pl.col("_fusion_reads").fill_null(0).cast(pl.Int64),
    )
    return links.with_columns(
        (
            (pl.col("fii") * 1000).round().cast(pl.Int64) * _LEVEL * _LEVEL
            + pl.col("_fusion_reads").clip(0, _CAP) * _LEVEL
            + pl.col("weight").clip(0, _CAP)
        )
        .cast(pl.Int64)
        .alias("rank_score")
    ).select(list(OUTPUT_SCHEMA))


__all__ = ["OUTPUT_SCHEMA", "SOURCES", "transform"]
