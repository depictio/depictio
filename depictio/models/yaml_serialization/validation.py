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


def _get_data_collection_columns(
    workflow_tag: str,
    data_collection_tag: str,
) -> tuple[list[str], str | None]:
    """
    Get available column names for a data collection.

    Supports both data models:
    - Standalone collections (workflows_collection, data_collections_collection)
    - Hierarchical projects collection (projects.workflows.data_collections)

    Args:
        workflow_tag: Workflow tag name (e.g., 'iris_workflow' or 'python/iris_workflow')
        data_collection_tag: Data collection tag name (e.g., 'iris_table')

    Returns:
        Tuple of (column_names, error_message)
        - column_names: List of available column names (empty if error)
        - error_message: Error message if lookup failed, None if successful
    """
    from depictio.api.v1.db import (
        data_collections_collection,
        deltatables_collection,
        projects_collection,
        workflows_collection,
    )

    # Normalize workflow tag (strip prefix like "python/" if present)
    # This matches the behavior of the MVP format converter
    normalized_workflow_tag = workflow_tag.split("/")[-1] if "/" in workflow_tag else workflow_tag

    dc_id = None

    # Try Method 1: Standalone collections (legacy/flat structure)
    # Try both normalized and original tags
    workflow = workflows_collection.find_one(
        {"workflow_tag": {"$in": [workflow_tag, normalized_workflow_tag]}}
    )
    if workflow:
        workflow_id = workflow["_id"]
        dc_query = {
            "workflow_id": workflow_id,
            "data_collection_tag": data_collection_tag,
        }
        data_collection = data_collections_collection.find_one(dc_query)
        if data_collection:
            dc_id = data_collection["_id"]

    # Try Method 2: Projects collection (hierarchical structure)
    if dc_id is None:
        # Search for both normalized and original workflow tags
        project = projects_collection.find_one(
            {"workflows.workflow_tag": {"$in": [workflow_tag, normalized_workflow_tag]}}
        )
        if project:
            # Find the workflow in the project (match either tag)
            workflows = project.get("workflows", [])
            for wf in workflows:
                wf_tag = wf.get("workflow_tag", "")
                # Match if tag equals either original or normalized version
                if wf_tag == workflow_tag or wf_tag == normalized_workflow_tag:
                    # Find the data collection in the workflow
                    data_collections = wf.get("data_collections", [])
                    for dc in data_collections:
                        if dc.get("data_collection_tag") == data_collection_tag:
                            dc_id = dc.get("_id")
                            break
                    break

    # If still not found, return error
    if dc_id is None:
        return (
            [],
            f"Data collection '{data_collection_tag}' not found in workflow '{workflow_tag}'",
        )

    # Fetch column specs from deltatable
    deltatable_query = {"data_collection_id": dc_id}
    deltatable = deltatables_collection.find_one(deltatable_query)
    if not deltatable:
        return [], f"No deltatable found for data collection '{data_collection_tag}'"

    # Get latest aggregation's column specs
    aggregations = deltatable.get("aggregation", [])
    if not aggregations:
        return [], f"No aggregations found for data collection '{data_collection_tag}'"

    latest_agg = aggregations[-1]
    column_specs = latest_agg.get("aggregation_columns_specs", [])

    # Extract column names
    column_names = [col["name"] for col in column_specs]

    return column_names, None


def _find_similar_columns(target: str, available: list[str]) -> list[str]:
    """
    Find similar column names using fuzzy matching.

    Args:
        target: The column name that wasn't found
        available: List of available column names

    Returns:
        List of similar column names, sorted by similarity
    """
    from difflib import get_close_matches

    return get_close_matches(target, available, n=3, cutoff=0.6)


def _validate_component_columns(
    component: dict,
    available_columns: list[str],
    component_id: str,
) -> list[ValidationError]:
    """
    Validate that all column references in a component exist in the data collection.

    Args:
        component: Component dictionary from YAML
        available_columns: List of available column names
        component_id: Component ID for error messages

    Returns:
        List of validation errors (empty if all columns valid)
    """
    errors: list[ValidationError] = []
    component_type = component.get("type")

    # Helper to check a single column reference
    def check_column(field_path: str, column_name: str | None) -> None:
        if column_name and column_name not in available_columns:
            # Find similar column names for suggestions
            suggestions = _find_similar_columns(column_name, available_columns)
            error_msg = f"Column '{column_name}' not found in data collection"
            if suggestions:
                error_msg += f". Did you mean: {', '.join(suggestions[:3])}?"

            errors.append(
                cast(
                    ValidationError,
                    {
                        "severity": "error",
                        "message": error_msg,
                        "field": field_path,
                        "component_id": component_id,
                    },
                )
            )

    # Validate based on component type
    if component_type == "figure":
        viz = component.get("visualization", {})
        check_column("visualization.x", viz.get("x"))
        check_column("visualization.y", viz.get("y"))
        check_column("visualization.color", viz.get("color"))
        check_column("visualization.size", viz.get("size"))

    elif component_type == "card":
        agg = component.get("aggregation", {})
        check_column("aggregation.column", agg.get("column"))

    elif component_type == "interactive":
        filt = component.get("filter", {})
        check_column("filter.column", filt.get("column"))

    # Table components don't reference specific columns

    return errors


def validate_yaml_file(yaml_path: str, check_column_names: bool = True) -> ValidationResult:
    """
    Validate a YAML dashboard file using Pydantic models.

    Args:
        yaml_path: Path to the YAML file to validate
        check_column_names: Whether to validate column names against data collection schema

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

    # Column name validation (if enabled and basic validation passed)
    if check_column_names and result["valid"]:
        try:
            # Check if MongoDB is available
            try:
                from depictio.api.v1.db import workflows_collection  # noqa: F401
            except Exception:
                result["warnings"].append(
                    {
                        "severity": "warning",
                        "message": "MongoDB not available, skipping column validation",
                        "field": None,
                        "component_id": None,
                    }
                )
            else:
                # Validate columns for each component
                for comp in dashboard.components:
                    comp_dict = comp.model_dump()

                    # Get available columns for this component's data collection
                    columns, error = _get_data_collection_columns(
                        workflow_tag=comp.workflow,
                        data_collection_tag=comp.data_collection,
                    )

                    if error:
                        # Data collection or workflow not found - warning, not error
                        result["warnings"].append(
                            {
                                "severity": "warning",
                                "message": f"Cannot validate columns: {error}",
                                "field": None,
                                "component_id": comp.id,
                            }
                        )
                        continue

                    # Validate column references
                    column_errors = _validate_component_columns(
                        component=comp_dict,
                        available_columns=columns,
                        component_id=comp.id,
                    )

                    result["errors"].extend(column_errors)

        except Exception as e:
            # Column validation failure shouldn't break the whole validation
            result["warnings"].append(
                {
                    "severity": "warning",
                    "message": f"Column validation failed: {e}",
                    "field": None,
                    "component_id": None,
                }
            )

    result["valid"] = len(result["errors"]) == 0
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
