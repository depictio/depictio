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
    ExpectedDataCollection,
    TemplateConditional,
    TemplateMetadata,
    TemplateOrigin,
)

_TEMPLATE_VAR_RE = re.compile(r"\{([A-Z0-9_]+)\}")


def _load_yaml(path: str) -> dict:
    """Load a YAML file and return its contents as a dict."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML file: expected a dictionary in {path}")
    return data


def locate_template(template_id: str) -> Path:
    """Find template YAML by template_id (e.g., 'nf-core/ampliseq/2.16.0').

    Searches in the depictio/projects/ directory relative to the package installation.
    Looks for template.yaml first (dedicated template file), then falls back to
    project.yaml (for backwards compatibility).

    Args:
        template_id: Template identifier (e.g., 'nf-core/ampliseq/2.16.0').

    Returns:
        Path to the template YAML file.

    Raises:
        FileNotFoundError: If no template YAML exists.
    """
    # Resolve relative to depictio package root
    package_root = Path(__file__).resolve().parents[4]  # cli/cli/utils/ -> depictio/
    template_dir = package_root / "depictio" / "projects" / template_id

    # Prefer template.yaml (dedicated template file) over project.yaml (fixture)
    for filename in ("template.yaml", "project.yaml"):
        candidate = template_dir / filename
        if candidate.is_file():
            return candidate

    # Also try without the package nesting (for installed packages)
    alt_root = Path(__file__).resolve().parents[3]  # cli/cli/utils/ -> cli/
    alt_dir = alt_root / "projects" / template_id
    for filename in ("template.yaml", "project.yaml"):
        candidate = alt_dir / filename
        if candidate.is_file():
            return candidate

    available = _list_available_templates(package_root)
    available_str = ", ".join(available) if available else "none found"
    raise FileNotFoundError(
        f"Template '{template_id}' not found at {template_dir}. "
        f"Available templates: {available_str}"
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
    resolved_vars: dict[str, str],
    template_dir: Path,
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
        resolved_vars: Resolved variables (name → value), incl. applied defaults.
            Presence checks use the keys; if_var_equals compares the values.
        template_dir: Template directory for resolving dashboard paths.

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
        if rule.if_var_absent and rule.if_var_absent not in resolved_vars:
            fires = True
            reason = f"gated: {rule.if_var_absent} absent (if_var_absent)"
        elif rule.if_var_present and rule.if_var_present in resolved_vars:
            fires = True
            reason = f"gated: {rule.if_var_present} present (if_var_present)"
        elif rule.if_var_equals and all(
            (resolved_vars.get(k) or "").lower() == str(v).lower()
            for k, v in rule.if_var_equals.items()
        ):
            fires = True
            pairs = ", ".join(f"{k}={v}" for k, v in rule.if_var_equals.items())
            reason = f"gated: {pairs} (if_var_equals)"

        if not fires:
            continue

        # Collect DC tags to remove
        for tag in rule.remove_dc_tags:
            removed_dc_tags.add(tag)
            removal_reasons.setdefault(tag, reason)
            logger.info(f"Conditional rule: removing DC tag '{tag}'")

        # Collect DC source-binding overrides (last-write-wins per tag)
        for ov in rule.override_dcs:
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
                    f"(rule {rule.if_var_present or rule.if_var_absent or rule.if_var_equals})"
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
    """Check if a DC's source files exist. Return missing path or None if all OK."""
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


def _normalize_param_value(value: Any) -> str:
    """Render a ``params.json`` scalar as the string a template variable compares against.

    Booleans become ``"true"`` / ``"false"`` so they match ``if_var_equals`` routes
    written against the nf flag (e.g. ``{SKIP_PANGOLIN: "true"}``); everything else is
    stringified and trimmed. nf flag *values* are mirrored verbatim (lower-cased enums
    like ``nanopore`` already match the case-insensitive ``if_var_equals`` compare).
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _introspect_pipeline_params(
    data_root: str, variables: dict[str, str], declared_vars: list[str]
) -> None:
    """Mirror the run's nf-core ``params.json`` into the template's declared variables.

    nf-core writes every resolved parameter to ``pipeline_info/params*.json`` — the same
    parameters that drove the pipeline. We therefore derive routing directly from it,
    using nf's own vocabulary: for each variable a template declares, if ``params.json``
    has the same-named key (lower-cased — ``PLATFORM`` ↔ ``platform``, ``SKIP_PANGOLIN``
    ↔ ``skip_pangolin``, ``ANCOMBC`` ↔ ``ancombc``), its value is copied in. So a user
    who knows their nf run needs no ``--var`` — the template adapts to what the pipeline
    recorded. ``setdefault`` keeps explicit ``--var`` wins; template-declared ``default``
    values (applied later) cover params an older run omitted. Best-effort: silently
    no-ops when no params file is found/parseable.

    ``METADATA_FILE`` is the one derived (not 1:1) case — the ``metadata`` param is a
    source URL; the local copy lands in ``input/``.
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

    # Generic param → variable derivation (nf vocabulary). DATA_ROOT is caller-resolved
    # and never sourced from params.
    for name in declared_vars:
        if name == "DATA_ROOT" or name in variables:
            continue
        key = name.lower()
        if key in params and params[key] is not None:
            value = _normalize_param_value(params[key])
            variables[name] = value
            logger.info(f"{name}={value} auto-derived from params.json ({key})")

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


def resolve_template(
    template_id: str,
    data_root: str,
    project_name: str | None = None,
    extra_vars: dict[str, str] | None = None,
) -> tuple[dict[str, Any], TemplateMetadata, TemplateOrigin, list[Path], dict[str, str]]:
    """Load template YAML, substitute variables, apply conditionals, return resolved config.

    This is the main entry point for the template system. It:
    1. Locates the template YAML
    2. Extracts and validates template metadata
    3. Builds variables dict (DATA_ROOT + extra_vars from --var flags)
    4. Validates required variables; skips optional vars gracefully if absent
    5. Substitutes template variables in all paths
    6. Applies conditional rules (remove DCs, prune links, select dashboards)
    7. Strips hardcoded IDs
    8. Sets project name
    9. Builds TemplateOrigin for DB tracking
    10. Resolves dashboard YAML paths

    Args:
        template_id: Template identifier (e.g., 'nf-core/ampliseq/2.16.0').
        data_root: Absolute path to user's data root directory.
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

    # 3. Build variables dict: DATA_ROOT is always set; extra_vars adds --var values
    data_root_abs = str(Path(data_root).absolute())
    variables: dict[str, str] = {"DATA_ROOT": data_root_abs}
    if extra_vars:
        variables.update(extra_vars)

    # 3a. Introspect the run's params.json: mirror nf params into the template's
    # declared variables + auto-fill METADATA_FILE (does not override explicit --var).
    declared_var_names = [v.name for v in template_metadata.variables]
    _introspect_pipeline_params(data_root_abs, variables, declared_var_names)

    # 3b. Auto-detect metadata annotation columns when METADATA_FILE is provided
    if "METADATA_FILE" in variables:
        metadata_path = Path(variables["METADATA_FILE"])
        if not metadata_path.is_absolute():
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
    # caller to pass an explicit path.
    if "SAMPLESHEET_FILE" not in variables:
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

    # Apply declared defaults for any optional variable not supplied / introspected.
    # Lets a template offer an explicit value variable (e.g. PLATFORM=illumina) instead
    # of sniffing it from the run — the default fills the common case, --var overrides it.
    for var in template_metadata.variables:
        if var.default is not None:
            variables.setdefault(var.name, var.default)

    # 4. Validate required variables; warn about unknown extras
    required_vars = template_metadata.get_required_variable_names()
    missing_vars = [v for v in required_vars if v not in variables]
    if missing_vars:
        raise ValueError(
            f"Missing required template variables: {', '.join(missing_vars)}. "
            f"Provided: {', '.join(variables.keys())}"
        )

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
        variables,
        template_dir,
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

    # 7. Strip hardcoded IDs (fresh project gets new ones)
    resolved_config = _strip_ids(resolved_config)

    # 8. Set project name
    if project_name:
        resolved_config["name"] = project_name
    elif "name" not in resolved_config or not resolved_config.get("name"):
        resolved_config["name"] = f"{template_id} - {Path(data_root).name}"

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
