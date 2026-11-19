"""De novo against constraint genome, side by side, per sample and virus segment.

viralmetagenome can rebuild a genome twice: de novo, by refining the sample's
own contig clusters, and against a constraint reference (``--mapping_constraints``;
a reference picked from a pool by Mash when the sheet says ``selection: true``).
The two routes answer each other: a constraint genome much better than the de
novo one says the assembly fell short; a de novo genome far from its constraint
reference says the reference was a poor pick. The genome hub holds them as
separate rows; this recipe lines them up, one row per sample and virus segment,
the best genome of each route (highest reference cover, then fewest N) in its
two columns.

Sources:
    genomes  ``genomes``, the genome hub

Output schema:
    sample, virus, segment, virus_segment : Utf8
    denovo_genome_id, constraint_genome_id : Utf8     best genome of each route
    constraint_reference : Utf8                        the reference of the constraint one
    denovo_*, constraint_* : one column per measure in ``_MEASURES`` and route
    cover_gain : Float64       constraint minus de novo reference cover, points
    n_gain : Float64           de novo minus constraint N share, points (positive: constraint has fewer N)
    better_route : Utf8        de novo, constraint, similar (within 2 points either way), or the only route
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import ROUTE_CONSTRAINT, ROUTE_DENOVO

#: Measure -> dtype, read off each route's best genome.
_MEASURES: dict[str, type[pl.DataType]] = {
    "consensus_length": pl.Int64,
    "ref_cover_pct": pl.Float64,
    "n_pct": pl.Float64,
    "blast_identity_pct": pl.Float64,
    "mean_depth": pl.Float64,
    "cov_10x_pct": pl.Float64,
    "completeness_call": pl.Utf8,
}
#: Two routes whose reference cover is this close read "similar".
SIMILAR_POINTS = 2.0

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="genomes",
        dc_ref="genomes",
        input_schema={
            "genome_id": pl.Utf8,
            "sample": pl.Utf8,
            "reference": pl.Utf8,
            "route": pl.Utf8,
            "virus": pl.Utf8,
            "virus_segment": pl.Utf8,
        },
    ),
]

_PREFIX = {ROUTE_DENOVO: "denovo", ROUTE_CONSTRAINT: "constraint"}

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "virus": pl.Utf8,
    "segment": pl.Utf8,
    "virus_segment": pl.Utf8,
    "denovo_genome_id": pl.Utf8,
    "constraint_genome_id": pl.Utf8,
    "constraint_reference": pl.Utf8,
    **{f"{p}_{m}": t for p in _PREFIX.values() for m, t in _MEASURES.items()},
    "cover_gain": pl.Float64,
    "n_gain": pl.Float64,
    "better_route": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    g = sources["genomes"]
    for col, dtype in {**_MEASURES, "segment": pl.Utf8}.items():
        if col not in g.columns:
            g = g.with_columns(pl.lit(None, dtype=dtype).alias(col))
    g = g.filter(pl.col("route").is_in(list(_PREFIX)) & pl.col("virus_segment").is_not_null())
    if g.is_empty():
        raise ValueError("viralmetagenome route_comparison: the genome hub holds no genome")
    best = g.sort(["ref_cover_pct", "n_pct"], descending=[True, False], nulls_last=True).unique(
        subset=["sample", "virus_segment", "route"], keep="first", maintain_order=True
    )
    keys = best.select("sample", "virus", "segment", "virus_segment").unique(
        subset=["sample", "virus_segment"], keep="first", maintain_order=True
    )
    out = keys
    for route, prefix in _PREFIX.items():
        part = best.filter(pl.col("route") == route).select(
            "sample",
            "virus_segment",
            pl.col("genome_id").alias(f"{prefix}_genome_id"),
            *(
                [pl.col("reference").alias("constraint_reference")]
                if route == ROUTE_CONSTRAINT
                else []
            ),
            *[pl.col(m).cast(t).alias(f"{prefix}_{m}") for m, t in _MEASURES.items()],
        )
        out = out.join(part, on=["sample", "virus_segment"], how="left")
    if "constraint_reference" not in out.columns:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("constraint_reference"))
    gain = pl.col("constraint_ref_cover_pct") - pl.col("denovo_ref_cover_pct")
    out = out.with_columns(
        gain.round(2).alias("cover_gain"),
        (pl.col("denovo_n_pct") - pl.col("constraint_n_pct")).round(3).alias("n_gain"),
        pl.when(pl.col("denovo_genome_id").is_null())
        .then(pl.lit("constraint only"))
        .when(pl.col("constraint_genome_id").is_null())
        .then(pl.lit("de novo only"))
        .when(gain.is_null())
        .then(pl.lit("no BLAST hit"))
        .when(gain > SIMILAR_POINTS)
        .then(pl.lit(ROUTE_CONSTRAINT))
        .when(gain < -SIMILAR_POINTS)
        .then(pl.lit(ROUTE_DENOVO))
        .otherwise(pl.lit("similar"))
        .alias("better_route"),
    )
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["sample", "virus", "virus_segment"]
    )
