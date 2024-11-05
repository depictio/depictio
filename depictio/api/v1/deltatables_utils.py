from bson import ObjectId
import httpx
import polars as pl
import pandas as pd
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.s3 import s3_client, minio_storage_options
from depictio.api.v1.configs.logging import logger


import polars as pl


# Function to add filter criteria to a list
def add_filter(filter_list, interactive_component_type, column_name, value, min_value=None, max_value=None):
    # logger.info(f"filter_list: {filter_list}")

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
        if "metadata" in component:
            # logger.info(f"Component {i} does not have metadata key : {component}")
            # continue
            logger.info(f"i: {i}")
            logger.info(f"component: {component}")
            interactive_component_type = component["metadata"]["interactive_component_type"]
            column_name = component["metadata"]["column_name"]
        else:
            interactive_component_type = component["interactive_component_type"]
            column_name = component["column_name"]
        # logger.info(f"interactive_component_type: {interactive_component_type}")
        # logger.info(f"column_name: {column_name}")
        value = component["value"]

        add_filter(filter_list, interactive_component_type=interactive_component_type, column_name=column_name, value=value)

    # Apply the filters to the DataFrame
    return filter_list


def convert_filter_model_to_metadata(filter_model):
    """
    Convert dash_ag_grid filterModel to a metadata list compatible with Polars filtering.
    """
    metadata = []
    for column, filter_details in filter_model.items():
        filter_type = filter_details.get("filterType", "text")
        operator = filter_details.get("type", "contains")
        value = filter_details.get("filter")
        filter_to = filter_details.get("filterTo")

        if operator == "inRange":
            # Range filter corresponds to RangeSlider
            interactive_component_type = "RangeSlider"
            if value is not None and filter_to is not None:
                metadata.append(
                    {
                        "metadata": {"interactive_component_type": interactive_component_type, "column_name": column, "min_value": value, "max_value": filter_to},
                        "value": [value, filter_to],
                    }
                )
        elif operator in ["equals", "notEqual", "greaterThan", "greaterThanOrEqual", "lessThan", "lessThanOrEqual"]:
            # Numerical or exact match filters
            if filter_type == "number":
                interactive_component_type = "Slider"
                metadata.append(
                    {
                        "metadata": {
                            "interactive_component_type": interactive_component_type,
                            "column_name": column,
                        },
                        "value": value,
                    }
                )
            else:
                # Non-number filters treated as TextInput
                interactive_component_type = "TextInput"
                metadata.append(
                    {
                        "metadata": {
                            "interactive_component_type": interactive_component_type,
                            "column_name": column,
                        },
                        "value": value,
                    }
                )
        elif operator in ["contains", "notContains", "startsWith", "notStartsWith", "endsWith", "notEndsWith"]:
            # String filters
            interactive_component_type = "TextInput"
            metadata.append(
                {
                    "metadata": {
                        "interactive_component_type": interactive_component_type,
                        "column_name": column,
                    },
                    "value": value,
                }
            )
        elif operator in ["blank", "notBlank"]:
            # Special filters for null values
            interactive_component_type = "Select"  # Assuming a select component to choose between blank/notBlank
            metadata.append(
                {
                    "metadata": {
                        "interactive_component_type": interactive_component_type,
                        "column_name": column,
                    },
                    "value": None,  # Value not needed for blank/notBlank
                }
            )
        # Extend with more operators as needed

    return metadata


def load_deltatable_lite(workflow_id: ObjectId, data_collection_id: ObjectId, metadata: dict = dict(), TOKEN: str = None):
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
        logger.info(f"Loading deltatable for workflow {workflow_id} and data collection {data_collection_id} and metadata: {metadata} from file_id: {file_id}")

        raw_df = pl.scan_delta(file_id, storage_options=minio_storage_options).collect()
        logger.info(f"Raw df: {raw_df}")

        # If metadata is None or empty, return the DataFrame without filtering
        if not metadata:
            logger.info(f"No metadata for wf {workflow_id} DC {data_collection_id}")
            return pl.scan_delta(file_id, storage_options=minio_storage_options).collect()
            # return pl.scan_delta(file_id, storage_options=minio_storage_options).collect().drop("depictio_aggregation_time")

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
        logger.error(f"Error loading deltatable for workflow {workflow_id} and data collection {data_collection_id} : {response.json()}")
        raise Exception("Error loading deltatable")


def iterative_join(workflow_id: ObjectId, joins_dict: dict, metadata_dict: dict, TOKEN: str = None):
    logger.info(f"worfklow_id: {workflow_id}")
    logger.info(f"joins_dict: {joins_dict}")
    logger.info(f"metadata_dict: {metadata_dict}")

    # Initialize a dictionary to store loaded dataframes
    loaded_dfs = {}
    used_dcs = set()

    values_dict = dict()

    # Load all necessary dataframes based on joins_dict
    for join_key_tuple in joins_dict.keys():
        for dc_id in join_key_tuple:
            if dc_id not in loaded_dfs:
                logger.info(f"Metadata dict: {metadata_dict}")
                # Filter metadata for the current dc_id
                relevant_metadata = [md for md in metadata_dict.values() if md["metadata"]["dc_id"] == dc_id]
                logger.info(f"Relevant metadata: {relevant_metadata}")
                for e in relevant_metadata:
                    values_dict[e["metadata"]["dc_id"]] = e["value"]
                logger.info(f"Loading dataframe for dc_id: {dc_id} with metadata: {relevant_metadata}")
                loaded_dfs[dc_id] = load_deltatable_lite(workflow_id, dc_id, relevant_metadata, TOKEN=TOKEN)
                logger.info(f"Loaded df : {loaded_dfs[dc_id]}")
                logger.info(f"Loaded dataframe for dc_id: {dc_id} with shape: {loaded_dfs[dc_id].shape}")
    logger.info(f"values_dict: {values_dict}")

    # Initialize merged_df with the first dataframe in the first join
    initial_dc_id = next(iter(joins_dict.keys()))[0]
    merged_df = loaded_dfs[initial_dc_id]
    used_dcs.add(initial_dc_id)
    logger.info(f"Initial merged_df shape: {merged_df.shape}")
    logger.info(f"Used data collections: {used_dcs}")

    # Iteratively join dataframes based on joins_dict
    for join_key_tuple, join_list in joins_dict.items():
        logger.info(f"Processing joins for: {join_key_tuple}")
        for join in join_list:
            logger.info(f"Join elem : {join}")
            join_id, join_details = list(join.items())[0]
            dc_id1, dc_id2 = join_id.split("--")

            # Determine which dataframe to join with merged_df
            if dc_id1 in used_dcs and dc_id2 in used_dcs:
                logger.info(f"Skipping join {join_id} as both data collections are already used.")
                continue
            elif dc_id1 in used_dcs:
                right_df = loaded_dfs[dc_id2]
                used_dcs.add(dc_id2)
            elif dc_id2 in used_dcs:
                right_df = loaded_dfs[dc_id1]
                used_dcs.add(dc_id1)
            else:
                right_df = loaded_dfs[dc_id2]
                used_dcs.add(dc_id2)
                merged_df = loaded_dfs[dc_id1]
                used_dcs.add(dc_id1)
                logger.info(f"Initial join with {dc_id1} and {dc_id2} on columns: {join_details['on_columns']} with method: {join_details['how']}")

            logger.info(f"Used data collections: {used_dcs}")

            logger.info(f"Joining {dc_id1} and {dc_id2} on columns: {join_details['on_columns']} with method: {join_details['how']}")

            # Perform the join
            merged_df = merged_df.join(right_df, on=join_details["on_columns"], how=join_details["how"])

            logger.info(f"Merged dataframe shape after join: {merged_df.shape}")

    return merged_df


def join_deltatables_dev(wf_id: str, joins: list, metadata: dict = dict(), TOKEN: str = None):
    # Initialize a dictionary to store loaded dataframes
    loaded_dfs = {}
    logger.info(f"Loading dataframes for workflow {wf_id}")
    logger.info(f"Joins: {joins}")
    logger.info(f"Metadata: {metadata}")

    # Load all necessary dataframes based on join_dict
    for join_dict in joins:
        for join_id in join_dict:
            dc_id1, dc_id2 = join_id.split("--")

            if dc_id1 not in loaded_dfs:
                logger.info(f"Loading dataframe for dc_id1: {dc_id1}")
                logger.info(f"Metadata: {[e for e in metadata if e['metadata']['dc_id'] == dc_id1]}")
                loaded_dfs[dc_id1] = load_deltatable_lite(wf_id, dc_id1, [e for e in metadata if e["metadata"]["dc_id"] == dc_id1], TOKEN=TOKEN)
                logger.info(f"dc1 columns: {loaded_dfs[dc_id1].columns}")
                logger.info(f"dc1 shape: {loaded_dfs[dc_id1].shape}")
            if dc_id2 not in loaded_dfs:
                logger.info(f"Loading dataframe for dc_id2: {dc_id2}")
                logger.info(f"Metadata: {[e for e in metadata if e['metadata']['dc_id'] == dc_id2]}")

                loaded_dfs[dc_id2] = load_deltatable_lite(wf_id, dc_id2, [e for e in metadata if e["metadata"]["dc_id"] == dc_id2], TOKEN=TOKEN)
                logger.info(f"dc2 columns: {loaded_dfs[dc_id2].columns}")
                logger.info(f"dc2 shape: {loaded_dfs[dc_id2].shape}")

    logger.info(f"AFTER 1st FOR LOOP - Loaded dataframes columns: {[df.columns for df in loaded_dfs.values()]}")
    logger.info(f"AFTER 1st FOR LOOP - Loaded dataframes shapes: {[df.shape for df in loaded_dfs.values()]}")

    # Initialize merged_df with the first join
    join_dict = joins[0]
    join_id, join_details = list(join_dict.items())[0]
    dc_id1, dc_id2 = join_id.split("--")

    # Merge based on common columns
    common_columns = list(set(loaded_dfs[dc_id1].columns).intersection(set(loaded_dfs[dc_id2].columns)))
    merged_df = loaded_dfs[dc_id1].join(loaded_dfs[dc_id2], on=common_columns, how=join_details["how"])

    # logger.info(f"Initial merged_df shape: {merged_df.shape}")
    # logger.info(f"Columns in merged_df: {merged_df.columns}")
    # logger.info(f"dc1 columns: {loaded_dfs[dc_id1].columns}")
    # logger.info(f"dc2 columns: {loaded_dfs[dc_id2].columns}")
    # logger.info(f"Common columns: {common_columns}")

    # Track which dataframes have been merged
    used_dfs = {dc_id1, dc_id2}

    # Perform remaining joins iteratively
    for join_dict in joins[1:]:
        for join_id, join_details in join_dict.items():
            dc_id1, dc_id2 = join_id.split("--")

            if dc_id2 not in used_dfs and dc_id2 in loaded_dfs:
                new_df = loaded_dfs[dc_id2]
                # logger.info(f"new_df shape: {new_df.shape}")
                # logger.info(f"new_df columns: {new_df.columns}")
                used_dfs.add(dc_id2)
            elif dc_id1 not in used_dfs and dc_id1 in loaded_dfs:
                new_df = loaded_dfs[dc_id1]
                used_dfs.add(dc_id1)
            else:
                continue

            common_columns = list(set(merged_df.columns).intersection(set(new_df.columns)))
            merged_df = merged_df.join(new_df, on=common_columns, how=join_details["how"])

    logger.info(f"AFTER 2nd FOR LOOP - merged_df shape: {merged_df.shape}")
    logger.info(f"Columns in merged_df: {merged_df.columns}")
    logger.info(f"Common columns: {common_columns}")
    logger.info(f"Used dataframes: {used_dfs}")
    logger.info(f"Loaded dataframes: {loaded_dfs.keys()}")
    logger.info(f"Merged df: {merged_df}")

    return merged_df
