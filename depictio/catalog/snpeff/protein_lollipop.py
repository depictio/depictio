"""Coding variants positioned along their protein, for a lollipop track.

``lollipop`` draws one lane per ``feature_id`` with a stem per variant, so it
needs a protein coordinate, not a genomic one: the position comes from SnpEff's
HGVS.p (``p.Trp344Arg`` -> 344), which exists only for variants that change a
codon. Everything else is dropped rather than plotted at its genomic position,
which would put every lane on a different scale.

The gene universe is capped because the kind switches to a single-gene picker
above a handful of lanes and because a lane with one stem says nothing.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="variants", dc_ref="snpeff_ann_variants")]

#: Genes kept, ranked by how many coding variants they carry across the run.
TOP_GENES = 40

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "gene": pl.Utf8,
    "aa_pos": pl.Int64,
    "impact": pl.Utf8,
    "consequence": pl.Utf8,
    "hgvs_p": pl.Utf8,
    "variant_key": pl.Utf8,
    "vaf": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Keep coding variants with a protein position, on the busiest genes."""
    coding = sources["variants"].filter(
        pl.col("aa_pos").is_not_null()
        & pl.col("gene").is_not_null()
        & (pl.col("gene") != "")
        & pl.col("impact").is_in(["HIGH", "MODERATE", "LOW"])
    )

    top = (
        coding.group_by("gene")
        .agg(pl.col("variant_key").n_unique().alias("n_variants"))
        .sort(["n_variants", "gene"], descending=[True, False])
        .head(TOP_GENES)
        .select("gene")
    )

    return (
        coding.join(top, on="gene", how="inner")
        .select(list(EXPECTED_SCHEMA))
        .with_columns(pl.col("vaf").cast(pl.Float64))
        .sort(["gene", "aa_pos", "sample", "caller"])
    )
