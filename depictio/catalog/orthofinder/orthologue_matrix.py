"""One-to-one orthologues between every pair of species, as a square matrix.

OrthoFinder writes ``Comparative_Genomics_Statistics/OrthologuesStats_one-to-one.tsv``:
species on both axes, the number of one-to-one orthologues of the row species
with the column species in each cell. Closely related, well-annotated genomes
share the most; a genome short of them against every other one has lost gene
models (or split them). The matrix keeps OrthoFinder's shape, one row per
species and one column per species named after it, so a heatmap reads it as
it is; the diagonal, a species against itself, is null rather than 0.

Input: ``Comparative_Genomics_Statistics/OrthologuesStats_one-to-one.tsv``.

Output schema:
    genome : Utf8         the row species
    <species> : Int64     one-to-one orthologues with that species (null on the diagonal)

Nothing else is numeric, so a heatmap that draws every numeric column draws the
matrix and only the matrix.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="matrix",
        glob_pattern="**/Comparative_Genomics_Statistics/OrthologuesStats_one-to-one.tsv",
        format="csv",
        read_kwargs={"separator": "\t", "infer_schema_length": 0},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it. The species
# columns are named by the run and pass through unvalidated.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["matrix"]
    first = raw.columns[0]
    species = [c for c in raw.columns[1:] if c.strip()]
    if not species:
        raise ValueError("orthofinder_orthologue_matrix: no species column in the matrix")
    frame = raw.select(
        pl.col(first).cast(pl.Utf8).str.strip_chars().alias("genome"),
        *[pl.col(s).cast(pl.Float64, strict=False).alias(s) for s in species],
    ).filter(pl.col("genome").is_not_null() & (pl.col("genome") != ""))
    cells = [
        pl.when(pl.col("genome") == s).then(None).otherwise(pl.col(s)).cast(pl.Int64).alias(s)
        for s in species
    ]
    return frame.with_columns(cells).select("genome", *species).sort("genome")
