"""Which files a data collection would ingest, and whether they agree with each other.

The list comes from the collection's own scan block (``assemble.dc_config``)
handed to ``template_preview.scan_dc_hits``, the function the from_run dry run
counts with, and which walks and filters exactly as the scan does. So "these
files will be ingested" is the scan's answer, not a look-alike.

Collections of image stores (bioimage, SpatialData tables) register ``*.zarr``
folders instead of files, by the same name rule (``stores.match_stores``); an
OME-TIFF collection keeps its ``*.ome.tif(f)`` files outside any store. A
genomic tracks collection's manifest is matched like a table, then read back
for what ingestion would make of its rows (``tracks.check_manifest``).
"""

from __future__ import annotations

import re
from typing import Any

from depictio.cli.cli.utils.data_root import DataRoot
from depictio.cli.cli.utils.file_preview import preview_root_file
from depictio.cli.cli.utils.template_preview import scan_dc_hits
from depictio.models.local_access import LocalPathRefused
from depictio.models.logging import logger
from depictio.project_builder.assemble import (
    BioimageProps,
    DcDraft,
    GenomicTracksProps,
    IndexedFileProps,
    TableProps,
    dc_config,
)
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.roots import confine_rel
from depictio.project_builder.stores import inside_store, is_ome_tiff, match_stores
from depictio.project_builder.tracks import check_manifest, infer_track_format

# Files listed back to the browser at most.
MAX_LISTED = 500
# Files whose header is read to compare schemas: a local read is cheap, an S3
# one is a ranged GET each.
SCHEMA_SAMPLE_LOCAL = 50
SCHEMA_SAMPLE_REMOTE = 20
BUNDLE_FOLDER = ".depictio/"


def _runs(root: DataRoot, structure: str, runs_regex: str | None) -> list[str]:
    if structure != "sequencing-runs":
        return []
    if not runs_regex:
        raise BuilderRefused(400, "Sequencing runs need a runs regex.", "runs_regex_missing")
    try:
        re.compile(runs_regex)
    except re.error as exc:
        raise BuilderRefused(400, f"Invalid runs regex: {exc}", "runs_regex_invalid") from exc
    return root.runs(runs_regex)


def _schema(root: DataRoot, rel: str) -> dict[str, str] | None:
    try:
        preview = preview_root_file(root, rel, max_rows=1, infer_types=True)
    except (FileNotFoundError, LocalPathRefused) as exc:
        logger.debug(f"builder match: cannot read {rel}: {exc}")
        return None
    if preview.format != "table":
        return None
    return preview.dtypes or dict.fromkeys(preview.columns, "String")


_NUMERIC_TYPE = re.compile(r"^(U?Int(8|16|32|64)|Float(32|64))$")


def _widened(types: set[str]) -> str | None:
    """The type a column read as several numeric types becomes, or None when a
    type is not numeric (a real conflict). Ingestion concatenates the files with
    relaxed dtypes, so integers and floats of one column are widened, not refused."""
    if len(types) < 2 or not all(_NUMERIC_TYPE.match(t) for t in types):
        return None
    return "Float64" if any(t.startswith("Float") for t in types) else "Int64"


def _compare(files: list[str], schemas: dict[str, dict[str, str]]) -> tuple[Any, ...]:
    """``(reference schema, all agree, mismatches, widened)``.

    The reference is the first file's. Columns read as different *numeric* types
    (a column of 0 and 1 is Int64 in one file, Float64 in another) are widened by
    ingestion, so they are reported in ``widened`` and are no mismatch; a missing
    or extra column, or a change to or from a non-numeric type, is.
    """
    readable = [f for f in files if schemas.get(f) is not None]
    if not readable:
        return None, None, [], {}
    reference = schemas[readable[0]]
    seen: dict[str, set[str]] = {}
    for rel in readable:
        for column, dtype in schemas[rel].items():
            seen.setdefault(column, set()).add(dtype)
    widened = {
        column: {"types": sorted(types), "as": target}
        for column, types in seen.items()
        if (target := _widened(types))
    }
    mismatches = []
    for rel in readable[1:]:
        other = schemas[rel]
        missing = [column for column in reference if column not in other]
        extra = [column for column in other if column not in reference]
        changed = {
            column: [reference[column], other[column]]
            for column in reference
            if column in other and reference[column] != other[column] and column not in widened
        }
        if missing or extra or changed:
            mismatches.append({"file": rel, "missing": missing, "extra": extra, "changed": changed})
    return reference, not mismatches, mismatches, widened


def _index_suffix(props: IndexedFileProps) -> str:
    from depictio.models.models.data_collections_types.indexed_file import DEFAULT_INDEX_SUFFIX

    if props.index_suffix is not None:
        return props.index_suffix
    return DEFAULT_INDEX_SUFFIX.get(props.format, "")


def store_kind(dc: DcDraft) -> str | None:
    """``zarr`` when ``dc`` registers stores, ``ome-tiff`` for OME-TIFF files, else None."""
    props = dc.props
    if isinstance(props, BioimageProps):
        return "ome-tiff" if props.format == "ome-tiff" else "zarr"
    if isinstance(props, TableProps) and props.format == "spatialdata":
        return "zarr"
    return None


def _full_regex(scan: dict[str, Any]) -> str:
    """The scan's regex with its wildcards spliced in, as the walk reads it."""
    regex_config = scan["scan_parameters"]["regex_config"]
    pattern = regex_config["pattern"]
    for wildcard in regex_config.get("wildcards") or []:
        pattern = pattern.replace(f"{{{wildcard['name']}}}", f"({wildcard['wildcard_regex']})")
    return pattern


def match_collection(
    root: DataRoot, structure: str, runs_regex: str | None, dc: DcDraft
) -> dict[str, Any]:
    """What ``dc`` would ingest from ``root``, for the builder's matches panel.

    Bounds (``max_depth``/``ignore``) apply under a local root and not under
    an ``s3://`` one, as at ingest; a warning says so when they are set there.
    """
    if dc.path:
        dc = dc.model_copy(update={"path": confine_rel(dc.path)})
    config = dc_config(dc, remote=root.is_remote)
    scan = config["scan"]
    runs = _runs(root, structure, runs_regex)
    warnings: list[str] = []
    stores = store_kind(dc)

    if stores and root.is_remote:
        files: list[str] = []
        regex = None
        warnings.append(
            "Image stores are read from a folder on this computer at ingest: an s3:// prefix "
            "can't be scanned for them."
        )
    elif scan["mode"] == "single":
        rel = dc.path or ""
        files = [rel] if rel and root.exists(rel) else []
        regex = None
    else:
        regex = scan["scan_parameters"]["regex_config"]["pattern"]
        try:
            re.compile(_full_regex(scan))
        except (re.error, KeyError) as exc:
            raise BuilderRefused(400, f"Invalid regex: {exc}", "regex_invalid") from exc
        if structure == "sequencing-runs" and not runs:
            # The scan walks run folders only: none matches, nothing is scanned.
            files = []
            warnings.append("No folder of the data root matches the runs regex.")
        elif stores == "zarr":
            files = match_stores(root, _full_regex(scan), runs or [""])
        else:
            files = sorted(scan_dc_hits(config, root, runs) or [])
            if stores == "ome-tiff":
                files = [rel for rel in files if is_ome_tiff(rel) and not inside_store(rel)]
            else:
                inside = [rel for rel in files if inside_store(rel)]
                if inside:
                    warnings.append(
                        f"{len(inside)} matched file(s) are inside a .zarr store: tighten the "
                        "regex so it does not read image chunks."
                    )
        if stores and (dc.max_depth is not None or dc.ignore):
            warnings.append("max_depth and ignore do not limit where stores are found.")
        elif root.is_remote and (dc.max_depth is not None or dc.ignore):
            warnings.append(
                "max_depth and ignore apply to local folders only: an S3 prefix is listed whole."
            )

    if not files and not (stores and root.is_remote):
        warnings.append("No store matches yet." if stores == "zarr" else "No file matches yet.")
    if regex is not None and any(
        rel.startswith(BUNDLE_FOLDER) or f"/{BUNDLE_FOLDER}" in rel for rel in files
    ):
        warnings.append(
            "The rule also matches files under .depictio/, where the builder writes its template."
        )

    schema: dict[str, str] | None = None
    consistent: bool | None = None
    mismatches: list[dict[str, Any]] = []
    widened: dict[str, Any] = {}
    if dc.type in ("table", "image", "genomic_tracks") and files and not stores:
        sample = files[: SCHEMA_SAMPLE_REMOTE if root.is_remote else SCHEMA_SAMPLE_LOCAL]
        schemas = {rel: _schema(root, rel) for rel in sample}
        schema, consistent, mismatches, widened = _compare(sample, schemas)
        if len(files) > len(sample):
            warnings.append(f"Schemas compared on the first {len(sample)} of {len(files)} files.")

    missing_indexes: list[str] = []
    if isinstance(dc.props, IndexedFileProps):
        suffix = _index_suffix(dc.props)
        if suffix:
            missing_indexes = [rel for rel in files[:MAX_LISTED] if not root.exists(rel + suffix)]

    tracks = None
    if isinstance(dc.props, GenomicTracksProps) and files and infer_track_format(files[0]):
        warnings.append(
            "These are track files: a genomic tracks collection reads a manifest listing "
            "them. Pick one, or generate it from the track files."
        )
    elif isinstance(dc.props, GenomicTracksProps) and files:
        props = dc.props
        tracks = check_manifest(
            root,
            files[0],
            uri_column=props.uri_column,
            format_column=props.format_column or "format",
            index_column=props.index_column or "index_uri",
            default_format=props.default_format,
            tracks_base=props.tracks_base_path,
        )
        if len(files) > 1:
            warnings.append(f"Track checks read the first of {len(files)} manifests.")

    if isinstance(dc.props, (TableProps,)) and dc.props.reader and dc.props.reader.polars_kwargs():
        warnings.append("Schemas are read without the reader options; ingestion applies them.")

    return {
        "regex": regex,
        "files": files[:MAX_LISTED],
        "count": len(files),
        "runs": runs,
        "truncated": len(files) > MAX_LISTED or root.truncated,
        "schema": schema,
        "consistent": consistent,
        "mismatches": mismatches,
        "widened": widened,
        "missing_indexes": missing_indexes,
        "stores": bool(stores),
        "tracks": tracks,
        "warnings": warnings,
    }
