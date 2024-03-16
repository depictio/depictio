from bson import ObjectId
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


from depictio.api.v1.endpoints.user_endpoints.auth import (
    ALGORITHM,
    PUBLIC_KEY,
    fetch_user_from_token,
)


SELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "100px",
    "border": "3px solid",
    "opacity": 1,
}

UNSELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "100px",
    "border": "3px solid",
    "opacity": 1,
}


def load_depictio_data():
    if os.path.exists("depictio_data.json"):
        with open("depictio_data.json", "r") as file:
            data = json.load(file)
            # print(data.keys())
        return data
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
    print("list_workflows")
    print(token)

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
    print(workflows_model_list)
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


def return_mongoid(workflow_tag: str = None, workflow_id: ObjectId = None, data_collection_tag: str = None, data_collection_id: ObjectId = None):

    workflows = list_workflows(TOKEN)
    if workflow_tag is not None and data_collection_tag is not None:
        workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_tag][0]["_id"]
        data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == data_collection_tag][0]["_id"]
    elif workflow_id is not None and data_collection_tag is not None:
        workflow_id = workflow_id
        data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == data_collection_tag][0]["_id"]
    else:
        print("Invalid input")
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
            print("get_columns_from_data_collection")
            print(json_cols)
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
    print("load_deltatable_lite")

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

    print("\n\n\n")
    print("JOIN TABLES")

    # Get join tables for the workflow
    join_tables_for_wf = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/get_join_tables/{workflow_id}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
        },
    )
    print(join_tables_for_wf.status_code())
    print(join_tables_for_wf.json())

    # Check if the response is not successful
    if join_tables_for_wf.status_code != 200:
        raise Exception("Error loading join tables")

    elif join_tables_for_wf.status_code == 200:
        # Extract the join tables for the current data collection
        join_tables_dict = join_tables_for_wf.json()[str(data_collection_id)]

        # Check if the data collection is present in the join config of other data collections
        if str(data_collection_id) in join_tables_for_wf.json():
            # Iterate over the join config of the data collection dict
            for join in join_tables_dict:
                # Iterate over the data collections that the current data collection is joined with
                for tmp_dc_tag in join["with_dc"]:
                    # Retrieve the data collection id
                    _, tmp_dc_id = return_mongoid(workflow_id=workflow_id, data_collection_tag=tmp_dc_tag)

                    # Load the deltable from the join data collection
                    tmp_df = load_deltatable_lite(str(workflow_id), str(tmp_dc_id))

                    # Merge the main data collection with the join data collection on the specified columns
                    # NOTE: hard-coded join for depictio_run_id currently (defined when creating the DeltaTable)
                    main_data_collection_df = pd.merge(main_data_collection_df, tmp_df, on=["depictio_run_id"] + join["on_columns"])

        return main_data_collection_df


def analyze_structure(struct, depth=0):
    """
    Recursively analyze a nested plotly dash structure.

    Args:
    - struct: The nested structure.
    - depth: Current depth in the structure. Default is 0 (top level).
    """

    if isinstance(struct, list):
        # print("  " * depth + f"Depth {depth} Type: List with {len(struct)} elements")
        for idx, child in enumerate(struct):
            print("  " * depth + f"Element {idx} ID: {child.get('props', {}).get('id', None)}")
            analyze_structure(child, depth=depth + 1)
        return

    # Base case: if the struct is not a dictionary, we stop the recursion
    if not isinstance(struct, dict):
        return

    # Extracting id if available

    id_value = struct.get("props", {}).get("id", None)
    children = struct.get("props", {}).get("children", None)

    # Printing the id value
    print("  " * depth + f"Depth {depth} ID: {id_value}")

    if isinstance(children, dict):
        print("  " * depth + f"Depth {depth} Type: Dict")
        # Recursive call
        analyze_structure(children, depth=depth + 1)

    elif isinstance(children, list):
        print("  " * depth + f"Depth {depth} Type: List with {len(children)} elements")
        for idx, child in enumerate(children):
            print("  " * depth + f"Element {idx} ID: {child.get('props', {}).get('id', None)}")
            # Recursive call
            analyze_structure(child, depth=depth + 1)


def analyze_structure_and_get_deepest_type(struct, depth=0, max_depth=0, deepest_type=None):
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

    # Update the maximum depth and deepest type if the current depth is greater
    current_type = None
    if isinstance(struct, dict):
        id_value = struct.get("props", {}).get("id", None)
        if isinstance(id_value, dict) and id_value.get("type") != "stored-metadata-component":
            current_type = id_value.get("type")

    if depth > max_depth:
        max_depth = depth
        deepest_type = current_type
    elif depth == max_depth and current_type is not None:
        deepest_type = current_type

    if isinstance(struct, list):
        for child in struct:
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(child, depth=depth + 1, max_depth=max_depth, deepest_type=deepest_type)
    elif isinstance(struct, dict):
        children = struct.get("props", {}).get("children", None)
        if isinstance(children, (list, dict)):
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(
                children,
                depth=depth + 1,
                max_depth=max_depth,
                deepest_type=deepest_type,
            )

    return max_depth, deepest_type
