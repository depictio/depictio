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
