"""Component and data collection type validation.

This module provides shared validation logic for ensuring compatibility between
component types and data collection types. It serves as the single source of truth
for both UI filtering (Dash stepper) and API-level validation (FastAPI endpoints).

The validation rules ensure that:
- Standard components (Figure, Card, Interactive, Table) only work with Table DCs
- Image components only work with Image DCs
- MultiQC components only work with MultiQC DCs
- JBrowse2 components only work with JBrowse2 DCs
- Map components only work with Table DCs whose config carries lat/lon column hints
  (enforced via `dc_has_coordinates`)
"""

from typing import Any

# Component type to allowed DC types mapping
COMPONENT_DC_TYPE_MAPPING: dict[str, list[str]] = {
    "Figure": ["table"],
    "Card": ["table"],
    "Interactive": ["table"],
    "Table": ["table"],
    "MultiQC": ["multiqc"],
    "Image": ["image"],
    "JBrowse2": ["jbrowse2"],
    "Map": ["table"],
    # Advanced viz consumes tabular DCs whose columns satisfy one of the
    # canonical viz schemas (see advanced_viz/schemas.py). The viz-side
    # binding validator enforces the exact column shape; this entry only
    # gates DC-type compatibility.
    "AdvancedViz": ["table"],
    # Text component doesn't use data collections (no entry needed)
    # Note: Map components also use "geojson" DCs for choropleth boundaries,
    # but the geojson DC is referenced via geojson_dc_id, not the primary DC binding.
}

# GeoJSON DC type mapping - separate because it's a secondary reference
GEOJSON_DC_ALLOWED_COMPONENTS: list[str] = ["Map"]

# Reverse mapping: DC type to allowed component types
# Used for UI filtering in stepper (shows which components are valid for a DC type)
DC_COMPONENT_TYPE_MAPPING: dict[str, list[str]] = {
    "table": ["Figure", "Card", "Interactive", "Table", "Map", "AdvancedViz"],
    "multiqc": ["MultiQC"],
    "image": ["Image"],
    "jbrowse2": ["JBrowse2"],
    "geojson": ["Map"],
}


def validate_component_dc_type_compatibility(component_type: str, dc_type: str) -> tuple[bool, str]:
    """
    Validate that a component type is compatible with a data collection type.

    This function enforces the business rule that each component type can only use
    specific data collection types. For example, Image components can only use Image DCs,
    and Figure components can only use Table DCs.

    Args:
        component_type: Component type (e.g., "Figure", "Card", "Image", "MultiQC")
        dc_type: Data collection type (e.g., "table", "image", "multiqc", "jbrowse2")

    Returns:
        tuple: (is_valid, error_message)
            - is_valid: True if compatible, False otherwise
            - error_message: Empty string if valid, error description if invalid

    Examples:
        >>> validate_component_dc_type_compatibility("Figure", "table")
        (True, "")
        >>> validate_component_dc_type_compatibility("Image", "table")
        (False, "Image components can only use 'image' data collections, but received 'table'")
        >>> validate_component_dc_type_compatibility("Figure", "image")
        (False, "Figure components can only use 'table' data collections, but received 'image'")
    """
    # Get allowed DC types for this component
    allowed_dc_types = COMPONENT_DC_TYPE_MAPPING.get(component_type, [])

    if not allowed_dc_types:
        # Unknown component type or component that doesn't use DCs (e.g., Text)
        return False, f"Unknown component type: {component_type}"

    if dc_type not in allowed_dc_types:
        allowed_str = ", ".join(f"'{t}'" for t in allowed_dc_types)
        return (
            False,
            f"{component_type} components can only use {allowed_str} data collections, "
            f"but received '{dc_type}'",
        )

    return True, ""


def _get(obj: Any, key: str) -> Any:
    """Read `key` from either a dict or an attribute-bearing object."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def dc_has_coordinates(dc_config: Any) -> bool:
    """Return True if a DC config is a table DC with `lat_column` and `lon_column` set.

    Accepts either a `DataCollectionConfig` instance or a plain dict (the shape used
    when configs are persisted in MongoDB or transferred over the wire). Map components
    require this — the dc_type alone is not enough since `table` covers both regular
    tables and geographic ones.
    """
    if dc_config is None:
        return False
    if _get(dc_config, "type") != "table":
        return False
    props = _get(dc_config, "dc_specific_properties")
    if props is None:
        return False
    return bool(_get(props, "lat_column")) and bool(_get(props, "lon_column"))


def validate_map_component_dc(dc_config: Any) -> tuple[bool, str]:
    """Strict check for Map components: the DC must be a coordinates-bearing table.

    Returns (True, "") on success or (False, reason) when the DC lacks lat/lon hints.
    Use after `validate_component_dc_type_compatibility` for Map components.
    """
    if dc_has_coordinates(dc_config):
        return True, ""
    return (
        False,
        "Map components require a table data collection with 'lat_column' and "
        "'lon_column' set on its dc_specific_properties.",
    )
