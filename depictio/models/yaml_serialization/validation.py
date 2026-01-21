"""
YAML Dashboard Validation System.

Provides validation utilities for dashboard YAML files to ensure correctness
before syncing to MongoDB. Validates syntax, schema, and required fields.
"""

from pathlib import Path
from typing import Literal, TypedDict

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


def _create_validation_error(
    message: str,
    field: str | None = None,
    component_id: str | None = None,
    severity: Literal["error", "warning"] = "error",
) -> ValidationError:
    """Create a ValidationError dict with the given parameters."""
    return ValidationError(
        severity=severity,
        message=message,
        field=field,
        component_id=component_id,
    )


def _get_non_null_fields(config: dict) -> set[str]:
    """Get field names that have non-None values from a configuration dict."""
    return {k for k, v in config.items() if v is not None}


def _build_error_message_with_suggestions(
    base_message: str,
    target: str,
    available: list[str],
    fallback_message: str | None = None,
) -> str:
    """
    Build an error message with suggestions for similar items.

    Args:
        base_message: The base error message
        target: The target string to find similar matches for
        available: List of available options to match against
        fallback_message: Optional message to append if no suggestions found

    Returns:
        Complete error message with suggestions if found
    """
    suggestions = _find_similar_columns(target, available)
    if suggestions:
        return f"{base_message}. Did you mean: {', '.join(suggestions)}?"
    if fallback_message:
        return f"{base_message}. {fallback_message}"
    return base_message


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

    def check_column(field_path: str, column_name: str | None) -> None:
        if column_name and column_name not in available_columns:
            error_msg = _build_error_message_with_suggestions(
                f"Column '{column_name}' not found in data collection",
                column_name,
                available_columns,
            )
            errors.append(_create_validation_error(error_msg, field_path, component_id))

    # Column fields to check by component type
    column_checks: dict[str, list[tuple[str, str]]] = {
        "figure": [
            ("visualization.x", "x"),
            ("visualization.y", "y"),
            ("visualization.color", "color"),
            ("visualization.size", "size"),
        ],
        "card": [("aggregation.column", "column")],
        "interactive": [("filter.column", "column")],
    }

    if component_type == "figure":
        viz = component.get("visualization", {})
        for field_path, key in column_checks["figure"]:
            check_column(field_path, viz.get(key))
    elif component_type == "card":
        agg = component.get("aggregation", {})
        for field_path, key in column_checks["card"]:
            check_column(field_path, agg.get(key))
    elif component_type == "interactive":
        filt = component.get("filter", {})
        for field_path, key in column_checks["interactive"]:
            check_column(field_path, filt.get(key))

    return errors


def _validate_chart_type(
    component: dict,
    component_id: str,
) -> list[ValidationError]:
    """
    Validate that the chart type is valid for figure components.

    Args:
        component: Component dictionary from YAML
        component_id: Component ID for error messages

    Returns:
        List of validation errors (empty if valid)
    """
    from depictio.models.yaml_serialization.validation_rules import (
        VALIDATION_RULES,
        get_allowed_visualization_fields,
    )

    errors: list[ValidationError] = []

    if component.get("type") != "figure":
        return errors

    viz = component.get("visualization", {})
    chart = viz.get("chart")

    if not chart:
        errors.append(
            _create_validation_error(
                "Figure component missing required field: visualization.chart",
                "visualization.chart",
                component_id,
            )
        )
        return errors

    if not VALIDATION_RULES.chart_types.is_valid_chart_type(chart):
        allowed = VALIDATION_RULES.chart_types.get_allowed_types_str()
        errors.append(
            _create_validation_error(
                f"Invalid chart type '{chart}'. Allowed types: {allowed}",
                "visualization.chart",
                component_id,
            )
        )

    # Check for unknown fields in visualization config
    allowed_fields = get_allowed_visualization_fields(chart)
    unknown_fields = _get_non_null_fields(viz) - allowed_fields

    for field in unknown_fields:
        error_msg = _build_error_message_with_suggestions(
            f"Unknown field 'visualization.{field}' for chart type '{chart}'",
            field,
            list(allowed_fields),
            f"Allowed fields: {', '.join(sorted(allowed_fields))}",
        )
        errors.append(_create_validation_error(error_msg, f"visualization.{field}", component_id))

    return errors


def _validate_unknown_fields(
    config: dict,
    allowed_fields: set[str],
    field_prefix: str,
    component_id: str,
) -> list[ValidationError]:
    """
    Validate that a config dictionary contains no unknown fields.

    Args:
        config: Configuration dictionary to validate
        allowed_fields: Set of allowed field names
        field_prefix: Prefix for field paths in error messages (e.g., "aggregation")
        component_id: Component ID for error messages

    Returns:
        List of validation errors for unknown fields
    """
    errors: list[ValidationError] = []
    unknown_fields = _get_non_null_fields(config) - allowed_fields

    for field in unknown_fields:
        error_msg = _build_error_message_with_suggestions(
            f"Unknown field '{field_prefix}.{field}'",
            field,
            list(allowed_fields),
        )
        errors.append(_create_validation_error(error_msg, f"{field_prefix}.{field}", component_id))

    return errors


def _validate_column_type_rules(
    column_type: str,
    field_prefix: str,
    component_id: str,
) -> tuple[object | None, list[ValidationError]]:
    """
    Get column type rules, returning an error if the column type is invalid.

    Args:
        column_type: The column type to validate
        field_prefix: Prefix for field paths (e.g., "aggregation" or "filter")
        component_id: Component ID for error messages

    Returns:
        Tuple of (rules, errors) where rules is None if column type is invalid
    """
    from depictio.models.yaml_serialization.validation_rules import VALIDATION_RULES

    rules = VALIDATION_RULES.get_column_type_rules(column_type)
    if rules:
        return rules, []

    valid_types = ", ".join(sorted(VALIDATION_RULES.column_type_rules.keys()))
    error = _create_validation_error(
        f"Unknown column type '{column_type}'. Valid types: {valid_types}",
        f"{field_prefix}.column_type",
        component_id,
    )
    return None, [error]


def _validate_aggregation_function(
    component: dict,
    component_id: str,
) -> list[ValidationError]:
    """
    Validate that aggregation function is valid for the column type.

    Args:
        component: Component dictionary from YAML
        component_id: Component ID for error messages

    Returns:
        List of validation errors (empty if valid)
    """
    from depictio.models.yaml_serialization.validation_rules import ALLOWED_AGGREGATION_FIELDS

    if component.get("type") != "card":
        return []

    agg = component.get("aggregation", {})
    column_type = agg.get("column_type")
    function = agg.get("function")

    if not column_type or not function:
        return []

    errors: list[ValidationError] = []

    rules, type_errors = _validate_column_type_rules(column_type, "aggregation", component_id)
    if type_errors:
        return type_errors

    if rules and not rules.is_valid_aggregation(function):
        allowed = rules.get_allowed_aggregations_str()
        errors.append(
            _create_validation_error(
                f"Invalid aggregation function '{function}' for column type '{column_type}'. "
                f"Allowed functions: {allowed}",
                "aggregation.function",
                component_id,
            )
        )

    errors.extend(
        _validate_unknown_fields(agg, ALLOWED_AGGREGATION_FIELDS, "aggregation", component_id)
    )

    return errors


def _validate_filter_type(
    component: dict,
    component_id: str,
) -> list[ValidationError]:
    """
    Validate that filter type is valid for the column type.

    Args:
        component: Component dictionary from YAML
        component_id: Component ID for error messages

    Returns:
        List of validation errors (empty if valid)
    """
    from depictio.models.yaml_serialization.validation_rules import ALLOWED_FILTER_FIELDS

    if component.get("type") != "interactive":
        return []

    filt = component.get("filter", {})
    column_type = filt.get("column_type")
    filter_type = filt.get("type")

    if not column_type or not filter_type:
        return []

    errors: list[ValidationError] = []

    rules, type_errors = _validate_column_type_rules(column_type, "filter", component_id)
    if type_errors:
        return type_errors

    if rules:
        if not rules.allowed_filters:
            errors.append(
                _create_validation_error(
                    f"Column type '{column_type}' does not support any filter types",
                    "filter.type",
                    component_id,
                )
            )
            return errors

        if not rules.is_valid_filter(filter_type):
            allowed = rules.get_allowed_filters_str()
            errors.append(
                _create_validation_error(
                    f"Invalid filter type '{filter_type}' for column type '{column_type}'. "
                    f"Allowed types: {allowed}",
                    "filter.type",
                    component_id,
                )
            )

    errors.extend(_validate_unknown_fields(filt, ALLOWED_FILTER_FIELDS, "filter", component_id))

    return errors


def _create_result_with_error(message: str) -> ValidationResult:
    """Create a ValidationResult with a single error."""
    return ValidationResult(
        valid=False,
        errors=[_create_validation_error(message)],
        warnings=[],
    )


def _create_empty_result() -> ValidationResult:
    """Create an empty ValidationResult ready to be populated."""
    return ValidationResult(valid=True, errors=[], warnings=[])


def _validate_component_types(
    dashboard: MVPDashboard,
    result: ValidationResult,
) -> None:
    """Validate component-specific types (chart, aggregation, filter)."""
    for comp in dashboard.components:
        comp_dict = comp.model_dump()
        result["errors"].extend(_validate_chart_type(comp_dict, comp.id))
        result["errors"].extend(_validate_aggregation_function(comp_dict, comp.id))
        result["errors"].extend(_validate_filter_type(comp_dict, comp.id))


def _validate_component_columns_for_dashboard(
    dashboard: MVPDashboard,
    result: ValidationResult,
) -> None:
    """Validate column references for all components in the dashboard."""
    for comp in dashboard.components:
        comp_dict = comp.model_dump()
        columns, error = _get_data_collection_columns(
            workflow_tag=comp.workflow,
            data_collection_tag=comp.data_collection,
        )

        if error:
            result["warnings"].append(
                _create_validation_error(
                    f"Cannot validate columns: {error}",
                    component_id=comp.id,
                    severity="warning",
                )
            )
            continue

        result["errors"].extend(
            _validate_component_columns(
                component=comp_dict,
                available_columns=columns,
                component_id=comp.id,
            )
        )


def validate_yaml_file(
    yaml_path: str,
    check_column_names: bool = True,
    check_component_types: bool = True,
) -> ValidationResult:
    """
    Validate a YAML dashboard file using Pydantic models.

    Args:
        yaml_path: Path to the YAML file to validate
        check_column_names: Whether to validate column names against data collection schema
        check_component_types: Whether to validate chart types, aggregation functions, and filter types

    Returns:
        ValidationResult with valid flag and any errors/warnings
    """
    yaml_file = Path(yaml_path)
    if not yaml_file.exists():
        return _create_result_with_error(f"File not found: {yaml_path}")

    # Parse YAML
    try:
        yaml_content = yaml_file.read_text()
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return _create_result_with_error(f"Invalid YAML syntax: {e}")
    except OSError as e:
        return _create_result_with_error(f"Error reading file: {e}")

    result = _create_empty_result()

    # Validate using Pydantic model
    try:
        dashboard = MVPDashboard.model_validate(data)

        if len(dashboard.components) == 0:
            result["warnings"].append(
                _create_validation_error(
                    "Dashboard has no components", "components", severity="warning"
                )
            )

    except PydanticValidationError as e:
        result["valid"] = False
        for error in e.errors():
            loc = error["loc"]
            field_path = ".".join(str(x) for x in loc)
            component_id = _extract_component_id(loc, data)
            result["errors"].append(
                _create_validation_error(error["msg"], field_path, component_id)
            )
        return result

    # Component type validation
    if check_component_types and result["valid"]:
        try:
            _validate_component_types(dashboard, result)
        except Exception as e:
            result["warnings"].append(
                _create_validation_error(
                    f"Component type validation failed: {e}", severity="warning"
                )
            )

    # Column name validation
    if check_column_names and result["valid"]:
        try:
            from depictio.api.v1.db import workflows_collection  # noqa: F401

            _validate_component_columns_for_dashboard(dashboard, result)
        except ImportError:
            result["warnings"].append(
                _create_validation_error(
                    "MongoDB not available, skipping column validation", severity="warning"
                )
            )
        except Exception as e:
            result["warnings"].append(
                _create_validation_error(f"Column validation failed: {e}", severity="warning")
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
