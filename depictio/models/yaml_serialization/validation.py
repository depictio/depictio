"""
YAML Dashboard Validation System.

Provides validation utilities for dashboard YAML files to ensure correctness
before syncing to MongoDB. Validates syntax, schema, and required fields.
"""

from pathlib import Path
from typing import Literal, TypedDict, cast

import yaml
from pydantic import ValidationError as PydanticValidationError

from depictio.models.yaml_serialization.mvp_models import MVPDashboard


class ValidationError(TypedDict):
    """Structured validation error information."""

    severity: Literal["error", "warning"]
    message: str
    field: str | None
    component_id: str | None


class ValidationResult(TypedDict):
    """Result of validating a YAML dashboard file."""

    valid: bool
    errors: list[ValidationError]
    warnings: list[ValidationError]


def validate_yaml_file(yaml_path: str) -> ValidationResult:
    """
    Validate a YAML dashboard file using Pydantic models.

    Args:
        yaml_path: Path to the YAML file to validate

    Returns:
        ValidationResult with valid flag and any errors/warnings
    """
    result: ValidationResult = cast(
        ValidationResult,
        {
            "valid": True,
            "errors": [],
            "warnings": [],
        },
    )

    yaml_file = Path(yaml_path)
    if not yaml_file.exists():
        result["valid"] = False
        result["errors"].append(
            {
                "severity": "error",
                "message": f"File not found: {yaml_path}",
                "field": None,
                "component_id": None,
            }
        )
        return result

    # Parse YAML
    try:
        yaml_content = yaml_file.read_text()
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        result["valid"] = False
        result["errors"].append(
            {
                "severity": "error",
                "message": f"Invalid YAML syntax: {e}",
                "field": None,
                "component_id": None,
            }
        )
        return result
    except OSError as e:
        result["valid"] = False
        result["errors"].append(
            {
                "severity": "error",
                "message": f"Error reading file: {e}",
                "field": None,
                "component_id": None,
            }
        )
        return result

    # Validate using Pydantic model
    try:
        dashboard = MVPDashboard.model_validate(data)

        # Check for empty components (warning, not error)
        if len(dashboard.components) == 0:
            result["warnings"].append(
                {
                    "severity": "warning",
                    "message": "Dashboard has no components",
                    "field": "components",
                    "component_id": None,
                }
            )

    except PydanticValidationError as e:
        result["valid"] = False

        # Convert Pydantic errors to our ValidationError format
        for error in e.errors():
            loc = error["loc"]
            field_path = ".".join(str(x) for x in loc)

            # Extract component_id if error is in a component
            component_id = _extract_component_id(loc, data)

            result["errors"].append(
                {
                    "severity": "error",
                    "message": error["msg"],
                    "field": field_path,
                    "component_id": component_id,
                }
            )

    return result


def _extract_component_id(loc: tuple, data: dict | None) -> str | None:
    """Extract component ID from error location if available."""
    if len(loc) < 2 or loc[0] != "components" or not isinstance(loc[1], int):
        return None

    comp_idx = loc[1]
    try:
        if isinstance(data, dict) and "components" in data:
            comp = data["components"][comp_idx]
            return comp.get("id", f"component-{comp_idx}")
    except (KeyError, IndexError, TypeError):
        pass

    return f"component-{comp_idx}"
