"""
YAML Serialization utilities for dashboard documents.

Provides bidirectional conversion between MongoDB documents and YAML format,
enabling declarative dashboard configuration and version-controlled dashboards.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

import yaml
from bson import ObjectId
from pydantic import BaseModel

from depictio.models.logging import logger

T = TypeVar("T", bound=BaseModel)


class DashboardYAMLDumper(yaml.SafeDumper):
    """Custom YAML dumper with improved formatting for dashboard configs."""

    pass


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Use literal block scalar for multiline strings."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


DashboardYAMLDumper.add_representer(str, _represent_str)


def convert_for_yaml(data: Any) -> Any:
    """
    Recursively convert data to YAML-serializable format.

    Handles:
    - ObjectId → string
    - datetime → ISO format string
    - Path → string
    - Nested dicts and lists
    - Pydantic models → dict

    Args:
        data: Any Python object to convert

    Returns:
        YAML-serializable data structure
    """
    if isinstance(data, ObjectId):
        return str(data)
    elif isinstance(data, datetime):
        return data.isoformat()
    elif isinstance(data, Path):
        return str(data)
    elif isinstance(data, BaseModel):
        return convert_for_yaml(data.model_dump())
    elif isinstance(data, dict):
        return {k: convert_for_yaml(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_for_yaml(item) for item in data]
    else:
        return data


def convert_from_yaml(data: Any) -> Any:
    """
    Recursively process YAML data for model instantiation.

    This is a lighter-touch conversion that preserves string ObjectIds
    since Pydantic models handle the conversion themselves.

    Args:
        data: Data loaded from YAML

    Returns:
        Processed data ready for Pydantic model instantiation
    """
    if isinstance(data, dict):
        return {k: convert_from_yaml(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_from_yaml(item) for item in data]
    else:
        return data


def dashboard_to_yaml(dashboard_data: dict, include_metadata: bool = True) -> str:
    """
    Convert a dashboard document to YAML string.

    Args:
        dashboard_data: Dashboard data as dictionary (from model_dump or MongoDB)
        include_metadata: Whether to include export metadata (timestamp, version)

    Returns:
        YAML string representation of the dashboard
    """
    # Convert to YAML-serializable format
    yaml_data = convert_for_yaml(dashboard_data)

    # Add export metadata if requested
    if include_metadata:
        yaml_data = {
            "_export_metadata": {
                "format_version": "1.0",
                "exported_at": datetime.now().isoformat(),
                "source": "depictio",
            },
            **yaml_data,
        }

    return yaml.dump(
        yaml_data,
        Dumper=DashboardYAMLDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )


def yaml_to_dashboard_dict(yaml_content: str) -> dict:
    """
    Parse YAML content to dashboard dictionary.

    Strips export metadata and prepares data for model instantiation.

    Args:
        yaml_content: YAML string content

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

    # Strip export metadata if present
    data.pop("_export_metadata", None)

    # Process the data for model instantiation
    return convert_from_yaml(data)


def export_dashboard_to_file(dashboard_data: dict, filepath: str | Path) -> Path:
    """
    Export a dashboard to a YAML file.

    Args:
        dashboard_data: Dashboard data as dictionary
        filepath: Destination file path

    Returns:
        Path to the written file
    """
    filepath = Path(filepath)

    # Ensure .yaml extension
    if filepath.suffix not in (".yaml", ".yml"):
        filepath = filepath.with_suffix(".yaml")

    yaml_content = dashboard_to_yaml(dashboard_data)

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(yaml_content, encoding="utf-8")

    logger.info(f"Dashboard exported to {filepath}")
    return filepath


def import_dashboard_from_file(filepath: str | Path) -> dict:
    """
    Import a dashboard from a YAML file.

    Args:
        filepath: Source YAML file path

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
    return yaml_to_dashboard_dict(yaml_content)


def create_dashboard_yaml_template() -> str:
    """
    Generate a template YAML for creating new dashboards.

    Returns:
        YAML string template with documented fields
    """
    template = {
        "_comment": "Dashboard configuration template - remove this field before import",
        "title": "My Dashboard",
        "subtitle": "Dashboard description",
        "icon": "mdi:view-dashboard",
        "icon_color": "orange",
        "icon_variant": "filled",
        "workflow_system": "none",
        "notes_content": "",
        "is_public": False,
        "stored_metadata": [
            {
                "_comment": "Component metadata - each component has its own configuration",
                "index": "uuid-will-be-generated",
                "component_type": "card",
                "title": "Example Component",
                "dict_kwargs": {},
            }
        ],
        "left_panel_layout_data": [],
        "right_panel_layout_data": [],
        "buttons_data": {
            "unified_edit_mode": True,
            "add_components_button": {"count": 0},
        },
    }

    return yaml.dump(
        template,
        Dumper=DashboardYAMLDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def create_figure_component_yaml_template(with_customizations: bool = True) -> str:
    """
    Generate a template YAML for a figure component with customizations.

    This shows all available customization options for Plotly figures.

    Args:
        with_customizations: Include full customization examples

    Returns:
        YAML string template with documented figure component fields
    """
    template: dict[str, Any] = {
        "_comment": "Figure component template with Plotly customizations",
        "index": "fig-001",
        "component_type": "figure",
        "title": "My Figure",
        "visu_type": "scatter",
        "dict_kwargs": {
            "_comment": "Plotly Express parameters",
            "x": "x_column",
            "y": "y_column",
            "color": "category_column",
            "title": "Figure Title",
            "template": "mantine_light",
            "opacity": 0.8,
        },
    }

    if with_customizations:
        template["customizations"] = {
            "_comment": "Post-rendering customizations applied to the Plotly figure",
            "axes": {
                "x": {
                    "scale": "linear",
                    "title": "X Axis Title",
                    "range": [0, 100],
                    "gridlines": True,
                    "zeroline": True,
                },
                "y": {
                    "scale": "log",
                    "title": "Y Axis Title (Log Scale)",
                },
            },
            "reference_lines": [
                {
                    "type": "hline",
                    "y": 0.05,
                    "line_color": "red",
                    "line_dash": "dash",
                    "line_width": 1,
                    "opacity": 0.7,
                    "annotation_text": "p = 0.05 threshold",
                    "annotation_position": "top right",
                },
                {
                    "type": "vline",
                    "x": 0,
                    "line_color": "gray",
                    "line_dash": "solid",
                },
            ],
            "highlights": [
                {
                    "conditions": [
                        {
                            "column": "significant",
                            "operator": "eq",
                            "value": True,
                        }
                    ],
                    "logic": "and",
                    "style": {
                        "marker_color": "red",
                        "marker_size": 10,
                        "dim_opacity": 0.3,
                    },
                    "label": "Significant",
                    "show_labels": False,
                }
            ],
            "annotations": [
                {
                    "text": "Important point",
                    "x": 50,
                    "y": 50,
                    "showarrow": True,
                    "arrowhead": 2,
                }
            ],
            "shapes": [
                {
                    "type": "rect",
                    "x0": 10,
                    "y0": 10,
                    "x1": 20,
                    "y1": 20,
                    "fillcolor": "rgba(255,0,0,0.1)",
                    "line_color": "red",
                    "layer": "below",
                }
            ],
            "legend": {
                "show": True,
                "orientation": "v",
                "x": 1.02,
                "y": 1,
            },
            "hover": {
                "mode": "closest",
            },
        }

    return yaml.dump(
        template,
        Dumper=DashboardYAMLDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
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

    # Required fields
    required_fields = ["title"]
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    # Validate component metadata structure if present
    if "stored_metadata" in data:
        if not isinstance(data["stored_metadata"], list):
            errors.append("stored_metadata must be a list")
        else:
            for i, component in enumerate(data["stored_metadata"]):
                if not isinstance(component, dict):
                    errors.append(f"Component {i} must be a dictionary")
                elif "component_type" not in component:
                    errors.append(f"Component {i} missing 'component_type' field")

    # Validate layout data structure
    for layout_field in ["left_panel_layout_data", "right_panel_layout_data", "stored_layout_data"]:
        if layout_field in data and not isinstance(data[layout_field], list):
            errors.append(f"{layout_field} must be a list")

    # Validate permissions structure if present
    if "permissions" in data:
        perms = data["permissions"]
        if not isinstance(perms, dict):
            errors.append("permissions must be a dictionary")
        else:
            for role in ["owners", "editors", "viewers"]:
                if role in perms and not isinstance(perms[role], list):
                    errors.append(f"permissions.{role} must be a list")

    return len(errors) == 0, errors


# ============================================================================
# Directory-based YAML Management
# ============================================================================


def sanitize_filename(name: str) -> str:
    """
    Sanitize a string to be safe for use as a filename.

    Args:
        name: The string to sanitize

    Returns:
        Sanitized filename-safe string
    """
    # Replace problematic characters with underscores
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_")


def get_dashboard_yaml_path(
    dashboard_id: str,
    dashboard_title: str,
    project_name: str | None = None,
    base_dir: str | Path | None = None,
    organize_by_project: bool = True,
    use_dashboard_title: bool = True,
) -> Path:
    """
    Get the file path for a dashboard YAML file.

    Args:
        dashboard_id: The dashboard ID
        dashboard_title: The dashboard title
        project_name: Optional project name for subdirectory organization
        base_dir: Base directory for YAML files (defaults to settings)
        organize_by_project: Whether to organize by project subdirectories
        use_dashboard_title: Whether to include title in filename

    Returns:
        Path object for the dashboard YAML file
    """
    if base_dir is None:
        # Use default from settings (lazy import to avoid circular imports)
        from depictio.api.v1.configs.config import settings

        base_dir = Path(settings.dashboard_yaml.yaml_dir_path)
    else:
        base_dir = Path(base_dir)

    # Build the directory path
    if organize_by_project and project_name:
        safe_project = sanitize_filename(project_name)
        dir_path = base_dir / safe_project
    else:
        dir_path = base_dir

    # Build the filename
    short_id = str(dashboard_id)[:8]
    if use_dashboard_title:
        safe_title = sanitize_filename(dashboard_title)
        filename = f"{safe_title}_{short_id}.yaml"
    else:
        filename = f"{short_id}.yaml"

    return dir_path / filename


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

    # Search path
    if project_name:
        search_path = base_dir / sanitize_filename(project_name)
    else:
        search_path = base_dir

    results = []

    # Find all YAML files
    yaml_files = list(search_path.glob("**/*.yaml")) + list(search_path.glob("**/*.yml"))

    for yaml_path in yaml_files:
        try:
            content = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            if not isinstance(data, dict):
                continue

            # Extract dashboard info
            dashboard_id = data.get("dashboard_id", "")
            title = data.get("title", yaml_path.stem)

            # Get project from parent directory if organized by project
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


def export_dashboard_to_yaml_dir(
    dashboard_data: dict,
    project_name: str | None = None,
    base_dir: str | Path | None = None,
    organize_by_project: bool | None = None,
    use_dashboard_title: bool | None = None,
    include_metadata: bool | None = None,
) -> Path:
    """
    Export a dashboard to the YAML directory using configured settings.

    Args:
        dashboard_data: Dashboard data dictionary (from model_dump or MongoDB)
        project_name: Project name for organization
        base_dir: Override base directory
        organize_by_project: Override organize_by_project setting
        use_dashboard_title: Override use_dashboard_title setting
        include_metadata: Override include_export_metadata setting

    Returns:
        Path to the written YAML file
    """
    # Get settings with overrides
    from depictio.api.v1.configs.config import settings

    yaml_config = settings.dashboard_yaml

    if base_dir is None:
        base_dir = Path(yaml_config.yaml_dir_path)
    if organize_by_project is None:
        organize_by_project = yaml_config.organize_by_project
    if use_dashboard_title is None:
        use_dashboard_title = yaml_config.use_dashboard_title
    if include_metadata is None:
        include_metadata = yaml_config.include_export_metadata

    # Get dashboard ID and title
    dashboard_id = str(dashboard_data.get("dashboard_id", ""))
    dashboard_title = dashboard_data.get("title", "untitled")

    # Get file path
    filepath = get_dashboard_yaml_path(
        dashboard_id=dashboard_id,
        dashboard_title=dashboard_title,
        project_name=project_name,
        base_dir=base_dir,
        organize_by_project=organize_by_project,
        use_dashboard_title=use_dashboard_title,
    )

    # Convert to YAML and write
    yaml_content = dashboard_to_yaml(dashboard_data, include_metadata=include_metadata)

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(yaml_content, encoding="utf-8")

    logger.info(f"Dashboard exported to YAML directory: {filepath}")
    return filepath


def import_dashboard_from_yaml_dir(
    filepath: str | Path,
) -> dict:
    """
    Import a dashboard from a file in the YAML directory.

    Args:
        filepath: Path to the YAML file (absolute or relative to base_dir)

    Returns:
        Dashboard dictionary ready for model instantiation

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file content is invalid
    """
    filepath = Path(filepath)

    # If relative path, resolve against base_dir
    if not filepath.is_absolute():
        from depictio.api.v1.configs.config import settings

        base_dir = Path(settings.dashboard_yaml.yaml_dir_path)
        filepath = base_dir / filepath

    return import_dashboard_from_file(filepath)


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

    # Find file(s) matching this dashboard ID
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

    # Find YAML file
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

            # Check if in sync (simple version comparison)
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

    # Create a README if it doesn't exist
    readme_path = base_dir / "README.md"
    if not readme_path.exists():
        readme_content = """# Dashboard YAML Directory

This directory contains YAML exports of dashboards from Depictio.

## Structure

Dashboards are organized by project:
```
dashboards_yaml/
├── project_name/
│   ├── dashboard_title_abc12345.yaml
│   └── another_dashboard_def67890.yaml
└── another_project/
    └── dashboard_ghi11111.yaml
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
