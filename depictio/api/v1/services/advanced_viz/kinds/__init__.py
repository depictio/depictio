"""Per-kind Python figure builders for advanced visualisations.

Importing this package registers every builder. Adding a kind means adding a
module here and importing it below — ``capabilities.formats_for`` picks it up
automatically and the export route stops answering 501 for that kind.

Ported so far: volcano, ma, qq, stacked_taxonomy, manhattan, embedding,
da_barplot, enrichment, sunburst. The remaining kinds still render client-side
only and are exportable as ``format=html``; see the notes in
``services/export/capabilities.py`` for why each is still outstanding.
"""

from depictio.api.v1.services.advanced_viz.kinds import (  # noqa: F401
    da_barplot,
    embedding,
    enrichment,
    ma,
    manhattan,
    qq,
    stacked_taxonomy,
    sunburst,
    volcano,
)

__all__ = [
    "da_barplot",
    "embedding",
    "enrichment",
    "ma",
    "manhattan",
    "qq",
    "stacked_taxonomy",
    "sunburst",
    "volcano",
]
