"""
YAML import functions for dashboard serialization.

Provides functions for importing dashboards from YAML files and directories,
as well as directory management utilities.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from depictio.models.logging import logger
from depictio.models.yaml_serialization.compact_format import yaml_dict_to_dashboard
from depictio.models.yaml_serialization.mvp_format import yaml_mvp_to_dashboard
from depictio.models.yaml_serialization.utils import convert_from_yaml, sanitize_filename


def yaml_to_dashboard_dict(
    yaml_content: str,
    regenerate_stats: bool = True,
    auto_layout: bool = False,
) -> dict:
    """
    Parse YAML content to dashboard dictionary.

    Automatically detects format (MVP, compact, or legacy) and reconstructs full data.

    Args:
        yaml_content: YAML string content
        regenerate_stats: Regenerate column statistics from data source
        auto_layout: Auto-generate layout if missing

    Returns:
        Dictionary ready to instantiate DashboardData model

    Raises:
        ValueError: If YAML parsing fails or content is invalid
    """
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML format: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("YAML content must be a dictionary at the root level")

    is_mvp = False
    if "components" in data and "stored_metadata" not in data:
        components = data.get("components", [])
        if components and isinstance(components, list):
            first_comp = components[0]
            if (
                isinstance(first_comp, dict)
                and ("data_collection" in first_comp or "data" in first_comp)
                and "type" in first_comp
            ):
                is_mvp = True

    is_compact = False
    if not is_mvp:
        metadata = data.get("_export_metadata", {})
        if metadata.get("format_version") == "2.0":
            is_compact = True
        elif any("dc_ref" in comp for comp in data.get("stored_metadata", [])):
            is_compact = True

    if is_mvp:
        logger.info("Detected MVP YAML format, converting to full dashboard")
        return yaml_mvp_to_dashboard(data)
    elif is_compact:
        logger.info("Detected compact YAML format, converting to full dashboard")
        return yaml_dict_to_dashboard(
            data,
            regenerate_stats=regenerate_stats,
            auto_layout=auto_layout,
        )
    else:
        logger.info("Detected legacy YAML format")
        data.pop("_export_metadata", None)
        return convert_from_yaml(data)


def import_dashboard_from_file(
    filepath: str | Path,
    regenerate_stats: bool = True,
    auto_layout: bool = False,
) -> dict:
    """
    Import a dashboard from a YAML file.

    Automatically detects and handles compact format.

    Args:
        filepath: Source YAML file path
        regenerate_stats: Regenerate column statistics from data source
        auto_layout: Auto-generate layout if missing

    Returns:
        Dashboard dictionary ready for model instantiation

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file content is invalid
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"Dashboard file not found: {filepath}")

    yaml_content = filepath.read_text(encoding="utf-8")
    return yaml_to_dashboard_dict(
        yaml_content,
        regenerate_stats=regenerate_stats,
        auto_layout=auto_layout,
    )


def import_dashboard_from_yaml_dir(
    filepath: str | Path,
    regenerate_stats: bool | None = None,
    auto_layout: bool | None = None,
) -> dict:
    """
    Import a dashboard from a file in the YAML directory.

    Automatically detects and handles compact format.

    Args:
        filepath: Path to the YAML file (absolute or relative to base_dir)
        regenerate_stats: Override regenerate_stats setting
        auto_layout: Override auto_layout setting

    Returns:
        Dashboard dictionary ready for model instantiation

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file content is invalid
    """
    from depictio.api.v1.configs.config import settings

    filepath = Path(filepath)

    if not filepath.is_absolute():
        base_dir = Path(settings.dashboard_yaml.yaml_dir_path)
        filepath = base_dir / filepath

    yaml_config = settings.dashboard_yaml
    if regenerate_stats is None:
        regenerate_stats = yaml_config.regenerate_stats
    if auto_layout is None:
        auto_layout = yaml_config.auto_layout

    if not filepath.exists():
        raise FileNotFoundError(f"Dashboard file not found: {filepath}")

    yaml_content = filepath.read_text(encoding="utf-8")
    return yaml_to_dashboard_dict(
        yaml_content,
        regenerate_stats=regenerate_stats,
        auto_layout=auto_layout,
    )


def validate_dashboard_yaml(yaml_content: str) -> tuple[bool, list[str]]:
    """
    Validate dashboard YAML content against expected schema.

    Args:
        yaml_content: YAML string to validate

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors: list[str] = []

    try:
        data = yaml_to_dashboard_dict(yaml_content)
    except ValueError as e:
        return False, [str(e)]

    required_fields = ["title"]
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if "stored_metadata" in data:
        if not isinstance(data["stored_metadata"], list):
            errors.append("stored_metadata must be a list")
        else:
            for i, component in enumerate(data["stored_metadata"]):
                if not isinstance(component, dict):
                    errors.append(f"Component {i} must be a dictionary")
                elif "component_type" not in component:
                    errors.append(f"Component {i} missing 'component_type' field")

    for layout_field in ["left_panel_layout_data", "right_panel_layout_data", "stored_layout_data"]:
        if layout_field in data and not isinstance(data[layout_field], list):
            errors.append(f"{layout_field} must be a list")

    if "permissions" in data:
        perms = data["permissions"]
        if not isinstance(perms, dict):
            errors.append("permissions must be a dictionary")
        else:
            for role in ["owners", "editors", "viewers"]:
                if role in perms and not isinstance(perms[role], list):
                    errors.append(f"permissions.{role} must be a list")

    return len(errors) == 0, errors


def list_yaml_dashboards(
    base_dir: str | Path | None = None,
    project_name: str | None = None,
) -> list[dict]:
    """
    List all dashboard YAML files in the directory.

    Args:
        base_dir: Base directory to search (defaults to settings)
        project_name: Optional project name to filter by subdirectory

    Returns:
        List of dicts with file info: {path, filename, dashboard_id, title, modified}
    """
    if base_dir is None:
        from depictio.api.v1.configs.config import settings

        base_dir = Path(settings.dashboard_yaml.yaml_dir_path)
    else:
        base_dir = Path(base_dir)

    if not base_dir.exists():
        return []

    if project_name:
        search_path = base_dir / sanitize_filename(project_name)
    else:
        search_path = base_dir

    results = []

    yaml_files = list(search_path.glob("**/*.yaml")) + list(search_path.glob("**/*.yml"))

    for yaml_path in yaml_files:
        try:
            content = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            if not isinstance(data, dict):
                continue

            dashboard_id = data.get("dashboard_id", "")
            title = data.get("title", yaml_path.stem)

            relative_path = yaml_path.relative_to(base_dir)
            project = relative_path.parent.name if len(relative_path.parts) > 1 else None

            results.append(
                {
                    "path": str(yaml_path),
                    "filename": yaml_path.name,
                    "dashboard_id": dashboard_id,
                    "title": title,
                    "project": project,
                    "modified": datetime.fromtimestamp(yaml_path.stat().st_mtime).isoformat(),
                }
            )
        except Exception as e:
            logger.warning(f"Failed to parse YAML file {yaml_path}: {e}")
            continue

    return sorted(results, key=lambda x: x["modified"], reverse=True)


def delete_dashboard_yaml(
    dashboard_id: str,
    base_dir: str | Path | None = None,
) -> bool:
    """
    Delete a dashboard YAML file by dashboard ID.

    Searches for any YAML file containing the dashboard ID.

    Args:
        dashboard_id: The dashboard ID to delete
        base_dir: Base directory to search

    Returns:
        True if file was deleted, False if not found
    """
    if base_dir is None:
        from depictio.api.v1.configs.config import settings

        base_dir = Path(settings.dashboard_yaml.yaml_dir_path)
    else:
        base_dir = Path(base_dir)

    for yaml_info in list_yaml_dashboards(base_dir):
        if yaml_info["dashboard_id"] == dashboard_id:
            yaml_path = Path(yaml_info["path"])
            yaml_path.unlink()
            logger.info(f"Deleted dashboard YAML: {yaml_path}")
            return True

    return False


def sync_status(
    dashboard_id: str,
    dashboard_data: dict | None = None,
    base_dir: str | Path | None = None,
) -> dict:
    """
    Check the sync status between MongoDB and YAML for a dashboard.

    Args:
        dashboard_id: The dashboard ID to check
        dashboard_data: Optional current MongoDB data for comparison
        base_dir: Base directory to search

    Returns:
        Dict with sync status information:
        - yaml_exists: bool
        - yaml_path: str | None
        - yaml_modified: str | None
        - mongodb_version: int | None
        - yaml_version: int | None
        - in_sync: bool | None (None if can't determine)
    """
    if base_dir is None:
        from depictio.api.v1.configs.config import settings

        base_dir = Path(settings.dashboard_yaml.yaml_dir_path)

    yaml_info = None
    for info in list_yaml_dashboards(base_dir):
        if info["dashboard_id"] == dashboard_id:
            yaml_info = info
            break

    result: dict[str, Any] = {
        "yaml_exists": yaml_info is not None,
        "yaml_path": yaml_info["path"] if yaml_info else None,
        "yaml_modified": yaml_info["modified"] if yaml_info else None,
        "mongodb_version": None,
        "yaml_version": None,
        "in_sync": None,
    }

    if dashboard_data:
        result["mongodb_version"] = dashboard_data.get("version")

    if yaml_info:
        try:
            yaml_data = import_dashboard_from_file(yaml_info["path"])
            result["yaml_version"] = yaml_data.get("version")

            if result["mongodb_version"] is not None and result["yaml_version"] is not None:
                result["in_sync"] = result["mongodb_version"] == result["yaml_version"]
        except Exception as e:
            logger.warning(f"Failed to read YAML for sync check: {e}")

    return result


def ensure_yaml_directory() -> Path:
    """
    Ensure the YAML dashboard directory exists.

    Returns:
        Path to the YAML directory
    """
    from depictio.api.v1.configs.config import settings

    base_dir = Path(settings.dashboard_yaml.yaml_dir_path)
    base_dir.mkdir(parents=True, exist_ok=True)

    readme_path = base_dir / "README.md"
    if not readme_path.exists():
        readme_content = """# Dashboard YAML Directory

This directory contains YAML exports of dashboards from Depictio.

## Structure

Dashboards are organized by project:
```
dashboards_yaml/
    project_name/
        dashboard_title_abc12345.yaml
        another_dashboard_def67890.yaml
    another_project/
        dashboard_ghi11111.yaml
```

## Usage

### Export from MongoDB to YAML
Dashboards are exported here when you use the "Export to YAML" feature
or when auto-export is enabled.

### Import from YAML to MongoDB
Edit YAML files directly, then use the "Import from YAML" feature
to update the dashboard in the database.

### Version Control
This directory can be committed to git for version-controlled dashboards.

## File Format

Each YAML file contains the complete dashboard configuration including:
- Title, subtitle, and icon settings
- Component metadata (stored_metadata)
- Layout data (left/right panel positions)
- Button states and UI configuration

See the Depictio documentation for the full schema.
"""
        readme_path.write_text(readme_content, encoding="utf-8")

    return base_dir
