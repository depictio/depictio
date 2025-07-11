import collections
import sys
import uuid

import httpx
import numpy as np
from bson import ObjectId

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger

SELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "100px",
    "border": "3px solid",
    "opacity": 1,
    "fontFamily": "Virgil",
}

UNSELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "100px",
    "border": "3px solid",
    "opacity": 1,
    "fontFamily": "Virgil",
}


# Helper Functions
def generate_unique_index():
    """
    Generate a unique index using UUID4.
    Used to create unique identifiers for components.
    """
    return str(uuid.uuid4())


def get_size(obj, seen=None):
    """Recursively finds size of objects"""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    # Important mark as seen *before* entering recursion to gracefully handle
    # self-referential objects
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(v, seen) for v in obj.values()])
        size += sum([get_size(k, seen) for k in obj.keys()])
    elif hasattr(obj, "__dict__"):
        size += get_size(obj.__dict__, seen)
    elif hasattr(obj, "__iter__") and not isinstance(obj, str | bytes | bytearray):
        size += sum([get_size(i, seen) for i in obj])
    return size


# Cache for component data to avoid redundant API calls
_component_data_cache: dict = dict()


def get_component_data(input_id, dashboard_id, TOKEN):
    """
    Get component data with caching to improve edit operation performance.
    """
    # Create cache key combining dashboard, component, and token hash
    cache_key = f"{dashboard_id}_{input_id}_{hash(TOKEN) % 10000 if TOKEN else 'none'}"

    # Check cache first
    if cache_key in _component_data_cache:
        logger.debug(f"Using cached component data for {input_id} in dashboard {dashboard_id}")
        return _component_data_cache[cache_key]

    logger.debug(f"Fetching component data for {input_id} in dashboard {dashboard_id}")

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/get_component_data/{dashboard_id}/{input_id}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    # logger.info(f"Code: {response.status_code}")
    # logger.info(f"Response: {response.json()}")

    if response.status_code == 200:
        component_data = response.json()
        # Cache the result
        _component_data_cache[cache_key] = component_data
        logger.debug(f"Cached component data for {input_id}")
        return component_data
    else:
        logger.warning(f"Failed to fetch component data for {input_id}: {response.status_code}")
        return None


def load_depictio_data_mongo(dashboard_id: str, TOKEN: str):
    url = f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}"
    try:
        response = httpx.get(url, headers={"Authorization": f"Bearer {TOKEN}"})
        if response.status_code == 200:
            response = response.json()
            return response
        else:
            print(f"Failed to load dashboard data. Status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"An error occurred while trying to fetch dashboard data: {e}")
        return None


def return_user_from_token(token: str) -> dict | None:
    # call API to get user from token without using PUBLIC KEY
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 200:
        return response.json()
    else:
        print("Error fetching user from token")
        return None


# Cache for workflows to avoid redundant API calls
_workflows_cache: dict = dict()


def list_workflows(token: str | None = None):
    """
    List workflows with caching to improve performance.
    """
    if not token:
        print("A valid token must be provided for authentication.")
        return None

    # Create cache key
    cache_key = f"workflows_{hash(token) % 10000}"

    # Check cache first
    if cache_key in _workflows_cache:
        logger.debug("Using cached workflows list")
        return _workflows_cache[cache_key]

    logger.debug("Fetching workflows from API")
    headers = {"Authorization": f"Bearer {token}"}

    workflows = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows", headers=headers
    )
    workflows_json = workflows.json()

    # Cache the result
    _workflows_cache[cache_key] = workflows_json
    logger.debug("Cached workflows list")

    return workflows_json


# def list_workflows_for_dropdown():
#     workflows_model_list = list_workflows(TOKEN)
#     # print(workflows_model_list)
#     workflows = [wf["workflow_tag"] for wf in workflows_model_list]
#     workflows_dict_for_dropdown = [{"label": wf, "value": wf} for wf in workflows]
#     return workflows_dict_for_dropdown


# def list_data_collections_for_dropdown(workflow_tag: str = None):
#     if workflow_tag is None:
#         return []
#     else:
#         data_collections = [dc["data_collection_tag"] for wf in list_workflows(TOKEN) for dc in wf["data_collections"] if wf["workflow_tag"] == workflow_tag]
#         data_collections_dict_for_dropdown = [{"label": dc, "value": dc} for dc in data_collections]
#         return data_collections_dict_for_dropdown


def return_wf_tag_from_id(workflow_id: ObjectId, TOKEN: str | None = None):
    # logger.info(f"return_wf_tag_from_id - TOKEN : {TOKEN}")
    # logger.info(f"return_wf_tag_from_id - workflow_id : {workflow_id}")
    # logger.info(f"return_wf_tag_from_id - workflows : {workflows}")
    # if not workflows:
    #     workflows = list_workflows(TOKEN)
    # else:
    #     workflows = [convert_objectid_to_str(workflow.mongo()) for workflow in workflows]

    # return [e for e in workflows if e["_id"] == workflow_id][0]["workflow_tag"]
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/workflows/get_tag_from_id/{workflow_id}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if response.status_code == 200:
        return response.json()
    else:
        logger.error("No workflows found")
        return None


def return_dc_tag_from_id(
    # workflow_id: ObjectId,
    data_collection_id: ObjectId,
    # workflows: list = None,
    TOKEN: str | None = None,
):
    # if not workflows:
    #     workflows = list_workflows(TOKEN)
    # # else:
    # # workflows = [convert_objectid_to_str(workflow.mongo()) for workflow in workflows]
    # # print("data_collection_id", data_collection_id)
    # return [
    #     f
    #     for e in workflows
    #     if e["_id"] == workflow_id
    #     for f in e["data_collections"]
    #     if f["_id"] == data_collection_id
    # ][0]["data_collection_tag"]
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/get_tag_from_id/{data_collection_id}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if response.status_code == 200:
        return response.json()
    else:
        logger.error("No data collections found")
        return None


def return_mongoid(
    workflow_tag: str | None = None,
    workflow_id: ObjectId | None = None,
    data_collection_tag: str | None = None,
    data_collection_id: ObjectId | None = None,
    workflows: list | None = None,
    TOKEN: str | None = None,
):
    if not workflows:
        workflows = list_workflows(TOKEN)
    # else:
    #     workflows = [convert_objectid_to_str(workflow.mongo()) for workflow in workflows]

    if workflow_tag is not None and data_collection_tag is not None:
        # print("workflow_tag and data_collection_tag")
        workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_tag][0]["_id"]
        # print("workflow_id", workflow_id)
        data_collection_id = [
            f
            for e in workflows
            if e["_id"] == workflow_id
            for f in e["data_collections"]
            if f["data_collection_tag"] == data_collection_tag
        ][0]["_id"]
        # print("data_collection_id", data_collection_id)
    elif workflow_id is not None and data_collection_tag is not None:
        # print("workflow_id and data_collection_tag")
        data_collection_id = [
            f
            for e in workflows
            if str(e["_id"]) == str(workflow_id)
            for f in e["data_collections"]
            if f["data_collection_tag"] == data_collection_tag
        ][0]["_id"]
    else:
        # print("Invalid input")
        return None, None

    return workflow_id, data_collection_id


# Cache for data collection specs to avoid duplicate API calls
_data_collection_specs_cache: dict = dict()


def get_columns_from_data_collection(
    workflow_id: str,
    data_collection_id: str,
    TOKEN: str,
):
    """
    Get columns from data collection with simple caching to avoid duplicate API calls.
    """
    # Create cache key
    cache_key = f"{data_collection_id}_{hash(TOKEN) % 10000 if TOKEN else 'none'}"

    # Check cache first
    if cache_key in _data_collection_specs_cache:
        logger.debug(f"Using cached specs for data_collection_id: {data_collection_id}")
        return _data_collection_specs_cache[cache_key]

    logger.debug(f"Fetching specs for data_collection_id: {data_collection_id}")

    if workflow_id is not None and data_collection_id is not None:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/deltatables/specs/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        )

        if response.status_code == 200:
            json_cols = response.json()
            reformat_cols: collections.defaultdict = collections.defaultdict(dict)
            for c in json_cols:
                reformat_cols[c["name"]]["type"] = c["type"]
                reformat_cols[c["name"]]["description"] = c["description"]
                reformat_cols[c["name"]]["specs"] = c["specs"]

            # Cache the result
            _data_collection_specs_cache[cache_key] = reformat_cols
            logger.debug(f"Cached specs for data_collection_id: {data_collection_id}")

            return reformat_cols
        else:
            logger.error(f"Error getting columns for {data_collection_id}: {response.text}")
            return collections.defaultdict(dict)
    else:
        logger.error("workflow_id or data_collection_id is None")
        return collections.defaultdict(dict)


def serialize_dash_component(obj):
    # If the object is a NumPy array, convert it to a list
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: serialize_dash_component(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_dash_component(v) for v in obj]
    elif hasattr(obj, "to_dict"):
        # If the object is a Dash component with a to_dict method
        return obj.to_dict()
    elif hasattr(obj, "__dict__"):
        # Attempt to serialize objects by converting their __dict__ attribute
        return serialize_dash_component(obj.__dict__)
    else:
        # Return the object as is if none of the above conditions are met
        return obj


def analyze_structure(struct, depth=0):
    """
    Recursively analyze a nested plotly dash structure.

    Args:
    - struct: The nested structure.
    - depth: Current depth in the structure. Default is 0 (top level).
    """

    if isinstance(struct, list):
        logger.info("  " * depth + f"Depth {depth} Type: List with {len(struct)} elements")
        for idx, child in enumerate(struct):
            logger.info(
                "  " * depth + f"Element {idx} ID: {child.get('props', {}).get('id', None)}"
            )
            analyze_structure(child, depth=depth + 1)
        return

    # Base case: if the struct is not a dictionary, we stop the recursion
    if not isinstance(struct, dict):
        return

    # Extracting id if available

    id_value = struct.get("props", {}).get("id", None)
    children = struct.get("props", {}).get("children", None)

    # Printing the id value
    logger.info("  " * depth + f"Depth {depth} ID: {id_value}")

    if isinstance(children, dict):
        logger.info("  " * depth + f"Depth {depth} Type: Dict")
        # Recursive call
        analyze_structure(children, depth=depth + 1)

    elif isinstance(children, list):
        logger.info("  " * depth + f"Depth {depth} Type: List with {len(children)} elements")
        for idx, child in enumerate(children):
            logger.info(
                "  " * depth + f"Element {idx} ID: {child.get('props', {}).get('id', None)}"
            )
            # Recursive call
            analyze_structure(child, depth=depth + 1)


def analyze_structure_and_get_deepest_type(
    struct, depth=0, max_depth=0, deepest_type=None, print=False
):
    """
    Recursively analyze a nested plotly dash structure and return the type of the deepest element (excluding 'stored-metadata-component').

    Args:
    - struct: The nested structure.
    - depth: Current depth in the structure.
    - max_depth: Maximum depth encountered so far.
    - deepest_type: Type of the deepest element encountered so far.

    Returns:
    - tuple: (Maximum depth of the structure, Type of the deepest element)
    """

    if print:
        logger.info(f"Analyzing level: {depth}")  # Debug print

    # Update the maximum depth and deepest type if the current depth is greater
    current_type = None
    if isinstance(struct, dict):
        id_value = struct.get("props", {}).get("id", None)
        if isinstance(id_value, dict) and id_value.get("type") != "stored-metadata-component":
            current_type = id_value.get("type")
            if print:
                logger.info(
                    f"Found component of type: {current_type} at depth: {depth}"
                )  # Debug print

    if depth > max_depth:
        max_depth = depth
        deepest_type = current_type
        if print:
            logger.info(
                f"Updated max_depth to {max_depth} with deepest_type: {deepest_type}"
            )  # Debug print
    elif depth == max_depth and current_type is not None:
        deepest_type = current_type
        if print:
            logger.info(
                f"Updated deepest_type to {deepest_type} at same max_depth: {max_depth}"
            )  # Debug print

    if isinstance(struct, list):
        for child in struct:
            if print:
                logger.info(f"Descending into list at depth: {depth}")  # Debug print
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(
                child, depth=depth + 1, max_depth=max_depth, deepest_type=deepest_type
            )
    elif isinstance(struct, dict):
        children = struct.get("props", {}).get("children", None)
        if isinstance(children, list | dict):
            if print:
                logger.info(f"Descending into dict at depth: {depth}")  # Debug print
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(
                children,
                depth=depth + 1,
                max_depth=max_depth,
                deepest_type=deepest_type,
            )

    return max_depth, deepest_type
