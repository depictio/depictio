"""
Template resolver for depictio-cli.

Handles loading template project.yaml files, substituting {DATA_ROOT} variables,
and producing resolved config dicts ready for Project model validation.

Usage:
    resolved = resolve_template("nf-core/ampliseq/2.16.0", "/path/to/data")
"""

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from depictio.cli.cli_logging import logger
from depictio.models.models.templates import (
    DCOverride,
    ExpectedDataCollection,
    ProvenanceEntry,
    ProvenanceGroupRule,
    ProvenanceSource,
    ProvenanceSpec,
    TemplateConditional,
    TemplateMetadata,
    TemplateOrigin,
)

_TEMPLATE_VAR_RE = re.compile(r"\{([A-Z0-9_]+)\}")

# A template version directory: purely numeric dotted segments (e.g. "2.16.0").
_VERSION_DIR_RE = re.compile(r"^\d+(\.\d+)*$")


def latest_template_version(pipeline_dir: Path) -> str | None:
    """Highest numeric version subdirectory of ``pipeline_dir`` holding a template YAML.

    Returns e.g. ``"2.16.0"`` for ``depictio/projects/nf-core/ampliseq/``, or None
    when the directory has no versioned template subdirectories.
    """
    if not pipeline_dir.is_dir():
        return None
    versions = [
        d.name
        for d in pipeline_dir.iterdir()
        if d.is_dir()
        and _VERSION_DIR_RE.match(d.name)
        and any((d / f).is_file() for f in ("template.yaml", "project.yaml"))
    ]
    if not versions:
        return None
    return max(versions, key=lambda v: tuple(int(p) for p in v.split(".")))


def _resolve_template_id_in(projects_dir: Path, template_id: str) -> str:
    """Resolve ``latest`` / version-less template ids against one projects root.

    ``nf-core/ampliseq/latest`` and ``nf-core/ampliseq`` both resolve to the
    highest version directory that ships a template YAML (e.g.
    ``nf-core/ampliseq/2.16.0``). Ids that already point at a concrete template
    directory pass through untouched.
    """
    parts = [p for p in template_id.split("/") if p]
    if parts and parts[-1] == "latest":
        version = latest_template_version(projects_dir / Path(*parts[:-1]))
        if version:
            return "/".join([*parts[:-1], version])
        return template_id
    template_dir = projects_dir / Path(*parts) if parts else projects_dir
    if not any((template_dir / f).is_file() for f in ("template.yaml", "project.yaml")):
        version = latest_template_version(template_dir)
        if version:
            return "/".join([*parts, version])
    return template_id


def _load_yaml(path: str) -> dict:
    """Load a YAML file and return its contents as a dict."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML file: expected a dictionary in {path}")
    return data


class TemplateNotFoundError(FileNotFoundError):
    """No template YAML for ``template_id``.

    Carries the catalogue separately from the message so API callers can be
    told what exists without being shown the server's filesystem layout.
    """

    def __init__(self, message: str, template_id: str, available_templates: list[str]):
        super().__init__(message)
        self.template_id = template_id
        self.available_templates = available_templates


def _is_cli_context() -> bool:
    """True inside the depictio CLI process (it sets ``DEPICTIO_CONTEXT=CLI``)."""
    from depictio.models.utils import get_depictio_context

    return get_depictio_context().lower() == "cli"


def _locate_template_path(template_id: str) -> Path | None:
    """The path form: ``template_id`` names an existing directory or YAML file.

    Returns None when it names neither (the id form is tried next). A
    directory that exists but holds no template YAML is an error rather than
    a fall-through, since falling back to the catalogue would only confuse.
    """
    candidate_path = Path(template_id).expanduser()
    if candidate_path.is_file() and candidate_path.suffix in (".yaml", ".yml"):
        return candidate_path.resolve()
    if candidate_path.is_dir():
        for filename in ("template.yaml", "project.yaml"):
            candidate = candidate_path / filename
            if candidate.is_file():
                return candidate.resolve()
        raise FileNotFoundError(
            f"Directory '{template_id}' holds no template.yaml or project.yaml. "
            "Point --template at the directory produced by `depictio template export`."
        )
    return None


def _template_dir_within(projects_dir: Path, template_id: str) -> Path | None:
    """``projects_dir/<resolved id>``, or None when the id would leave ``projects_dir``.

    Ids reach here from API callers (``POST /projects/from_manifest``) as well
    as the CLI, so the candidate is resolved (symlinks included) and checked
    for containment instead of being trusted as a plain relative id. Dot
    segments are refused up front so nothing outside the directory is even
    stat'ed while resolving ``latest``.
    """
    parts = [p for p in template_id.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        return None
    root = projects_dir.resolve()
    candidate = (root / _resolve_template_id_in(root, template_id)).resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


def locate_template(template_id: str) -> Path:
    """Find template YAML by template_id (e.g., 'nf-core/ampliseq/2.16.0') or by path.

    Searches in the depictio/projects/ directory relative to the package installation.
    Looks for template.yaml first (dedicated template file), then falls back to
    project.yaml (for backwards compatibility).

    The version segment may be ``latest`` or omitted entirely
    (``nf-core/ampliseq/latest`` / ``nf-core/ampliseq``): both resolve to the
    highest version directory shipping a template, so callers never need to
    hardcode a pinned version.

    In the CLI a local directory or YAML file is also accepted. That is what
    makes an exported bundle usable by whoever receives it: ``depictio template
    export`` produces a directory, and without this the recipient would have to
    copy it into their own site-packages before it could be run. The server
    never accepts the path form: it resolves ids on behalf of remote callers,
    and a path there would let any request read an arbitrary YAML on the host.
    Ids are confined to the templates directory in both contexts.

    Args:
        template_id: Template identifier (e.g., 'nf-core/ampliseq/2.16.0'), or,
            on the CLI, a path to a template directory / YAML file.

    Returns:
        Path to the template YAML file.

    Raises:
        FileNotFoundError: If no template YAML exists (``TemplateNotFoundError``
            for an unknown or out-of-tree id).
    """
    # Path form first: an existing directory or YAML file wins over id lookup, so
    # a local bundle is never shadowed by an installed template of the same name.
    if _is_cli_context():
        located = _locate_template_path(template_id)
        if located is not None:
            return located

    # Resolve relative to depictio package root, then without the package
    # nesting (installed packages). template.yaml (dedicated template file)
    # is preferred over project.yaml (fixture) in each.
    package_root = Path(__file__).resolve().parents[4]  # cli/cli/utils/ -> depictio/
    projects_dir = package_root / "depictio" / "projects"
    alt_projects_dir = Path(__file__).resolve().parents[3] / "projects"  # cli/cli/utils/ -> cli/
    for root in (projects_dir, alt_projects_dir):
        template_dir = _template_dir_within(root, template_id)
        if template_dir is None:
            continue
        for filename in ("template.yaml", "project.yaml"):
            candidate = template_dir / filename
            if candidate.is_file():
                return candidate

    available = _list_available_templates(package_root)
    available_str = ", ".join(available) if available else "none found"
    raise TemplateNotFoundError(
        f"Template '{template_id}' not found under {projects_dir}. "
        f"Available templates: {available_str}",
        template_id=template_id,
        available_templates=available,
    )


def _list_available_templates(package_root: Path) -> list[str]:
    """List available template IDs by scanning the projects directory.

    Args:
        package_root: Root of the depictio package.

    Returns:
        List of template ID strings.
    """
    projects_dir = package_root / "depictio" / "projects"
    templates: list[str] = []

    if not projects_dir.is_dir():
        return templates

    for pattern in ("template.yaml", "project.yaml"):
        for yaml_path in projects_dir.rglob(pattern):
            try:
                config = _load_yaml(str(yaml_path))
                if "template" in config:
                    template_id = config["template"].get("template_id", "")
                    if template_id and template_id not in templates:
                        templates.append(template_id)
            except Exception:
                continue

    return sorted(templates)


def substitute_template_variables(config: Any, variables: dict[str, str]) -> Any:
    """Recursively substitute {VAR_NAME} placeholders in config dict/list/str.

    Uses the same {VAR_NAME} pattern as WorkflowDataLocation env var expansion,
    but resolves from an explicit variables dict rather than os.environ.

    Args:
        config: Configuration structure (dict, list, or string).
        variables: Mapping of variable names to values (e.g., {"DATA_ROOT": "/path"}).

    Returns:
        Config with all placeholders resolved.

    Raises:
        ValueError: If a required variable placeholder has no corresponding value.
    """
    if isinstance(config, dict):
        return {k: substitute_template_variables(v, variables) for k, v in config.items()}
    elif isinstance(config, list):
        return [substitute_template_variables(item, variables) for item in config]
    elif isinstance(config, str):
        matches = _TEMPLATE_VAR_RE.findall(config)
        result = config
        for match in matches:
            if match in variables:
                result = result.replace(f"{{{match}}}", variables[match])
            else:
                logger.warning(f"Variable '{match}' not provided for placeholder in: {config}")
        return result
    else:
        return config


def _prune_missing_optional_single_file_dcs(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Drop optional single-file DCs whose (already-substituted) file is absent.

    The Project model validates single-file (``scan.mode == "single"``) DCs by
    checking the file exists. Some pipeline outputs are produced only by certain
    sub-workflows (e.g. the QIIME2 phylogenetic tree is absent for ITS / IonTorrent
    / multi-region ampliseq runs). When such a DC is flagged ``optional: true`` and
    its file is missing, prune it (and any links referencing it) so the run ingests
    everything else instead of failing validation outright.

    Scoped deliberately: only DCs that are BOTH ``optional`` AND single-file scans
    are considered. Required DCs and recipe/glob DCs are left untouched so genuine
    gaps still raise.
    """
    removed: set[str] = set()
    for workflow in config.get("workflows", []):
        for dc in workflow.get("data_collections", []):
            if not dc.get("optional"):
                continue
            scan = dc.get("config", {}).get("scan", {})
            if scan.get("mode") != "single":
                continue
            filename = scan.get("scan_parameters", {}).get("filename")
            if filename and not Path(filename).is_file():
                removed.add(dc["data_collection_tag"])

    if removed:
        for workflow in config.get("workflows", []):
            workflow["data_collections"] = [
                dc
                for dc in workflow.get("data_collections", [])
                if dc.get("data_collection_tag") not in removed
            ]
        config["links"] = [
            link
            for link in config.get("links", [])
            if link.get("source_dc_tag") not in removed and link.get("target_dc_tag") not in removed
        ]
    return config, sorted(removed)


def prune_links_for_tags(config: dict[str, Any], tags: set[str]) -> None:
    """Drop every link whose source or target is one of ``tags``. In place.

    Removing a DC without removing the links that name it leaves the config
    referencing a collection that no longer exists, so the two always move
    together.
    """
    if not tags:
        return
    config["links"] = [
        link
        for link in config.get("links", [])
        if link.get("source_dc_tag") not in tags and link.get("target_dc_tag") not in tags
    ]


def materialize_recipe_seeds(
    config: dict[str, Any],
    data_root: str,
    *,
    drop_missing: bool,
) -> tuple[list[str], list[str]]:
    """Rewrite ``source: transformed`` DCs into file scans over pre-computed seeds.

    A reference template ships the output of each of its recipes as a committed
    ``{data_root}/{dc_tag}.tsv``. When that seed is present the recipe is
    short-circuited entirely: the ``transform`` block is flagged ``materialized``
    and the DC gains a single-file scan of the seed. This is what makes a bundled
    project ingestible from its own directory even though it does not ship the
    recipes' raw inputs.

    Shared by the boot-time reference seeding (``resolve_template_for_init``) and
    the CLI's ``--template`` path so the two cannot drift. The seed always wins
    over the recipe, which keeps both producers byte-identical.

    Args:
        config: Resolved project config dict. Modified in place.
        data_root: Absolute path the seed convention is resolved against.
        drop_missing: What to do with a recipe DC that has no seed. ``True``
            removes it (and its links) — the init behaviour, where one missing
            seed would otherwise abort the whole workflow scan. ``False`` leaves
            it untouched so its recipe runs normally — the CLI behaviour.

    Returns:
        ``(materialized_tags, missing_seed_tags)``, both sorted.
    """
    materialized: list[str] = []
    missing: set[str] = set()

    for workflow in config.get("workflows", []):
        surviving = []
        for dc in workflow.get("data_collections", []):
            dc_config = dc.get("config", {})
            if dc_config.get("source") != "transformed" or not isinstance(
                dc_config.get("transform"), dict
            ):
                surviving.append(dc)
                continue

            dc_tag = dc["data_collection_tag"]
            # Convention: pre-computed files are named {dc_tag}.tsv
            seed_path = str(Path(data_root) / f"{dc_tag}.tsv")
            if not Path(seed_path).exists():
                if drop_missing:
                    missing.add(dc_tag)
                    logger.warning(
                        f"Seed resolver: skipping recipe DC '{dc_tag}' — "
                        f"pre-computed seed not found at {seed_path}"
                    )
                    continue
                # No seed and the caller wants the recipe: leave the DC exactly
                # as the template declared it.
                surviving.append(dc)
                continue

            # Keep ``source: transformed`` AND the ``transform`` block on the DC so
            # the React viewer (data-source info card, admin panel, builder
            # dropdown) surfaces the lineage — the data IS the output of a recipe,
            # just materialised as a seed file rather than computed at scan time.
            # ``materialized`` marks it as already computed: consumers must not
            # re-run the recipe (see deltatables.process_data_collection) and must
            # not try to resolve its raw SOURCES, which are absent from a seed.
            # The catalog compose endpoint matches a collection to a catalog
            # output on ``transform.recipe``, so dropping the block here would
            # make every seeded recipe DC invisible to the catalog picker.
            dc_config["transform"]["materialized"] = True
            dc_config["scan"] = {
                "mode": "single",
                "scan_parameters": {"filename": seed_path},
            }
            # Bundled recipe seeds are tab-separated by convention
            # ({data_root}/{dc_tag}.tsv). The template's original
            # `dc_specific_properties.format` describes the recipe's *input*
            # source (e.g. summary_metrics consumes a real CSV from multiqc),
            # which is irrelevant once we've replaced the recipe with a file
            # scan. Force the seed format to TSV so polars uses the right
            # separator — otherwise a CSV-declared, TSV-bundled DC parses the
            # whole tab-row as one column.
            dc_specific = dc_config.get("dc_specific_properties") or {}
            dc_specific["format"] = "tsv"
            dc_config["dc_specific_properties"] = dc_specific
            materialized.append(dc_tag)
            logger.debug(f"Seed resolver: converted recipe DC '{dc_tag}' → file scan: {seed_path}")
            surviving.append(dc)

        workflow["data_collections"] = surviving

    prune_links_for_tags(config, missing)
    return sorted(materialized), sorted(missing)


def _collect_dc_superset(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Snapshot every DC across all workflows as {tag, type, optional}.

    Captured before any conditional/missing-file pruning so the expected-DC manifest
    records the full template superset (substitution does not add/remove DCs, so the
    timing within resolution is not sensitive).
    """
    superset: list[dict[str, Any]] = []
    seen: set[str] = set()
    for workflow in config.get("workflows", []):
        for dc in workflow.get("data_collections", []):
            tag = dc.get("data_collection_tag")
            if not tag or tag in seen:
                continue
            seen.add(tag)
            superset.append(
                {
                    "data_collection_tag": tag,
                    "type": dc.get("config", {}).get("type"),
                    "optional": bool(dc.get("optional", False)),
                }
            )
    return superset


def _build_expected_dcs(
    superset: list[dict[str, Any]],
    final_config: dict[str, Any],
    removal_reasons: dict[str, str],
) -> list[ExpectedDataCollection]:
    """Combine the pre-pruning DC superset with what survived into the final config.

    Each entry is marked ``included`` (still present after all pruning) with a
    ``removal_reason`` for excluded DCs. Used to populate
    ``TemplateOrigin.expected_data_collections``.
    """
    surviving: set[str] = {
        dc.get("data_collection_tag")
        for workflow in final_config.get("workflows", [])
        for dc in workflow.get("data_collections", [])
    }
    expected: list[ExpectedDataCollection] = []
    for entry in superset:
        tag = entry["data_collection_tag"]
        included = tag in surviving
        expected.append(
            ExpectedDataCollection(
                data_collection_tag=tag,
                type=entry["type"],
                optional=entry["optional"],
                included=included,
                removal_reason=None if included else removal_reasons.get(tag),
            )
        )
    return expected


def _strip_ids(config: Any) -> Any:
    """Remove hardcoded 'id' fields from config so fresh IDs are generated.

    Template project.yaml may contain example IDs that should not be reused
    when a new project is instantiated from the template.

    Args:
        config: Project config dict.

    Returns:
        Config with 'id' fields removed at all levels.
    """
    if isinstance(config, dict):
        return {k: _strip_ids(v) for k, v in config.items() if k != "id"}
    elif isinstance(config, list):
        return [_strip_ids(item) for item in config]
    else:
        return config


def _apply_conditionals(
    config: dict[str, Any],
    conditionals: list[TemplateConditional],
    provided_vars: set[str],
    template_dir: Path,
    variables: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    """Apply conditional rules based on which optional variables were provided.

    For each conditional that fires:
    - Removes DCs listed in remove_dc_tags from all workflows
    - Prunes links whose source_dc_tag or target_dc_tag references a removed DC
    - Repoints surviving DCs listed in override_dcs at the route's file layout
    - Overrides the active dashboard list

    Args:
        config: Resolved project config dict (modified in place).
        conditionals: List of conditional rules from template metadata.
        provided_vars: Set of variable names actually provided by the user.
        template_dir: Template directory for resolving dashboard paths.
        variables: Variable map, for the placeholders an override may carry.
            Conditionals run *after* the config-wide substitution pass, so an
            override written as `scan_filename: "{TREE_FILE}"` would otherwise
            reach the DC verbatim and read as a path that does not exist.

    Returns:
        Tuple of (modified_config, active_dashboard_rel_paths, removal_reasons),
        where removal_reasons maps each removed DC tag to a human-readable reason
        (used to build the project's expected-DC manifest).
    """
    removed_dc_tags: set[str] = set()
    removal_reasons: dict[str, str] = {}
    active_dashboards: list[str] = []
    overrides_by_tag: dict[str, Any] = {}

    for rule in conditionals:
        fires = False
        reason = ""
        if rule.if_var_absent and rule.if_var_absent not in provided_vars:
            fires = True
            reason = f"gated: {rule.if_var_absent} absent (if_var_absent)"
        elif rule.if_var_present and rule.if_var_present in provided_vars:
            fires = True
            reason = f"gated: {rule.if_var_present} present (if_var_present)"

        if not fires:
            continue

        # Collect DC tags to remove
        for tag in rule.remove_dc_tags:
            removed_dc_tags.add(tag)
            removal_reasons.setdefault(tag, reason)
            logger.info(f"Conditional rule: removing DC tag '{tag}'")

        # Collect DC source-binding overrides (last-write-wins per tag).
        # Resolved through the variable map first: the rule fires on a variable
        # being present, so pointing the DC at that variable's value is the
        # natural thing to write, and every override field can hold a path.
        for ov in rule.override_dcs:
            if variables:
                ov = DCOverride(**substitute_template_variables(ov.model_dump(), variables))
            overrides_by_tag[ov.data_collection_tag] = ov
            logger.info(f"Conditional rule: overriding DC source '{ov.data_collection_tag}'")

        # Override active dashboards. Multiple firing rules are last-write-wins;
        # warn if a later rule replaces a *different* selection so a future
        # multi-dashboard template (e.g. per-protocol variants) can't silently
        # pick the wrong one based on rule order.
        if rule.dashboards:
            if active_dashboards and active_dashboards != rule.dashboards:
                logger.warning(
                    f"Conditional dashboards override: {active_dashboards} → {rule.dashboards} "
                    f"(rule {rule.if_var_present or rule.if_var_absent})"
                )
            active_dashboards = rule.dashboards
            logger.info(f"Conditional rule: using dashboards {rule.dashboards}")

    # Remove DCs from all workflows
    if removed_dc_tags:
        for workflow in config.get("workflows", []):
            dcs = workflow.get("data_collections", [])
            original_count = len(dcs)
            workflow["data_collections"] = [
                dc for dc in dcs if dc.get("data_collection_tag") not in removed_dc_tags
            ]
            removed_count = original_count - len(workflow["data_collections"])
            if removed_count:
                logger.info(
                    f"Workflow '{workflow.get('name')}': removed {removed_count} DC(s) "
                    f"({', '.join(removed_dc_tags)})"
                )

        # Prune links referencing removed DCs
        surviving_links = []
        for link in config.get("links", []):
            src = link.get("source_dc_tag", "")
            tgt = link.get("target_dc_tag", "")
            if src in removed_dc_tags or tgt in removed_dc_tags:
                logger.info(f"Pruning link {src} → {tgt} (references removed DC)")
            else:
                surviving_links.append(link)
        config["links"] = surviving_links

    # Repoint surviving DCs at the route's file layout. Applied after removal so a
    # removed DC is never overridden; mutates the DC config in place so downstream
    # consumers (canonicals, dashboards) keep referencing the same tag.
    if overrides_by_tag:
        for workflow in config.get("workflows", []):
            for dc in workflow.get("data_collections", []):
                ov = overrides_by_tag.get(dc.get("data_collection_tag"))
                if ov is None:
                    continue
                cfg = dc.setdefault("config", {})
                if ov.scan_pattern is not None or ov.scan_filename is not None:
                    params = cfg.setdefault("scan", {}).setdefault("scan_parameters", {})
                    if ov.scan_pattern is not None:
                        params.setdefault("regex_config", {})["pattern"] = ov.scan_pattern
                    if ov.scan_filename is not None:
                        params["filename"] = ov.scan_filename
                if ov.format is not None:
                    cfg.setdefault("dc_specific_properties", {})["format"] = ov.format
                if ov.recipe is not None:
                    cfg.setdefault("transform", {})["recipe"] = ov.recipe
                if ov.source_overrides is not None:
                    so = cfg.setdefault("transform", {}).setdefault("source_overrides", {})
                    so.update(ov.source_overrides)
                logger.info(f"Repointed DC '{dc.get('data_collection_tag')}' for route")

    return config, active_dashboards, removal_reasons


def _file_exists_any(filepath: str, data_root: str) -> bool:
    """Check if a file exists, trying multiple resolution strategies.

    Tries: absolute path, relative to data_root, relative to CWD.
    """
    p = Path(filepath)
    if p.is_absolute():
        return p.exists()
    # Relative: try data_root first, then CWD
    return (Path(data_root) / p).exists() or p.exists()


def _check_dc_source_files(
    dc: dict[str, Any],
    data_root: str,
) -> str | None:
    """Check if a DC's source files exist. Return missing path or None if all OK.

    Unused: recipe DCs are handled by `materialize_recipe_seeds`, which
    short-circuits the recipe when a seed is present and otherwise leaves it to
    fail loudly at processing time. Kept — with `_remove_dcs_with_missing_files`
    and `_log_removal_report` — pending a decision on whether to wire up
    source-existence pruning or delete the three of them.
    """
    config = dc.get("config", {})
    source = config.get("source")

    if source == "transformed":
        # Recipe DC: load recipe, check SOURCES paths (with source_overrides)
        transform = config.get("transform", {})
        recipe_name = transform.get("recipe")
        if not recipe_name:
            return None
        try:
            from depictio.recipes import load_recipe

            module = load_recipe(recipe_name)
            overrides = {}
            if transform.get("source_overrides"):
                overrides = {
                    ref: so.get("path", "") if isinstance(so, dict) else so
                    for ref, so in transform["source_overrides"].items()
                }
            for src in module.SOURCES:
                if src.dc_ref is not None:
                    continue  # dc_ref sources checked via cascade
                if src.optional:
                    continue
                rel_path = overrides.get(src.ref, src.path)
                if rel_path and not _file_exists_any(rel_path, data_root):
                    return rel_path
        except Exception as exc:
            logger.warning(f"Could not validate recipe '{recipe_name}': {exc}")
            return None  # Don't remove on recipe load failure
    else:
        # Scan-based DC: check filename or regex pattern
        scan = config.get("scan", {})
        params = scan.get("scan_parameters", {})
        filename = params.get("filename")
        if filename:
            if not _file_exists_any(filename, data_root):
                return str(filename)
        regex = params.get("regex_config", {}).get("pattern")
        if regex and not any(c in regex for c in r".*+?[](){}|^$\\"):
            # Literal path (no regex metacharacters)
            if not _file_exists_any(regex, data_root):
                return regex

    return None


def _remove_dcs_with_missing_files(
    config: dict[str, Any],
    data_root: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Scan DCs for missing source files and auto-remove them.

    Also cascades removal for DCs whose dc_ref dependencies were removed.

    Args:
        config: Resolved project config dict (modified in place).
        data_root: Absolute path to data root directory.

    Returns:
        Tuple of (modified_config, removal_report).
    """
    removal_report: list[dict[str, str]] = []
    removed_tags: set[str] = set()

    # Pass 1: Check file existence for each DC
    for workflow in config.get("workflows", []):
        for dc in workflow.get("data_collections", []):
            tag = dc.get("data_collection_tag", "")
            missing = _check_dc_source_files(dc, data_root)
            if missing:
                removed_tags.add(tag)
                removal_report.append(
                    {
                        "tag": tag,
                        "reason": "source file not found",
                        "missing_path": missing,
                    }
                )

    # Pass 2: Cascade dc_ref removals (iterate until stable)
    changed = True
    while changed:
        changed = False
        for workflow in config.get("workflows", []):
            for dc in workflow.get("data_collections", []):
                tag = dc.get("data_collection_tag", "")
                if tag in removed_tags:
                    continue
                transform = dc.get("config", {}).get("transform", {})
                recipe_name = transform.get("recipe")
                if not recipe_name:
                    continue
                try:
                    from depictio.recipes import load_recipe

                    module = load_recipe(recipe_name)
                    for src in module.SOURCES:
                        if src.dc_ref and not src.optional and src.dc_ref in removed_tags:
                            removed_tags.add(tag)
                            removal_report.append(
                                {
                                    "tag": tag,
                                    "reason": f"depends on removed DC '{src.dc_ref}'",
                                    "missing_path": f"dc_ref:{src.dc_ref}",
                                }
                            )
                            changed = True
                            break
                except Exception:
                    pass

    # Remove DCs and prune links (same pattern as _apply_conditionals)
    if removed_tags:
        for workflow in config.get("workflows", []):
            dcs = workflow.get("data_collections", [])
            workflow["data_collections"] = [
                dc for dc in dcs if dc.get("data_collection_tag") not in removed_tags
            ]

        surviving_links = []
        for link in config.get("links", []):
            src = link.get("source_dc_tag", "")
            tgt = link.get("target_dc_tag", "")
            if src not in removed_tags and tgt not in removed_tags:
                surviving_links.append(link)
        config["links"] = surviving_links

    return config, removal_report


def _log_removal_report(report: list[dict[str, str]]) -> None:
    """Log a summary of auto-removed DCs with actionable messages."""
    if not report:
        return
    logger.warning(f"{len(report)} data collection(s) auto-removed (source files not found):")
    for entry in report:
        logger.warning(f"  • {entry['tag']}: {entry['missing_path']} ({entry['reason']})")
    logger.warning("Dashboard components referencing these will be excluded.")


# ---------------------------------------------------------------------------
# Run provenance collection
# ---------------------------------------------------------------------------

# Fallback when a template declares no `provenance:` block: nf-core pipelines
# all write pipeline_info/params*.json, so at minimum the run's parameters are
# captured, ungrouped. Templates refine this with their own sources/groups.
_DEFAULT_PROVENANCE_SPEC = ProvenanceSpec(
    sources=[
        ProvenanceSource(
            name="params",
            glob="pipeline_info/params*.json",
            format="json",
            pick="latest",
        ),
    ],
    groups=[ProvenanceGroupRule(group="Parameters", key_patterns=["*"])],
)

# Truncation guard for pathological values (a value is a scalar in practice;
# a nested structure that survives exclude_keys is compact-serialised).
_PROVENANCE_VALUE_MAX = 500


def _provenance_format_for(path: Path, declared: str) -> str:
    if declared != "auto":
        return declared
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in (".yml", ".yaml"):
        return "yaml"
    return "tsv"


def _flatten_provenance(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested mappings with dotted keys; everything else is a leaf."""
    if not isinstance(obj, dict):
        return {prefix or "value": obj}
    flat: dict[str, Any] = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            flat.update(_flatten_provenance(v, key))
        else:
            flat[key] = v
    return flat


def _parse_provenance_file(path: Path, fmt: str) -> dict[str, Any]:
    if fmt == "json":
        with open(path) as fh:
            return _flatten_provenance(json.load(fh))
    if fmt == "yaml":
        with open(path) as fh:
            return _flatten_provenance(yaml.safe_load(fh) or {})
    # tsv: two-column key<TAB>value (extra columns ignored); '#' comments skipped
    flat: dict[str, Any] = {}
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t") if "\t" in line else line.split(",")
            if len(parts) >= 2:
                flat[parts[0].strip()] = parts[1].strip()
    return flat


def _stringify_provenance_value(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        try:
            out = json.dumps(v, separators=(",", ":"))
        except (TypeError, ValueError):
            out = str(v)
    else:
        out = str(v)
    return out if len(out) <= _PROVENANCE_VALUE_MAX else out[: _PROVENANCE_VALUE_MAX - 1] + "…"


def collect_run_provenance(
    data_root: str | None,
    spec: ProvenanceSpec | None,
    extra_files: list[str] | None = None,
) -> tuple[list[ProvenanceEntry], list[str]]:
    """Collect the run's parameters / thresholds / tool versions.

    Generic across pipelines: the template's ``ProvenanceSpec`` names the files
    (globs under DATA_ROOT) and how keys map to display groups; ``extra_files``
    (the ``--provenance-file`` CLI flag) lets a user add an arbitrary recap
    file. Completeness is the contract: every key of every parsed file becomes
    an entry unless an explicit ``exclude_keys`` glob drops it — keys no group
    rule matches land in 'Other', never on the floor.

    Returns (entries ordered by group appearance, list of files read).
    Best-effort: unreadable files are logged and skipped.
    """
    from fnmatch import fnmatch

    spec = spec or _DEFAULT_PROVENANCE_SPEC
    # Manifest-driven templates have no local run directory: only the explicit
    # --provenance-file entries can be collected, the spec's globs have no root.
    root = Path(data_root) if data_root is not None else None

    def assign_group(key: str, source: ProvenanceSource | None) -> str:
        if source is not None and source.group:
            return source.group
        for rule in spec.groups:
            if any(fnmatch(key, pat) for pat in rule.key_patterns):
                return rule.group
        return "Other"

    highlight = set(spec.highlight)
    collected: list[tuple[str, str, str, Any]] = []  # (source, group, key, value)
    files_read: list[str] = []

    for source in spec.sources if root is not None else []:
        matches = sorted(root.glob(source.glob))
        if not matches:
            # sequencing-runs layouts keep pipeline_info one level down
            matches = sorted(root.glob(f"*/{source.glob}"))
        if not matches:
            logger.info(f"Provenance source '{source.name}': no file matches {source.glob!r}")
            continue
        if source.pick == "latest":
            matches = matches[-1:]
        elif source.pick == "first":
            matches = matches[:1]
        merged: dict[str, Any] = {}
        for path in matches:
            try:
                merged.update(
                    _parse_provenance_file(path, _provenance_format_for(path, source.format))
                )
                try:
                    files_read.append(str(path.relative_to(root)))
                except ValueError:
                    files_read.append(str(path))
            except (OSError, ValueError, yaml.YAMLError) as e:
                logger.warning(f"Provenance source '{source.name}': failed to parse {path}: {e}")
        for key, value in merged.items():
            if any(fnmatch(key, pat) for pat in source.exclude_keys):
                continue
            collected.append((source.name, assign_group(key, source), key, value))

    for extra in extra_files or []:
        path = Path(extra).expanduser()
        if not path.is_file():
            logger.warning(f"--provenance-file: {path} not found, skipped")
            continue
        try:
            flat = _parse_provenance_file(path, _provenance_format_for(path, "auto"))
        except (OSError, ValueError, yaml.YAMLError) as e:
            logger.warning(f"--provenance-file: failed to parse {path}: {e}")
            continue
        files_read.append(str(path))
        for key, value in flat.items():
            collected.append(("user", "User provided", key, value))

    # Stable presentation order: groups in spec order (Other, then User provided,
    # last), keys alphabetical inside a group.
    group_order = {rule.group: i for i, rule in enumerate(spec.groups)}
    for source in spec.sources:
        if source.group is not None:
            group_order.setdefault(source.group, len(group_order))
    group_order.setdefault("Other", len(group_order))
    group_order.setdefault("User provided", len(group_order))

    collected.sort(key=lambda t: (group_order.get(t[1], len(group_order)), t[2]))
    entries = [
        ProvenanceEntry(
            source=src,
            group=group,
            key=key,
            value=_stringify_provenance_value(value),
            highlight=key in highlight,
        )
        for src, group, key, value in collected
    ]
    if entries:
        logger.info(
            f"Collected {len(entries)} run-provenance entries from "
            f"{len(files_read)} file(s): {', '.join(files_read)}"
        )
    return entries, files_read


def _introspect_pipeline_params(data_root: str, variables: dict[str, str]) -> None:
    """Read the run's nf-core ``params.json`` and set synthesized template flags.

    nf-core pipelines write ``pipeline_info/params*.json``. We translate a few fields
    into present/absent flag variables so they compose with the existing
    ``if_var_present``/``if_var_absent`` conditionals (no model change), and auto-fill
    ``METADATA_FILE`` when the run shipped a metadata file — so the common cases need
    no ``--var``. Best-effort: silently no-ops when no params file is found/parseable.

    Flags set (only when applicable; never overrides an explicit ``--var``):
      - ``SKIP_QIIME``     — ampliseq ITS/sintax runs without QIIME2 outputs
      - ``SKIP_TAXONOMY`` / ``SKIP_ALPHA_RAREFACTION`` — ampliseq runs that suppress
        a qiime2/ output subtree via the matching --skip_* flag
      - ``SKIP_ANCOM`` — ampliseq runs where ANCOM-BC was not opted into (no
        ``--ancombc``), so qiime2/ancombc/ is absent
      - ``IS_METAGENOMIC`` — viralrecon metagenomic (non-amplicon) runs
      - ``IS_NANOPORE``    — viralrecon nanopore/artic runs
      - ``IS_MULTIREGION`` — ampliseq multiregion/SIDLE runs (per-region ASVs
        reconstructed into one cross-region feature table under ``sidle/``)
    """
    # Locate the run's params.json. For "flat" projects (e.g. ampliseq, one run =
    # one DATA_ROOT) it sits directly under DATA_ROOT. For "sequencing-runs" projects
    # (e.g. viralrecon, DATA_ROOT aggregates run_*/ subdirs — incl. the per-run
    # symlink-parent validation convention) it sits one level down in a run subdir;
    # all runs of a project share a platform/protocol, so the first run's params is
    # representative for these route flags.
    candidates = sorted(Path(data_root).glob("pipeline_info/params*.json"))
    if not candidates:
        candidates = sorted(Path(data_root).glob("*/pipeline_info/params*.json"))
        if candidates:
            logger.warning(
                f"params.json not found at DATA_ROOT; using a run subdir's params "
                f"({candidates[0].parent.parent.name}) for route flags. If this DATA_ROOT "
                f"mixes platforms (e.g. nanopore + illumina runs), pass the route flag "
                f"explicitly via --var."
            )
    params: dict = {}
    for c in candidates:
        try:
            with open(c) as fh:
                params = json.load(fh)
            break
        except (OSError, ValueError):
            continue
    if not params:
        return

    if (params.get("platform") or "").lower() == "nanopore":
        variables.setdefault("IS_NANOPORE", "true")
    if (params.get("protocol") or "").lower() == "metagenomic":
        variables.setdefault("IS_METAGENOMIC", "true")
    if params.get("skip_qiime") is True:
        variables.setdefault("SKIP_QIIME", "true")
    # ampliseq output-suppressing skip flags: each removes a subtree of qiime2/
    # outputs. Surface them as flags so the template prunes the dependent DCs
    # (otherwise a REQUIRED DC's missing source aborts ingestion on a valid run).
    if params.get("skip_taxonomy") is True:
        variables.setdefault("SKIP_TAXONOMY", "true")
    if params.get("skip_alpha_rarefaction") is True:
        variables.setdefault("SKIP_ALPHA_RAREFACTION", "true")
    # ANCOM-BC is opt-in (positive `ancombc` flag, default false) — there is no
    # `skip_ancom` param. When it didn't run, no qiime2/ancombc/ output exists, so
    # prune the differential-abundance DCs.
    if params.get("ancombc") is not True:
        variables.setdefault("SKIP_ANCOM", "true")
    # ampliseq multiregion/SIDLE: the route is keyed by a regions reference AND a
    # SIDLE reference taxonomy (standard runs leave 'multiregion' null).
    if params.get("multiregion") and params.get("sidle_ref_taxonomy"):
        variables.setdefault("IS_MULTIREGION", "true")

    # Auto-fill METADATA_FILE from the run's input/ when the run used metadata
    # (params 'metadata' is the source URL; the local copy lands in input/).
    if "METADATA_FILE" not in variables and params.get("metadata"):
        input_dir = Path(data_root) / "input"
        if input_dir.is_dir():
            metas = sorted(
                p
                for p in input_dir.iterdir()
                if p.is_file()
                and "metadata" in p.name.lower()
                and p.suffix.lower() in (".tsv", ".csv", ".txt")
            )
            if metas:
                variables["METADATA_FILE"] = str(metas[0])
                logger.info(f"METADATA_FILE auto-detected from params + input/: {metas[0]}")


def _auto_detect_metadata_columns(metadata_path: Path, variables: dict[str, str]) -> None:
    """Read metadata file headers and auto-populate GROUP_COL and ANNOTATION_COLS.

    The first column is assumed to be the sample ID.  All subsequent columns are
    treated as annotation columns.  If GROUP_COL was not explicitly provided by
    the user, it defaults to the first annotation column.

    Args:
        metadata_path: Absolute path to the metadata file (TSV or CSV).
        variables: Variables dict to update in place.
    """
    try:
        with open(metadata_path) as f:
            header_line = f.readline().strip()
        if not header_line:
            return
        sep = "\t" if "\t" in header_line else ","
        cols = [c.strip() for c in header_line.split(sep)]
        if len(cols) < 2:
            return
        # First column is always the sample ID; the rest are annotations.
        # The ID column name is pipeline/user dependent (nf-core test data uses
        # "ID", the megatest metadata uses "sample"), so expose it as a variable
        # that the metadata→* link source columns substitute against.
        variables.setdefault("METADATA_ID_COL", cols[0])
        annotation_cols = [c for c in cols[1:] if c]
        if annotation_cols:
            variables.setdefault("GROUP_COL", annotation_cols[0])
            variables.setdefault(
                "GROUP_COL_DISPLAY", variables["GROUP_COL"].replace("_", " ").title()
            )
            variables["ANNOTATION_COLS"] = ",".join(annotation_cols)
            logger.info(
                f"Metadata auto-detect: {len(annotation_cols)} annotation columns "
                f"({', '.join(annotation_cols)}), GROUP_COL={variables['GROUP_COL']}"
            )
    except OSError as exc:
        logger.warning(f"Could not read metadata file for column detection: {exc}")


UNBOUND_VAR_SENTINEL = "__DEPICTIO_UNBOUND_{name}__"


def resolve_template(
    template_id: str,
    data_root: str | None,
    project_name: str | None = None,
    extra_vars: dict[str, str] | None = None,
    provenance_files: list[str] | None = None,
    allow_missing_vars: bool = False,
) -> tuple[dict[str, Any], TemplateMetadata, TemplateOrigin, list[Path], dict[str, str]]:
    """Load template YAML, substitute variables, apply conditionals, return resolved config.

    This is the main entry point for the template system. It:
    1. Locates the template YAML
    2. Extracts and validates template metadata
    3. Builds variables dict (DATA_ROOT + extra_vars from --var flags)
    4. Validates required variables; skips optional vars gracefully if absent
    5. Substitutes template variables in all paths
    6. Applies conditional rules (remove DCs, prune links, select dashboards)
    6c. Materializes recipe DCs that ship a pre-computed seed
    7. Strips hardcoded IDs
    8. Sets project name
    9. Builds TemplateOrigin for DB tracking
    10. Resolves dashboard YAML paths

    Args:
        template_id: Template identifier (e.g., 'nf-core/ampliseq/2.16.0').
        data_root: Absolute path to user's data root directory, or None for
            manifest-driven templates whose sources are remote (every
            filesystem-local step — params introspection, samplesheet/metadata
            auto-detection — is skipped in that case).
        project_name: Custom project name. If None, auto-generated from template.
        extra_vars: Additional variables from --var KEY=VALUE flags (e.g., METADATA_FILE).

    Returns:
        Tuple of (resolved_config_dict, template_metadata, template_origin,
        dashboard_paths, resolved_variables).

    Raises:
        FileNotFoundError: If template not found.
        ValueError: If template metadata is invalid or required variables missing.
    """
    # 1. Locate and load template YAML
    template_path = locate_template(template_id)
    logger.info(f"Loading template from: {template_path}")
    raw_config = _load_yaml(str(template_path))

    # 2. Extract and validate template metadata
    template_section = raw_config.pop("template", None)
    if template_section is None:
        raise ValueError(
            f"YAML at {template_path} does not contain a 'template' section. "
            "This file is not a valid template."
        )

    template_metadata = TemplateMetadata(**template_section)
    logger.info(f"Template: {template_metadata.template_id} v{template_metadata.version}")

    # 3. Build variables dict: DATA_ROOT when a local data root is given (None
    # for manifest-driven templates); extra_vars adds --var values
    data_root_abs: str | None = None
    variables: dict[str, str] = {}
    if data_root is not None:
        data_root_abs = str(Path(data_root).absolute())
        variables["DATA_ROOT"] = data_root_abs
    if extra_vars:
        variables.update(extra_vars)

    # 3a. Introspect the run's params.json to set protocol/skip flags + auto-fill
    # METADATA_FILE (does not override explicit --var values). Local runs only.
    if data_root_abs is not None:
        _introspect_pipeline_params(data_root_abs, variables)

    # 3b. Collect the run's provenance (parameters, thresholds, tool versions)
    # per the template's spec — persisted on TemplateOrigin for the ingestion
    # report and the dashboard Settings drawer.
    run_provenance, run_provenance_files = collect_run_provenance(
        data_root_abs, template_metadata.provenance, provenance_files
    )

    # 3b. Auto-detect metadata annotation columns when METADATA_FILE is provided
    if "METADATA_FILE" in variables:
        metadata_path = Path(variables["METADATA_FILE"])
        if not metadata_path.is_absolute() and data_root_abs is not None:
            # Try relative to data_root first, then CWD
            candidate = Path(data_root_abs) / metadata_path
            if candidate.is_file():
                metadata_path = candidate
            # else keep as-is (relative to CWD)
        if metadata_path.is_file():
            _auto_detect_metadata_columns(metadata_path, variables)

    # 3c. Auto-resolve SAMPLESHEET_FILE from the run's input/ directory when not
    # supplied. nf-core/ampliseq copies the input samplesheet into <run>/input/
    # under a pipeline/user dependent name (e.g. "Samplesheet.tsv",
    # "samplesheet.csv"), so locate it case-insensitively rather than forcing the
    # caller to pass an explicit path. Local runs only.
    if "SAMPLESHEET_FILE" not in variables and data_root_abs is not None:
        input_dir = Path(data_root_abs) / "input"
        if input_dir.is_dir():
            candidates = sorted(
                p
                for p in input_dir.iterdir()
                if p.is_file()
                and "samplesheet" in p.name.lower()
                and p.suffix.lower() in (".csv", ".tsv", ".tab", ".txt")
            )
            if candidates:
                variables["SAMPLESHEET_FILE"] = str(candidates[0])
                logger.info(f"Samplesheet auto-detected: {candidates[0]}")

    # Metadata ID column defaults to "sample" (megatest convention) when no
    # metadata file is present; the metadata→* links are pruned in that case, so
    # the placeholder simply resolves harmlessly.
    variables.setdefault("METADATA_ID_COL", "sample")

    # GROUP_COL drives per-group faceting/colouring in dashboards. When no
    # metadata (or no annotation column) is available it cannot resolve to a real
    # data column, so default it to a sentinel that no column matches: group-aware
    # figures test `'{GROUP_COL}' in df.columns` and fall back to an ungrouped
    # view, and the display label keeps titles readable instead of leaking the
    # raw `{GROUP_COL_DISPLAY}` placeholder.
    variables.setdefault("GROUP_COL", "__no_group__")
    variables.setdefault("GROUP_COL_DISPLAY", "Group")

    provided_vars: set[str] = set(variables.keys())

    # 4. Validate required variables; warn about unknown extras
    required_vars = template_metadata.get_required_variable_names()
    missing_vars = [v for v in required_vars if v not in variables]
    if missing_vars and allow_missing_vars:
        # --bind replaces whole scan blocks after resolution, which can make a
        # required variable irrelevant (e.g. MANIFEST_URL once every manifest DC
        # is bound elsewhere). Substitute a sentinel now; the caller must verify
        # none survives binding, so a genuinely-needed variable still fails loudly.
        for name in missing_vars:
            variables[name] = UNBOUND_VAR_SENTINEL.format(name=name)
        logger.info(
            f"Deferred template variables (expected to be replaced by --bind): "
            f"{', '.join(missing_vars)}"
        )
        missing_vars = []
    if missing_vars:
        raise ValueError(
            f"Missing required template variables: {', '.join(missing_vars)}. "
            f"Provided: {', '.join(variables.keys())}"
        )

    declared_var_names = {var.name for var in template_metadata.variables}
    for v in variables:
        if v not in declared_var_names and v != "DATA_ROOT":
            logger.warning(f"Variable '{v}' provided via --var but not declared in template")

    # 5. Substitute template variables in all paths
    resolved_config = substitute_template_variables(raw_config, variables)

    # 5b. Snapshot the full DC superset before any pruning, so the expected-DC
    # manifest can record what the template expected (incl. gated-out optionals).
    dc_superset = _collect_dc_superset(resolved_config)
    removal_reasons: dict[str, str] = {}

    # 6. Apply conditional rules based on which optional vars were provided
    template_dir = template_path.parent
    resolved_config, conditional_dashboards, conditional_reasons = _apply_conditionals(
        resolved_config,
        template_metadata.conditional,
        provided_vars,
        template_dir,
        variables,
    )
    removal_reasons.update(conditional_reasons)

    # 6b. Prune optional single-file DCs whose file is absent. Scoped strictly to
    # DCs flagged optional with a `single` scan (e.g. the phylogenetic tree, only
    # produced by some ampliseq sub-workflows) so a legitimate run that simply
    # lacks that output ingests the rest instead of failing the Project model's
    # ScanSingle existence check. Required DCs and recipe/glob DCs are untouched —
    # their absence still surfaces as a loud error.
    resolved_config, pruned_optional = _prune_missing_optional_single_file_dcs(resolved_config)
    if pruned_optional:
        logger.info(
            f"Pruned {len(pruned_optional)} optional DC(s) with missing source files: "
            f"{', '.join(pruned_optional)}"
        )
        for tag in pruned_optional:
            removal_reasons.setdefault(tag, "optional source file not found")

    # 6c. Materialize recipe DCs that ship a pre-computed seed
    #     ({data_root}/{dc_tag}.tsv). Parity with the boot-time reference
    #     resolver: the seed short-circuits the recipe, so a bundled template is
    #     ingestible from its own directory even though it does not ship the
    #     recipes' raw inputs. A DC with no seed is left untouched and its recipe
    #     runs exactly as before.
    #
    #     Placement is constrained on both sides: after `_apply_conditionals` so a
    #     gated-out DC stays gated out even when a seed sits next to it, and
    #     before `_strip_ids` / `_build_expected_dcs` so tags and links are still
    #     intact and the manifest reflects the final config.
    #     Seeds live under DATA_ROOT, so manifest-driven templates (no local
    #     root) have nothing to materialize.
    materialized_seeds: list[str] = []
    if data_root_abs is not None:
        materialized_seeds, _ = materialize_recipe_seeds(
            resolved_config, data_root_abs, drop_missing=False
        )
    if materialized_seeds:
        logger.info(
            f"Materialized {len(materialized_seeds)} recipe DC(s) from pre-computed seeds: "
            f"{', '.join(materialized_seeds)}"
        )

    # 7. Strip hardcoded IDs (fresh project gets new ones)
    resolved_config = _strip_ids(resolved_config)

    # 8. Set project name
    if project_name:
        resolved_config["name"] = project_name
    elif "name" not in resolved_config or not resolved_config.get("name"):
        # template_metadata.template_id (resolved), not the raw template_id param —
        # otherwise "nf-core/ampliseq/latest" runs all name-collide under one
        # generic project name instead of the concrete version actually ingested.
        if data_root is not None:
            suffix = Path(data_root).name
        else:
            # Manifest-driven: derive the suffix from the manifest filename.
            manifest_url = variables.get("MANIFEST_URL", "")
            suffix = Path(manifest_url.split("?", 1)[0]).stem or "manifest"
        resolved_config["name"] = f"{template_metadata.template_id} - {suffix}"

    # 9. Build TemplateOrigin for DB tracking
    expected_dcs = _build_expected_dcs(dc_superset, resolved_config, removal_reasons)
    template_origin = TemplateOrigin(
        template_id=template_metadata.template_id,
        template_version=template_metadata.version,
        data_root=data_root_abs,
        variables=dict(variables),
        applied_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        config_snapshot=copy.deepcopy(resolved_config),
        expected_data_collections=expected_dcs,
        run_provenance=run_provenance,
        run_provenance_files=run_provenance_files,
    )

    # 10. Inject template_origin into config
    resolved_config["template_origin"] = template_origin.model_dump()

    # 11. Resolve dashboard YAML paths — conditional overrides template defaults
    active_dashboard_rels = conditional_dashboards or template_metadata.dashboards
    dashboard_paths: list[Path] = []
    for rel_path in active_dashboard_rels:
        abs_path = (template_dir / rel_path).resolve()
        if abs_path.is_file():
            dashboard_paths.append(abs_path)
            logger.info(f"Dashboard found: {abs_path}")
        else:
            logger.warning(f"Dashboard YAML not found: {abs_path}")

    logger.info(f"Template resolved successfully. Project name: {resolved_config['name']}")
    return resolved_config, template_metadata, template_origin, dashboard_paths, variables


def import_dashboards_from_template(
    dashboard_paths: list[Path],
    api_url: str,
    headers: dict[str, str],
    project_id: str | None = None,
    overwrite: bool = True,
    variables: dict[str, str] | None = None,
    dashboard_name: str | None = None,
) -> list[dict[str, Any]]:
    """Import dashboard YAML files from a template into the server.

    Called after project sync during ``depictio run --template`` to automatically
    create the template's default dashboards.

    Args:
        dashboard_paths: Absolute paths to dashboard YAML files.
        api_url: Base API URL (e.g., ``http://localhost:8058``).
        headers: Auth headers (from ``generate_api_headers``).
        project_id: Project ObjectId string. When provided, overrides
            ``project_tag`` inside the YAML.
        overwrite: If True, update existing dashboards with the same title.
        variables: Template variables to substitute in dashboard YAML
            (e.g., ``{GROUP_COL}`` placeholders).
        dashboard_name: When provided, overrides the main dashboard's title
            (child tabs keep their own titles).

    Returns:
        List of result dicts, one per dashboard file.  Each contains
        ``path``, ``success``, and either ``dashboard_id``/``title`` or ``error``.
    """
    results: list[dict[str, Any]] = []
    url = f"{api_url}/depictio/api/v1/dashboards/import/yaml"

    for path in dashboard_paths:
        entry: dict[str, Any] = {"path": str(path), "success": False}
        try:
            yaml_content = path.read_text(encoding="utf-8")

            # Substitute template variables and/or override the dashboard title.
            if variables or dashboard_name:
                parsed = yaml.safe_load(yaml_content)
                if variables:
                    parsed = substitute_template_variables(parsed, variables)
                if dashboard_name and isinstance(parsed, dict):
                    # Override only the main dashboard's title; child-tab files
                    # (which carry their own top-level `title`) keep theirs.
                    if isinstance(parsed.get("main_dashboard"), dict):
                        parsed["main_dashboard"]["title"] = dashboard_name
                    elif "title" in parsed:
                        parsed["title"] = dashboard_name
                yaml_content = yaml.dump(parsed, default_flow_style=False, allow_unicode=True)

            params: dict[str, str | bool] = {}
            if project_id:
                params["project_id"] = project_id
            if overwrite:
                params["overwrite"] = True

            response = httpx.post(
                url,
                params=params,
                content=yaml_content,
                headers={**headers, "Content-Type": "text/plain"},
                timeout=60,
            )

            if response.status_code == 200:
                data = response.json()
                entry.update(
                    success=True,
                    dashboard_id=data.get("dashboard_id"),
                    title=data.get("title"),
                    updated=data.get("updated", False),
                    dash_url=data.get("dash_url"),
                )
                logger.info(f"Dashboard imported: {data.get('title')} ({path.name})")
            else:
                detail = response.text
                try:
                    detail = response.json().get("detail", detail)
                except Exception:
                    pass
                entry["error"] = f"HTTP {response.status_code}: {detail}"
                logger.error(f"Dashboard import failed for {path.name}: {entry['error']}")

        except Exception as exc:
            entry["error"] = str(exc)
            logger.error(f"Dashboard import failed for {path.name}: {exc}")

        results.append(entry)

    return results
