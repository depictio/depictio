"""
YAML Serialization utilities for dashboard documents.

Provides bidirectional conversion between MongoDB documents and YAML format,
enabling declarative dashboard configuration and version-controlled dashboards.
"""

import uuid
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


# ============================================================================
# Compact YAML Export/Import (75-80% size reduction)
# ============================================================================


def filter_defaults(dict_kwargs: dict, component_type: str = "figure") -> dict:
    """
    Remove default values from component parameters to reduce YAML size.

    Args:
        dict_kwargs: Component parameters dictionary
        component_type: Type of component (figure, card, etc.)

    Returns:
        Filtered dictionary with only non-default values
    """
    # Common defaults across all component types
    common_defaults = {
        "template": "mantine_light",
        "orientation": "v",
        "log_x": False,
        "log_y": False,
        "category_orders": "",
        "labels": "",
        "color_discrete_sequence": "",
        "title": "",
        "subtitle": "",
        "facet_row_spacing": "",
        "facet_col_spacing": "",
        "facet_col_wrap": "",
        "range_x": "",
        "range_y": "",
    }

    # Component-specific defaults
    component_defaults = {
        "figure": {
            **common_defaults,
            "color_discrete_map": "",
            "color_continuous_scale": "",
            "color_continuous_midpoint": "",
            "symbol_sequence": "",
            "symbol_map": "",
            "trendline_options": "",
            "trendline_color_override": "",
            "trendline_scope": "trace",
            "render_mode": "auto",
            "error_x": "",
            "error_x_minus": "",
            "error_y": "",
            "error_y_minus": "",
            "range_color": "",
        },
        "card": {**common_defaults},
    }

    defaults = component_defaults.get(component_type, common_defaults)

    # Filter out defaults and empty strings/nulls
    filtered = {}
    for k, v in dict_kwargs.items():
        # Skip if value matches default
        if k in defaults and v == defaults[k]:
            continue
        # Skip empty strings and None values
        if v == "" or v is None:
            continue
        filtered[k] = v

    return filtered


def auto_generate_layout(index: int, component_type: str = "figure") -> dict:
    """
    Generate default layout based on component index and type.

    Creates a simple grid layout (3 columns, stack vertically).

    Args:
        index: Component position in list
        component_type: Type of component

    Returns:
        Layout dictionary with position and size
    """
    # Default grid: 3 columns (16 units each = 48 total width)
    col = index % 3
    row = index // 3

    # Default sizes by component type
    sizes = {
        "figure": {"w": 16, "h": 12},
        "card": {"w": 16, "h": 6},
        "table": {"w": 48, "h": 20},  # Full width for tables
    }

    # Get size for this component type (default to figure size)
    component_type_lower = component_type.lower().replace("component", "")
    size = sizes.get(component_type_lower, sizes["figure"])

    # Adjust x position based on column
    x_pos = col * 16

    # Adjust y position based on row (use average height)
    y_pos = row * 12

    return {
        "w": size["w"],
        "h": size["h"],
        "x": x_pos,
        "y": y_pos,
        "i": f"box-{uuid.uuid4()}",
        "moved": False,
        "static": False,
    }


def generate_component_id(component: dict, index: int) -> str:
    """
    Generate meaningful human-readable component ID based on content.

    Creates descriptive IDs like:
    - "sepal-length-average" for card showing average of sepal.length
    - "sepal-length-filter" for interactive filtering sepal.length
    - "box-variety-sepal-length" for box plot
    - "data-table" for table component

    Args:
        component: Component dictionary
        index: Component position in list

    Returns:
        Human-readable ID string
    """
    import re

    comp_type = component.get("component_type", "component")

    # Helper to sanitize field names
    def sanitize(text: str) -> str:
        if not text:
            return ""
        # Remove dots, replace with hyphens, lowercase
        return re.sub(r"[^a-z0-9]+", "-", str(text).replace(".", "-").lower()).strip("-")

    # Card: {column}-{aggregation}
    if comp_type == "card":
        column = component.get("column_name", "")
        agg = component.get("aggregation", "")
        if column and agg:
            return f"{sanitize(column)}-{sanitize(agg)}"
        return f"card-{index + 1}"

    # Interactive: {column}-filter
    elif comp_type in ("InteractiveComponent", "interactive"):
        column = component.get("column_name", "")
        if column:
            return f"{sanitize(column)}-filter"
        return f"filter-{index + 1}"

    # Figure: {chart}-{x}-{y} or {chart}-{x}
    elif comp_type == "figure":
        visu_type = component.get("visu_type", "")
        dict_kwargs = component.get("dict_kwargs", {})
        x = dict_kwargs.get("x", "")
        y = dict_kwargs.get("y", "")

        if visu_type and x and y:
            return f"{sanitize(visu_type)}-{sanitize(x)}-{sanitize(y)}"
        elif visu_type and x:
            return f"{sanitize(visu_type)}-{sanitize(x)}"
        return f"figure-{index + 1}"

    # Table: just "data-table" (no index suffix)
    elif comp_type == "table":
        return "data-table"

    # Fallback: use title if present
    title = component.get("title", "")
    if title and title.strip():
        base_id = sanitize(title)[:40]
        return base_id if base_id else f"{comp_type.lower()}-{index + 1}"

    # Final fallback
    return f"{comp_type.lower()}-{index + 1}"


def _get_db_connection_for_enrichment(
    db_client: Any = None,
    db_name: str = "depictioDB",
) -> tuple[Any, str, str] | None:
    """
    Get database connection and collection names for tag enrichment.

    Args:
        db_client: Optional MongoDB client to use
        db_name: Database name to use if db_client is provided

    Returns:
        Tuple of (db, dc_collection_name, wf_collection_name) or None if unavailable
    """
    # Default collection names
    dc_collection_name = "data_collections"
    wf_collection_name = "workflows"

    # Try to get collection names from settings
    try:
        from depictio.api.v1.configs.config import settings

        dc_collection_name = settings.mongodb.collections.data_collection
        wf_collection_name = settings.mongodb.collections.workflow_collection
    except ImportError:
        pass

    if db_client is not None:
        return db_client[db_name], dc_collection_name, wf_collection_name

    # Try to import from API context
    try:
        from depictio.api.v1.db import db

        return db, dc_collection_name, wf_collection_name
    except ImportError:
        logger.debug("Could not import MongoDB dependencies for tag enrichment, skipping")
        return None
    except Exception as e:
        logger.debug(f"MongoDB connection unavailable for tag enrichment: {e}")
        return None


def _enrich_component_dc_tag(
    comp: dict,
    dc_cache: dict[str, dict | None],
    collection: Any,
) -> None:
    """Enrich a component with data collection tag from MongoDB."""
    dc_id = comp.get("dc_id")
    if not dc_id:
        return

    dc_id_str = str(dc_id)

    # Fetch and cache if not already cached
    if dc_id_str not in dc_cache:
        try:
            dc_cache[dc_id_str] = collection.find_one({"_id": ObjectId(dc_id)})
        except Exception as e:
            logger.debug(f"Failed to lookup data collection {dc_id}: {e}")
            dc_cache[dc_id_str] = None

    dc_doc = dc_cache[dc_id_str]
    if not dc_doc:
        return

    # Ensure dc_config exists
    if "dc_config" not in comp:
        comp["dc_config"] = {}

    # Add tag (prefer data_collection_tag, fallback to name)
    tag = dc_doc.get("data_collection_tag") or dc_doc.get("name")
    if tag:
        comp["dc_config"]["data_collection_tag"] = tag
    comp["dc_config"]["id"] = dc_id_str
    comp["dc_config"]["type"] = dc_doc.get("type", "table")


def _enrich_component_wf_tag(
    comp: dict,
    wf_cache: dict[str, dict | None],
    collection: Any,
) -> None:
    """Enrich a component with workflow tag from MongoDB."""
    wf_id = comp.get("wf_id")
    if not wf_id:
        return

    wf_id_str = str(wf_id)

    # Fetch and cache if not already cached
    if wf_id_str not in wf_cache:
        try:
            wf_cache[wf_id_str] = collection.find_one({"_id": ObjectId(wf_id)})
        except Exception as e:
            logger.debug(f"Failed to lookup workflow {wf_id}: {e}")
            wf_cache[wf_id_str] = None

    wf_doc = wf_cache[wf_id_str]
    if not wf_doc:
        return

    wf_tag = wf_doc.get("workflow_tag") or wf_doc.get("name")
    if wf_tag:
        comp["wf_name"] = wf_tag


def enrich_dashboard_with_tags(
    dashboard_data: dict,
    db_client: Any = None,
    db_name: str = "depictioDB",
) -> dict:
    """
    Enrich dashboard components with data_collection_tag and workflow tags from MongoDB.

    Looks up dc_id and wf_id in their respective collections to get human-readable tags.

    Args:
        dashboard_data: Dashboard dictionary from MongoDB
        db_client: Optional MongoDB client to use (if None, tries to import from depictio.api.v1.db)
        db_name: Database name to use if db_client is provided (default: "depictioDB")

    Returns:
        Enriched dashboard dictionary with tags in dc_config
    """
    db_connection = _get_db_connection_for_enrichment(db_client, db_name)
    if db_connection is None:
        return dashboard_data

    db, dc_collection_name, wf_collection_name = db_connection
    dc_collection = db[dc_collection_name]
    wf_collection = db[wf_collection_name]

    # Caches to avoid repeated lookups
    dc_cache: dict[str, dict | None] = {}
    wf_cache: dict[str, dict | None] = {}

    for comp in dashboard_data.get("stored_metadata", []):
        _enrich_component_dc_tag(comp, dc_cache, dc_collection)
        _enrich_component_wf_tag(comp, wf_cache, wf_collection)

    return dashboard_data


def _build_mvp_figure_config(comp: dict) -> dict[str, Any] | None:
    """Build MVP visualization config for figure components."""
    visu_type = comp.get("visu_type")
    if not visu_type:
        return None

    dict_kwargs = comp.get("dict_kwargs", {})
    viz_config: dict[str, Any] = {"chart": visu_type}

    # Filter out default parameters
    filtered_kwargs = filter_defaults(dict_kwargs, "figure")

    # Separate main params from style params
    main_params = {"x", "y", "color", "size", "facet_row", "facet_col"}
    style_params: dict[str, Any] = {}

    for key, value in filtered_kwargs.items():
        if key in main_params:
            viz_config[key] = value
        elif key in ("color_discrete_map", "color_continuous_scale"):
            # Simplify color map key names
            style_key = key.replace("color_discrete_", "").replace("color_continuous_", "")
            style_params[style_key] = value
        else:
            style_params[key] = value

    if style_params:
        viz_config["style"] = style_params

    return viz_config


def _build_mvp_card_config(comp: dict) -> dict[str, Any] | None:
    """Build MVP aggregation config for card components."""
    agg_config: dict[str, Any] = {}

    column_name = comp.get("column_name")
    if column_name:
        agg_config["column"] = column_name

    aggregation = comp.get("aggregation")
    if aggregation:
        agg_config["function"] = aggregation

    column_type = comp.get("column_type")
    if column_type:
        agg_config["column_type"] = column_type

    value = comp.get("value")
    if value is not None:
        agg_config["value"] = value

    return agg_config if agg_config else None


def _build_mvp_interactive_config(comp: dict) -> dict[str, Any] | None:
    """Build MVP filter config for interactive components."""
    filter_config: dict[str, Any] = {}

    column_name = comp.get("column_name")
    if column_name:
        filter_config["column"] = column_name

    interactive_component_type = comp.get("interactive_component_type")
    if interactive_component_type:
        filter_config["type"] = interactive_component_type

    column_type = comp.get("column_type")
    if column_type:
        filter_config["column_type"] = column_type

    # Process default_state based on its type
    default_state = comp.get("default_state")
    if default_state and isinstance(default_state, dict):
        state_type = default_state.get("type")
        if state_type == "range":
            filter_config["min"] = default_state.get("min_value")
            filter_config["max"] = default_state.get("max_value")
            default_range = default_state.get("default_range")
            if default_range:
                filter_config["default"] = default_range
        elif state_type == "select":
            options = default_state.get("options")
            if options:
                filter_config["options"] = options
            default_value = default_state.get("default_value")
            if default_value is not None:
                filter_config["default"] = default_value

    value = comp.get("value")
    if value is not None:
        filter_config["value"] = value

    return filter_config if filter_config else None


def _get_mvp_workflow_tag(comp: dict) -> str | None:
    """Get workflow tag for MVP export, generating placeholder if needed."""
    wf_id = comp.get("wf_id")
    if not wf_id:
        return None

    wf_name = comp.get("wf_name")
    if wf_name:
        return wf_name

    # Generate placeholder tag from ObjectId prefix
    return f"wf_{str(wf_id)[:8]}"


def _get_mvp_data_collection_tag(comp: dict) -> str | None:
    """Get data collection tag for MVP export, generating placeholder if needed."""
    dc_config = comp.get("dc_config", {})
    if dc_config and dc_config.get("data_collection_tag"):
        return dc_config["data_collection_tag"]

    dc_id = comp.get("dc_id")
    if dc_id:
        # Generate placeholder tag from ObjectId prefix
        return f"dc_{str(dc_id)[:8]}"

    return None


def _build_mvp_component(comp: dict, idx: int) -> dict[str, Any]:
    """Build a single MVP component from full component data."""
    comp_type = comp.get("component_type", "figure")

    mvp_comp: dict[str, Any] = {
        "id": generate_component_id(comp, idx),
        "type": comp_type,
    }

    # Add title if present
    title = comp.get("title", "")
    if title and title.strip():
        mvp_comp["title"] = title

    # Add workflow reference
    wf_tag = _get_mvp_workflow_tag(comp)
    if wf_tag:
        mvp_comp["workflow"] = wf_tag

    # Add data collection reference
    data_tag = _get_mvp_data_collection_tag(comp)
    if data_tag:
        mvp_comp["data_collection"] = data_tag

    # Add component-type-specific configuration
    if comp_type == "figure":
        viz_config = _build_mvp_figure_config(comp)
        if viz_config:
            mvp_comp["visualization"] = viz_config
    elif comp_type == "card":
        agg_config = _build_mvp_card_config(comp)
        if agg_config:
            mvp_comp["aggregation"] = agg_config
    elif comp_type in ("InteractiveComponent", "interactive"):
        filter_config = _build_mvp_interactive_config(comp)
        if filter_config:
            mvp_comp["filter"] = filter_config
    # Table components only need data reference (already added above)

    return mvp_comp


def dashboard_to_yaml_mvp(dashboard_data: dict) -> dict:
    """
    Convert dashboard data to MVP minimal YAML format (~60-80 lines).

    MVP optimizations:
    - Remove: export metadata, duplicate IDs, runtime state, layout
    - Simplify component IDs: human-readable strings instead of UUIDs
    - Simplify data references: just tag instead of full dc_ref
    - Flatten visualization: merge dict_kwargs + visu_type
    - Omit defaults: version=1, workflow_system=none, empty permissions

    Args:
        dashboard_data: Full dashboard dictionary (from model_dump or MongoDB)

    Returns:
        Minimal MVP dictionary ready for YAML serialization
    """
    mvp_dict: dict[str, Any] = {}

    # Dashboard ID
    dashboard_id = dashboard_data.get("dashboard_id", dashboard_data.get("id"))
    if dashboard_id:
        mvp_dict["dashboard"] = str(dashboard_id)

    # Title is required
    mvp_dict["title"] = dashboard_data.get("title", "Untitled Dashboard")

    # Version (only include if not default)
    version = dashboard_data.get("version", 1)
    if version != 1:
        mvp_dict["version"] = version

    # Subtitle (only include if meaningful)
    subtitle = dashboard_data.get("subtitle", "")
    if subtitle and subtitle.strip():
        mvp_dict["subtitle"] = subtitle

    # Convert components
    stored_metadata = dashboard_data.get("stored_metadata", [])
    mvp_dict["components"] = [
        _build_mvp_component(comp, idx) for idx, comp in enumerate(stored_metadata)
    ]

    return mvp_dict


def dashboard_to_yaml_dict(
    dashboard_data: dict,
    compact_mode: bool = True,
    include_metadata: bool = False,
) -> dict:
    """
    Convert dashboard data to compact YAML-ready dictionary.

    Optimizations in compact mode (75-80% size reduction):
    - Replace full dc_config with compact dc_ref (id, tag, type, description)
    - Replace wf_id/wf_name with compact wf_ref (id, name)
    - Remove cols_json entirely (regenerated on import)
    - Omit null and empty string fields
    - Filter out default dict_kwargs parameters
    - Simplify layout (omit moved/static false defaults)

    Args:
        dashboard_data: Full dashboard dictionary (from model_dump or MongoDB)
        compact_mode: Enable compact reference mode (default: True)
        include_metadata: Include export metadata header (default: False)

    Returns:
        Compact or full dictionary ready for YAML serialization
    """
    # If compact mode disabled, return original data with basic conversion
    if not compact_mode:
        result = convert_for_yaml(dashboard_data)
        if include_metadata:
            result = {
                "_export_metadata": {
                    "format_version": "1.0",
                    "exported_at": datetime.now().isoformat(),
                    "source": "depictio",
                },
                **result,
            }
        return result

    # Build compact dashboard dict
    compact_dict: dict[str, Any] = {}

    # Add export metadata if requested
    if include_metadata:
        compact_dict["_export_metadata"] = {
            "format_version": "2.0",  # Indicate compact format
            "exported_at": datetime.now().isoformat(),
            "source": "depictio",
        }

    # Essential dashboard fields (always include)
    essential_fields = [
        "dashboard_id",
        "id",  # Include both dashboard_id and id for compatibility
        "title",
        "version",
    ]
    for field in essential_fields:
        if field in dashboard_data and dashboard_data[field] is not None:
            compact_dict[field] = convert_for_yaml(dashboard_data[field])

    # Optional dashboard fields (include if not empty/null)
    optional_fields = [
        "subtitle",
        "icon",
        "icon_color",
        "icon_variant",
        "description",
        "notes_content",
        "is_public",
        "permissions",
        "project_name",
        "workflow_system",
    ]
    for field in optional_fields:
        value = dashboard_data.get(field)
        if value is not None and value != "":
            compact_dict[field] = convert_for_yaml(value)

    # Process components with compact references
    stored_metadata = dashboard_data.get("stored_metadata", [])
    compact_components = []

    for comp in stored_metadata:
        # Build compact component
        compact_comp: dict[str, Any] = {
            "index": comp.get("index"),
            "component_type": comp.get("component_type"),
        }

        # Add title if present and not empty
        if comp.get("title"):
            compact_comp["title"] = comp["title"]

        # Build dc_ref (compact data collection reference)
        dc_config = comp.get("dc_config", {})
        if dc_config:
            dc_ref = {
                "id": str(dc_config.get("id", "")),
                "tag": dc_config.get("data_collection_tag", comp.get("dc_id", "unknown")),
                "type": dc_config.get("type", "table"),
            }
            # Add description if meaningful (not null/empty)
            dc_description = dc_config.get("description")
            if dc_description:
                dc_ref["description"] = dc_description
            else:
                # Generate default description from type
                dc_ref["description"] = f"{dc_ref['type']} data"

            compact_comp["dc_ref"] = dc_ref

        # Build wf_ref (compact workflow reference) if workflow present
        wf_id = comp.get("wf_id")
        wf_name = comp.get("wf_name")
        if wf_id:
            wf_ref = {
                "id": str(wf_id),
                "name": wf_name or "unknown",
            }
            compact_comp["wf_ref"] = wf_ref

        # Filter and add dict_kwargs (remove defaults)
        dict_kwargs = comp.get("dict_kwargs", {})
        if dict_kwargs:
            filtered_kwargs = filter_defaults(dict_kwargs, comp.get("component_type", "figure"))
            if filtered_kwargs:  # Only add if non-empty after filtering
                compact_comp["dict_kwargs"] = filtered_kwargs

        # Add visu_type for figure components
        if comp.get("visu_type"):
            compact_comp["visu_type"] = comp["visu_type"]

        # Add value for card components
        if comp.get("value") is not None:
            compact_comp["value"] = comp["value"]

        # Add other optional fields if present
        optional_comp_fields = ["parent_index", "filter_applied", "mode"]
        for field in optional_comp_fields:
            value = comp.get(field)
            if value is not None and value != "":
                compact_comp[field] = convert_for_yaml(value)

        # Note: We intentionally omit:
        # - dc_config (full config - will be retrieved from MongoDB on import)
        # - cols_json (column stats - will be regenerated on import)
        # - dc_id (replaced by dc_ref.id)
        # - wf_name (included in wf_ref)
        # - last_updated, displayed_data_count, total_data_count, was_sampled
        #   (runtime metadata, not needed for declarative config)

        compact_components.append(compact_comp)

    compact_dict["stored_metadata"] = compact_components

    # Simplify layout data (keep structure but omit moved/static false defaults)
    stored_layout_data = dashboard_data.get("stored_layout_data", [])
    if stored_layout_data:
        simplified_layout = []
        for layout in stored_layout_data:
            simplified = {
                "w": layout["w"],
                "h": layout["h"],
                "x": layout["x"],
                "y": layout["y"],
                "i": layout["i"],
            }
            # Only include moved/static if true (omit false defaults)
            if layout.get("moved") is True:
                simplified["moved"] = True
            if layout.get("static") is True:
                simplified["static"] = True

            simplified_layout.append(simplified)

        compact_dict["stored_layout_data"] = simplified_layout

    # Include other essential arrays if present (but omit empty ones)
    for field in ["left_panel_layout_data", "right_panel_layout_data"]:
        value = dashboard_data.get(field, [])
        if value:  # Only include if non-empty
            compact_dict[field] = convert_for_yaml(value)

    # Include buttons_data if present and not default
    buttons_data = dashboard_data.get("buttons_data")
    if buttons_data:
        compact_dict["buttons_data"] = convert_for_yaml(buttons_data)

    # Note: We intentionally omit:
    # - tmp_children_data (always empty)
    # - stored_children_data (always empty)
    # - hash, flexible_metadata, description (if null)

    return compact_dict


def yaml_mvp_to_dashboard(yaml_dict: dict) -> dict:
    """
    Convert MVP YAML dictionary back to full MongoDB dashboard format.

    Reconstructs all omitted data:
    - Generates UUIDs for component indices
    - Resolves data tags to full dc_config from MongoDB
    - Auto-generates layout
    - Fills in all MongoDB-required fields (runtime state, etc.)

    Args:
        yaml_dict: MVP dictionary from YAML file

    Returns:
        Full dashboard dictionary ready for MongoDB insertion

    Raises:
        ValueError: If required data collection not found in MongoDB
    """
    # Lazy imports to avoid circular dependencies
    import os

    import pymongo

    from depictio.api.v1.configs.config import settings

    # Build full dashboard dict
    full_dict: dict[str, Any] = {}

    # Dashboard ID (MVP uses "dashboard" instead of "dashboard_id")
    dashboard_id = yaml_dict.get("dashboard", yaml_dict.get("dashboard_id"))
    if dashboard_id:
        full_dict["dashboard_id"] = str(dashboard_id)
        full_dict["id"] = str(dashboard_id)  # Also set id for compatibility

    # Essential fields
    full_dict["title"] = yaml_dict.get("title", "Untitled Dashboard")
    full_dict["version"] = yaml_dict.get("version", 1)

    # Optional fields with defaults
    full_dict["subtitle"] = yaml_dict.get("subtitle", "")
    full_dict["icon"] = yaml_dict.get("icon")
    full_dict["icon_color"] = yaml_dict.get("icon_color")
    full_dict["icon_variant"] = yaml_dict.get("icon_variant")
    full_dict["description"] = yaml_dict.get("description")
    full_dict["notes_content"] = yaml_dict.get("notes_content", "")
    full_dict["is_public"] = yaml_dict.get("is_public", False)
    full_dict["workflow_system"] = yaml_dict.get("workflow_system", "none")
    full_dict["flexible_metadata"] = yaml_dict.get("flexible_metadata")
    full_dict["hash"] = yaml_dict.get("hash")

    # Permissions (use empty if not provided)
    full_dict["permissions"] = yaml_dict.get(
        "permissions",
        {
            "owners": [],
            "editors": [],
            "viewers": [],
        },
    )

    # Connect to MongoDB for data collection lookups
    context = os.getenv("DEPICTIO_CONTEXT", "client")
    if context == "server":
        mongo_host = settings.mongodb.service_name
    else:
        mongo_host = "localhost"

    mongo_url = f"mongodb://{mongo_host}:{settings.mongodb.service_port}"
    logger.debug(f"MVP import: Connecting to MongoDB at {mongo_url}")

    client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client[settings.mongodb.db_name]
    collection = db[settings.mongodb.collections.data_collection]

    # Process components - expand MVP format to full format
    mvp_components = yaml_dict.get("components", [])
    full_components = []

    for idx, mvp_comp in enumerate(mvp_components):
        # Generate UUID for component index
        comp_uuid = str(uuid.uuid4())

        full_comp: dict[str, Any] = {
            "index": comp_uuid,
            "component_type": mvp_comp.get("type", "figure"),
            "title": mvp_comp.get("id", f"component-{idx + 1}"),  # Use MVP id as title
        }

        # Resolve data tag to full dc_config
        # Support both "data_collection" (new) and "data" (legacy) for backwards compatibility
        data_tag = mvp_comp.get("data_collection") or mvp_comp.get("data")
        if data_tag:
            # Try tag lookup first
            dc_doc = collection.find_one({"data_collection_tag": data_tag})

            # Fallback: treat as ObjectId if tag lookup fails
            if not dc_doc:
                try:
                    dc_doc = collection.find_one({"_id": ObjectId(data_tag)})
                except Exception:
                    pass

            if not dc_doc:
                logger.error(f"Data collection not found for tag: {data_tag}")
                raise ValueError(f"Data collection not found: {data_tag}")

            # Extract full dc_config
            full_comp["dc_config"] = {
                "id": str(dc_doc["_id"]),
                "type": dc_doc.get("type"),
                "metatype": dc_doc.get("metatype"),
                "description": dc_doc.get("description"),
                "flexible_metadata": dc_doc.get("flexible_metadata"),
                "hash": dc_doc.get("hash"),
                "scan": dc_doc.get("scan"),
                "dc_specific_properties": dc_doc.get("dc_specific_properties"),
                "join": dc_doc.get("join"),
                "data_collection_tag": dc_doc.get("data_collection_tag"),
            }
            full_comp["dc_id"] = str(dc_doc["_id"])

        # Reconstruct dict_kwargs from MVP format
        dict_kwargs = {}
        visu_type = None

        if full_comp["component_type"] == "figure":
            # Extract chart type
            visu_type = mvp_comp.get("chart", "scatter")

            # Map MVP fields back to dict_kwargs
            for field in ["x", "y", "color", "size", "facet_row", "facet_col"]:
                if field in mvp_comp:
                    dict_kwargs[field] = mvp_comp[field]

            # Extract style parameters
            style = mvp_comp.get("style", {})
            for k, v in style.items():
                # Map back to full parameter names
                if k == "colors" or k == "map":
                    dict_kwargs["color_discrete_map"] = v
                elif k == "scale":
                    dict_kwargs["color_continuous_scale"] = v
                else:
                    dict_kwargs[k] = v

            # Apply defaults
            dict_kwargs.setdefault("template", "mantine_light")
            dict_kwargs.setdefault("orientation", "v")
            dict_kwargs.setdefault("log_x", False)
            dict_kwargs.setdefault("log_y", False)

        full_comp["dict_kwargs"] = dict_kwargs
        if visu_type:
            full_comp["visu_type"] = visu_type

        # Value for interactive/card components
        if "value" in mvp_comp:
            full_comp["value"] = mvp_comp["value"]

        # Add workflow reference (default unknown)
        full_comp["wf_id"] = None
        full_comp["wf_name"] = None

        # Add runtime metadata
        full_comp["parent_index"] = None
        full_comp["filter_applied"] = False
        full_comp["last_updated"] = datetime.now().isoformat()
        full_comp["mode"] = "ui"
        full_comp["displayed_data_count"] = 0
        full_comp["total_data_count"] = 0
        full_comp["was_sampled"] = False
        full_comp["cols_json"] = {}

        full_components.append(full_comp)

    full_dict["stored_metadata"] = full_components

    # Auto-generate layout (MVP always regenerates layout)
    generated_layout = []
    for idx, comp in enumerate(full_components):
        layout = auto_generate_layout(idx, comp.get("component_type", "figure"))
        # Use actual component UUID in layout
        layout["i"] = f"box-{comp['index']}"
        generated_layout.append(layout)

    full_dict["stored_layout_data"] = generated_layout

    # Add empty arrays
    full_dict["tmp_children_data"] = []
    full_dict["stored_children_data"] = []
    full_dict["left_panel_layout_data"] = []
    full_dict["right_panel_layout_data"] = []

    # Add default buttons_data
    full_dict["buttons_data"] = {
        "unified_edit_mode": True,
        "add_components_button": {"count": 0},
    }

    return full_dict


def yaml_dict_to_dashboard(
    yaml_dict: dict,
    regenerate_stats: bool = True,
    auto_layout: bool = False,
) -> dict:
    """
    Convert compact YAML dictionary back to full dashboard data.

    Reconstructs omitted data:
    - Resolves dc_ref to full dc_config from MongoDB
    - Regenerates cols_json from data source (if regenerate_stats=True)
    - Applies default dict_kwargs parameters
    - Auto-generates layout if missing (if auto_layout=True)

    Args:
        yaml_dict: Compact dictionary from YAML file
        regenerate_stats: Regenerate column statistics from data source
        auto_layout: Auto-generate layout if missing

    Returns:
        Full dashboard dictionary ready for model instantiation

    Raises:
        ValueError: If required data collection not found in MongoDB
    """
    # Strip export metadata if present
    yaml_dict.pop("_export_metadata", None)

    # Check if this is compact format (version 2.0 or has dc_ref)
    is_compact = any("dc_ref" in comp for comp in yaml_dict.get("stored_metadata", []))

    # If not compact format, just process normally
    if not is_compact:
        return convert_from_yaml(yaml_dict)

    # Lazy import to avoid circular dependencies
    from depictio.api.v1.configs.config import settings

    # Build full dashboard dict
    full_dict = dict(yaml_dict)  # Start with all provided fields

    # Process components - resolve references to full configs
    stored_metadata = yaml_dict.get("stored_metadata", [])
    full_components = []

    for idx, comp in enumerate(stored_metadata):
        # Build full component starting with all provided fields
        full_comp = dict(comp)

        # Resolve dc_ref to full dc_config if present
        if "dc_ref" in comp:
            dc_ref = comp["dc_ref"]
            dc_id = dc_ref["id"]

            # Look up data collection in MongoDB
            # Use sync pymongo for compatibility
            import os

            import pymongo

            # Build MongoDB connection string based on context
            context = os.getenv("DEPICTIO_CONTEXT", "client")
            if context == "server":
                mongo_host = settings.mongodb.service_name
            else:
                # Use localhost for client/CLI context
                mongo_host = "localhost"

            mongo_url = f"mongodb://{mongo_host}:{settings.mongodb.service_port}"
            logger.debug(f"Connecting to MongoDB at: {mongo_url}")

            client = pymongo.MongoClient(
                mongo_url,
                serverSelectionTimeoutMS=5000,  # 5 second timeout
            )
            db = client[settings.mongodb.db_name]
            collection = db[settings.mongodb.collections.data_collection]

            dc_doc = collection.find_one({"_id": ObjectId(dc_id)})
            if not dc_doc:
                logger.error(
                    f"Data collection not found: {dc_id}\n"
                    f"Tag: {dc_ref.get('tag')}, Type: {dc_ref.get('type')}\n"
                    f"Description: {dc_ref.get('description')}"
                )
                raise ValueError(f"Data collection not found: {dc_id}")

            # Validate metadata matches (catch ID mismatches)
            if dc_doc.get("data_collection_tag") != dc_ref.get("tag"):
                logger.warning(
                    f"DC tag mismatch for component {idx}: "
                    f"YAML has '{dc_ref.get('tag')}', "
                    f"MongoDB has '{dc_doc.get('data_collection_tag')}'"
                )

            # Extract full dc_config from MongoDB document
            # Convert ObjectId fields to strings for YAML compatibility
            full_dc_config = {
                "id": str(dc_doc["_id"]),
                "type": dc_doc.get("type"),
                "metatype": dc_doc.get("metatype"),
                "description": dc_doc.get("description"),
                "flexible_metadata": dc_doc.get("flexible_metadata"),
                "hash": dc_doc.get("hash"),
                "scan": dc_doc.get("scan"),
                "dc_specific_properties": dc_doc.get("dc_specific_properties"),
                "join": dc_doc.get("join"),
                "data_collection_tag": dc_doc.get("data_collection_tag"),
            }

            # Add full dc_config to component
            full_comp["dc_config"] = full_dc_config

            # Also add dc_id for compatibility
            full_comp["dc_id"] = str(dc_doc["_id"])

            # Remove dc_ref (replaced with full dc_config)
            del full_comp["dc_ref"]

        # Resolve wf_ref to wf_id/wf_name if present
        if "wf_ref" in comp:
            wf_ref = comp["wf_ref"]
            full_comp["wf_id"] = wf_ref["id"]
            full_comp["wf_name"] = wf_ref.get("name", "unknown")
            del full_comp["wf_ref"]

        # Apply default parameters to dict_kwargs if needed
        dict_kwargs = comp.get("dict_kwargs", {})
        component_type = comp.get("component_type", "figure")

        # Merge with defaults
        if component_type.lower() == "figure":
            defaults = {
                "template": "mantine_light",
                "orientation": "v",
                "log_x": False,
                "log_y": False,
                "category_orders": "",
                "labels": "",
                "color_discrete_sequence": "",
                "title": "",
            }
            # Merge defaults with provided kwargs (provided values take precedence)
            full_kwargs = {**defaults, **dict_kwargs}
            full_comp["dict_kwargs"] = full_kwargs

        # Regenerate column statistics if requested (for interactive/table components)
        if regenerate_stats and component_type in [
            "InteractiveComponent",
            "TableComponent",
            "figure",
        ]:
            # Note: Actual stats regeneration would require loading the data
            # For now, we'll add an empty cols_json and let the frontend regenerate
            full_comp["cols_json"] = {}

        # Add default runtime metadata if missing
        full_comp.setdefault("parent_index", None)
        full_comp.setdefault("filter_applied", False)
        full_comp.setdefault("last_updated", datetime.now().isoformat())
        full_comp.setdefault("mode", "ui")
        full_comp.setdefault("displayed_data_count", 0)
        full_comp.setdefault("total_data_count", 0)
        full_comp.setdefault("was_sampled", False)

        full_components.append(full_comp)

    full_dict["stored_metadata"] = full_components

    # Auto-generate layout if missing and requested
    if auto_layout and not full_dict.get("stored_layout_data"):
        generated_layout = []
        for idx, comp in enumerate(full_components):
            layout = auto_generate_layout(idx, comp.get("component_type", "figure"))
            generated_layout.append(layout)
        full_dict["stored_layout_data"] = generated_layout

    # Fill in layout defaults (moved=false, static=false) if missing
    stored_layout_data = full_dict.get("stored_layout_data", [])
    for layout in stored_layout_data:
        layout.setdefault("moved", False)
        layout.setdefault("static", False)

    # Add default empty arrays if missing
    full_dict.setdefault("tmp_children_data", [])
    full_dict.setdefault("stored_children_data", [])
    full_dict.setdefault("left_panel_layout_data", [])
    full_dict.setdefault("right_panel_layout_data", [])

    # Add default buttons_data if missing
    if "buttons_data" not in full_dict:
        full_dict["buttons_data"] = {
            "unified_edit_mode": True,
            "add_components_button": {"count": 0},
        }

    # Ensure essential fields are present
    full_dict.setdefault("description", None)
    full_dict.setdefault("flexible_metadata", None)
    full_dict.setdefault("hash", None)
    full_dict.setdefault("workflow_system", "none")
    full_dict.setdefault("notes_content", "")
    full_dict.setdefault("is_public", False)

    return full_dict


def dashboard_to_yaml(
    dashboard_data: dict,
    include_metadata: bool = True,
    compact_mode: bool = True,
    mvp_mode: bool = False,
    db_client: Any = None,
) -> str:
    """
    Convert a dashboard document to YAML string.

    Args:
        dashboard_data: Dashboard data as dictionary (from model_dump or MongoDB)
        include_metadata: Whether to include export metadata (timestamp, version)
        compact_mode: Use compact format with references (75-80% size reduction)
        mvp_mode: Use MVP minimal format (60-80 lines, human-readable, no layout)
        db_client: Optional MongoDB client for tag enrichment (MVP mode only)

    Returns:
        YAML string representation of the dashboard
    """
    # Use MVP format if enabled (takes precedence over compact)
    if mvp_mode:
        # Enrich with actual tags from MongoDB before converting to MVP
        enriched_data = enrich_dashboard_with_tags(dashboard_data, db_client=db_client)
        yaml_data = dashboard_to_yaml_mvp(enriched_data)
    # Use compact export if enabled
    elif compact_mode:
        yaml_data = dashboard_to_yaml_dict(
            dashboard_data,
            compact_mode=True,
            include_metadata=include_metadata,
        )
    else:
        # Legacy full export
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
        indent=4,
    )


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

    # Auto-detect format
    # MVP format: has "components" array with "data_collection" or "data" tags and no "stored_metadata"
    is_mvp = False
    if "components" in data and "stored_metadata" not in data:
        # Check if components have MVP structure (id, type, data_collection/data)
        components = data.get("components", [])
        if components and isinstance(components, list):
            first_comp = components[0]
            if (
                isinstance(first_comp, dict)
                and ("data_collection" in first_comp or "data" in first_comp)
                and "type" in first_comp
            ):
                is_mvp = True

    # Compact format: has dc_ref or format_version 2.0
    is_compact = False
    if not is_mvp:
        metadata = data.get("_export_metadata", {})
        if metadata.get("format_version") == "2.0":
            is_compact = True
        elif any("dc_ref" in comp for comp in data.get("stored_metadata", [])):
            is_compact = True

    # Process based on format
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
        # Legacy format - strip metadata and convert
        logger.info("Detected legacy YAML format")
        data.pop("_export_metadata", None)
        return convert_from_yaml(data)


def export_dashboard_to_file(
    dashboard_data: dict,
    filepath: str | Path,
    include_metadata: bool = True,
    compact_mode: bool = True,
    mvp_mode: bool = False,
) -> Path:
    """
    Export a dashboard to a YAML file.

    Args:
        dashboard_data: Dashboard data as dictionary
        filepath: Destination file path
        include_metadata: Include export metadata (default: True)
        compact_mode: Use compact format (default: True)
        mvp_mode: Use MVP minimal format (default: False)

    Returns:
        Path to the written file
    """
    filepath = Path(filepath)

    # Ensure .yaml extension
    if filepath.suffix not in (".yaml", ".yml"):
        filepath = filepath.with_suffix(".yaml")

    yaml_content = dashboard_to_yaml(
        dashboard_data,
        include_metadata=include_metadata,
        compact_mode=compact_mode,
        mvp_mode=mvp_mode,
    )

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(yaml_content, encoding="utf-8")

    mode_desc = "MVP" if mvp_mode else ("compact" if compact_mode else "full")
    logger.info(f"Dashboard exported to {filepath} ({mode_desc} format)")
    return filepath


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
        indent=4,
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
        indent=4,
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
    compact_mode: bool | None = None,
    mvp_mode: bool | None = None,
    db_client: Any = None,
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
        compact_mode: Override compact_mode setting
        mvp_mode: Override mvp_mode setting
        db_client: Optional MongoDB client for tag enrichment (MVP mode only)

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
    if compact_mode is None:
        compact_mode = yaml_config.compact_mode
    if mvp_mode is None:
        mvp_mode = yaml_config.mvp_mode

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
    yaml_content = dashboard_to_yaml(
        dashboard_data,
        include_metadata=include_metadata,
        compact_mode=compact_mode,
        mvp_mode=mvp_mode,
        db_client=db_client,
    )

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(yaml_content, encoding="utf-8")

    mode_desc = "MVP" if mvp_mode else ("compact" if compact_mode else "full")
    logger.info(f"Dashboard exported to YAML directory ({mode_desc} format): {filepath}")
    return filepath


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

    # If relative path, resolve against base_dir
    if not filepath.is_absolute():
        base_dir = Path(settings.dashboard_yaml.yaml_dir_path)
        filepath = base_dir / filepath

    # Get settings for import behavior
    yaml_config = settings.dashboard_yaml
    if regenerate_stats is None:
        regenerate_stats = yaml_config.regenerate_stats
    if auto_layout is None:
        auto_layout = yaml_config.auto_layout

    # Read and parse YAML
    if not filepath.exists():
        raise FileNotFoundError(f"Dashboard file not found: {filepath}")

    yaml_content = filepath.read_text(encoding="utf-8")
    return yaml_to_dashboard_dict(
        yaml_content,
        regenerate_stats=regenerate_stats,
        auto_layout=auto_layout,
    )


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
