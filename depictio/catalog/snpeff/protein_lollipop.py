"""Coding variants positioned along their protein, for a lollipop track.

``lollipop`` draws one lane per ``feature_id`` with a stem per variant, so it
needs a protein coordinate, not a genomic one: the position comes from SnpEff's
HGVS.p (``p.Trp344Arg`` -> 344), which exists only for variants that change a
codon. Everything else is dropped rather than plotted at its genomic position,
which would put every lane on a different scale.

The gene universe is capped because the kind switches to a single-gene picker
above a handful of lanes and because a lane with one stem says nothing.

``ref_aa`` is the residue SnpEff names at the position (``p.Trp344Arg`` ->
``Trp``). A structure tile checks it against the model it draws, so a variant
whose numbering the model does not share (SnpEff counts along an Ensembl
transcript, a predicted structure along the UniProt isoform) is listed as a
mismatch instead of being drawn on the wrong residue.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants",
        dc_ref="snpeff_ann_variants",
        input_schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "gene": pl.Utf8,
            "aa_pos": pl.Int64,
            "impact": pl.Utf8,
            "consequence": pl.Utf8,
            "hgvs_p": pl.Utf8,
            "variant_key": pl.Utf8,
            "vaf": pl.Float64,
        },
    )
]

#: Genes kept, ranked by how many coding variants they carry across the run.
TOP_GENES = 40

#: ``p.Trp344Arg`` -> ``Trp``.
_REF_AA_RE = r"^p\.([A-Z][a-z]{2})\d+"
#: The stop codon a stop-loss names is no residue of the model.
_STOP = "Ter"

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "gene": pl.Utf8,
    "aa_pos": pl.Int64,
    "impact": pl.Utf8,
    "consequence": pl.Utf8,
    "hgvs_p": pl.Utf8,
    "ref_aa": pl.Utf8,
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

    ref = pl.col("hgvs_p").str.extract(_REF_AA_RE, 1)
    return (
        coding.join(top, on="gene", how="inner")
        .with_columns(
            pl.when(ref != _STOP).then(ref).alias("ref_aa"),
            pl.col("vaf").cast(pl.Float64),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["gene", "aa_pos", "sample", "caller"])
    )
