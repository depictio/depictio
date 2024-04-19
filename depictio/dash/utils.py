from bson import ObjectId
import numpy as np
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN
from depictio.api.v1.db import redis_cache
from io import BytesIO
from jose import JWTError
import bson
import collections
import httpx
import jwt
import os
import json
import pandas as pd
import polars as pl
import sys

from depictio.api.v1.configs.config import logger
from depictio.api.v1.endpoints.user_endpoints.auth import (
    ALGORITHM,
    PUBLIC_KEY,
    fetch_user_from_token,
)
from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow
from depictio.api.v1.models.base import convert_objectid_to_str


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
    elif hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, bytearray)):
        size += sum([get_size(i, seen) for i in obj])
    return size


def load_depictio_data():
    if os.path.exists("/app/data/depictio_data.json"):
        with open("/app/data/depictio_data.json", "r") as file:
            data = json.load(file)
            # print(data.keys())
        return data
    return None


def load_depictio_data_mongo(dashboard_id: str):
    url = f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}"
    try:
        response = httpx.get(url)
        if response.status_code == 200:
            response = response.json()
            return response
        else:
            print(f"Failed to load dashboard data. Status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"An error occurred while trying to fetch dashboard data: {e}")
        return None


def return_user_from_token(token: str) -> dict:
    # call API to get user from token without using PUBLIC KEY
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 200:
        return response.json()
    else:
        print("Error fetching user from token")
        return None


def list_workflows(token: str = None):
    # print("list_workflows")
    # print(token)

    if not token:
        print("A valid token must be provided for authentication.")
        return None

    # # print(token)
    # user = return_user_from_token(token)  # Decode the token to get the user information
    # if not user:
    #     print("Invalid token or unable to decode user information.")
    #     return None

    # # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    # print(token)
    workflows = httpx.get(f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows", headers=headers)
    workflows_json = workflows.json()
    # pretty_workflows = json.dumps(workflows_json, indent=4)
    # typer.echo(pretty_workflows)
    return workflows_json


def list_workflows_for_dropdown():
    workflows_model_list = list_workflows(TOKEN)
    # print(workflows_model_list)
    workflows = [wf["workflow_tag"] for wf in workflows_model_list]
    workflows_dict_for_dropdown = [{"label": wf, "value": wf} for wf in workflows]
    return workflows_dict_for_dropdown


def list_data_collections_for_dropdown(workflow_tag: str = None):
    if workflow_tag is None:
        return []
    else:
        data_collections = [dc["data_collection_tag"] for wf in list_workflows(TOKEN) for dc in wf["data_collections"] if wf["workflow_tag"] == workflow_tag]
        data_collections_dict_for_dropdown = [{"label": dc, "value": dc} for dc in data_collections]
        return data_collections_dict_for_dropdown


def return_wf_tag_from_id(workflow_id: ObjectId, workflows: list = None):
    if not workflows:
        workflows = list_workflows(TOKEN)
    else:
        workflows = [convert_objectid_to_str(workflow.mongo()) for workflow in workflows]

    return [e for e in workflows if e["_id"] == workflow_id][0]["workflow_tag"]


def return_dc_tag_from_id(workflow_id: ObjectId, data_collection_id: ObjectId, workflows: list = None):
    if not workflows:
        workflows = list_workflows(TOKEN)
    # else:
    # workflows = [convert_objectid_to_str(workflow.mongo()) for workflow in workflows]
    # print("data_collection_id", data_collection_id)
    return [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["_id"] == data_collection_id][0]["data_collection_tag"]


def return_mongoid(workflow_tag: str = None, workflow_id: ObjectId = None, data_collection_tag: str = None, data_collection_id: ObjectId = None, workflows: list = None):
    if not workflows:
        workflows = list_workflows(TOKEN)
    # else:
    #     workflows = [convert_objectid_to_str(workflow.mongo()) for workflow in workflows]

    if workflow_tag is not None and data_collection_tag is not None:
        # print("workflow_tag and data_collection_tag")
        workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_tag][0]["_id"]
        # print("workflow_id", workflow_id)
        data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == data_collection_tag][0]["_id"]
        # print("data_collection_id", data_collection_id)
    elif workflow_id is not None and data_collection_tag is not None:
        # print("workflow_id and data_collection_tag")
        workflow_id = str(workflow_id)
        data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == data_collection_tag][0]["_id"]
    else:
        # print("Invalid input")
        return None, None

    return workflow_id, data_collection_id


# TODO: utils / config


def get_columns_from_data_collection(
    workflow_tag: str,
    data_collection_tag: str,
):
    # print("\n\n\n")
    # print("get_columns_from_data_collection")

    # workflows = list_workflows(TOKEN)
    # workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_id][0]["_id"]
    # data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == data_collection_id][0]["_id"]
    workflow_id, data_collection_id = return_mongoid(workflow_tag=workflow_tag, data_collection_tag=data_collection_tag)

    if workflow_id is not None and data_collection_id is not None:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/deltatables/specs/{workflow_id}/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        )
        # print(response)
        if response.status_code == 200:
            json_cols = response.json()
            # print("get_columns_from_data_collection")
            # print(json_cols)
            # json_cols = json["columns"]
            reformat_cols = collections.defaultdict(dict)
            # print(json_cols)
            for c in json_cols:
                reformat_cols[c["name"]]["type"] = c["type"]
                reformat_cols[c["name"]]["description"] = c["description"]
                reformat_cols[c["name"]]["specs"] = c["specs"]
            return reformat_cols
        else:
            print("No workflows found")
            return None


def load_deltatable_lite(workflow_id: ObjectId, data_collection_id: ObjectId, cols: list = None, raw: bool = False):
    # print("load_deltatable_lite")

    # Turn objectid to string
    workflow_id = str(workflow_id)
    data_collection_id = str(data_collection_id)

    # Get file location corresponding to Dfrom API
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{workflow_id}/{data_collection_id}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
        },
    )

    # Check if the response is successful
    if response.status_code == 200:
        file_id = response.json()["delta_table_location"]

        ### FIXME: not-delete below - optimise and benchmark to check if redis is useful or if optimised polars read is more eficient

        # if redis_cache.exists(file_id):
        #     # print("Loading from redis cache")
        #     data_stream = BytesIO(redis_cache.get(file_id))
        #     data_stream.seek(0)  # Important: reset stream position to the beginning
        #     df = pl.read_parquet(data_stream, columns=cols if cols else None)
        #     # print(df)
        # else:
        #     # print("Loading from DeltaTable")

        #     # Convert DataFrame to parquet and then to bytes
        #     output_stream = BytesIO()
        #     df.write_parquet(output_stream)
        #     output_stream.seek(0)  # Reset stream position after writing
        #     redis_cache.set(file_id, output_stream.read())

        # Read the file from DeltaTable using polars and convert to pandas
        df = pl.read_delta(file_id, columns=cols if cols else None)

        # TODO: move to polars
        df = df.to_pandas()
        return df
    else:
        raise Exception("Error loading deltatable")


def join_deltatables(workflow_id: str, data_collection_id: str):
    # Turn str to objectid
    workflow_id = ObjectId(workflow_id)
    data_collection_id = ObjectId(data_collection_id)

    # Load the main data collection
    main_data_collection_df = load_deltatable_lite(workflow_id, data_collection_id)

    # FIXME: remove the column "Depictio_aggregation_time" from the main data collection
    main_data_collection_df = main_data_collection_df.drop(["depictio_aggregation_time"], axis=1)

    # Get join tables for the workflow
    join_tables_for_wf = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/get_join_tables/{workflow_id}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
        },
    )
    # print("main_data_collection_df")
    print(main_data_collection_df)
    # print("join_tables_for_wf")
    # print(join_tables_for_wf.json())

    logger.info("Join tables for workflow")
    logger.info(join_tables_for_wf.json())

    # Check if the response is not successful
    if join_tables_for_wf.status_code != 200:
        raise Exception("Error loading join tables")

    elif join_tables_for_wf.status_code == 200:
        # Check if the data collection is present in the join config of other data collections
        if str(data_collection_id) in join_tables_for_wf.json():
            # Extract the join tables for the current data collection
            join_tables_dict = join_tables_for_wf.json()[str(data_collection_id)]

            # print('join_tables_dict["with_dc_id"]')
            # print(join_tables_dict["with_dc_id"])
            # Iterate over the data collections that the current data collection is joined with
            for tmp_dc_id in join_tables_dict["with_dc_id"]:
                logger.info(tmp_dc_id)
                # Load the deltable from the join data collection
                tmp_df = load_deltatable_lite(str(workflow_id), str(tmp_dc_id))

                print(tmp_df)
                # Merge the main data collection with the join data collection on the specified columns
                # NOTE: hard-coded join for depictio_run_id currently (defined when creating the DeltaTable)
                tmp_df = tmp_df.drop(["depictio_aggregation_time"], axis=1)
                if "Metadata" in tmp_df["depictio_run_id"].values.tolist():
                    tmp_df = tmp_df.drop(["depictio_run_id"], axis=1)

                join_columns = join_tables_dict["on_columns"]
                if ("depictio_run_id" in main_data_collection_df.columns) and ("depictio_run_id" in tmp_df.columns):
                    join_columns = ["depictio_run_id"] + join_columns

                # print("tmp_df")
                # print(tmp_df)
                print(main_data_collection_df)
                main_data_collection_df = pd.merge(main_data_collection_df, tmp_df, on=join_columns)
                # print("main_data_collection_df AFTER MERGE")
                # print(main_data_collection_df)
                # print(main_data_collection_df.columns)

    # print(main_data_collection_df)
    return main_data_collection_df


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
            logger.info("  " * depth + f"Element {idx} ID: {child.get('props', {}).get('id', None)}")
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
            logger.info("  " * depth + f"Element {idx} ID: {child.get('props', {}).get('id', None)}")
            # Recursive call
            analyze_structure(child, depth=depth + 1)


def analyze_structure_and_get_deepest_type(struct, depth=0, max_depth=0, deepest_type=None, print=False):
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
                logger.info(f"Found component of type: {current_type} at depth: {depth}")  # Debug print

    if depth > max_depth:
        max_depth = depth
        deepest_type = current_type
        if print:
            logger.info(f"Updated max_depth to {max_depth} with deepest_type: {deepest_type}")  # Debug print
    elif depth == max_depth and current_type is not None:
        deepest_type = current_type
        if print:
            logger.info(f"Updated deepest_type to {deepest_type} at same max_depth: {max_depth}")  # Debug print

    if isinstance(struct, list):
        for child in struct:
            if print:
                logger.info(f"Descending into list at depth: {depth}")  # Debug print
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(child, depth=depth + 1, max_depth=max_depth, deepest_type=deepest_type)
    elif isinstance(struct, dict):
        children = struct.get("props", {}).get("children", None)
        if isinstance(children, (list, dict)):
            if print:
                logger.info(f"Descending into dict at depth: {depth}")  # Debug print
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(
                children,
                depth=depth + 1,
                max_depth=max_depth,
                deepest_type=deepest_type,
            )

    return max_depth, deepest_type
