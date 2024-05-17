from bson import ObjectId
import httpx
import polars as pl
import pandas as pd
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN
from depictio.api.v1.s3 import s3_client, minio_storage_options
from depictio.api.v1.configs.config import logger


import polars as pl


# Function to add filter criteria to a list
def add_filter(filter_list, interactive_component_type, column_name, value, min_value=None, max_value=None):
    logger.info(f"filter_list: {filter_list}")

    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        if value:
            filter_list.append(pl.col(column_name).is_in(value))

    elif interactive_component_type == "TextInput":
        if value:
            filter_list.append(pl.col(column_name).str.contains(value))

    elif interactive_component_type == "Slider":
        if value:
            filter_list.append(pl.col(column_name) == value)

    elif interactive_component_type == "RangeSlider":
        if value:
            filter_list.append((pl.col(column_name) >= value[0]) & (pl.col(column_name) <= value[1]))


# Function to process metadata and build filter list
def process_metadata_and_filter(metadata):
    filter_list = []

    for i, component in enumerate(metadata):
        logger.info(f"i: {i}")
        logger.info(f"component: {component}")
        interactive_component_type = component["metadata"]["interactive_component_type"]
        column_name = component["metadata"]["column_name"]
        logger.info(f"interactive_component_type: {interactive_component_type}")
        logger.info(f"column_name: {column_name}")
        value = component["value"]

        add_filter(filter_list, interactive_component_type=interactive_component_type, column_name=column_name, value=value)

    # Apply the filters to the DataFrame
    return filter_list


def load_deltatable_lite(workflow_id: ObjectId, data_collection_id: ObjectId, metadata: dict = dict()):
    # print("load_deltatable_lite")
    logger.info("load_deltatable_lite")


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

        logger.info(f"file_id: {file_id}")
        logger.info(f"metadata: {metadata}")
        logger.info(f"type of metadata: {type(metadata)}")
        logger.info(f"check if metadata dict is empty : {not metadata}")
        logger.info(f"minio_storage_options: {minio_storage_options}")
        # If metadata is None or empty, return the DataFrame without filtering
        if not metadata:
            return pl.scan_delta(file_id, storage_options=minio_storage_options).collect().drop("depictio_aggregation_time")

        # Process metadata to generate filter list
        filter_list = process_metadata_and_filter(metadata)
        logger.info(f"filter_list: {filter_list}")

        # Apply filters if any
        if filter_list:
            combined_filter = filter_list[0]
            for filt in filter_list[1:]:
                combined_filter &= filt
            return pl.scan_delta(file_id, storage_options=minio_storage_options).filter(combined_filter).collect().drop("depictio_aggregation_time")
        else:
            return pl.scan_delta(file_id, storage_options=minio_storage_options).collect().drop("depictio_aggregation_time")

    else:
        raise Exception("Error loading deltatable")


def join_deltatables_dev(wf_id: str, joins: list, metadata: dict = dict()):
    # Initialize a dictionary to store loaded dataframes
    loaded_dfs = {}

    # Load all necessary dataframes based on join_dict
    for join_dict in joins:
        for join_id in join_dict:
            dc_id1, dc_id2 = join_id.split("--")

            if dc_id1 not in loaded_dfs:
                loaded_dfs[dc_id1] = load_deltatable_lite(wf_id, dc_id1, [e for e in metadata if e["metadata"]["dc_id"] == dc_id1])
            if dc_id2 not in loaded_dfs:
                loaded_dfs[dc_id2] = load_deltatable_lite(wf_id, dc_id2, [e for e in metadata if e["metadata"]["dc_id"] == dc_id2])

    # Initialize merged_df with the first join
    join_dict = joins[0]
    join_id, join_details = list(join_dict.items())[0]
    dc_id1, dc_id2 = join_id.split("--")
    merged_df = loaded_dfs[dc_id1].join(loaded_dfs[dc_id2], on=join_details["on_columns"], how=join_details["how"])

    # Perform remaining joins iteratively
    for join_dict in joins[1:]:
        for join_id, join_details in join_dict.items():
            dc_id1, dc_id2 = join_id.split("--")

            if dc_id1 in loaded_dfs and dc_id2 in loaded_dfs:
                merged_df = merged_df.join(loaded_dfs[dc_id2], on=join_details["on_columns"], how=join_details["how"])
            elif dc_id1 in loaded_dfs:
                merged_df = merged_df.join(loaded_dfs[dc_id1], on=join_details["on_columns"], how=join_details["how"])
            elif dc_id2 in loaded_dfs:
                merged_df = merged_df.join(loaded_dfs[dc_id2], on=join_details["on_columns"], how=join_details["how"])

    return merged_df

