"""One row per final de novo consensus genome, from the viralmetagenome contigs overview.

``overview-tables/[<prefix>-]contigs_overview.tsv`` holds the consensus each
contig cluster ended its iterative refinement with, one row per sample and
cluster (``step`` says at which step the refinement stopped).

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

Output schema: ``GENOME_SCHEMA`` of the shared library, one row per sample and cluster.
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
        glob_pattern="overview-tables/*contigs_overview.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        input_schema={"sample": pl.Utf8, "cluster": pl.Utf8, "step": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = dict(GENOME_SCHEMA)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    out = tidy_genome_overview(sources["overview"], ROUTE_DENOVO)
    return out.sort(["sample", "reference"])
