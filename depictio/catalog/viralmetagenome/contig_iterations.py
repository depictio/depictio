"""One row per de novo consensus and refinement step, from the viralmetagenome contigs overview with iterations.

``overview-tables/[<prefix>-]contigs_overview-with-iterations.tsv`` holds the
consensus of every contig cluster at every step: the scaffold built from the
contigs (``consensus``), each mapping iteration (``it1``, ``it2``...) and the
final variant-calling round (``itvariant-calling``). Read down a cluster, the
ambiguous bases and the mismatches to the closest reference show how far the
refinement moved the consensus.

The table is the pipeline's merge of every per-genome MultiQC section: the
closest reference of the annotation database and its taxonomy, the best BLAST
hit in the reference pool, CheckV, QUAST's ambiguous bases, samtools and Picard
mapping statistics, iVar and bcftools variant counts and mosdepth depth and
breadth, plus the cluster the consensus came from (centroid, members). Column names are MultiQC labels (``(<tool>) <metric>``);
``depictio.recipes.lib.viralmetagenome.tidy_genome_overview`` gives them stable
names, reads the annotation identity and the Picard duplication as percentages,
and keys each genome as ``<sample>_<reference>`` (``genome_id``), the key the
variant and coverage collections join on.

``virus`` names what the genome is: the annotation's acronym, else its name,
else the species the constraint sheet gave, else ``Unclassified``.

``step_order`` puts the steps in the order they ran: the scaffold is 0, the
mapping iterations 1 to N, the variant-calling round N + 1.

Output schema: ``GENOME_SCHEMA`` of the shared library plus ``step_order``
(Int64), one row per sample, cluster and refinement step.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import (
    GENOME_SCHEMA,
    ROUTE_DENOVO,
    tidy_genome_overview,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="overview",
        # The file carries the run prefix, so the glob matches on the suffix.
        glob_pattern="overview-tables/*contigs_overview-with-iterations.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        input_schema={"sample": pl.Utf8, "cluster": pl.Utf8, "step": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {**GENOME_SCHEMA, "step_order": pl.Int64}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    out = tidy_genome_overview(sources["overview"], ROUTE_DENOVO)
    iteration = pl.col("step").str.extract(r"^it(\d+)$", 1).cast(pl.Int64, strict=False)
    out = out.with_columns(iteration.alias("_it"))
    out = out.with_columns(
        pl.when(pl.col("step") == "consensus")
        .then(0)
        .when(pl.col("_it").is_not_null())
        .then(pl.col("_it"))
        .when(pl.col("step") == "itvariant-calling")
        .then(pl.col("_it").max().over("genome_id").fill_null(0) + 1)
        .otherwise(None)
        .cast(pl.Int64)
        .alias("step_order")
    ).drop("_it")
    return out.sort(["sample", "reference", "step_order"])
