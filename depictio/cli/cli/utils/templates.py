"""
Template resolver for depictio-cli.

Handles loading template project.yaml files, substituting {DATA_ROOT} variables,
and producing resolved config dicts ready for Project model validation.

Usage:
    resolved = resolve_template("nf-core/ampliseq/2.16.0", "/path/to/data")
"""

import copy
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from depictio.cli.cli_logging import logger
from depictio.models.models.templates import TemplateMetadata, TemplateOrigin

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


def resolve_template(
    template_id: str,
    data_root: str,
    project_name: str | None = None,
) -> tuple[dict[str, Any], TemplateMetadata, TemplateOrigin, list[Path]]:
    """Load template YAML, substitute {DATA_ROOT}, return resolved config.

    This is the main entry point for the template system. It:
    1. Locates the template YAML
    2. Extracts and validates template metadata
    3. Substitutes {DATA_ROOT} in all paths
    4. Strips hardcoded IDs
    5. Sets project name
    6. Builds TemplateOrigin for DB tracking
    7. Resolves dashboard YAML paths from template metadata

    Args:
        template_id: Template identifier (e.g., 'nf-core/ampliseq/2.16.0').
        data_root: Absolute path to user's data root directory.
        project_name: Custom project name. If None, auto-generated from template.

    Returns:
        Tuple of (resolved_config_dict, template_metadata, template_origin, dashboard_paths).

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

    # 3. Validate required variables are available
    data_root_abs = str(Path(data_root).absolute())
    variables: dict[str, str] = {"DATA_ROOT": data_root_abs}

    required_vars = template_metadata.get_required_variable_names()
    missing_vars = [v for v in required_vars if v not in variables]
    if missing_vars:
        raise ValueError(
            f"Missing required template variables: {', '.join(missing_vars)}. "
            f"Provided: {', '.join(variables.keys())}"
        )

    # 4. Substitute template variables in all paths
    resolved_config = substitute_template_variables(raw_config, variables)

    # 5. Strip hardcoded IDs (fresh project gets new ones)
    resolved_config = _strip_ids(resolved_config)

    # 6. Set project name
    if project_name:
        resolved_config["name"] = project_name
    elif "name" not in resolved_config or not resolved_config.get("name"):
        resolved_config["name"] = f"{template_id} - {Path(data_root).name}"

    # 7. Build TemplateOrigin for DB tracking
    template_origin = TemplateOrigin(
        template_id=template_metadata.template_id,
        template_version=template_metadata.version,
        data_root=data_root_abs,
        applied_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        config_snapshot=copy.deepcopy(resolved_config),
    )

    # 8. Inject template_origin into config
    resolved_config["template_origin"] = template_origin.model_dump()

    # 9. Resolve dashboard YAML paths relative to the template directory
    dashboard_paths: list[Path] = []
    if template_metadata.dashboards:
        template_dir = template_path.parent
        for rel_path in template_metadata.dashboards:
            abs_path = (template_dir / rel_path).resolve()
            if abs_path.is_file():
                dashboard_paths.append(abs_path)
                logger.info(f"Dashboard found: {abs_path}")
            else:
                logger.warning(f"Dashboard YAML not found: {abs_path}")

    logger.info(f"Template resolved successfully. Project name: {resolved_config['name']}")
    return resolved_config, template_metadata, template_origin, dashboard_paths


def import_dashboards_from_template(
    dashboard_paths: list[Path],
    api_url: str,
    headers: dict[str, str],
    project_id: str | None = None,
    overwrite: bool = True,
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
