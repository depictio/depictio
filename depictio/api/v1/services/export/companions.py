"""Companion collections an advanced-viz config binds beside its own.

Shared by the component export (``embed._add_table_companions``) and the
serverless bundle (``depictio.serverless.pruning.advanced_viz_companions``):
both have to ship the second table a tile reads (the hits of an HMM logo, the
domains and variants of a sequence track, a ranked table's family rows) under
the id the renderer asks for. Kept free of FastAPI so producer B, which builds
bundles without a server, can import it.
"""

from __future__ import annotations

from typing import Any

#: ``<base>_dc_id`` keys that name no table companion read under its own id: the
#: phylogeny (``tree_dc_id``, embedded under its own synthetic key by the
#: export), the volcano's MA source (``ma_dc_id``, loaded from the view plan by
#: the export) and the unused ``matrix_dc_id`` of a complex heatmap.
_NOT_TABLE_COMPANION_KEYS = frozenset({"tree_dc_id", "ma_dc_id", "matrix_dc_id"})

#: Columns a companion table is read by under a fixed name, which no ``*_col``
#: key carries (constants of ``SequenceTrackRenderer.tsx``): a domain's
#: annotation database, a variant's reference and alternate residues.
_FIXED_COMPANION_COLUMNS: dict[str, tuple[str, ...]] = {
    "domains_dc_id": ("source",),
    "variants_dc_id": ("ref_aa", "alt_aa"),
}


def _companion_dc_ids(config: dict[str, Any]) -> dict[str, tuple[str | None, list[str]]]:
    """Every companion collection a config binds: ``{dc_id: (wf_id, fixed columns)}``.

    Advanced-viz configs bind a second collection with a ``<base>_dc_id`` key (the
    hits of an HMM logo, the domains and variants of a sequence track, the
    alignment under a structure, the PAE file of a matrix) and, beside it, the
    ``<base>_wf_id`` of its workflow. The renderer asks for it by that real id, so
    the payload keys it the same way. A collection named twice is listed once.
    """
    found: dict[str, tuple[str | None, list[str]]] = {}
    for key, value in config.items():
        if not key.endswith("_dc_id") or key in _NOT_TABLE_COMPANION_KEYS or not value:
            continue
        dc_id = str(value)
        wf_id = config.get(f"{key[: -len('_dc_id')]}_wf_id")
        known_wf, known_extra = found.get(dc_id, (None, []))
        extra = [c for c in _FIXED_COMPANION_COLUMNS.get(key, ()) if c not in known_extra]
        found[dc_id] = (known_wf or (str(wf_id) if wf_id else None), [*known_extra, *extra])
    return found
