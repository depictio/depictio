"""Which files a data collection would ingest, and whether they agree with each other.

The list comes from the collection's own scan block (``assemble.dc_config``)
handed to ``template_preview.scan_dc_hits``, the function the from_run dry run
counts with, and which walks and filters exactly as the scan does. So "these
files will be ingested" is the scan's answer, not a look-alike.
"""

from __future__ import annotations

import re
from typing import Any

from depictio.cli.cli.utils.data_root import DataRoot
from depictio.cli.cli.utils.file_preview import preview_root_file
from depictio.cli.cli.utils.template_preview import scan_dc_hits
from depictio.models.local_access import LocalPathRefused
from depictio.models.logging import logger
from depictio.project_builder.assemble import DcDraft, IndexedFileProps, dc_config
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.roots import confine_rel

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


def _compare(files: list[str], schemas: dict[str, dict[str, str]]) -> tuple[Any, ...]:
    """The reference schema (the first file's), whether all agree, and how each other differs."""
    readable = [f for f in files if schemas.get(f) is not None]
    if not readable:
        return None, None, []
    reference = schemas[readable[0]]
    mismatches = []
    for rel in readable[1:]:
        other = schemas[rel]
        missing = [column for column in reference if column not in other]
        extra = [column for column in other if column not in reference]
        changed = {
            column: [reference[column], other[column]]
            for column in reference
            if column in other and reference[column] != other[column]
        }
        if missing or extra or changed:
            mismatches.append({"file": rel, "missing": missing, "extra": extra, "changed": changed})
    return reference, not mismatches, mismatches


def _index_suffix(props: IndexedFileProps) -> str:
    from depictio.models.models.data_collections_types.indexed_file import DEFAULT_INDEX_SUFFIX

    if props.index_suffix is not None:
        return props.index_suffix
    return DEFAULT_INDEX_SUFFIX.get(props.format, "")


def match_collection(
    root: DataRoot, structure: str, runs_regex: str | None, dc: DcDraft
) -> dict[str, Any]:
    """What ``dc`` would ingest from ``root``, for the builder's matches panel.

    Bounds (``max_depth``/``ignore``) apply under a local root and not under
    an ``s3://`` one, as at ingest; a warning says so when they are set there.
    """
    if dc.path:
        dc = dc.model_copy(update={"path": confine_rel(dc.path)})
    config = dc_config(dc)
    scan = config["scan"]
    runs = _runs(root, structure, runs_regex)
    warnings: list[str] = []

    if scan["mode"] == "single":
        rel = dc.path or ""
        files = [rel] if rel and root.exists(rel) else []
        regex = None
    else:
        regex = scan["scan_parameters"]["regex_config"]["pattern"]
        try:
            re.compile(regex)
        except re.error as exc:
            raise BuilderRefused(400, f"Invalid regex: {exc}", "regex_invalid") from exc
        if structure == "sequencing-runs" and not runs:
            # The scan walks run folders only: none matches, nothing is scanned.
            files = []
            warnings.append("No folder of the data root matches the runs regex.")
        else:
            files = sorted(scan_dc_hits(config, root, runs) or [])
        if root.is_remote and (dc.max_depth is not None or dc.ignore):
            warnings.append(
                "max_depth and ignore apply to local folders only: an S3 prefix is listed whole."
            )

    if not files:
        warnings.append("No file matches yet.")
    if any(rel.startswith(BUNDLE_FOLDER) or f"/{BUNDLE_FOLDER}" in rel for rel in files):
        warnings.append(
            "The rule also matches files under .depictio/, where the builder writes its template."
        )

    schema: dict[str, str] | None = None
    consistent: bool | None = None
    mismatches: list[dict[str, Any]] = []
    if dc.type in ("table", "image") and files:
        sample = files[: SCHEMA_SAMPLE_REMOTE if root.is_remote else SCHEMA_SAMPLE_LOCAL]
        schemas = {rel: _schema(root, rel) for rel in sample}
        schema, consistent, mismatches = _compare(sample, schemas)
        if len(files) > len(sample):
            warnings.append(f"Schemas compared on the first {len(sample)} of {len(files)} files.")

    missing_indexes: list[str] = []
    if isinstance(dc.props, IndexedFileProps):
        suffix = _index_suffix(dc.props)
        if suffix:
            missing_indexes = [rel for rel in files[:MAX_LISTED] if not root.exists(rel + suffix)]

    return {
        "regex": regex,
        "files": files[:MAX_LISTED],
        "count": len(files),
        "runs": runs,
        "truncated": len(files) > MAX_LISTED or root.truncated,
        "schema": schema,
        "consistent": consistent,
        "mismatches": mismatches,
        "missing_indexes": missing_indexes,
        "warnings": warnings,
    }
