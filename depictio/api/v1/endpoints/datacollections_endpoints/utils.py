from typing import Dict, List
from depictio.api.v1.configs.custom_logging import logger


def symmetrize_join_details(join_details_map: Dict[str, List[dict]]):
    """Ensure symmetric join details across all related data collections."""
    # Create a list of items to iterate over, so the original dict can be modified
    items = list(join_details_map.items())
    for dc_id, joins in items:
        for join in joins:
            for related_dc_id in join["with_dc"]:
                # Initialize related_dc_join list if not already present
                if related_dc_id not in join_details_map:
                    join_details_map[related_dc_id] = []

                # Check if related data collection already has symmetric join details with the current one
                related_joins = join_details_map[related_dc_id]
                symmetric_join_exists = any(
                    dc_id in join_detail["with_dc"] for join_detail in related_joins
                )

                if not symmetric_join_exists:
                    # Create symmetric join detail for related data collection
                    symmetric_join = {
                        "on_columns": join["on_columns"],
                        "how": join["how"],
                        "with_dc": [dc_id],  # Link back to the current data collection
                    }
                    join_details_map[related_dc_id].append(symmetric_join)


def generate_join_dict(workflow: Dict) -> Dict[str, Dict[str, dict]]:
    logger.info(f"Workflow: {workflow}")

    join_dict = {}

    wf_id = str(workflow["_id"])
    logger.info(f"Workflow ID: {wf_id}")
    join_dict[wf_id] = {}

    dc_ids = {
        str(dc["_id"]): dc
        for dc in workflow["data_collections"]
        if dc["config"]["type"].lower() == "table"
    }
    logger.info(f"Data collections: {dc_ids}")
    visited = set()

    def find_joins(dc_id, join_configs):
        logger.info(f"Data collection: {dc_id}")
        logger.info(f"Visited: {visited}")
        logger.info(f"Join configs: {join_configs}")

        if dc_id in visited:
            return
        visited.add(dc_id)
        if "join" in dc_ids[dc_id]["config"]:
            join_info = dc_ids[dc_id]["config"]["join"]
            logger.info(f"Join info: {join_info}")
            if join_info:
                for related_dc_tag in join_info.get("with_dc", []):
                    related_dc_id = next(
                        (
                            str(dc["_id"])
                            for dc in workflow["data_collections"]
                            if dc["data_collection_tag"] == related_dc_tag
                        ),
                        None,
                    )
                    if related_dc_id:
                        join_configs[f"{dc_id}--{related_dc_id}"] = {
                            "how": join_info["how"],
                            "on_columns": join_info["on_columns"],
                            "dc_tags": [
                                dc_ids[dc_id]["data_collection_tag"],
                                dc_ids[related_dc_id]["data_collection_tag"],
                            ],
                        }
                        find_joins(related_dc_id, join_configs)

    for dc_id in dc_ids:
        if dc_id not in visited:
            join_configs = {}
            find_joins(dc_id, join_configs)
            join_dict[wf_id].update(join_configs)

    return join_dict


def normalize_join_details(join_details):
    normalized_details = {}

    # Initialize entries for all DCs
    for dc_id, joins in join_details.items():
        for join in joins:
            if dc_id not in normalized_details:
                normalized_details[dc_id] = {
                    "on_columns": join["on_columns"],
                    "how": join["how"],
                    "with_dc": set(
                        join.get("with_dc", [])
                    ),  # Use set for unique elements
                    "with_dc_id": set(
                        join.get("with_dc_id", [])
                    ),  # Use set for unique elements
                }

    # Update relationships
    for dc_id, joins in join_details.items():
        for join in joins:
            # Update related by ID
            for related_dc_id in join.get("with_dc_id", []):
                # Ensure reciprocal relationship exists
                normalized_details[dc_id]["with_dc_id"].add(related_dc_id)
                if related_dc_id not in normalized_details:
                    normalized_details[related_dc_id] = {
                        "on_columns": join["on_columns"],
                        "how": join["how"],
                        "with_dc": set(),
                        "with_dc_id": set(),
                    }
                normalized_details[related_dc_id]["with_dc_id"].add(dc_id)

            # Update related by Tag
            for related_dc_tag in join.get("with_dc", []):
                normalized_details[dc_id]["with_dc"].add(related_dc_tag)
                # This assumes tags to IDs resolution happens elsewhere or they're handled as equivalent identifiers
                # If 'related_dc_tag' could also appear in 'normalized_details', consider adding reciprocal logic here

    # Convert sets back to lists for the final output
    for dc_id in normalized_details:
        normalized_details[dc_id]["with_dc"] = list(
            normalized_details[dc_id]["with_dc"]
        )
        normalized_details[dc_id]["with_dc_id"] = list(
            normalized_details[dc_id]["with_dc_id"]
        )

    return normalized_details
