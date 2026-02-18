"""
Shared utilities for YAML serialization.

Contains common functions used across export/import and format modules.
"""

import hashlib
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from bson import ObjectId
from pydantic import BaseModel

from depictio.models.logging import logger


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
    - ObjectId -> string
    - datetime -> ISO format string
    - Path -> string
    - Nested dicts and lists
    - Pydantic models -> dict

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


def sanitize_filename(name: str) -> str:
    """
    Sanitize a string to be safe for use as a filename.

    Args:
        name: The string to sanitize

    Returns:
        Sanitized filename-safe string
    """
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_")


def _compute_component_hash(component: dict) -> str:
    """
    Compute a 6-character hash from component metadata for unique identification.

    Args:
        component: Component dictionary

    Returns:
        6-character hash string (first 6 chars of MD5)
    """
    # Include only stable semantic fields — NOT internal DB IDs (workflow_id,
    # data_collection_id) which differ between import cycles and break round-trip
    # stability.
    # Use fallback field names to handle both old DB documents (wf_tag) and new ones
    # (workflow_tag) — mirrors the same resolution logic used in from_full().
    dc_config = component.get("dc_config", {})
    hash_fields = {
        "component_type": component.get("component_type", ""),
        "title": component.get("title", ""),
        "workflow_tag": component.get("workflow_tag") or component.get("wf_tag", ""),
        "data_collection_tag": component.get("data_collection_tag")
        or (dc_config.get("data_collection_tag", "") if isinstance(dc_config, dict) else ""),
        # Type-specific semantic fields
        "visu_type": component.get("visu_type", ""),
        "aggregation": component.get("aggregation", ""),
        "column_name": component.get("column_name", ""),
        "interactive_component_type": component.get("interactive_component_type", ""),
        "selected_module": component.get("selected_module", ""),
        "selected_plot": component.get("selected_plot", ""),
        "image_column": component.get("image_column", ""),
    }

    # Create deterministic string for hashing
    hash_string = "|".join(f"{k}:{v}" for k, v in sorted(hash_fields.items()) if v)

    # Return first 6 chars of MD5 hex digest
    return hashlib.md5(hash_string.encode()).hexdigest()[:6]


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
    col = index % 3
    row = index // 3

    sizes = {
        "figure": {"w": 16, "h": 12},
        "card": {"w": 16, "h": 6},
        "table": {"w": 48, "h": 20},
    }

    component_type_lower = component_type.lower().replace("component", "")
    size = sizes.get(component_type_lower, sizes["figure"])

    x_pos = col * 16
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

    Format: {component_type}-{semantic_identifier}-{hash[:6]}

    Examples:
    - "interactive-sampling_date-a3f4d2" for date picker on sampling_date
    - "card-sepal_length_average-7b2c8e" for card showing average
    - "figure-scatter-sepal_length-petal_width-9d4e1f" for scatter plot
    - "multiqc-fastqc_sequence_quality-2a5c3b" for MultiQC components

    Args:
        component: Component dictionary
        index: Component position in list

    Returns:
        Human-readable ID: {type}-{semantic_id}-{hash[:6]}
        Semantic ID preserves underscores, uses hyphens as separators
    """
    comp_type = component.get("component_type", "component")

    def sanitize(text: str) -> str:
        if not text:
            return ""
        # Preserve underscores, replace dots with underscores, other special chars with hyphens
        text = str(text).replace(".", "_").lower()
        return re.sub(r"[^a-z0-9_]+", "-", text).strip("-")

    # Compute 6-character hash for uniqueness
    comp_hash = _compute_component_hash(component)

    # Priority 1: Use existing index field if present AND it's a semantic identifier (not a UUID)
    existing_index = component.get("index", "")
    if existing_index and existing_index.strip():
        # Skip if it looks like a UUID (contains 4+ hyphens or is >30 chars)
        is_uuid_like = existing_index.count("-") >= 4 or len(existing_index) > 30
        if not is_uuid_like:
            semantic_id = sanitize(existing_index)
            return f"{comp_type}-{semantic_id}-{comp_hash}"

    # Priority 2: Generate semantic ID based on component type and data

    # MultiQC component
    if comp_type == "multiqc":
        module = component.get("selected_module", "")
        plot = component.get("selected_plot", "")
        if module and plot:
            semantic_id = f"{sanitize(module)}_{sanitize(plot)}"
        elif module:
            semantic_id = sanitize(module)
        else:
            semantic_id = "multiqc"
        return f"{comp_type}-{semantic_id}-{comp_hash}"

    # Image component
    elif comp_type == "image":
        image_column = component.get("image_column", "")
        semantic_id = sanitize(image_column) if image_column else "image"
        return f"{comp_type}-{semantic_id}-{comp_hash}"

    # Card component
    elif comp_type == "card":
        column = component.get("column_name", "")
        agg = component.get("aggregation", "")
        if column and agg:
            semantic_id = f"{sanitize(column)}_{sanitize(agg)}"
        elif column:
            semantic_id = sanitize(column)
        else:
            semantic_id = "card"
        return f"{comp_type}-{semantic_id}-{comp_hash}"

    # Interactive component
    elif comp_type in ("InteractiveComponent", "interactive"):
        column = component.get("column_name", "")
        semantic_id = sanitize(column) if column else "filter"
        return f"{comp_type}-{semantic_id}-{comp_hash}"

    # Figure component
    elif comp_type == "figure":
        visu_type = component.get("visu_type", "")
        dict_kwargs = component.get("dict_kwargs", {})
        x = dict_kwargs.get("x", "")
        y = dict_kwargs.get("y", "")

        parts = []
        if visu_type:
            parts.append(sanitize(visu_type))
        if x:
            parts.append(sanitize(x))
        if y:
            parts.append(sanitize(y))

        semantic_id = "_".join(parts) if parts else "figure"
        return f"{comp_type}-{semantic_id}-{comp_hash}"

    # Table component
    elif comp_type == "table":
        return f"{comp_type}-table-{comp_hash}"

    # Generic fallback: use title or generic name
    title = component.get("title", "")
    if title and title.strip():
        semantic_id = sanitize(title)[:40]
    else:
        semantic_id = comp_type.lower()

    return f"{comp_type}-{semantic_id}-{comp_hash}"


def filter_defaults(dict_kwargs: dict, component_type: str = "figure") -> dict:
    """
    Remove default values from component parameters to reduce YAML size.

    Args:
        dict_kwargs: Component parameters dictionary
        component_type: Type of component (figure, card, etc.)

    Returns:
        Filtered dictionary with only non-default values
    """
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

    filtered = {}
    for k, v in dict_kwargs.items():
        if k in defaults and v == defaults[k]:
            continue
        if v == "" or v is None:
            continue
        filtered[k] = v

    return filtered


def get_db_connection_for_enrichment(
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
    dc_collection_name = "data_collections"
    wf_collection_name = "workflows"

    try:
        from depictio.api.v1.configs.config import settings

        dc_collection_name = settings.mongodb.collections.data_collection
        wf_collection_name = settings.mongodb.collections.workflow_collection
    except ImportError:
        pass

    if db_client is not None:
        return db_client[db_name], dc_collection_name, wf_collection_name

    try:
        from depictio.api.v1.db import db

        return db, dc_collection_name, wf_collection_name
    except ImportError:
        logger.debug("Could not import MongoDB dependencies for tag enrichment, skipping")
        return None
    except Exception as e:
        logger.debug(f"MongoDB connection unavailable for tag enrichment: {e}")
        return None


def enrich_component_dc_tag(
    comp: dict,
    dc_cache: dict[str, dict | None],
    projects_collection: Any,
) -> None:
    """Enrich a component with data collection tag from MongoDB (nested in projects)."""
    dc_id = comp.get("dc_id")
    if not dc_id:
        return

    dc_id_str = str(dc_id)

    if dc_id_str not in dc_cache:
        try:
            # Search nested in projects (data collections are nested in workflows)
            dc_doc = None
            for project in projects_collection.find():
                if "workflows" in project:
                    for wf in project["workflows"]:
                        if "data_collections" in wf:
                            for dc in wf["data_collections"]:
                                if str(dc.get("_id")) == str(dc_id):
                                    dc_doc = dc
                                    break
                        if dc_doc:
                            break
                if dc_doc:
                    break
            dc_cache[dc_id_str] = dc_doc
        except Exception as e:
            logger.debug(f"Failed to lookup data collection {dc_id}: {e}")
            dc_cache[dc_id_str] = None

    dc_doc = dc_cache[dc_id_str]
    if not dc_doc:
        logger.warning(f"Data collection document not found for dc_id: {dc_id}")
        return

    if "dc_config" not in comp:
        comp["dc_config"] = {}

    tag = dc_doc.get("data_collection_tag") or dc_doc.get("name")
    if tag:
        comp["dc_config"]["data_collection_tag"] = tag
        logger.debug(f"Enriched component with dc_tag: {tag}")
    else:
        logger.warning(
            f"Data collection {dc_id} found but has no 'data_collection_tag' or 'name' field. "
            f"Available fields: {list(dc_doc.keys())}"
        )
    comp["dc_config"]["id"] = dc_id_str
    comp["dc_config"]["type"] = dc_doc.get("type", "table")


def enrich_component_wf_tag(
    comp: dict,
    wf_cache: dict[str, dict | None],
    projects_collection: Any,
) -> None:
    """Enrich a component with workflow tag from MongoDB (nested in projects)."""
    wf_id = comp.get("wf_id")
    if not wf_id:
        return

    wf_id_str = str(wf_id)

    if wf_id_str not in wf_cache:
        try:
            # Search nested in projects
            wf_doc = None
            for project in projects_collection.find():
                if "workflows" in project:
                    for wf in project["workflows"]:
                        if str(wf.get("_id")) == str(wf_id):
                            wf_doc = wf
                            break
                if wf_doc:
                    break
            wf_cache[wf_id_str] = wf_doc
        except Exception as e:
            logger.debug(f"Failed to lookup workflow {wf_id}: {e}")
            wf_cache[wf_id_str] = None

    wf_doc = wf_cache[wf_id_str]
    if not wf_doc:
        logger.warning(f"Workflow document not found for wf_id: {wf_id}")
        return

    wf_tag = wf_doc.get("workflow_tag") or wf_doc.get("name")
    if wf_tag:
        comp["workflow_tag"] = wf_tag  # Set workflow_tag (not wf_name!)
        logger.debug(f"Enriched component with workflow_tag: {wf_tag}")
    else:
        logger.warning(
            f"Workflow {wf_id} found but has no 'workflow_tag' or 'name' field. "
            f"Available fields: {list(wf_doc.keys())}"
        )


def enrich_dashboard_with_tags(
    dashboard_data: dict,
    db_client: Any = None,
    db_name: str = "depictioDB",
) -> dict:
    """
    Enrich dashboard components with data_collection_tag and workflow tags from MongoDB.

    Looks up dc_id and wf_id nested in project workflows to get human-readable tags.

    Args:
        dashboard_data: Dashboard dictionary from MongoDB
        db_client: Optional MongoDB client to use (if None, tries to import from depictio.api.v1.db)
        db_name: Database name to use if db_client is provided (default: "depictioDB")

    Returns:
        Enriched dashboard dictionary with tags in dc_config
    """
    db_connection = get_db_connection_for_enrichment(db_client, db_name)
    if db_connection is None:
        return dashboard_data

    db, dc_collection_name, wf_collection_name = db_connection

    # Get projects collection (workflows and data collections are nested in projects)
    from depictio.api.v1.configs.config import settings

    projects_collection = db[settings.mongodb.collections.projects_collection]

    dc_cache: dict[str, dict | None] = {}
    wf_cache: dict[str, dict | None] = {}

    for comp in dashboard_data.get("stored_metadata", []):
        enrich_component_dc_tag(comp, dc_cache, projects_collection)
        enrich_component_wf_tag(comp, wf_cache, projects_collection)

    return dashboard_data


def dump_yaml(data: dict) -> str:
    """
    Dump a dictionary to YAML string using configured dumper.

    Args:
        data: Dictionary to dump

    Returns:
        YAML string
    """
    return yaml.dump(
        data,
        Dumper=DashboardYAMLDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
        indent=4,
    )
