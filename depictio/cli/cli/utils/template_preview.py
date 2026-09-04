"""What a template would yield against a data root, before anything is created.

Answers the question a user actually has in front of ``depictio run --dry-run``:
given this directory or this ``s3://`` prefix, which data collections will find
their data, which will come up empty, and which variables did the run's own
parameters decide.

Reporting only: resolution itself lives in :mod:`depictio.cli.cli.utils.templates`
and this module reads it, never the other way round. Every question is asked of
one :class:`DataRoot`, so previewing a remote prefix costs a single listing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import translate
from typing import Any, Literal

from depictio.cli.cli.utils.data_root import DataRoot, as_data_root
from depictio.cli.cli.utils.scan_utils import construct_full_regex
from depictio.cli.cli.utils.templates import OPTIONAL_SOURCE_MISSING_REASON, resolve_template
from depictio.cli.cli_logging import logger
from depictio.models.models.data_collections import Regex

PreviewStatus = Literal["ok", "empty", "missing", "pruned"]
"""How a data collection fared under the previewed root.

``ok`` it will ingest, ``empty`` the scan matched nothing, ``missing`` a source
it needs is not there, ``pruned`` it was dropped because an optional source was
absent. The renderer in ``commands/run.py`` colours and counts these, so the
vocabulary is defined once here.
"""

# The variables worth showing before a run: the ones resolution *derived* rather
# than the ones the user typed. The SKIP_*/IS_* flags matter most, because they
# are what the conditionals gate on, so they decide which DCs exist at all.
_PREVIEW_VARIABLE_NAMES = (
    "SAMPLESHEET_FILE",
    "METADATA_FILE",
    "METADATA_ID_COL",
    "GROUP_COL",
    "GROUP_COL_DISPLAY",
    "ANNOTATION_COLS",
)
_PREVIEW_FLAG_PREFIXES = ("SKIP_", "IS_")


@dataclass
class DataCollectionPreview:
    """What one data collection would find under a given data root.

    ``matched`` is a count taken with the rule the scan itself will use, so an
    ``empty`` row means the scan will genuinely find nothing, not that the
    preview looked somewhere else. Where nothing can be counted from the root -
    a manifest that is fetched at ingest, a URL on another host - the row is
    ``ok`` with ``matched`` 0 and ``location`` says where it points.
    """

    tag: str
    kind: Literal["scan", "recipe"]
    mode: str | None  # scan mode, None for recipe DCs
    location: str  # what it looked at, human readable
    matched: int  # files found
    missing_sources: list[str] = field(default_factory=list)  # unresolvable recipe sources
    optional: bool = False
    status: PreviewStatus = "ok"


@dataclass
class RunPreview:
    """What ``--data-root <location>`` would actually yield, before anything is created."""

    template_id: str
    data_root: str
    project_name: str
    resolved_variables: dict[str, str]
    detected_runs: list[str]
    data_collections: list[DataCollectionPreview]
    pruned_optional_dcs: list[str] = field(default_factory=list)
    dashboards: list[str] = field(default_factory=list)
    truncated: bool = False  # the listing hit its key cap, so the view is partial


def _scan_match_regex(mode: str, parameters: dict) -> str:
    """The regex a pattern-based scan will match files with.

    ``recursive`` carries a regex already (with the template's wildcards
    expanded exactly as the walk expands them); ``s3_prefix`` carries a glob
    unless it says otherwise, so translate it to the one dialect the data root's
    matcher speaks.
    """
    if mode == "recursive":
        regex_config = parameters.get("regex_config") or {}
        return construct_full_regex(
            Regex(
                pattern=regex_config.get("pattern") or ".*",
                wildcards=regex_config.get("wildcards"),
            )
        )
    pattern = parameters.get("pattern") or "*"
    if str(parameters.get("pattern_syntax") or "glob").lower() == "regex":
        return pattern
    return translate(pattern)


def _preview_scan_dc(
    tag: str,
    dc_config: dict,
    root: DataRoot,
    runs: list[str],
    optional: bool,
) -> DataCollectionPreview:
    """One row for a DC that acquires its data by scanning."""
    scan = dc_config.get("scan") or {}
    mode = str(scan.get("mode") or "").lower()
    parameters = scan.get("scan_parameters") or {}

    if mode in ("single", "url"):
        location = parameters.get("filename") or parameters.get("url") or ""
        relative = root.relative_of(location) if location else None
        if relative is None:
            # Not under this root (a foreign https:// URL, or a path elsewhere
            # on disk). We cannot count it, and must not report it missing.
            return DataCollectionPreview(
                tag=tag, kind="scan", mode=mode, location=location, matched=0, optional=optional
            )
        found = root.exists(relative)
        return DataCollectionPreview(
            tag=tag,
            kind="scan",
            mode=mode,
            location=root.url(relative),
            matched=1 if found else 0,
            optional=optional,
            status="ok" if found else "missing",
        )

    if mode == "manifest":
        # The manifest is fetched at ingest, not here: its entries are not
        # visible from the data root's listing.
        return DataCollectionPreview(
            tag=tag,
            kind="scan",
            mode=mode,
            location=parameters.get("manifest_url") or "",
            matched=0,
            optional=optional,
        )

    if mode in ("recursive", "s3_prefix"):
        regex = _scan_match_regex(mode, parameters)
        within = ""
        location = root.url("")
        if mode == "s3_prefix":
            prefix = parameters.get("prefix") or ""
            location = prefix
            relative = root.relative_of(prefix)
            if relative is None:
                # A prefix on another bucket: outside what this root listed.
                return DataCollectionPreview(
                    tag=tag,
                    kind="scan",
                    mode=mode,
                    location=prefix,
                    matched=0,
                    optional=optional,
                )
            within = relative
        # One pass per run directory when the workflow has them, the way the
        # scan itself scopes its walk; otherwise a single pass over the root.
        scopes = [f"{run}/{within}".strip("/") for run in runs] if runs else [within]
        matched = sum(len(root.match(regex, within=scope)) for scope in scopes)
        return DataCollectionPreview(
            tag=tag,
            kind="scan",
            mode=mode,
            location=location,
            matched=matched,
            optional=optional,
            status="ok" if matched else "empty",
        )

    return DataCollectionPreview(
        tag=tag, kind="scan", mode=mode or None, location=root.url(""), matched=0, optional=optional
    )


def _override_binding(override: Any, attribute: str) -> str | None:
    """One field of a source override, whether it arrived as a dict or a model.

    ``None`` (no override for this source) answers ``None`` for every field.
    """
    if isinstance(override, dict):
        return override.get(attribute)
    return getattr(override, attribute, None)


def _preview_recipe_dc(
    tag: str,
    dc_config: dict,
    root: DataRoot,
    optional: bool,
    present_tags: frozenset[str] = frozenset(),
) -> DataCollectionPreview:
    """One row for a ``source: transformed`` DC, resolved through its recipe's SOURCES.

    ``matched`` counts inputs found, not files: a ``dc_ref`` source is satisfied
    by another collection's output, so it counts when that collection is in the
    resolved project (``present_tags``). Without this every canonical that only
    reads other tables previewed as "0 files", indistinguishable from a
    collection whose inputs are genuinely absent. A required ``dc_ref`` to a
    collection that resolution dropped is reported missing by name, since the
    recipe would fail on it at ingestion.
    """
    transform = dc_config.get("transform") or {}
    recipe_name = transform.get("recipe") or ""
    row = DataCollectionPreview(
        tag=tag, kind="recipe", mode=None, location=root.url(""), matched=0, optional=optional
    )
    if not recipe_name:
        return row

    try:
        from depictio.recipes import load_recipe

        module = load_recipe(recipe_name)
    except Exception as exc:  # noqa: BLE001 - a preview never fails the run
        logger.warning(f"Preview: could not load recipe '{recipe_name}' for '{tag}': {exc}")
        return row

    overrides = transform.get("source_overrides") or {}
    for source in module.SOURCES:
        if source.dc_ref is not None:
            if source.dc_ref in present_tags:
                row.matched += 1
            elif not source.optional:
                row.missing_sources.append(f"collection '{source.dc_ref}'")
            continue
        override = overrides.get(source.ref)
        glob_pattern = _override_binding(override, "glob_pattern")
        path = _override_binding(override, "path")
        if glob_pattern is None and path is None:
            glob_pattern, path = source.glob_pattern, source.path

        if glob_pattern:
            hits = len(root.glob(glob_pattern))
        elif path:
            hits = 1 if root.exists(path) else 0
        else:
            continue
        row.matched += hits
        if not hits and not source.optional:
            row.missing_sources.append(glob_pattern or path or source.ref)

    row.status = "missing" if row.missing_sources else "ok"
    return row


def preview_data_root(
    template_id: str,
    data_root: str,
    variables: dict[str, str] | None = None,
    CLI_config=None,
) -> RunPreview:
    """What a template would resolve to against a data root, without creating anything.

    Answers the question a user actually has before running an ingestion: given
    this directory or this ``s3://`` prefix, which data collections will find
    their data, which will come up empty, and which variables did the run's own
    parameters decide. It resolves the template exactly as ``depictio run``
    would - same auto-detection, same conditionals, same pruning - and then
    counts each surviving DC's matches with the rule its scan will use.

    Every question is asked of the same :class:`DataRoot`, so a remote prefix
    costs one listing for the whole preview.

    Args:
        template_id: Template identifier, or a path to a template bundle.
        data_root: The directory or ``s3://`` prefix to preview.
        variables: ``--var`` values, exactly as ``resolve_template`` takes them.
        CLI_config: Used to build a remote root's S3 client.
    """
    root = as_data_root(data_root, CLI_config)
    if root is None:
        raise ValueError("preview_data_root needs a data root; got None")

    config, template_metadata, template_origin, dashboard_paths, resolved = resolve_template(
        template_id=template_id,
        data_root=root,
        extra_vars=dict(variables) if variables else None,
        CLI_config=CLI_config,
    )

    rows: list[DataCollectionPreview] = []
    detected_runs: list[str] = []
    present_tags = frozenset(
        dc.get("data_collection_tag") or ""
        for workflow in config.get("workflows") or []
        for dc in workflow.get("data_collections") or []
    )
    for workflow in config.get("workflows") or []:
        data_location = workflow.get("data_location") or {}
        runs: list[str] = []
        if data_location.get("structure") == "sequencing-runs" and data_location.get("runs_regex"):
            # One run directory per scan pass, the same way the walk scopes it.
            runs = root.runs(data_location["runs_regex"])
            detected_runs.extend(run for run in runs if run not in detected_runs)

        for dc in workflow.get("data_collections") or []:
            tag = dc.get("data_collection_tag") or ""
            dc_config = dc.get("config") or {}
            optional = bool(dc.get("optional"))
            # A materialized recipe DC has a scan block over its seed, so it is
            # previewed as what it now is: a file scan.
            if dc_config.get("source") == "transformed" and not dc_config.get("scan"):
                rows.append(_preview_recipe_dc(tag, dc_config, root, optional, present_tags))
            else:
                rows.append(_preview_scan_dc(tag, dc_config, root, runs, optional))

    pruned = [
        entry.data_collection_tag
        for entry in template_origin.expected_data_collections
        if not entry.included and entry.removal_reason == OPTIONAL_SOURCE_MISSING_REASON
    ]
    rows.extend(
        DataCollectionPreview(
            tag=tag, kind="scan", mode=None, location="", matched=0, optional=True, status="pruned"
        )
        for tag in pruned
    )

    return RunPreview(
        template_id=template_metadata.template_id,
        data_root=root.location,
        project_name=config.get("name") or "",
        resolved_variables={
            name: value
            for name, value in resolved.items()
            if name in _PREVIEW_VARIABLE_NAMES or name.startswith(_PREVIEW_FLAG_PREFIXES)
        },
        detected_runs=detected_runs,
        data_collections=rows,
        pruned_optional_dcs=pruned,
        dashboards=[path.name for path in dashboard_paths],
        truncated=root.truncated,
    )
