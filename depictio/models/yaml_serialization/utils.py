"""
Shared utilities for YAML serialization.

Contains common functions used across export/import and format modules.
"""

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
    comp_type = component.get("component_type", "component")

    def sanitize(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"[^a-z0-9]+", "-", str(text).replace(".", "-").lower()).strip("-")

    if comp_type == "card":
        column = component.get("column_name", "")
        agg = component.get("aggregation", "")
        if column and agg:
            return f"{sanitize(column)}-{sanitize(agg)}"
        return f"card-{index + 1}"

    elif comp_type in ("InteractiveComponent", "interactive"):
        column = component.get("column_name", "")
        if column:
            return f"{sanitize(column)}-filter"
        return f"filter-{index + 1}"

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

    elif comp_type == "table":
        return "data-table"

    title = component.get("title", "")
    if title and title.strip():
        base_id = sanitize(title)[:40]
        return base_id if base_id else f"{comp_type.lower()}-{index + 1}"

    return f"{comp_type.lower()}-{index + 1}"


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
    collection: Any,
) -> None:
    """Enrich a component with data collection tag from MongoDB."""
    dc_id = comp.get("dc_id")
    if not dc_id:
        return

    dc_id_str = str(dc_id)

    if dc_id_str not in dc_cache:
        try:
            dc_cache[dc_id_str] = collection.find_one({"_id": ObjectId(dc_id)})
        except Exception as e:
            logger.debug(f"Failed to lookup data collection {dc_id}: {e}")
            dc_cache[dc_id_str] = None

    dc_doc = dc_cache[dc_id_str]
    if not dc_doc:
        return

    if "dc_config" not in comp:
        comp["dc_config"] = {}

    tag = dc_doc.get("data_collection_tag") or dc_doc.get("name")
    if tag:
        comp["dc_config"]["data_collection_tag"] = tag
    comp["dc_config"]["id"] = dc_id_str
    comp["dc_config"]["type"] = dc_doc.get("type", "table")


def enrich_component_wf_tag(
    comp: dict,
    wf_cache: dict[str, dict | None],
    collection: Any,
) -> None:
    """Enrich a component with workflow tag from MongoDB."""
    wf_id = comp.get("wf_id")
    if not wf_id:
        return

    wf_id_str = str(wf_id)

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
    db_connection = get_db_connection_for_enrichment(db_client, db_name)
    if db_connection is None:
        return dashboard_data

    db, dc_collection_name, wf_collection_name = db_connection
    dc_collection = db[dc_collection_name]
    wf_collection = db[wf_collection_name]

    dc_cache: dict[str, dict | None] = {}
    wf_cache: dict[str, dict | None] = {}

    for comp in dashboard_data.get("stored_metadata", []):
        enrich_component_dc_tag(comp, dc_cache, dc_collection)
        enrich_component_wf_tag(comp, wf_cache, wf_collection)

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
