"""Per-kind Python figure builders for advanced visualisations.

Importing this package registers every builder. Adding a kind means adding a
module here and importing it below — ``capabilities.formats_for`` picks it up
automatically and the export route stops answering 501 for that kind.

Ported so far: volcano, ma, qq. The remaining kinds still render client-side
only and are exportable as ``format=html``.
"""

from depictio.api.v1.services.advanced_viz.kinds import ma, qq, volcano  # noqa: F401

__all__ = ["ma", "qq", "volcano"]
