"""Image stores for the builder: ``*.zarr`` folders read as one thing, never as
the thousands of chunk files inside them.

A bioimage collection (OME-Zarr, SpatialData) and a table read from a
SpatialData store both scan *stores*: folders named ``*.zarr``, found by the
same basename-then-path regex rule as files, and never descended into. An
OME-TIFF collection scans ``*.ome.tif(f)`` files, outside any store. The tree
shows a store as a leaf, ``describe_store`` sniffs what one holds, and
``match_stores`` lists what a collection would register, the way the scanner
collects its candidates.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from depictio.cli.cli.utils.data_root import DataRoot
from depictio.cli.cli.utils.scan_utils import file_matches_data_collection

STORE_SUFFIX = ".zarr"
OME_TIFF_SUFFIXES = (".ome.tiff", ".ome.tif")
SPATIALDATA_ELEMENTS = frozenset({"images", "labels", "points", "shapes", "tables"})


def is_store_name(name: str) -> bool:
    """A folder name that marks a zarr store (``x.zarr``, never a bare ``.zarr``)."""
    return name.lower().endswith(STORE_SUFFIX) and len(name) > len(STORE_SUFFIX)


def is_ome_tiff(name: str) -> bool:
    return name.lower().endswith(OME_TIFF_SUFFIXES)


def inside_store(rel: str) -> bool:
    """Whether ``rel`` lies inside a store (one of its folders, not the store itself)."""
    return any(is_store_name(part) for part in rel.split("/")[:-1])


def describe_store(root: DataRoot, rel: str) -> dict[str, Any]:
    """What the store ``rel`` looks like from its top level.

    NGFF 0.5 stores carry ``zarr.json``, 0.4 ones ``.zattrs``/``.zgroup``; a
    SpatialData store has element folders (``images``, ``tables``…). A server
    that hides dot-files cannot see 0.4 markers, so the version is then
    unknown and the store is checked at ingest instead.
    """
    names = {entry.name: entry.is_dir for entry in root.children(rel)}
    if "zarr.json" in names:
        version: str | None = "0.5"
    elif ".zattrs" in names or ".zgroup" in names:
        version = "0.4"
    else:
        version = None
    elements = {name for name, is_dir in names.items() if is_dir} & SPATIALDATA_ELEMENTS
    spatial = bool(elements & {"images", "tables", "shapes", "points"})

    def members(element: str) -> list[str]:
        if element not in elements:
            return []
        return [
            f"{element}/{entry.name}"
            for entry in root.children(f"{rel}/{element}")
            if entry.is_dir and not entry.name.startswith(".")
        ]

    return {
        "format": "spatialdata" if spatial else "ome-zarr",
        "ngff_version": version,
        "images": members("images"),
        "tables": members("tables"),
    }


def _local_stores(root: DataRoot, within: str) -> list[str]:
    """Every store under ``within`` of a local root, root-relative, not descended into."""
    base = Path(root.url(within))
    if not base.is_dir():
        return []
    if is_store_name(base.name):
        return [within] if root.exists(within) else []
    top = Path(root.url(""))
    found: list[str] = []
    for dirpath, dirnames, _files in os.walk(base, followlinks=False):
        keep = []
        for name in dirnames:
            if is_store_name(name):
                rel = (Path(dirpath) / name).relative_to(top).as_posix()
                if root.exists(rel):
                    found.append(rel)
            else:
                keep.append(name)
        dirnames[:] = keep
    return sorted(found)


def match_stores(root: DataRoot, regex: str, scopes: list[str]) -> list[str]:
    """The stores a recursive scan of each scope (a run folder, or the root) registers.

    Matched by the scan's own rule (:func:`file_matches_data_collection`): the
    store's name first, then its path from the scope when the regex spells one.
    Local roots only: stores are read from disk at ingest.
    """
    if root.is_remote:
        return []
    matched: list[str] = []
    for scope in scopes:
        run_location = root.url(scope)
        for rel in _local_stores(root, scope):
            if file_matches_data_collection(root.url(rel), run_location, regex):
                matched.append(rel)
    return sorted(dict.fromkeys(matched))
