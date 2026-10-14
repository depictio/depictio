"""One folder level of a data root, for the builder's file tree."""

from __future__ import annotations

from typing import Any

from depictio.cli.cli.utils.data_root import DataRoot
from depictio.models.local_access import is_hidden_name
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.roots import confine_rel
from depictio.project_builder.stores import is_store_name

# More entries than this in one folder and the listing says ``truncated``.
MAX_ENTRIES = 1000


def list_folder(root: DataRoot, rel: str = "") -> dict[str, Any]:
    """The entries directly inside folder ``rel`` of ``root``, folders first.

    Hidden like every other listing of a data root: dot-names and the noise
    folders (``is_hidden_name``). Lazy by design: a tree is expanded one folder
    at a time, so an S3 prefix or a home folder is never walked whole for it.
    A ``*.zarr`` folder is a store (``store: "zarr"``): one thing to pick, not
    a folder to open.
    """
    rel = confine_rel(rel)
    if rel and not root.exists(rel):
        raise BuilderRefused(404, f"'{rel}' is not a folder of the data root.", "folder_missing")
    entries = [entry for entry in root.children(rel) if not is_hidden_name(entry.name)]
    shown = entries[:MAX_ENTRIES]
    return {
        "path": rel,
        "entries": [
            {
                "name": entry.name,
                "path": f"{rel}/{entry.name}" if rel else entry.name,
                "is_dir": entry.is_dir,
                "size": entry.size,
                "store": "zarr" if entry.is_dir and is_store_name(entry.name) else None,
            }
            for entry in shown
        ],
        "truncated": len(entries) > MAX_ENTRIES or root.truncated,
        "is_remote": root.is_remote,
        "root_label": root.location,
    }
