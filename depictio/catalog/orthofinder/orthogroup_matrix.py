"""Which genomes each orthogroup reaches, from ``Orthogroups.GeneCount.tsv``.

OrthoFinder counts the genes of every species in every orthogroup, one column
per species and a ``Total``. This recipe keeps one row per orthogroup with a
0/1 membership column per species (named after the species, so an UpSet draws
the sets under their own names), the number of species it reaches, its genes
in all, and a copy class: ``single-copy`` (one gene in every species it
reaches), ``multi-copy`` otherwise. An orthogroup in all species with one gene
each is what OrthoFinder calls a single-copy orthologue, the set phylogenomics
is built on.

Input: ``Orthogroups/Orthogroups.GeneCount.tsv`` (tab-separated, header).

Output schema:
    orthogroup : Utf8         OrthoFinder's id (OG0000000...)
    <species> : Int64         1 when the orthogroup holds a gene of that species, else 0
    n_genomes : Int64         species it reaches
    total_genes : Int64       genes in it, over every species
    copy_class : Utf8         single-copy or multi-copy
    sharing : Utf8            core (every species of the run), shared (several) or unique (one)

No column but the species ones holds only 0 and 1 (``sharing`` is text, not a
boolean), so an UpSet that draws every binary column draws the species and
nothing else.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="counts",
        glob_pattern="**/Orthogroups/Orthogroups.GeneCount.tsv",
        format="csv",
        read_kwargs={"separator": "\t", "infer_schema_length": 0},
        input_schema={"Orthogroup": pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it. The species
# columns are named by the run and pass through unvalidated.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "orthogroup": pl.Utf8,
    "n_genomes": pl.Int64,
    "total_genes": pl.Int64,
    "copy_class": pl.Utf8,
    "sharing": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per orthogroup, a 0/1 column per species."""
    raw = sources["counts"]
    species = [c for c in raw.columns if c not in ("Orthogroup", "Total")]
    if not species:
        raise ValueError("orthofinder_orthogroup_matrix: no species column in the gene counts")
    counts = raw.select(
        pl.col("Orthogroup").cast(pl.Utf8).alias("orthogroup"),
        *[pl.col(s).cast(pl.Int64, strict=False).fill_null(0).alias(s) for s in species],
    ).filter(pl.col("orthogroup").is_not_null())
    present = [(pl.col(s) > 0).cast(pl.Int64) for s in species]
    n_genomes = pl.sum_horizontal(present)
    total = pl.sum_horizontal([pl.col(s) for s in species])
    single = pl.all_horizontal([(pl.col(s) <= 1) for s in species])
    return counts.select(
        "orthogroup",
        *[(pl.col(s) > 0).cast(pl.Int64).alias(s) for s in species],
        n_genomes.cast(pl.Int64).alias("n_genomes"),
        total.cast(pl.Int64).alias("total_genes"),
        pl.when(single)
        .then(pl.lit("single-copy"))
        .otherwise(pl.lit("multi-copy"))
        .alias("copy_class"),
        pl.when(n_genomes == len(species))
        .then(pl.lit("core"))
        .when(n_genomes > 1)
        .then(pl.lit("shared"))
        .otherwise(pl.lit("unique"))
        .alias("sharing"),
    ).filter(pl.col("n_genomes") > 0)
