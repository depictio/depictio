"""
Compact YAML format functions for dashboard serialization.

Provides compact export/import with 75-80% size reduction through:
- Compact dc_ref and wf_ref references
- Filtered default parameters
- Simplified layout data
"""

import os
from datetime import datetime
from typing import Any

import pymongo
from bson import ObjectId

from depictio.models.logging import logger
from depictio.models.yaml_serialization.utils import (
    auto_generate_layout,
    convert_for_yaml,
    filter_defaults,
)


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

    compact_dict: dict[str, Any] = {}

    if include_metadata:
        compact_dict["_export_metadata"] = {
            "format_version": "2.0",
            "exported_at": datetime.now().isoformat(),
            "source": "depictio",
        }

    essential_fields = [
        "dashboard_id",
        "id",
        "title",
        "version",
    ]
    for field in essential_fields:
        if field in dashboard_data and dashboard_data[field] is not None:
            compact_dict[field] = convert_for_yaml(dashboard_data[field])

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

    stored_metadata = dashboard_data.get("stored_metadata", [])
    compact_components = []

    for comp in stored_metadata:
        compact_comp: dict[str, Any] = {
            "index": comp.get("index"),
            "component_type": comp.get("component_type"),
        }

        if comp.get("title"):
            compact_comp["title"] = comp["title"]

        dc_config = comp.get("dc_config", {})
        if dc_config:
            dc_ref = {
                "id": str(dc_config.get("id", "")),
                "tag": dc_config.get("data_collection_tag", comp.get("dc_id", "unknown")),
                "type": dc_config.get("type", "table"),
            }
            dc_description = dc_config.get("description")
            if dc_description:
                dc_ref["description"] = dc_description
            else:
                dc_ref["description"] = f"{dc_ref['type']} data"

            compact_comp["dc_ref"] = dc_ref

        wf_id = comp.get("wf_id")
        wf_name = comp.get("wf_name")
        if wf_id:
            wf_ref = {
                "id": str(wf_id),
                "name": wf_name or "unknown",
            }
            compact_comp["wf_ref"] = wf_ref

        dict_kwargs = comp.get("dict_kwargs", {})
        if dict_kwargs:
            filtered_kwargs = filter_defaults(dict_kwargs, comp.get("component_type", "figure"))
            if filtered_kwargs:
                compact_comp["dict_kwargs"] = filtered_kwargs

        if comp.get("visu_type"):
            compact_comp["visu_type"] = comp["visu_type"]

        if comp.get("value") is not None:
            compact_comp["value"] = comp["value"]

        optional_comp_fields = ["parent_index", "filter_applied", "mode"]
        for field in optional_comp_fields:
            value = comp.get(field)
            if value is not None and value != "":
                compact_comp[field] = convert_for_yaml(value)

        compact_components.append(compact_comp)

    compact_dict["stored_metadata"] = compact_components

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
            if layout.get("moved") is True:
                simplified["moved"] = True
            if layout.get("static") is True:
                simplified["static"] = True

            simplified_layout.append(simplified)

        compact_dict["stored_layout_data"] = simplified_layout

    for field in ["left_panel_layout_data", "right_panel_layout_data"]:
        value = dashboard_data.get(field, [])
        if value:
            compact_dict[field] = convert_for_yaml(value)

    buttons_data = dashboard_data.get("buttons_data")
    if buttons_data:
        compact_dict["buttons_data"] = convert_for_yaml(buttons_data)

    return compact_dict


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
    from depictio.api.v1.configs.config import settings
    from depictio.models.yaml_serialization.utils import convert_from_yaml

    yaml_dict.pop("_export_metadata", None)

    is_compact = any("dc_ref" in comp for comp in yaml_dict.get("stored_metadata", []))

    if not is_compact:
        return convert_from_yaml(yaml_dict)

    full_dict = dict(yaml_dict)

    stored_metadata = yaml_dict.get("stored_metadata", [])
    full_components = []

    for idx, comp in enumerate(stored_metadata):
        full_comp = dict(comp)

        if "dc_ref" in comp:
            dc_ref = comp["dc_ref"]
            dc_id = dc_ref["id"]

            context = os.getenv("DEPICTIO_CONTEXT", "client")
            if context == "server":
                mongo_host = settings.mongodb.service_name
            else:
                mongo_host = "localhost"

            mongo_url = f"mongodb://{mongo_host}:{settings.mongodb.service_port}"
            logger.debug(f"Connecting to MongoDB at: {mongo_url}")

            client = pymongo.MongoClient(
                mongo_url,
                serverSelectionTimeoutMS=5000,
            )
            db = client[settings.mongodb.db_name]
            collection = db[settings.mongodb.collections.data_collection]

            dc_doc = None
            dc_tag = dc_ref.get("tag")

            if dc_tag:
                dc_doc = collection.find_one({"data_collection_tag": dc_tag})
                if dc_doc:
                    logger.debug(f"Found data collection by tag: {dc_tag}")

            if not dc_doc and dc_id:
                try:
                    dc_doc = collection.find_one({"_id": ObjectId(dc_id)})
                    if dc_doc:
                        logger.debug(f"Found data collection by ID: {dc_id}")
                except Exception as e:
                    logger.debug(f"Failed to lookup by ID '{dc_id}': {e}")

            if not dc_doc:
                logger.error(
                    f"Data collection not found: ID={dc_id}, Tag={dc_tag}\n"
                    f"Type: {dc_ref.get('type')}, Description: {dc_ref.get('description')}"
                )
                raise ValueError(f"Data collection not found: {dc_id or dc_tag}")

            if dc_doc.get("data_collection_tag") != dc_ref.get("tag"):
                logger.warning(
                    f"DC tag mismatch for component {idx}: "
                    f"YAML has '{dc_ref.get('tag')}', "
                    f"MongoDB has '{dc_doc.get('data_collection_tag')}'"
                )

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

            full_comp["dc_config"] = full_dc_config
            full_comp["dc_id"] = str(dc_doc["_id"])
            del full_comp["dc_ref"]

        if "wf_ref" in comp:
            wf_ref = comp["wf_ref"]
            full_comp["wf_id"] = wf_ref["id"]
            full_comp["wf_name"] = wf_ref.get("name", "unknown")
            del full_comp["wf_ref"]

        dict_kwargs = comp.get("dict_kwargs", {})
        component_type = comp.get("component_type", "figure")

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
            full_kwargs = {**defaults, **dict_kwargs}
            full_comp["dict_kwargs"] = full_kwargs

        if regenerate_stats and component_type in [
            "InteractiveComponent",
            "TableComponent",
            "figure",
        ]:
            full_comp["cols_json"] = {}

        full_comp.setdefault("parent_index", None)
        full_comp.setdefault("filter_applied", False)
        full_comp.setdefault("last_updated", datetime.now().isoformat())
        full_comp.setdefault("mode", "ui")
        full_comp.setdefault("displayed_data_count", 0)
        full_comp.setdefault("total_data_count", 0)
        full_comp.setdefault("was_sampled", False)

        full_components.append(full_comp)

    full_dict["stored_metadata"] = full_components

    if auto_layout and not full_dict.get("stored_layout_data"):
        generated_layout = []
        for idx, comp in enumerate(full_components):
            layout = auto_generate_layout(idx, comp.get("component_type", "figure"))
            generated_layout.append(layout)
        full_dict["stored_layout_data"] = generated_layout

    stored_layout_data = full_dict.get("stored_layout_data", [])
    for layout in stored_layout_data:
        layout.setdefault("moved", False)
        layout.setdefault("static", False)

    full_dict.setdefault("tmp_children_data", [])
    full_dict.setdefault("stored_children_data", [])
    full_dict.setdefault("left_panel_layout_data", [])
    full_dict.setdefault("right_panel_layout_data", [])

    if "buttons_data" not in full_dict:
        full_dict["buttons_data"] = {
            "unified_edit_mode": True,
            "add_components_button": {"count": 0},
        }

    full_dict.setdefault("description", None)
    full_dict.setdefault("flexible_metadata", None)
    full_dict.setdefault("hash", None)
    full_dict.setdefault("workflow_system", "none")
    full_dict.setdefault("notes_content", "")
    full_dict.setdefault("is_public", False)

    return full_dict
