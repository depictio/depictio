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

import os
from dataclasses import dataclass, field
from fnmatch import translate
from pathlib import Path
from typing import Any, Literal

from depictio.cli.cli.utils.data_root import (
    DataRoot,
    LocalDataRoot,
    as_data_root,
    relative_to_root,
)
from depictio.cli.cli.utils.scan_utils import construct_full_regex
from depictio.cli.cli.utils.templates import (
    OPTIONAL_SOURCE_MISSING_REASON,
    _local_fallback_allowed,
    resolve_template,
)
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

# How many of the files a collection or a recipe source matched a row names.
# The counts always cover every match; only the names are capped.
PREVIEW_SAMPLES = 5


@dataclass
class RecipeSourcePreview:
    """What one entry of a recipe's ``SOURCES`` found under the data root.

    ``kind`` is ``collection`` for a ``dc_ref`` source (found when that
    collection settled), ``file`` for a glob or a path, and ``url`` for a URL
    outside the root, which is read at ingest and cannot be counted from here
    (``found`` is None). ``pattern`` is the glob or path the source is looked
    up with once the template's ``source_overrides`` apply, ``samples`` the
    first :data:`PREVIEW_SAMPLES` locations it found, and ``found_in`` the
    deepest folder holding all of them (see :func:`_common_folder`).
    """

    ref: str
    kind: Literal["file", "collection", "url"]
    pattern: str | None = None
    dc_ref: str | None = None
    optional: bool = False
    matched: int = 0
    samples: list[str] = field(default_factory=list)
    found: bool | None = None
    found_in: str | None = None


@dataclass
class RecipePreview:
    """The recipe a ``source: transformed`` collection is built with.

    ``name`` is the recipe as the template names it, ``summary`` the first
    line of its module docstring. ``sources`` is empty when the recipe names
    no module or its module fails to load.
    """

    name: str
    summary: str | None = None
    sources: list[RecipeSourcePreview] = field(default_factory=list)


@dataclass
class DataCollectionPreview:
    """What one data collection would find under a given data root.

    ``matched`` is a count taken with the rule the scan itself will use, so an
    ``empty`` row means the scan will genuinely find nothing, not that the
    preview looked somewhere else. Where nothing can be counted from the root -
    a manifest that is fetched at ingest, a URL on another host - the row is
    ``ok`` with ``matched`` 0 and ``location`` says where it points.

    ``rule`` is what a scanning collection looks for, as the template wrote it,
    ``samples`` the first :data:`PREVIEW_SAMPLES` locations it matched, and
    ``found_in`` the deepest folder holding every one it matched, not only
    the samples (see :func:`_common_folder`). A recipe collection has no rule:
    ``recipe`` says what it is built from.
    """

    tag: str
    kind: Literal["scan", "recipe"]
    mode: str | None  # scan mode, None for recipe DCs
    location: str  # what it looked at, human readable
    matched: int  # files found
    missing_sources: list[str] = field(default_factory=list)  # unresolvable recipe sources
    # The tags of the other collections among ``missing_sources`` (a required
    # dc_ref that did not settle), so a caller never reads them back from text.
    missing_collections: list[str] = field(default_factory=list)
    optional: bool = False
    status: PreviewStatus = "ok"
    rule: str | None = None
    samples: list[str] = field(default_factory=list)
    found_in: str | None = None
    recipe: RecipePreview | None = None


def _common_folder(relatives: list[str]) -> str | None:
    """The deepest folder holding every one of ``relatives``, paths relative to
    the root: ``""`` when one of them sits at its top, None for no path.

    Said of every match, not of the first few shown, so a search across the
    whole run folder can say where its files are (``hicpro/stats/``) without
    naming the folder of the first sample alone.
    """
    common: list[str] | None = None
    for relative in relatives:
        folder = relative.strip("/").split("/")[:-1]
        if common is None:
            common = folder
            continue
        depth = 0
        while depth < min(len(common), len(folder)) and common[depth] == folder[depth]:
            depth += 1
        common = common[:depth]
    return None if common is None else "/".join(common)


@dataclass
class RunPreview:
    """What DATA_DIR would actually yield, before anything is created."""

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
                tag=tag,
                kind="scan",
                mode=mode,
                location=location,
                matched=0,
                optional=optional,
                rule=location or None,
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
            rule=location,
            samples=[root.url(relative)] if found else [],
        )

    if mode == "manifest":
        # The manifest is fetched at ingest, not here: its entries are not
        # visible from the data root's listing.
        manifest_url = parameters.get("manifest_url") or ""
        return DataCollectionPreview(
            tag=tag,
            kind="scan",
            mode=mode,
            location=manifest_url,
            matched=0,
            optional=optional,
            rule=manifest_url or None,
        )

    if mode in ("recursive", "s3_prefix"):
        regex = _scan_match_regex(mode, parameters)
        if mode == "recursive":
            rule = (parameters.get("regex_config") or {}).get("pattern")
        else:
            rule = parameters.get("pattern")
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
                    rule=rule,
                )
            within = relative
        # One pass per run directory when the workflow has them, the way the
        # scan itself scopes its walk; otherwise a single pass over the root.
        scopes = [f"{run}/{within}".strip("/") for run in runs] if runs else [within]
        matched = 0
        samples: list[str] = []
        every_hit: list[str] = []
        for scope in scopes:
            hits = root.match(regex, within=scope)
            matched += len(hits)
            every_hit.extend(hits)
            samples.extend(root.url(rel) for rel in hits[: PREVIEW_SAMPLES - len(samples)])
        return DataCollectionPreview(
            tag=tag,
            kind="scan",
            mode=mode,
            location=location,
            matched=matched,
            optional=optional,
            status="ok" if matched else "empty",
            rule=rule,
            samples=samples,
            found_in=_common_folder(every_hit),
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


def _docstring_summary(module: Any) -> str | None:
    """The first non-empty line of ``module``'s docstring, or None without one."""
    doc = getattr(module, "__doc__", None)
    if not isinstance(doc, str):
        return None
    return next((line.strip() for line in doc.splitlines() if line.strip()), None)


def _preview_recipe_dc(
    tag: str,
    dc_config: dict,
    root: DataRoot,
    optional: bool,
    settled_tags: frozenset[str] = frozenset(),
    pipeline_version: str | None = None,
) -> DataCollectionPreview:
    """One row for a ``source: transformed`` DC, resolved through its recipe's SOURCES.

    The recipe is loaded the way ingestion loads it, with the version of the
    pipeline its workflow names (``pipeline_version``), so a recipe kept in a
    version folder (``<pipeline>/<version>/recipes/``) is found here too.

    ``matched`` counts inputs found, not files: a ``dc_ref`` source is satisfied
    by another collection's table, so it counts when that collection is in
    ``settled_tags``, the ones already known to find their own inputs. Without
    this every canonical that only reads other tables previewed as "0 files",
    indistinguishable from a collection whose inputs are genuinely absent; and
    counting a mere presence in the project would make a prefix at the wrong
    level look partly matched through collections that will never be written.
    A required ``dc_ref`` that is not settled is reported missing by name.

    ``recipe`` describes each source as it was looked up (see
    :class:`RecipeSourcePreview`).
    """
    transform = dc_config.get("transform") or {}
    recipe_name = transform.get("recipe") or ""
    # "empty" until proven otherwise: a recipe that names no module, or whose
    # module fails to load, has found nothing and must not settle a dc_ref.
    row = DataCollectionPreview(
        tag=tag,
        kind="recipe",
        mode=None,
        location=root.url(""),
        matched=0,
        optional=optional,
        status="empty",
        recipe=RecipePreview(name=recipe_name),
    )
    if not recipe_name:
        return row

    try:
        from depictio.recipes import load_recipe

        module = load_recipe(recipe_name, pipeline_version)
    except Exception as exc:  # noqa: BLE001 - a preview never fails the run
        logger.warning(f"Preview: could not load recipe '{recipe_name}' for '{tag}': {exc}")
        return row

    recipe = RecipePreview(name=recipe_name, summary=_docstring_summary(module))
    row.recipe = recipe
    overrides = transform.get("source_overrides") or {}
    # A URL outside the root is read as it is at ingest, so it cannot be
    # counted from here, and must not be reported missing either.
    uncounted = False
    for source in module.SOURCES:
        if source.dc_ref is not None:
            settled = source.dc_ref in settled_tags
            if settled:
                row.matched += 1
            elif not source.optional:
                row.missing_sources.append(f"collection '{source.dc_ref}'")
                row.missing_collections.append(source.dc_ref)
            recipe.sources.append(
                RecipeSourcePreview(
                    ref=source.ref,
                    kind="collection",
                    dc_ref=source.dc_ref,
                    optional=source.optional,
                    matched=1 if settled else 0,
                    found=settled,
                )
            )
            continue
        override = overrides.get(source.ref)
        glob_pattern = _override_binding(override, "glob_pattern")
        path = _override_binding(override, "path")
        if glob_pattern is None and path is None:
            glob_pattern, path = source.glob_pattern, source.path

        samples: list[str] = []
        found_in: str | None = None
        if glob_pattern:
            globbed = root.glob(glob_pattern)
            hits = len(globbed)
            samples = [root.url(rel) for rel in globbed[:PREVIEW_SAMPLES]]
            found_in = _common_folder(globbed)
        elif path:
            # The recipe layer's own rule (``resolve_sources``): a location
            # under the root is looked up in it, one outside it as it is.
            relative = relative_to_root(root, path)
            if relative is not None:
                hits = 1 if root.exists(relative) else 0
                samples = [root.url(relative)] if hits else []
                found_in = _common_folder([relative]) if hits else None
            elif "://" in path:
                uncounted = True
                recipe.sources.append(
                    RecipeSourcePreview(
                        ref=source.ref, kind="url", pattern=path, optional=source.optional
                    )
                )
                continue
            else:
                found = _local_fallback_allowed(root, path) and Path(path).is_file()
                hits = 1 if found else 0
                samples = [path] if found else []
        else:
            continue
        row.matched += hits
        if not hits and not source.optional:
            row.missing_sources.append(glob_pattern or path or source.ref)
        recipe.sources.append(
            RecipeSourcePreview(
                ref=source.ref,
                kind="file",
                pattern=glob_pattern or path,
                optional=source.optional,
                matched=hits,
                samples=samples,
                found=hits > 0,
                found_in=found_in,
            )
        )

    if row.missing_sources:
        row.status = "missing"
    elif row.matched or uncounted:
        row.status = "ok"
    else:
        row.status = "empty"
    return row


def _workflow_root(workflow: dict, root: DataRoot) -> DataRoot:
    """The root a workflow's walk and its recipes read: ``root``, unless the
    workflow's ``data_location`` names another local folder.

    A local ``--bind`` moves the walk of its whole workflow to the folder it
    names (``bindings.apply_bindings``), and ingestion then walks that folder
    and runs the workflow's recipes against it, so the preview counts there
    too. A folder below ``root`` is a view of it; one outside it is looked at
    only where any location outside the root may be (``_local_fallback_allowed``).
    No location, several, a URL or a placeholder: ``root``.
    """
    locations = (workflow.get("data_location") or {}).get("locations") or []
    if len(locations) != 1:
        return root
    location = str(locations[0])
    if "://" in location or not os.path.isabs(location):
        return root
    relative = root.relative_of(location)
    if relative is not None:
        return root.scoped(relative)
    if not _local_fallback_allowed(root, location):
        return root
    return LocalDataRoot(location, root.CLI_config)


def _scan_root(dc_config: dict, workflow_root: DataRoot, root: DataRoot) -> DataRoot:
    """The root a scanning collection's location is judged against.

    A ``single`` or ``url`` collection names its own location: a bind that
    moved its workflow's walk did not move it, so a location the workflow
    root does not hold is judged against the data root, where a file that is
    gone is still reported missing. Every other scan walks the workflow root.
    """
    scan = dc_config.get("scan") or {}
    if workflow_root is root or str(scan.get("mode") or "").lower() not in ("single", "url"):
        return workflow_root
    parameters = scan.get("scan_parameters") or {}
    location = parameters.get("filename") or parameters.get("url") or ""
    if location and workflow_root.relative_of(location) is None:
        return root
    return workflow_root


def preview_data_collections(
    config: dict, root: DataRoot
) -> tuple[list[DataCollectionPreview], list[str]]:
    """One row per data collection of ``config`` under ``root``, and the run directories found.

    ``config`` is anything with the project shape (``workflows``, each with
    its ``data_collections``): a template ``resolve_template`` just resolved,
    or a project stored from one, whose collections are the resolved ones.
    So the same folder gets the same rows whichever of the two is asked, which
    is what lets a refresh decide exactly as the creation did.

    A workflow whose ``data_location`` a local ``--bind`` moved is counted in
    the folder it now walks (see :func:`_workflow_root`).

    Pruned collections are not in ``config`` at all, so they have no row here.
    """
    rows: list[DataCollectionPreview] = []
    detected_runs: list[str] = []
    recipe_slots: list[tuple[int, str, dict, bool, DataRoot, str | None]] = []
    for workflow in config.get("workflows") or []:
        workflow_root = _workflow_root(workflow, root)
        # Ingestion loads a recipe with its workflow's version: so does the preview.
        version = workflow.get("version") or None
        data_location = workflow.get("data_location") or {}
        runs: list[str] = []
        if data_location.get("structure") == "sequencing-runs" and data_location.get("runs_regex"):
            # One run directory per scan pass, the same way the walk scopes it.
            runs = workflow_root.runs(data_location["runs_regex"])
            detected_runs.extend(run for run in runs if run not in detected_runs)

        for dc in workflow.get("data_collections") or []:
            tag = dc.get("data_collection_tag") or ""
            dc_config = dc.get("config") or {}
            optional = bool(dc.get("optional"))
            # A materialized recipe DC has a scan block over its seed, so it is
            # previewed as what it now is: a file scan.
            if dc_config.get("source") == "transformed" and not dc_config.get("scan"):
                recipe_slots.append((len(rows), tag, dc_config, optional, workflow_root, version))
                rows.append(
                    _preview_recipe_dc(
                        tag, dc_config, workflow_root, optional, pipeline_version=version
                    )
                )
            else:
                scan_root = _scan_root(dc_config, workflow_root, root)
                rows.append(_preview_scan_dc(tag, dc_config, scan_root, runs, optional))

    # Recipes chain through dc_ref (a canonical reads the table another recipe
    # writes), so recipe rows are re-evaluated until no further collection
    # settles. Settling is monotone and the references form a DAG, so this
    # ends within the depth of the longest chain.
    settled = frozenset(row.tag for row in rows if row.status == "ok")
    while True:
        for index, tag, dc_config, optional, workflow_root, version in recipe_slots:
            rows[index] = _preview_recipe_dc(
                tag, dc_config, workflow_root, optional, settled, pipeline_version=version
            )
        now_settled = frozenset(row.tag for row in rows if row.status == "ok")
        if now_settled == settled:
            break
        settled = now_settled
    return rows, detected_runs


def preview_data_root(
    template_id: str,
    data_root: str | DataRoot,
    variables: dict[str, str] | None = None,
    CLI_config=None,
    resolution: tuple | None = None,
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
        resolution: What a ``resolve_template`` call already returned, possibly
            changed since (``depictio ingest --bind`` rebinds collections in
            it). Previewed as it is instead of resolving the template again,
            so the preview shows the configuration the run will use.
    """
    root = as_data_root(data_root, CLI_config)
    if root is None:
        raise ValueError("preview_data_root needs a data root; got None")

    if resolution is None:
        resolution = resolve_template(
            template_id=template_id,
            data_root=root,
            extra_vars=dict(variables) if variables else None,
            CLI_config=CLI_config,
        )
    config, template_metadata, template_origin, dashboard_paths, resolved = resolution

    rows, detected_runs = preview_data_collections(config, root)

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
