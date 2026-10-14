"""What this Depictio can build: the collection kinds its models know, and the
instance settings a project's options depend on.

Two kinds come from work that may not be in every Depictio yet: genome-browser
track collections (``genomic_tracks``) and bioimages (``bioimage``, plus table
collections read from a SpatialData store). Each is detected from the models
themselves, never from a version number, so a Depictio that has them reports
them available and one that does not lists them with the reason. The builder
offers only what is available, and ``validate`` refuses the rest.

Real-time updates are a project flag the server only acts on with
``DEPICTIO_EVENTS_ENABLED``; the standalone builder runs without a server and
cannot know, so it answers ``None``.
"""

from __future__ import annotations

import importlib
import importlib.util
from functools import cache
from typing import Any, Literal, get_args

from depictio.project_builder.validate import ALLOWED_POLARS_KWARGS

GENOMIC_TRACKS_MODULE = "depictio.models.models.data_collections_types.genomic_tracks"
BIOIMAGE_MODULE = "depictio.models.models.data_collections_types.bioimage"
ASSEMBLIES_MODULE = "depictio.api.v1.services.jbrowse.assemblies"

CORE_TYPES = ("table", "multiqc", "image", "indexed_file", "geojson", "phylogeny")
BASE_TABLE_FORMATS = ("csv", "tsv", "parquet", "feather", "xls", "xlsx")
BIOIMAGE_FORMATS = ("ome-zarr", "ome-tiff", "spatialdata")

UNAVAILABLE = {
    "genomic_tracks": "This Depictio has no genome-browser track collections yet.",
    "bioimage": "This Depictio has no bioimage collections yet.",
}
EVENTS_OFF = (
    "Real-time events are off on this server (DEPICTIO_EVENTS_ENABLED). Under depictio "
    "local, set DEPICTIO_EVENTS_ENABLED=true before depictio local up."
)
EVENTS_UNKNOWN = "Takes effect only on a server with real-time events on."


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@cache
def genomic_tracks_model() -> Any | None:
    """The genomic tracks model module, or None when this Depictio has none."""
    if not _has_module(GENOMIC_TRACKS_MODULE):
        return None
    try:
        return importlib.import_module(GENOMIC_TRACKS_MODULE)
    except ImportError:
        return None


@cache
def bioimage_model() -> Any | None:
    """The bioimage model module, or None when this Depictio has none."""
    if not _has_module(BIOIMAGE_MODULE):
        return None
    try:
        return importlib.import_module(BIOIMAGE_MODULE)
    except ImportError:
        return None


def spatialdata_tables() -> bool:
    """Whether a table collection may read a SpatialData store (``format: spatialdata``)."""
    from depictio.models.models.data_collections_types.table import DCTableConfig

    return "spatialdata" in DCTableConfig.model_fields


def available_types() -> set[str]:
    types = set(CORE_TYPES)
    if genomic_tracks_model() is not None:
        types.add("genomic_tracks")
    if bioimage_model() is not None:
        types.add("bioimage")
    return types


def table_formats() -> list[str]:
    """The table formats the table model accepts (``spatialdata`` when it reads stores)."""
    from depictio.models.models.data_collections_types.table import DCTableConfig

    accepted = []
    for fmt in BASE_TABLE_FORMATS:
        try:
            DCTableConfig(format=fmt)
        except ValueError:
            continue
        accepted.append(fmt)
    if spatialdata_tables():
        accepted.append("spatialdata")
    return accepted


def link_target_types() -> list[str]:
    """The ``target_type`` values a link may name on this Depictio."""
    from depictio.models.models.links import DCLink

    annotation = DCLink.model_fields["target_type"].annotation
    return [str(value) for value in get_args(annotation)]


def track_formats() -> list[str]:
    module = genomic_tracks_model()
    return list(getattr(module, "TRACK_FORMATS", ())) if module is not None else []


def assemblies() -> list[str]:
    """The genome browser's built-in assemblies, when the server ships them.

    Read from the API's own presets, so only on the server: the standalone
    builder answers no list and takes any assembly name.
    """
    try:
        module = importlib.import_module(ASSEMBLIES_MODULE)
    except ImportError:
        return []
    return list(getattr(module, "ASSEMBLY_PRESETS", {}) or {})


def capabilities(
    mode: Literal["server", "standalone"], events_enabled: bool | None
) -> dict[str, Any]:
    """The ``GET /projects/builder/capabilities`` answer."""
    present = available_types()
    dc_types = [
        {
            "type": dc_type,
            "available": dc_type in present,
            "reason": None if dc_type in present else UNAVAILABLE.get(dc_type),
        }
        for dc_type in (*CORE_TYPES, "genomic_tracks", "bioimage")
    ]
    if events_enabled is None:
        realtime = {"events_enabled": None, "reason": EVENTS_UNKNOWN}
    else:
        realtime = {
            "events_enabled": bool(events_enabled),
            "reason": None if events_enabled else EVENTS_OFF,
        }
    return {
        "mode": mode,
        "dc_types": dc_types,
        "table_formats": table_formats(),
        "reader_options": sorted(ALLOWED_POLARS_KWARGS),
        "link_target_types": link_target_types(),
        "realtime": realtime,
        "genomic_tracks": (
            {
                "assemblies": assemblies() if mode == "server" else [],
                "track_formats": track_formats(),
            }
            if "genomic_tracks" in present
            else None
        ),
        "bioimage": {"formats": list(BIOIMAGE_FORMATS)} if "bioimage" in present else None,
    }
