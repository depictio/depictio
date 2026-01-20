"""
MVP YAML format functions for dashboard serialization.

Provides minimal human-readable format (~60-80 lines) with:
- Human-readable component IDs
- Simplified data references using tags
- No layout data (auto-generated on import)
- Flat visualization configuration
"""

import os
import uuid
from datetime import datetime
from typing import Any

import pymongo
from bson import ObjectId

from depictio.models.logging import logger
from depictio.models.yaml_serialization.utils import (
    auto_generate_layout,
    filter_defaults,
    generate_component_id,
    get_db_connection_for_enrichment,
)

FIGURE_MAIN_PARAMS = frozenset({"x", "y", "color", "size", "facet_row", "facet_col"})


def _build_mvp_figure_config(comp: dict) -> dict[str, Any] | None:
    """Build MVP visualization config for figure components."""
    visu_type = comp.get("visu_type")
    if not visu_type:
        return None

    dict_kwargs = comp.get("dict_kwargs", {})
    viz_config: dict[str, Any] = {"chart": visu_type}
    style_params: dict[str, Any] = {}

    for key, value in filter_defaults(dict_kwargs, "figure").items():
        if key in FIGURE_MAIN_PARAMS:
            viz_config[key] = value
        elif key == "color_discrete_map":
            style_params["map"] = value
        elif key == "color_continuous_scale":
            style_params["scale"] = value
        else:
            style_params[key] = value

    if style_params:
        viz_config["style"] = style_params

    return viz_config


def _build_mvp_card_config(comp: dict) -> dict[str, Any] | None:
    """Build MVP aggregation config for card components."""
    field_mapping = {
        "column_name": "column",
        "aggregation": "function",
        "column_type": "column_type",
    }

    agg_config: dict[str, Any] = {}
    for source_field, target_field in field_mapping.items():
        value = comp.get(source_field)
        if value:
            agg_config[target_field] = value

    # Handle value separately (can be 0 which is falsy)
    value = comp.get("value")
    if value is not None:
        agg_config["value"] = value

    return agg_config if agg_config else None


CARD_STYLING_FIELDS = (
    "title_color",
    "icon_name",
    "icon_color",
    "title_font_size",
    "value_font_size",
    "metric_theme",
    "background_color",
)

INTERACTIVE_STYLING_FIELDS = (
    "custom_color",
    "icon_name",
    "title_size",
    "scale",
    "marks_number",
)


def _extract_styling_fields(comp: dict, fields: tuple[str, ...]) -> dict[str, Any] | None:
    """Extract styling fields from component into a styling config dict."""
    styling = {field: comp[field] for field in fields if comp.get(field) is not None}
    return styling if styling else None


def _build_mvp_card_styling(comp: dict) -> dict[str, Any] | None:
    """Build MVP styling config for card components."""
    return _extract_styling_fields(comp, CARD_STYLING_FIELDS)


def _build_mvp_interactive_config(comp: dict) -> dict[str, Any] | None:
    """Build MVP filter config for interactive components."""
    field_mapping = {
        "column_name": "column",
        "interactive_component_type": "type",
        "column_type": "column_type",
    }

    filter_config: dict[str, Any] = {}
    for source_field, target_field in field_mapping.items():
        value = comp.get(source_field)
        if value:
            filter_config[target_field] = value

    default_state = comp.get("default_state")
    if default_state and isinstance(default_state, dict):
        _apply_default_state_to_filter(default_state, filter_config)

    value = comp.get("value")
    if value is not None:
        filter_config["value"] = value

    return filter_config if filter_config else None


def _apply_default_state_to_filter(default_state: dict, filter_config: dict) -> None:
    """Apply default state configuration to filter config based on state type."""
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


def _build_mvp_interactive_styling(comp: dict) -> dict[str, Any] | None:
    """Build MVP styling config for interactive components."""
    return _extract_styling_fields(comp, INTERACTIVE_STYLING_FIELDS)


def _get_mvp_workflow_tag(comp: dict) -> str | None:
    """Get workflow tag for MVP export in engine/name format."""
    wf_id = comp.get("wf_id")
    if not wf_id:
        return None

    # Use wf_tag if available (should be engine/name format)
    wf_tag = comp.get("wf_tag")
    if wf_tag:
        return wf_tag

    # Fallback: try to construct from MongoDB
    try:
        mongo_result = get_db_connection_for_enrichment()
        if mongo_result:
            db, dc_collection_name, wf_collection_name = mongo_result
            # Try nested search in projects first
            from depictio.api.v1.configs.config import settings

            projects_collection = db[settings.mongodb.collections.projects_collection]
            for project in projects_collection.find():
                if "workflows" in project:
                    for wf in project["workflows"]:
                        if str(wf.get("_id")) == str(wf_id):
                            engine_name = wf.get("engine", {}).get("name", "unknown")
                            wf_name = wf.get("name", "")
                            return f"{engine_name}/{wf_name}"
    except Exception as e:
        logger.debug(f"Failed to lookup workflow for {wf_id}: {e}")

    return f"wf_{str(wf_id)[:8]}"


def _get_mvp_data_collection_tag(comp: dict) -> str | None:
    """Get data collection tag for MVP export, looking up from MongoDB if needed."""
    dc_config = comp.get("dc_config", {})
    if dc_config and dc_config.get("data_collection_tag"):
        return dc_config["data_collection_tag"]

    dc_id = comp.get("dc_id")
    if dc_id:
        try:
            mongo_result = get_db_connection_for_enrichment()
            if mongo_result:
                db, dc_collection_name, wf_collection_name = mongo_result
                dc_collection = db[dc_collection_name]
                dc_doc = dc_collection.find_one({"_id": ObjectId(str(dc_id))})
                if dc_doc and dc_doc.get("data_collection_tag"):
                    return dc_doc["data_collection_tag"]
        except Exception as e:
            logger.debug(f"Failed to lookup data collection tag for {dc_id}: {e}")

        return f"dc_{str(dc_id)[:8]}"

    return None


def _add_component_specific_config(mvp_comp: dict, comp: dict, comp_type: str) -> None:
    """Add type-specific configuration to MVP component."""
    if comp_type == "figure":
        viz_config = _build_mvp_figure_config(comp)
        if viz_config:
            mvp_comp["visualization"] = viz_config

    elif comp_type == "card":
        agg_config = _build_mvp_card_config(comp)
        if agg_config:
            mvp_comp["aggregation"] = agg_config
        styling = _build_mvp_card_styling(comp)
        if styling:
            mvp_comp["styling"] = styling

    elif comp_type in ("InteractiveComponent", "interactive"):
        filter_config = _build_mvp_interactive_config(comp)
        if filter_config:
            mvp_comp["filter"] = filter_config
        styling = _build_mvp_interactive_styling(comp)
        if styling:
            mvp_comp["styling"] = styling


def _build_mvp_component(comp: dict, idx: int) -> dict[str, Any]:
    """Build a single MVP component from full component data."""
    comp_type = comp.get("component_type", "figure")

    mvp_comp: dict[str, Any] = {
        "id": generate_component_id(comp, idx),
        "type": comp_type,
    }

    title = comp.get("title", "")
    if title and title.strip():
        mvp_comp["title"] = title

    wf_tag = _get_mvp_workflow_tag(comp)
    if wf_tag:
        mvp_comp["workflow"] = wf_tag

    data_tag = _get_mvp_data_collection_tag(comp)
    if data_tag:
        mvp_comp["data_collection"] = data_tag

    _add_component_specific_config(mvp_comp, comp, comp_type)

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

    dashboard_id = dashboard_data.get("dashboard_id", dashboard_data.get("id"))
    if dashboard_id:
        mvp_dict["dashboard"] = str(dashboard_id)

    mvp_dict["title"] = dashboard_data.get("title", "Untitled Dashboard")

    version = dashboard_data.get("version", 1)
    if version != 1:
        mvp_dict["version"] = version

    subtitle = dashboard_data.get("subtitle", "")
    if subtitle and subtitle.strip():
        mvp_dict["subtitle"] = subtitle

    stored_metadata = dashboard_data.get("stored_metadata", [])
    mvp_dict["components"] = [
        _build_mvp_component(comp, idx) for idx, comp in enumerate(stored_metadata)
    ]

    return mvp_dict


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
    from depictio.api.v1.configs.config import settings

    full_dict: dict[str, Any] = {}

    dashboard_id = yaml_dict.get("dashboard", yaml_dict.get("dashboard_id"))
    if dashboard_id:
        full_dict["dashboard_id"] = str(dashboard_id)
        full_dict["id"] = str(dashboard_id)

    full_dict["title"] = yaml_dict.get("title", "Untitled Dashboard")
    full_dict["version"] = yaml_dict.get("version", 1)

    full_dict["subtitle"] = yaml_dict.get("subtitle", "")
    full_dict["icon"] = yaml_dict.get("icon", "mdi:view-dashboard")
    full_dict["icon_color"] = yaml_dict.get("icon_color", "orange")
    full_dict["icon_variant"] = yaml_dict.get("icon_variant", "filled")
    full_dict["description"] = yaml_dict.get("description")
    full_dict["notes_content"] = yaml_dict.get("notes_content", "")
    full_dict["is_public"] = yaml_dict.get("is_public", False)
    full_dict["workflow_system"] = yaml_dict.get("workflow_system", "none")
    full_dict["flexible_metadata"] = yaml_dict.get("flexible_metadata")
    full_dict["hash"] = yaml_dict.get("hash")

    full_dict["permissions"] = yaml_dict.get(
        "permissions",
        {
            "owners": [],
            "editors": [],
            "viewers": [],
        },
    )

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

    mvp_components = yaml_dict.get("components", [])
    full_components = []

    for idx, mvp_comp in enumerate(mvp_components):
        comp_uuid = str(uuid.uuid4())

        full_comp: dict[str, Any] = {
            "index": comp_uuid,
            "component_type": mvp_comp.get("type", "figure"),
            "title": mvp_comp.get("title", ""),
        }

        data_tag = mvp_comp.get("data_collection") or mvp_comp.get("data")
        if data_tag:
            # First try standalone data_collections collection (legacy)
            dc_doc = collection.find_one({"data_collection_tag": data_tag})

            if not dc_doc:
                try:
                    dc_doc = collection.find_one({"_id": ObjectId(data_tag)})
                except Exception:
                    pass

            # NEW: Search in projects for nested data collections
            if not dc_doc:
                projects_collection = db[settings.mongodb.collections.projects_collection]
                # Check if data_tag is a hash-based ID (e.g., "dc_646b0f3c")
                prefix = data_tag[3:] if data_tag.startswith("dc_") else ""

                for project in projects_collection.find():
                    if "workflows" in project and isinstance(project["workflows"], list):
                        for wf in project["workflows"]:
                            if "data_collections" in wf and isinstance(
                                wf["data_collections"], list
                            ):
                                for dc in wf["data_collections"]:
                                    dc_id_str = str(dc.get("_id", ""))
                                    # Match by data_collection_tag, full ID, or ID prefix
                                    if (
                                        dc.get("data_collection_tag") == data_tag
                                        or dc_id_str == data_tag
                                        or (prefix and dc_id_str.startswith(prefix))
                                    ):
                                        # Extract the config from nested structure
                                        dc_doc = dc.get("config") if "config" in dc else dc
                                        # Preserve the ID and tag from parent
                                        dc_doc["_id"] = dc.get("_id")
                                        dc_doc["data_collection_tag"] = dc.get(
                                            "data_collection_tag"
                                        )
                                        logger.debug(
                                            f"Found data collection '{data_tag}' (resolved to '{dc.get('data_collection_tag')}') nested in workflow {wf.get('name')}"
                                        )
                                        break
                            if dc_doc:
                                break
                    if dc_doc:
                        break

            if not dc_doc and data_tag.startswith("dc_"):
                prefix = data_tag[3:]
                try:
                    for candidate in collection.find():
                        if str(candidate["_id"]).startswith(prefix):
                            dc_doc = candidate
                            logger.debug(f"Matched dc prefix {prefix} to {candidate['_id']}")
                            break
                except Exception as e:
                    logger.debug(f"Failed to lookup by prefix {prefix}: {e}")

            if dc_doc:
                full_comp["dc_config"] = {
                    "_id": dc_doc["_id"]
                    if isinstance(dc_doc["_id"], ObjectId)
                    else ObjectId(dc_doc["_id"]),
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
                full_comp["dc_id"] = (
                    dc_doc["_id"]
                    if isinstance(dc_doc["_id"], ObjectId)
                    else ObjectId(dc_doc["_id"])
                )
                logger.debug(
                    f"Resolved data collection tag '{data_tag}' to ID {full_comp['dc_id']}"
                )
            else:
                full_comp["dc_config"] = {
                    "data_collection_tag": data_tag,
                    "type": "table",
                    "description": f"Unresolved data collection: {data_tag}",
                }
                full_comp["dc_id"] = None
                logger.warning(f"Data collection not found in MongoDB, preserving tag: {data_tag}")

        dict_kwargs: dict[str, Any] = {}
        visu_type = None

        if full_comp["component_type"] == "figure":
            # Extract from 'visualization' section if present, otherwise fall back to top level
            viz_section = mvp_comp.get("visualization", mvp_comp)

            visu_type = viz_section.get("chart", "scatter")

            for field in ["x", "y", "color", "size", "facet_row", "facet_col"]:
                if field in viz_section:
                    dict_kwargs[field] = viz_section[field]

            style = viz_section.get("style", {})
            for k, v in style.items():
                if k == "colors" or k == "map":
                    dict_kwargs["color_discrete_map"] = v
                elif k == "scale":
                    dict_kwargs["color_continuous_scale"] = v
                else:
                    dict_kwargs[k] = v

            dict_kwargs.setdefault("template", "mantine_light")
            dict_kwargs.setdefault("orientation", "v")
            dict_kwargs.setdefault("log_x", False)
            dict_kwargs.setdefault("log_y", False)

        full_comp["dict_kwargs"] = dict_kwargs
        if visu_type:
            full_comp["visu_type"] = visu_type

        if "value" in mvp_comp:
            full_comp["value"] = mvp_comp["value"]

        # Handle card component aggregation config
        if "aggregation" in mvp_comp:
            agg_config = mvp_comp["aggregation"]

            # Map to TOP-LEVEL fields (NOT dict_kwargs):
            if "column" in agg_config:
                full_comp["column_name"] = agg_config["column"]
            if "function" in agg_config:
                full_comp["aggregation"] = agg_config["function"]
            if "column_type" in agg_config:
                full_comp["column_type"] = agg_config["column_type"]

            # Optional: Store pre-computed value if provided
            if "value" in agg_config:
                full_comp["value"] = agg_config["value"]

        # Handle interactive component filter config
        if "filter" in mvp_comp:
            filter_config = mvp_comp["filter"]

            # Map to TOP-LEVEL fields (NOT dict_kwargs):
            if "column" in filter_config:
                full_comp["column_name"] = filter_config["column"]
            if "type" in filter_config:
                full_comp["interactive_component_type"] = filter_config["type"]
            if "column_type" in filter_config:
                full_comp["column_type"] = filter_config["column_type"]

            # Only slider-specific config goes in dict_kwargs:
            for key in ["min", "max", "default", "options", "step"]:
                if key in filter_config:
                    dict_kwargs[key] = filter_config[key]
            full_comp["dict_kwargs"] = dict_kwargs

        # Handle component styling (for cards and interactive components)
        if "styling" in mvp_comp:
            styling_config = mvp_comp["styling"]
            # Map all styling fields to TOP-LEVEL fields
            for key, value in styling_config.items():
                full_comp[key] = value

        workflow_tag = mvp_comp.get("workflow")
        if workflow_tag:
            # Parse engine/name format (e.g., "python/iris_workflow")
            workflow_name = workflow_tag
            expected_engine = None
            if "/" in workflow_tag:
                parts = workflow_tag.split("/", 1)
                expected_engine = parts[0]
                workflow_name = parts[1]

            # First try standalone workflows collection (legacy)
            wf_collection = db[settings.mongodb.collections.workflow_collection]
            wf_doc = wf_collection.find_one({"workflow_name": workflow_name})

            if not wf_doc:
                wf_doc = wf_collection.find_one({"workflow_tag": workflow_name})

            if not wf_doc:
                wf_doc = wf_collection.find_one({"name": workflow_name})

            if not wf_doc:
                try:
                    wf_doc = wf_collection.find_one({"_id": ObjectId(workflow_tag)})
                except Exception:
                    pass

            # NEW: Search in projects for nested workflows
            if not wf_doc:
                projects_collection = db[settings.mongodb.collections.projects_collection]
                # Check if workflow_tag is a hash-based ID (e.g., "wf_646b0f3c")
                prefix = workflow_name[3:] if workflow_name.startswith("wf_") else ""

                for project in projects_collection.find():
                    if "workflows" in project and isinstance(project["workflows"], list):
                        for wf in project["workflows"]:
                            wf_id_str = str(wf.get("_id", ""))
                            engine_matches = True
                            if expected_engine:
                                wf_engine = wf.get("engine", {}).get("name", "")
                                engine_matches = wf_engine == expected_engine

                            # Match by workflow_tag, name, full ID, or ID prefix (and verify engine if specified)
                            if engine_matches and (
                                wf.get("workflow_tag") == workflow_name
                                or wf.get("name") == workflow_name
                                or wf_id_str == workflow_name
                                or (prefix and wf_id_str.startswith(prefix))
                            ):
                                wf_doc = wf
                                logger.debug(
                                    f"Found workflow '{workflow_tag}' (resolved to '{wf.get('name')}') nested in project {project.get('name')}"
                                )
                                break
                    if wf_doc:
                        break

            if not wf_doc and workflow_tag.startswith("wf_"):
                prefix = workflow_tag[3:]
                try:
                    for candidate in wf_collection.find():
                        if str(candidate["_id"]).startswith(prefix):
                            wf_doc = candidate
                            logger.debug(f"Matched wf prefix {prefix} to {candidate['_id']}")
                            break
                except Exception as e:
                    logger.debug(f"Failed to lookup by prefix {prefix}: {e}")

            if wf_doc:
                full_comp["wf_id"] = (
                    wf_doc["_id"]
                    if isinstance(wf_doc["_id"], ObjectId)
                    else ObjectId(wf_doc["_id"])
                )
                # Store wf_tag in engine/name format
                engine_name = wf_doc.get("engine", {}).get("name", "unknown")
                wf_name = wf_doc.get("name") or wf_doc.get("workflow_tag") or workflow_tag
                full_comp["wf_tag"] = f"{engine_name}/{wf_name}"
                logger.debug(
                    f"Resolved workflow tag '{workflow_tag}' to ID {full_comp['wf_id']} with wf_tag '{full_comp['wf_tag']}'"
                )
            else:
                full_comp["wf_id"] = None
                full_comp["wf_name"] = workflow_tag
                logger.warning(f"Workflow not found in MongoDB, preserving tag: {workflow_tag}")
        else:
            full_comp["wf_id"] = None
            full_comp["wf_name"] = None

        full_comp["parent_index"] = None
        full_comp["filter_applied"] = False
        full_comp["last_updated"] = datetime.now().isoformat()
        full_comp["mode"] = "ui"
        full_comp["displayed_data_count"] = None
        full_comp["total_data_count"] = None
        full_comp["was_sampled"] = None
        full_comp["cols_json"] = {}

        full_components.append(full_comp)

    full_dict["stored_metadata"] = full_components

    generated_layout = []
    for idx, comp in enumerate(full_components):
        layout = auto_generate_layout(idx, comp.get("component_type", "figure"))
        layout["i"] = f"box-{comp['index']}"
        generated_layout.append(layout)

    full_dict["stored_layout_data"] = generated_layout

    full_dict["tmp_children_data"] = []
    full_dict["stored_children_data"] = []
    full_dict["left_panel_layout_data"] = []
    full_dict["right_panel_layout_data"] = []

    full_dict["buttons_data"] = {
        "unified_edit_mode": True,
        "add_components_button": {"count": 0},
    }

    return full_dict
