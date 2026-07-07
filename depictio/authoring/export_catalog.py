"""Catalogue-mode export — deferred.

The tool-catalogue output (``module.yaml`` + ``<output>.yaml`` + fixture) requires
a scaffolder that must be built from scratch (there is no ``dev catalog new``
generator in this tree yet). It is intentionally out of scope for this pass; the
studio UI shows the "Tool catalogue" toggle disabled, and this endpoint returns
``501 Not Implemented``.
"""

from __future__ import annotations


class CatalogExportNotImplemented(NotImplementedError):
    """Raised by the catalogue-export endpoint until the scaffolder lands."""


def export_catalog(*_args, **_kwargs):
    raise CatalogExportNotImplemented(
        "Catalogue export is not yet implemented in the studio. "
        "Use Dashboard mode, or contribute a catalog module by hand under "
        "depictio/catalog/<tool>/ (validated by `depictio dev catalog validate`)."
    )
