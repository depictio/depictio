"""Sample x virus segment matrix of nf-core/viralmetagenome, for the clustered heatmap.

A segmented virus is several genomes in one sample: Lassa virus is an S and an
L segment, CCHFV an S, an M and an L, influenza A eight. Counting genomes per
virus hides a segment that failed, and a table of genomes is one row per
segment per sample, too long to read across samples. This matrix puts every
virus segment on a row and every sample on a column, and colours the cell with
the BLAST reference cover of the best genome of that segment in that sample
(``ref_cover_pct`` of the genome hub, the de novo and constraint routes both
counted, the higher one kept). A cell of 0 is a segment the sample has no
genome of, or one with no BLAST hit: the heatmap clusters on a full matrix.

``virus`` rides along as a row annotation, so the segments of one virus sit
next to each other when the rows are clustered.

Sources:
    genomes  ``genomes``, the genome hub

Output: ``virus_segment``, ``virus``, then one Float64 column per sample (its name
made safe for the store; a sample whose safe name is taken gets a ``_<n>``
suffix).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import sanitise

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="genomes",
        dc_ref="genomes",
        input_schema={
            "sample": pl.Utf8,
            "virus": pl.Utf8,
            "virus_segment": pl.Utf8,
            "ref_cover_pct": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "virus_segment": pl.Utf8,
    "virus": pl.Utf8,
}
# One column per sample; the names are run-dependent, so they are not declared.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def sample_columns(samples: list[str]) -> dict[str, str]:
    """Sample -> its matrix column: safe for the store, unique, clear of the row keys."""
    taken = set(OUTPUT_SCHEMA)
    out: dict[str, str] = {}
    for sample in samples:
        base = sanitise(sample)
        name, n = base, 1
        while name in taken:
            n += 1
            name = f"{base}_{n}"
        taken.add(name)
        out[sample] = name
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    genomes = sources["genomes"].filter(
        pl.col("sample").is_not_null() & pl.col("virus_segment").is_not_null()
    )
    if genomes.is_empty():
        raise ValueError("viralmetagenome genome_matrix: the genome hub holds no genome")
    best = genomes.group_by("virus_segment", "sample").agg(
        pl.col("virus").first(),
        pl.col("ref_cover_pct").max().alias("ref_cover_pct"),
    )
    samples = sorted(best["sample"].unique().to_list())
    names = sample_columns(samples)
    wide = best.pivot(
        on="sample", index="virus_segment", values="ref_cover_pct", aggregate_function="max"
    )
    virus = best.group_by("virus_segment").agg(pl.col("virus").first())
    wide = wide.join(virus, on="virus_segment", how="left")
    for sample in samples:
        if sample not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(sample))
    return wide.select(
        pl.col("virus_segment").cast(pl.Utf8),
        pl.col("virus").cast(pl.Utf8),
        *[pl.col(s).cast(pl.Float64).fill_null(0.0).alias(names[s]) for s in samples],
    ).sort(["virus", "virus_segment"])
