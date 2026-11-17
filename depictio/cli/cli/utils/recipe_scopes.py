"""How a recipe's output relates to the runs of a project (epic #1399).

Most recipes read one sample's rows at a time: run once per run and stacked,
they give exactly what one run over all of them would (``run``). Some mix
samples: a distance between every pair, an ordination, a top-N cut, a share
of a total. Stacked per run they are wrong, so they are recomputed over every
run at once (``aggregate``). Others reshape a statistic the pipeline computed
over its own run (PERMANOVA, ANCOM-BC, DESeq2): no union of runs can recompute
it, so it stays per run (``pipeline``).

With one run the three are the same computation, so a single-run project is
never affected. ``TransformConfig.scope`` overrides this registry.

``combine`` says how a source read from several runs is put back together:

* ``rows`` (the default): the tables are stacked, as a long table (one row per
  sample and feature) is;
* ``wide``: one column per sample, so the runs' tables are joined on the
  columns they share, a feature absent from a run counting 0 there;
* ``unique``: stacked, then deduplicated (a feature table every run repeats).

``sample_column`` names the output column that identifies one sample, which
gives each recomputed row its run. A row that aggregates several samples has
no run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from depictio.models.models.deltatables import RunScope as Scope

Combine = Literal["rows", "wide", "unique"]


@dataclass(frozen=True)
class RecipeScope:
    scope: Scope
    sample_column: str | None = None
    combine: dict[str, Combine] = field(default_factory=dict)


def _agg(sample_column: str | None = None, **combine: Combine) -> RecipeScope:
    return RecipeScope("aggregate", sample_column, dict(combine))


PIPELINE = RecipeScope("pipeline")

#: Keyed by the recipe as a template names it, without ``.py``.
REGISTRY: dict[str, RecipeScope] = {
    # nf-core/ampliseq
    "nf-core/ampliseq/bray_curtis_canonical": _agg("sample"),
    "qiime2/embedding_pcoa": _agg("sample_id", taxonomy_heatmap="wide"),
    "nf-core/ampliseq/upset_canonical": _agg(),
    # A Phylum x sample pivot, and the canonical tile that passes it through: a
    # recomputed source carries no run, so its reader has to be recomputed too.
    "qiime2/taxonomy_heatmap": _agg(),
    "nf-core/ampliseq/complex_heatmap_canonical": _agg(),
    "nf-core/ampliseq/sankey_canonical": _agg("sample_id", asv_tax="wide", genus="wide"),
    "nf-core/ampliseq/tree_metadata_canonical": _agg(asv_tax="wide", taxonomy="unique"),
    "nf-core/ampliseq/ma_canonical": PIPELINE,
    "nf-core/ampliseq/beta_adonis": PIPELINE,
    "qiime2/ancombc": PIPELINE,
    "sidle/reconstruction_qc": PIPELINE,
    # nf-core/rnaseq
    "salmon/sample_pca": _agg("sample_id", matrix="wide"),
    "salmon/top_variable_genes": _agg(matrix="wide"),
    "nf-core/rnaseq/gene_summary": _agg(matrix="wide"),
    "deseq2/qc_pca": PIPELINE,
    "deseq2/qc_sample_dists": PIPELINE,
    # nf-core/riboseq wraps the salmon PCA
    "nf-core/riboseq/sample_pca": _agg("sample_id", matrix="wide"),
    # nf-core/differentialabundance: the VST matrix is genes x samples
    "deseq2/vst_pca": _agg("sample_id", vst="wide"),
    "deseq2/vst_sample_distance": _agg("sample", vst="wide"),
    "deseq2/vst_top_variable": _agg(vst="wide"),
    # nf-core/smrnaseq
    "mirtop/sample_pca": _agg("sample"),
    "mirtop/top_variable_heatmap": _agg(),
    "mirtop/sample_matrix": _agg("sample"),
    "mirtop/mirna_summary": _agg(),
    # nf-core/nascent
    "subread/correlation": _agg("sample"),
    # nf-core/methylseq
    "bismark/window_pca": _agg("sample_id"),
    "bismark/window_correlation": _agg("sample"),
    "bismark/top_variable_windows": _agg(),
    # nf-core/funcscan
    "hamronization/gene_matrix": _agg(),
    "hamronization/class_matrix": _agg(),
    # nf-core/rnavar
    "nf-core/rnavar/sample_concordance": _agg("sample"),
    # nf-core/viralrecon
    "nf-core/viralrecon/upset_canonical": _agg(),
    "nf-core/viralrecon/variant_feature_matrix_canonical": _agg("sample_id"),
    # nf-core/taxprofiler
    "taxpasta/embedding": _agg("sample_id"),
    "taxpasta/matrix": _agg(),
    # nf-core/sarek
    "snpeff/protein_lollipop": _agg(),
    "snpeff/gene_upset": _agg(),
    "snpeff/gene_heatmap": _agg(),
    # nf-core/quantms: an MS run is one sample, named by run_id
    "nf-core/quantms/sample_correlation": _agg("run_id"),
    "nf-core/quantms/sample_embedding": _agg("run_id"),
    # nf-core/atacseq
    "macs2/consensus_boolean": PIPELINE,
    "macs2/consensus_fc": PIPELINE,
    "nf-core/atacseq/deseq2_qc_pca": PIPELINE,
}

RUN = RecipeScope("run")


def _key(recipe: str) -> str:
    return recipe[:-3] if recipe.endswith(".py") else recipe


def recipe_scope(recipe: str, declared: Scope | None = None) -> RecipeScope:
    """The scope of ``recipe``; ``declared`` (``TransformConfig.scope``) wins."""
    known = REGISTRY.get(_key(recipe), RUN)
    if declared is None or declared == known.scope:
        return known
    return RecipeScope(declared)
