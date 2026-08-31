"""Per-kind Python figure builders for advanced visualisations.

Importing this package registers every builder. Adding a kind means adding a
module here and importing it below — ``capabilities.formats_for`` picks it up
automatically and the export route stops answering 501 for that kind.

Ported so far: volcano, ma, qq, stacked_taxonomy, manhattan, embedding,
da_barplot, enrichment, sunburst, and the four benchmarking kinds
(roc_pr_curve, pr_benchmark, confusion_matrix, metric_ci_bars). The remaining
kinds still render client-side only and are exportable as ``format=html``; see
the notes in ``services/export/capabilities.py`` for why each is outstanding.
"""

from depictio.api.v1.services.advanced_viz.kinds import (  # noqa: F401
    confusion_matrix,
    da_barplot,
    embedding,
    enrichment,
    ma,
    manhattan,
    metric_ci_bars,
    pr_benchmark,
    qq,
    roc_pr_curve,
    stacked_taxonomy,
    sunburst,
    volcano,
)

__all__ = [
    "confusion_matrix",
    "da_barplot",
    "embedding",
    "enrichment",
    "ma",
    "manhattan",
    "metric_ci_bars",
    "pr_benchmark",
    "qq",
    "roc_pr_curve",
    "stacked_taxonomy",
    "sunburst",
    "volcano",
]
