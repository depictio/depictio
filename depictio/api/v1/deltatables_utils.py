import itertools

import httpx
import polars as pl
from bson import ObjectId

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.s3 import polars_s3_config


# Function to add filter criteria to a list
def add_filter(
    filter_list,
    interactive_component_type,
    column_name,
    value,
    min_value=None,
    max_value=None,
):
    # logger.debug(f"filter_list: {filter_list}")
    # logger.info(f"interactive_component_type: {interactive_component_type}")
    # logger.info(f"column_name: {column_name}")
    # logger.info(f"value: {value}")
    # logger.info(f"min_value: {min_value}")
    # logger.info(f"max_value: {max_value}")

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
            filter_list.append(
                (pl.col(column_name) >= value[0]) & (pl.col(column_name) <= value[1])
            )


# Function to process metadata and build filter list
def process_metadata_and_filter(metadata):
    filter_list = []

    for i, component in enumerate(metadata):
        if "metadata" in component:
            # logger.info(f"Component {i} does not have metadata key : {component}")
            # continue
            # logger.info(f"i: {i}")
            # logger.info(f"component: {component}")
            interactive_component_type = component["metadata"]["interactive_component_type"]
            column_name = component["metadata"]["column_name"]
        else:
            interactive_component_type = component["interactive_component_type"]
            column_name = component["column_name"]
        # logger.info(f"interactive_component_type: {interactive_component_type}")
        # logger.info(f"column_name: {column_name}")
        value = component["value"]

        add_filter(
            filter_list,
            interactive_component_type=interactive_component_type,
            column_name=column_name,
            value=value,
        )

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
                        "metadata": {
                            "interactive_component_type": interactive_component_type,
                            "column_name": column,
                            "min_value": value,
                            "max_value": filter_to,
                        },
                        "value": [value, filter_to],
                    }
                )
        elif operator in [
            "equals",
            "notEqual",
            "greaterThan",
            "greaterThanOrEqual",
            "lessThan",
            "lessThanOrEqual",
        ]:
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
        elif operator in [
            "contains",
            "notContains",
            "startsWith",
            "notStartsWith",
            "endsWith",
            "notEndsWith",
        ]:
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
            interactive_component_type = (
                "Select"  # Assuming a select component to choose between blank/notBlank
            )
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


def load_deltatable_lite(
    workflow_id: ObjectId,
    data_collection_id: ObjectId,
    metadata: dict | None = None,
    TOKEN: str | None = None,
    limit_rows: int | None = None,
) -> pl.DataFrame:
    """
    Load a Delta table with optional filtering based on metadata.

    Args:
        workflow_id (ObjectId): The ID of the workflow.
        data_collection_id (ObjectId): The ID of the data collection.
        metadata (Optional[dict], optional): Metadata for filtering the DataFrame. Defaults to None.
        token (Optional[str], optional): Authorization token. Defaults to None.

    Returns:
        pl.DataFrame: The loaded and optionally filtered DataFrame.

    Raises:
        Exception: If the HTTP request to load the Delta table fails.
    """
    # Convert ObjectId to string
    workflow_id_str = str(workflow_id)
    data_collection_id_str = str(data_collection_id)

    # Prepare the request URL and headers
    url = f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{data_collection_id_str}"
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

    # Make the HTTP GET request to fetch the Delta table location
    try:
        response = httpx.get(url, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(
            f"HTTP error loading deltatable for workflow {workflow_id_str} "
            f"and data collection {data_collection_id_str}: {e}"
        )
        raise Exception("Error loading deltatable") from e

    # Extract the file ID from the response
    file_id = response.json().get("delta_table_location")
    if not file_id:
        logger.error(
            f"No 'delta_table_location' found in response for workflow {workflow_id_str} "
            f"and data collection {data_collection_id_str}: {response.json()}"
        )
        raise Exception("Invalid response: missing 'delta_table_location'")

    # logger.info(
    #     f"Loading deltatable for workflow {workflow_id_str}, data collection "
    #     f"{data_collection_id_str}, metadata: {metadata}, from file_id: {file_id}"
    # )

    # logger.debug(f"polars_s3_config: {polars_s3_config}")
    # logger.debug(f"file_id: {file_id}")

    # Initialize the Delta table scan
    delta_scan = pl.scan_delta(file_id, storage_options=polars_s3_config)

    # Apply filtering if metadata is provided
    if metadata:
        filter_expressions = process_metadata_and_filter(metadata)
        logger.debug(f"Filter expressions: {filter_expressions}")

        if filter_expressions:
            combined_filter = filter_expressions[0]
            for filt in filter_expressions[1:]:
                combined_filter &= filt
            delta_scan = delta_scan.filter(combined_filter)
            logger.debug("Applied filters based on metadata.")

    if limit_rows:
        delta_scan = delta_scan.limit(limit_rows)
        logger.debug(f"Applied row limit: {limit_rows}")

    # Collect the DataFrame
    try:
        df = delta_scan.collect()
    except Exception as e:
        logger.error(f"Error collecting Delta table data: {e}")
        raise Exception("Error collecting Delta table data") from e

    # Drop the 'depictio_aggregation_time' column if it exists
    if "depictio_aggregation_time" in df.columns:
        df = df.drop("depictio_aggregation_time")
        logger.debug("Dropped 'depictio_aggregation_time' column.")

    logger.debug(f"Loaded DataFrame with {df.height} rows and {df.width} columns.")
    return df


def merge_multiple_dataframes(
    dataframes: dict[str, pl.DataFrame],
    join_instructions: list[dict],
    essential_cols: set[str] = set(),
) -> pl.DataFrame:
    """
    Merge multiple Polars DataFrames based on join instructions, handling type alignment and overlapping columns.

    Parameters:
    - dataframes: Dict[str, pl.DataFrame]
        A dictionary mapping unique DataFrame identifiers to Polars DataFrames.
    - join_instructions: List[Dict]
        A list where each element is a dictionary specifying a join step with the following keys:
            - 'left': str - Identifier of the left DataFrame.
            - 'right': str - Identifier of the right DataFrame.
            - 'how': str - Type of join ('inner', 'left', 'right', 'outer', etc.).
            - 'on': List[str] - Columns to join on.
    - essential_cols: Set[str] (optional)
        A set of column names that should not be renamed during the join process to preserve their integrity.
    - logger: logging.Logger (optional)
        A logger instance for logging information and warnings. If not provided, a default logger is created.

    Returns:
    - pl.DataFrame
        The final merged DataFrame after performing all join operations.
    """

    logger.info("Starting the merge process.")

    # Step 1: Determine Common Column Types
    logger.debug("Aligning column types across all DataFrames.")
    column_types = {}

    for df_id, df in dataframes.items():
        for col, dtype in df.schema.items():
            if col not in column_types:
                column_types[col] = dtype
            else:
                # Determine the most general type
                current_type = column_types[col]
                if current_type != dtype:
                    # Define rules for type promotion
                    if pl.Utf8 in {current_type, dtype}:
                        column_types[col] = pl.Utf8
                    elif pl.Float64 in {current_type, dtype}:
                        column_types[col] = pl.Float64
                    elif pl.Int64 in {current_type, dtype}:
                        column_types[col] = pl.Int64
                    elif pl.Boolean in {current_type, dtype}:
                        column_types[col] = pl.Boolean
                    else:
                        # Default to Utf8 for complex type mismatches
                        column_types[col] = pl.Utf8
                    logger.debug(f"Column '{col}' type promoted to {column_types[col]}.")

    logger.debug(f"Common column types determined: {column_types}")

    # Step 2: Cast Columns to Common Types
    for df_id, df in dataframes.items():
        cast_columns = []
        for col, desired_dtype in column_types.items():
            if col in df.columns and df[col].dtype != desired_dtype:
                cast_columns.append(pl.col(col).cast(desired_dtype))
                logger.debug(
                    f"Casting column '{col}' in DataFrame '{df_id}' from {df[col].dtype} to {desired_dtype}."
                )
        if cast_columns:
            dataframes[df_id] = df.with_columns(cast_columns)
            logger.debug(f"DataFrame '{df_id}' columns casted to common types.")

    # Step 3: Perform Joins
    merged_df = None
    dc_ids_processed = set()
    if not join_instructions:
        logger.debug("No join instructions provided. Returning the first DataFrame.")
        return next(iter(dataframes.values()))
    for idx, join_step in enumerate(join_instructions, start=1):
        left_id = join_step["left"]
        right_id = join_step["right"]
        how = join_step["how"]
        on = join_step["on"].copy()  # Make a copy to modify

        logger.debug(
            f"Join Step {idx}: '{left_id}' {how} joined with '{right_id}' on columns {on}."
        )

        # Determine the current left DataFrame
        if merged_df is None:
            left_df = dataframes[left_id]
        else:
            left_df = merged_df

        if right_id in dc_ids_processed:
            logger.debug(f"Skipping join with '{right_id}' as it has already been processed.")
            continue

        # The right DataFrame is always from the join instructions
        right_df = dataframes[right_id]

        # Identify overlapping columns excluding join keys
        overlapping_cols = set(left_df.columns).intersection(set(right_df.columns)) - set(on)

        logger.debug(f"Overlapping columns detected: {overlapping_cols}")

        # Determine overlapping essential columns
        overlapping_essential_cols = overlapping_cols.intersection(essential_cols)

        logger.debug(f"Overlapping essential columns detected: {overlapping_essential_cols}")

        # # Add overlapping essential columns to 'on' list and drop them from right_df
        if overlapping_cols:
            logger.debug(
                f"Overlapping essential columns detected: {overlapping_cols}. Adding to join keys."
            )
            on += list(overlapping_cols)
        #     # # Drop these columns from the right DataFrame to prevent duplication
        #     # right_df = right_df.drop(list(overlapping_essential_cols))
        #     # logger.info(f"Dropped overlapping essential columns {overlapping_essential_cols} from right DataFrame '{right_id}'.")

        # logger.info(f"Columns to join on after adding overlapping essential columns: {on}")

        # # Re-identify overlapping columns after adding essential columns to 'on'
        # overlapping_cols = set(left_df.columns).intersection(set(right_df.columns)) - set(on)
        # logger.info(f"Remaining overlapping columns after adjusting join keys: {overlapping_cols}")

        # # Handle overlapping non-essential columns by dropping them from the right DataFrame
        # if overlapping_cols:
        #     logger.info(f"Overlapping non-essential columns detected: {overlapping_cols}. Dropping from right DataFrame '{right_id}'.")
        #     right_df = right_df.drop(list(overlapping_cols))
        #     dataframes[right_id] = right_df  # Update the DataFrame in the dictionary

        #     logger.info(f"Dropped overlapping non-essential columns from '{right_id}'. Remaining columns: {right_df.columns}")

        # Perform the join using Polars' join method
        try:
            logger.debug(
                f"Performing '{how}' join between left DataFrame and '{right_id}' on columns: {on}."
            )
            logger.debug(f"Left DataFrame shape: {left_df.shape} and columns: {left_df.columns}")
            logger.debug(
                f"Right DataFrame '{right_id}' shape: {right_df.shape} and columns: {right_df.columns}"
            )

            if merged_df is None:
                # Initial merge
                merged_df = left_df.join(right_df, on=on, how=how)
                logger.debug(
                    f"Joined '{left_id}' and '{right_id}'. Merged DataFrame shape: {merged_df.shape}"
                )
            else:
                # Subsequent merges
                merged_df = left_df.join(right_df, on=on, how=how)
                logger.debug(f"Joined with '{right_id}'. Merged DataFrame shape: {merged_df.shape}")
            dc_ids_processed.add(left_id)
            dc_ids_processed.add(right_id)
        except Exception as e:
            logger.error(f"Error during join between '{left_id}' and '{right_id}': {e}")
            raise

    logger.info("All join operations completed.")

    # Step 4: Verify Essential Columns
    missing_essentials = essential_cols - set(merged_df.columns)
    if missing_essentials:
        logger.warning(f"Essential columns missing from the final DataFrame: {missing_essentials}")

    logger.debug(f"Final merged DataFrame shape: {merged_df.shape}")
    logger.debug(f"Final merged DataFrame columns: {merged_df.columns}")

    return merged_df


def transform_joins_dict_to_instructions(
    joins_dict: dict[tuple, list[dict]],
) -> list[dict]:
    """
    Transform joins_dict into a list of join instructions compatible with merge_multiple_dataframes.

    Parameters:
    - joins_dict: Dict[tuple, List[Dict]]
        The original joins_dict structure.

    Returns:
    - List[Dict]
        A list of join instructions.
    """
    join_instructions = []
    for join_key_tuple, join_list in joins_dict.items():
        for join in join_list:
            for join_id, join_details in join.items():
                dc_id1, dc_id2 = join_id.split("--")
                instruction = {
                    "left": dc_id1,
                    "right": dc_id2,
                    "how": join_details["how"],
                    "on": join_details["on_columns"],
                }
                join_instructions.append(instruction)
    return join_instructions


def compute_essential_columns(dataframes: dict[str, pl.DataFrame]) -> set[str]:
    """
    Compute essential columns as those appearing in more than one DataFrame.

    Parameters:
    - dataframes: Dict[str, pl.DataFrame]
        A dictionary mapping DataFrame identifiers to Polars DataFrames.

    Returns:
    - Set[str]
        A set of column names that are present in multiple DataFrames.
    """
    from collections import defaultdict

    column_counts = defaultdict(int)
    for df in dataframes.values():
        for col in df.columns:
            column_counts[col] += 1

    # Essential columns are those appearing in two or more DataFrames
    essential_cols = {col for col, count in column_counts.items() if count > 1}
    return essential_cols


# def iterative_join(workflow_id: ObjectId, joins_dict: dict, metadata_dict: dict, TOKEN: str = None):
#     logger.info(f"workflow_id: {workflow_id}")
#     logger.info(f"joins_dict: {joins_dict}")
#     logger.info(f"metadata_dict: {metadata_dict}")

#     # Extract interactive components
#     interactive_components_list = [metadata for metadata in metadata_dict.values() if metadata.get("component_type") == "interactive"]
#     logger.info(f"Interactive components: {interactive_components_list}")

#     # If no joins are specified, load a single DataFrame
#     if not joins_dict:
#         first_dc_id = next(iter(metadata_dict.keys()))["metadata"]["dc_id"]
#         return load_deltatable_lite(workflow_id, first_dc_id, interactive_components_list, TOKEN=TOKEN)

#     # Initialize dictionary to store loaded DataFrames
#     loaded_dfs = {}
#     used_dcs = set()

#     # Load all necessary DataFrames based on joins_dict
#     for join_key_tuple in joins_dict.keys():
#         for dc_id in join_key_tuple:
#             if dc_id not in loaded_dfs:
#                 logger.info(f"Loading DataFrame for dc_id: {dc_id}")
#                 # Filter metadata for the current dc_id
#                 relevant_metadata = [md for md in metadata_dict.values() if md["metadata"]["dc_id"] == dc_id]
#                 logger.info(f"Relevant metadata for dc_id {dc_id}: {relevant_metadata}")
#                 # Load the DataFrame
#                 loaded_dfs[dc_id] = load_deltatable_lite(workflow_id, dc_id, relevant_metadata, TOKEN=TOKEN)
#                 logger.info(f"Loaded DataFrame for dc_id {dc_id} with shape: {loaded_dfs[dc_id].shape}")
#                 logger.info(f"Loaded DataFrame columns: {loaded_dfs[dc_id].columns}")

#     # Transform joins_dict to join_instructions
#     join_instructions = transform_joins_dict_to_instructions(joins_dict)
#     logger.info(f"Join instructions: {join_instructions}")

#     # Compute essential_cols dynamically
#     essential_cols = compute_essential_columns(loaded_dfs)
#     logger.info(f"Essential columns determined: {essential_cols}")

#     # Perform the merge using the updated generic function
#     merged_df = merge_multiple_dataframes(
#         dataframes=loaded_dfs,
#         join_instructions=join_instructions,
#         essential_cols=essential_cols,
#     )
#     return merged_df


def iterative_join(
    workflow_id: ObjectId,
    joins_dict: dict,
    metadata_dict: dict,
    TOKEN: str | None = None,
):
    # logger.debug(f"worfklow_id: {workflow_id}")
    # logger.debug(f"joins_dict: {joins_dict}")
    # logger.debug(f"metadata_dict: {metadata_dict}")

    interactive_components_list = list()
    for metadata in metadata_dict.values():
        if "component_type" in metadata:
            if metadata["component_type"] in ["interactive"]:
                interactive_components_list.append(metadata)

    if not joins_dict:
        return load_deltatable_lite(
            workflow_id,
            next(iter(metadata_dict.keys()))["metadata"]["dc_id"],
            interactive_components_list,
            TOKEN=TOKEN,
        )

    # Initialize a dictionary to store loaded dataframes
    loaded_dfs = {}
    used_dcs = set()

    values_dict = dict()

    # Load all necessary dataframes based on joins_dict
    for join_key_tuple in joins_dict.keys():
        for dc_id in join_key_tuple:
            if dc_id not in loaded_dfs:
                # logger.info(f"Metadata dict: {metadata_dict}")
                # Filter metadata for the current dc_id
                relevant_metadata = [
                    md for md in metadata_dict.values() if md["metadata"]["dc_id"] == dc_id
                ]
                # logger.info(f"Relevant metadata: {relevant_metadata}")
                for e in relevant_metadata:
                    values_dict[e["metadata"]["dc_id"]] = e["value"]
                # logger.info(
                #     f"Loading dataframe for dc_id: {dc_id} with metadata: {relevant_metadata}"
                # )
                loaded_dfs[dc_id] = load_deltatable_lite(
                    workflow_id, dc_id, relevant_metadata, TOKEN=TOKEN
                )
                # logger.info(f"Loaded df : {loaded_dfs[dc_id]}")
                logger.info(
                    f"Loaded dataframe for dc_id: {dc_id} with shape: {loaded_dfs[dc_id].shape}"
                )
    # logger.info(f"values_dict: {values_dict}")

    # Initialize merged_df with the first dataframe in the first join
    initial_dc_id = next(iter(joins_dict.keys()))[0]
    merged_df = loaded_dfs[initial_dc_id]
    used_dcs.add(initial_dc_id)
    logger.debug(f"Initial merged_df shape: {merged_df.shape}")
    logger.debug(f"Initial merged_df columns: {merged_df.columns}")
    logger.debug(f"Used data collections: {used_dcs}")

    # Iteratively join dataframes based on joins_dict
    for join_key_tuple, join_list in joins_dict.items():
        logger.debug(f"Processing joins for: {join_key_tuple}")
        for join in join_list:
            logger.debug(f"Join elem : {join}")
            join_id, join_details = list(join.items())[0]
            dc_id1, dc_id2 = join_id.split("--")

            # Determine which dataframe to join with merged_df
            if dc_id1 in used_dcs and dc_id2 in used_dcs:
                logger.debug(f"Skipping join {join_id} as both data collections are already used.")
                continue
            elif dc_id1 in used_dcs:
                logger.debug(
                    f"dc_id1 already in used_dcs - {dc_id1} - joinin with dc_id2 - {dc_id2}"
                )
                right_df = loaded_dfs[dc_id2]
                logger.debug(f"right_df shape: {right_df.shape}")
                logger.debug(f"right_df columns: {right_df.columns}")
                used_dcs.add(dc_id2)
            elif dc_id2 in used_dcs:
                logger.debug(
                    f"dc_id2 already in used_dcs - {dc_id2} - joinin with dc_id1 - {dc_id1}"
                )
                right_df = loaded_dfs[dc_id1]
                logger.debug(f"right_df shape: {right_df.shape}")
                logger.debug(f"right_df columns: {right_df.columns}")
                used_dcs.add(dc_id1)
            else:
                logger.debug(
                    f"Initial join with {dc_id1} and {dc_id2} on columns: {join_details['on_columns']} with method: {join_details['how']}"
                )
                right_df = loaded_dfs[dc_id2]
                logger.debug(f"right_df shape: {right_df.shape}")
                logger.debug(f"right_df columns: {right_df.columns}")
                used_dcs.add(dc_id2)
                merged_df = loaded_dfs[dc_id1]
                used_dcs.add(dc_id1)
                logger.debug(
                    f"Initial join with {dc_id1} and {dc_id2} on columns: {join_details['on_columns']} with method: {join_details['how']}"
                )

            logger.debug(f"Used data collections: {used_dcs}")

            logger.debug(
                f"Joining {dc_id1} and {dc_id2} on columns: {join_details['on_columns']} with method: {join_details['how']}"
            )

            if "depictio_run_id" in merged_df.columns and "depictio_run_id" in right_df.columns:
                join_columns = join_details["on_columns"] + ["depictio_run_id"]
            else:
                join_columns = join_details["on_columns"]

            # Perform the join
            merged_df = merged_df.join(right_df, on=join_columns, how=join_details["how"])

            logger.debug(f"Merged dataframe shape after join: {merged_df.shape}")
            logger.debug(f"Merged dataframe columns after join: {merged_df.columns}")

    return merged_df


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, item):
        if item not in self.parent:
            self.parent[item] = item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, item1, item2):
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 != root2:
            self.parent[root2] = root1


def get_join_tables(wf, TOKEN):
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/get_dc_joined/{wf}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if response.status_code == 200:
        return response.json()
    return {}


def return_joins_dict(wf, stored_metadata, TOKEN, extra_dc=None):
    # logger.info(f"wf - {wf}")
    # logger.info(f"return_joins_dict - stored_metadata - {stored_metadata}")
    # Extract all the data collection IDs from the stored metadata
    dc_ids_all_components = list(
        set([v["dc_id"] for v in stored_metadata if v["component_type"] not in ["jbrowse"]])
    )
    if extra_dc:
        dc_ids_all_components += [extra_dc]
    # logger.info(f"dc_ids_all_components - {dc_ids_all_components}")

    # Using itertools, generate all the combinations of dc_ids in order to get all the possible joins
    dc_ids_all_joins = list(itertools.combinations(dc_ids_all_components, 2))
    # Turn the list of tuples into a list of strings with -- as separator, and store it in dc_ids_all_joins in the 2 possible orders
    dc_ids_all_joins = [f"{dc_id1}--{dc_id2}" for dc_id1, dc_id2 in dc_ids_all_joins] + [
        f"{dc_id2}--{dc_id1}" for dc_id1, dc_id2 in dc_ids_all_joins
    ]

    # logger.info(f"dc_ids_all_joins - {dc_ids_all_joins}")

    stored_metadata_interactive_components_wf = [e for e in stored_metadata if e["wf_id"] == wf]
    # stored_metadata_interactive_components_wf = [e for e in stored_metadata if e["component_type"] in ["interactive"] and e["wf_id"] == wf]
    # logger.info(
    #     f"stored_metadata_interactive_components_wf - {stored_metadata_interactive_components_wf}"
    # )
    # stored_metadata_interactive_components_wf = [v for k, v in interactive_components_dict.items() if v["metadata"]["wf_id"] == wf]
    join_tables_for_wf = get_join_tables(wf, TOKEN)
    # logger.info(f"join_tables_for_wf - {join_tables_for_wf}")

    # Extract the intersection between dc_ids_all_joins and join_tables_for_wf[wf].keys()
    join_tables_for_wf[wf] = {
        k: join_tables_for_wf[wf][k] for k in join_tables_for_wf[wf].keys() if k in dc_ids_all_joins
    }
    # logger.info(f"join_tables_for_wf - {join_tables_for_wf}")

    # Initialize Union-Find structure
    uf = UnionFind()

    joins = []

    # logger.info(
    #     f"stored_metadata_interactive_components_wf - {stored_metadata_interactive_components_wf}"
    # )
    for interactive_component in stored_metadata_interactive_components_wf:
        wf_dc_key = (interactive_component["wf_id"], interactive_component["dc_id"])
        # logger.info(f"wf_dc - {wf_dc_key}")

        # Gather joins for the current workflow data collection
        for j in join_tables_for_wf[wf_dc_key[0]].keys():
            if (wf_dc_key[1] in j) and (wf_dc_key[1] in dc_ids_all_components):
                # logger.info(f"j - {j}")
                # logger.info(f"dc_ids_all_components - {dc_ids_all_components}")
                # logger.info(f"wf_dc[1] - {wf_dc_key[1]}")
                joins.append({j: join_tables_for_wf[wf_dc_key[0]][j]})

        # Union the related data collection IDs
        for join in joins:
            for join_id in join.keys():
                dc_id1, dc_id2 = join_id.split("--")
                uf.union(dc_id1, dc_id2)

    # Create groups of related data collection IDs
    groups = {}
    for dc_id in dc_ids_all_components:
        root = uf.find(dc_id)
        if root not in groups:
            groups[root] = set()
        groups[root].add(dc_id)

    # Create the joins dictionary based on these groups
    joins_dict = {}
    for root, group in groups.items():
        join_key_tuple = tuple(sorted(group))
        joins_dict[join_key_tuple] = []

    # Populate the joins dictionary
    added_joins = set()
    for join in joins:
        for join_id in join.keys():
            dc_id1, dc_id2 = join_id.split("--")
            root = uf.find(dc_id1)
            join_key_tuple = tuple(sorted(groups[root]))
            if join_id not in added_joins and f"{dc_id2}--{dc_id1}" not in added_joins:
                joins_dict[join_key_tuple].append(join)
                added_joins.add(join_id)

    # logger.info(f"joins_dict - {joins_dict}")

    # Identify and add missing joins
    for join_key_tuple, join_list in joins_dict.items():
        # for join_key_tuple, joins in joins_dict.items():
        # logger.info(f"Processing joins for: {join_key_tuple}")

        dc_ids = list(join_key_tuple)
        all_possible_joins = list(itertools.combinations(dc_ids, 2))
        for dc_id1, dc_id2 in all_possible_joins:
            join_id = f"{dc_id1}--{dc_id2}"
            reverse_join_id = f"{dc_id2}--{dc_id1}"
            if join_id not in added_joins and reverse_join_id not in added_joins:
                # Create a placeholder join based on available join details
                if dc_id1 in join_tables_for_wf[wf] and dc_id2 in join_tables_for_wf[wf]:
                    example_join = next(iter(join_tables_for_wf[wf].values()))
                    new_join = {
                        join_id: {
                            "how": example_join["how"],
                            "on_columns": example_join["on_columns"],
                            "dc_tags": example_join["dc_tags"],
                        }
                    }
                    joins_dict[join_key_tuple].append(new_join)
                    added_joins.add(join_id)
    return joins_dict


def join_deltatables_dev(
    wf_id: str, joins: list, metadata: dict = dict(), TOKEN: str | None = None
):
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
                logger.info(
                    f"Metadata: {[e for e in metadata if e['metadata']['dc_id'] == dc_id1]}"
                )
                loaded_dfs[dc_id1] = load_deltatable_lite(
                    wf_id,
                    dc_id1,
                    [e for e in metadata if e["metadata"]["dc_id"] == dc_id1],
                    TOKEN=TOKEN,
                )
                logger.info(f"dc1 columns: {loaded_dfs[dc_id1].columns}")
                logger.info(f"dc1 shape: {loaded_dfs[dc_id1].shape}")
            if dc_id2 not in loaded_dfs:
                logger.info(f"Loading dataframe for dc_id2: {dc_id2}")
                logger.info(
                    f"Metadata: {[e for e in metadata if e['metadata']['dc_id'] == dc_id2]}"
                )

                loaded_dfs[dc_id2] = load_deltatable_lite(
                    wf_id,
                    dc_id2,
                    [e for e in metadata if e["metadata"]["dc_id"] == dc_id2],
                    TOKEN=TOKEN,
                )
                logger.info(f"dc2 columns: {loaded_dfs[dc_id2].columns}")
                logger.info(f"dc2 shape: {loaded_dfs[dc_id2].shape}")

    logger.info(
        f"AFTER 1st FOR LOOP - Loaded dataframes columns: {[df.columns for df in loaded_dfs.values()]}"
    )
    logger.info(
        f"AFTER 1st FOR LOOP - Loaded dataframes shapes: {[df.shape for df in loaded_dfs.values()]}"
    )

    # Initialize merged_df with the first join
    join_dict = joins[0]
    join_id, join_details = list(join_dict.items())[0]
    dc_id1, dc_id2 = join_id.split("--")

    # Merge based on common columns
    common_columns = list(
        set(loaded_dfs[dc_id1].columns).intersection(set(loaded_dfs[dc_id2].columns))
    )
    merged_df = loaded_dfs[dc_id1].join(
        loaded_dfs[dc_id2], on=common_columns, how=join_details["how"]
    )

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
