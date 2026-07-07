"""Live preview: (picked file, viz spec) → the viewer's render payload.

The single preview engine is ``build_payload`` (``depictio.catalog.payload``),
which computes a Dash-free ``window.__CATALOG_PREVIEW__`` blob for a
``CatalogOutput``'s ``renders_as`` on its fixture. The studio has no catalog
entry to preview — it has an arbitrary local file + a viz spec — so we synthesize
a **transient** ``CatalogOutput`` whose fixture *is* the picked file and whose
single render *is* the spec, then call ``build_payload`` unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from depictio.authoring.paths import safe_resolve


def render_spec(root: Path, rel: str, spec: dict[str, Any], theme: str = "light") -> dict[str, Any]:
    """Build the preview payload for one viz ``spec`` on the picked file ``rel``.

    ``spec`` is a ``Render``-native dict, e.g.
    ``{"component": "figure", "visu_type": "scatter", "dict_kwargs": {"x": "a", "y": "b"}}``
    or ``{"component": "card", "column": "depth", "aggregation": "median"}``.
    """
    from depictio.catalog.payload import build_payload
    from depictio.models.components.advanced_viz.catalog import (
        CatalogFind,
        CatalogOutput,
        Render,
    )

    path = safe_resolve(root, rel)
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {rel!r}")

    render = Render(**spec)
    output = CatalogOutput(
        id="studio",
        find=CatalogFind(filename=path.name),
        fixture=path.name,
        renders_as=[render],
    )
    # `fixture_file()` resolves as `_source_dir / fixture`; point it at the pick.
    output._source_dir = path.parent
    return build_payload(output, theme=theme, tool=None)
