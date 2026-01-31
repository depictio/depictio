"""
Dash Mantine Components Validation.

Validates interactive component configurations against DMC requirements.
Ensures component types are compatible with column data types.

Usage:
    from depictio.models.validation.dash_mantine import (
        validate_interactive_component,
        SUPPORTED_INTERACTIVE_TYPES,
    )

    is_valid, errors = validate_interactive_component("Slider", "object")
    # errors: [{"loc": ..., "msg": "Slider requires numeric column type..."}]
"""

from typing import Any, Literal

# Supported interactive component types
InteractiveComponentType = Literal[
    "Select",
    "MultiSelect",
    "SegmentedControl",
    "Slider",
    "RangeSlider",
    "DateRangePicker",
    "Switch",
]

SUPPORTED_INTERACTIVE_TYPES: list[str] = [
    "Select",
    "MultiSelect",
    "SegmentedControl",
    "Slider",
    "RangeSlider",
    "DateRangePicker",
    "Switch",
]

# Column types compatible with each interactive component
COMPONENT_COLUMN_COMPATIBILITY: dict[str, set[str]] = {
    # Selection components work with categorical/string data
    "Select": {"object", "string", "category", "bool", "int64", "float64"},
    "MultiSelect": {"object", "string", "category", "bool", "int64", "float64"},
    "SegmentedControl": {"object", "string", "category", "bool"},
    # Sliders need numeric data
    "Slider": {"int64", "int32", "float64", "float32"},
    "RangeSlider": {"int64", "int32", "float64", "float32"},
    # Date picker needs datetime
    "DateRangePicker": {"datetime", "date"},
    # Switch is for boolean filtering
    "Switch": {"bool", "object", "string", "category"},
}

# Numeric column types (for slider validation)
NUMERIC_TYPES = {"int64", "int32", "float64", "float32"}

# Datetime column types
DATETIME_TYPES = {"datetime", "date", "timedelta"}

# Categorical column types
CATEGORICAL_TYPES = {"object", "string", "category"}


def validate_interactive_component(
    interactive_type: str,
    column_type: str,
    config: dict[str, Any] | None = None,
    raise_on_error: bool = False,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    """Validate interactive component configuration.

    Args:
        interactive_type: The DMC component type (Select, Slider, etc.)
        column_type: The data column type
        config: Optional component configuration dict
        raise_on_error: If True, raise ValidationError

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Check interactive_type is valid
    if interactive_type not in SUPPORTED_INTERACTIVE_TYPES:
        errors.append(
            {
                "loc": ("interactive_component_type",),
                "msg": f"Unknown component type: '{interactive_type}'. "
                f"Valid types: {SUPPORTED_INTERACTIVE_TYPES}",
                "type": "value_error",
            }
        )
        if raise_on_error and errors:
            from pydantic import ValidationError

            raise ValidationError.from_exception_data("DashMantine", errors)
        return False, errors, warnings

    # Check column_type compatibility
    compatible_types = COMPONENT_COLUMN_COMPATIBILITY.get(interactive_type, set())
    if column_type not in compatible_types:
        # Determine what types are expected
        if interactive_type in ("Slider", "RangeSlider"):
            expected = "numeric (int64, float64, etc.)"
        elif interactive_type == "DateRangePicker":
            expected = "datetime or date"
        else:
            expected = f"one of {sorted(compatible_types)}"

        errors.append(
            {
                "loc": ("column_type",),
                "msg": f"{interactive_type} expects {expected} column type, got '{column_type}'",
                "type": "value_error",
            }
        )

    # Config-specific validation
    if config:
        # Log scale only makes sense for numeric sliders
        if config.get("use_log_scale") and interactive_type not in ("Slider", "RangeSlider"):
            warnings.append(f"'use_log_scale' is ignored for {interactive_type}")

        # marks_count only for sliders
        if "marks_count" in config and interactive_type not in ("Slider", "RangeSlider"):
            warnings.append(f"'marks_count' is ignored for {interactive_type}")

        # searchable only for select components
        if "searchable" in config and interactive_type not in ("Select", "MultiSelect"):
            warnings.append(f"'searchable' is ignored for {interactive_type}")

    if raise_on_error and errors:
        from pydantic import ValidationError

        raise ValidationError.from_exception_data("DashMantine", errors)

    return len(errors) == 0, errors, warnings


def get_recommended_component(column_type: str, unique_count: int | None = None) -> str:
    """Suggest the best interactive component for a column type.

    Args:
        column_type: The data column type
        unique_count: Optional number of unique values

    Returns:
        Recommended component type
    """
    if column_type in DATETIME_TYPES:
        return "DateRangePicker"

    if column_type in NUMERIC_TYPES:
        return "RangeSlider"

    if column_type == "bool":
        return "Switch"

    # Categorical types
    if unique_count is not None:
        if unique_count <= 5:
            return "SegmentedControl"
        elif unique_count <= 20:
            return "Select"
        else:
            return "MultiSelect"  # Searchable for many options

    return "Select"  # Default for categorical
