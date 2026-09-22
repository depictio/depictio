"""DESeq2 results on Bambu counts, with labels a reader can read.

The pipeline-agnostic ``deseq2/results_long.py`` keeps whatever string the
tool put in the row-name column, which is the right call everywhere except
here: nanoseq runs DESeq2 directly on Bambu's matrix, so every feature id is a
GTF attribute string::

    ccds_id CCDS7755; exon_id ENSE00001433444; exon_number 2; gene_biotype protein_coding; ENSG00000166body

On a volcano that is the hover text, the point label and the axis of the top-N
annotations, and none of them is legible. This wrapper emits the same schema
the ``deseq2`` catalog renders bind (so ``use: deseq2/volcano`` and friends
keep working unchanged) with ``gene_id`` replaced by the Ensembl id extracted
out of that string, the biotype promoted to its own filterable column, and the
original string kept in ``feature_label`` so nothing is lost.

It also names the contrast. nanoseq writes one comparison file with no
per-contrast naming, so the catalog recipe labels every row ``all``; reading
the two conditions off the samplesheet gives the ``da_barplot`` and the
contrast filter something to say instead.

Row granularity is untouched: DESeq2 tested the annotation entries it was
given, and collapsing them to one row per gene here would be inventing a
statistic that was never computed.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bambu import DESEQ2_COLUMNS, contrast_label, deseq2_on_bambu

RAW_DC_TAG = "deseq2_results_raw"
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="raw", dc_ref=RAW_DC_TAG),
    RecipeSource(
        ref="samplesheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
        optional=True,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = dict(DESEQ2_COLUMNS)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Raw DESeq2 table -> the tidy differential frame, readably labelled."""
    return deseq2_on_bambu(sources["raw"], contrast_label(sources.get("samplesheet"))).sort(
        "padj", nulls_last=True
    )
