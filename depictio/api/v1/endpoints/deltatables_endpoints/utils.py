
import collections
from bson import ObjectId
import numpy as np
from depictio.api.v1.configs.logging import logger
import polars as pl
import os
from depictio.api.v1.db import files_collection
from depictio.api.v1.utils import numpy_to_python
from botocore.exceptions import ClientError
from fastapi import HTTPException
from depictio.api.v1.s3 import s3_client

def get_s3_folder_size(bucket_name, prefix):
    """
    Calculate the total size of all objects within a given S3 folder (prefix).

    :param bucket_name: Name of the S3 bucket
    :param prefix: Prefix (path) of the folder in the bucket
    :return: Total size of all objects in bytes or an error message if no objects are found
    """
    total_size = 0
    try:
        # List all objects within the given prefix
        logger.info(f"Listing objects in folder '{prefix}' within bucket '{bucket_name}'.")
        paginator = s3_client.get_paginator('list_objects_v2')
        response_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

        # Sum the sizes of all objects found in the folder
        objects_found = False
        for page in response_iterator:
            if 'Contents' in page:
                objects_found = True
                for obj in page['Contents']:
                    total_size += obj['Size']
                    logger.debug(f"Adding size of object: {obj['Key']} - {obj['Size']} bytes.")

        if not objects_found:
            logger.warning(f"No objects found in the folder '{prefix}'. It may be empty or not exist.")
            raise HTTPException(status_code=404, detail="Folder is empty or does not exist.")

        logger.info(f"Total size of objects in folder '{prefix}': {total_size} bytes.")
        return total_size
    except ClientError as e:
        logger.error(f"Error listing objects in folder '{prefix}': {str(e)}")
        raise HTTPException(status_code=500, detail="Error listing folder contents.")
    except Exception as e:
        logger.error(f"Unexpected error calculating folder size: {str(e)}")
        raise HTTPException(status_code=500, detail="Unexpected error occurred while calculating folder size.")



def read_table_for_DC_table(file_info, data_collection_config_raw, deltaTable):
    """
    Read a table file and return a Polars DataFrame.
    """

    file_path = file_info.file_location
    data_collection_config = data_collection_config_raw["dc_specific_properties"]

    if data_collection_config["format"].lower() in ["csv", "tsv", "txt"]:
            # Read the file using polars

        df = pl.read_csv(
            file_path,
            **dict(data_collection_config["polars_kwargs"]),
        )
    elif data_collection_config["format"].lower() in ["parquet"]:
        df = pl.read_parquet(file_path, **dict(data_collection_config["polars_kwargs"]))
    
    elif data_collection_config["format"].lower() in ["feather"]:
        df = pl.read_feather(file_path, **dict(data_collection_config["polars_kwargs"]))
    
    elif data_collection_config["format"].lower() in ["xls", "xlsx"]:
        df = pl.read_excel(file_path, **dict(data_collection_config["polars_kwargs"]))

    # logger.info(df)
    raw_cols = df.columns
    no_run_id = False
    logger.debug(f"data_collection_config : {data_collection_config_raw}")
    if "metatype" in data_collection_config_raw and data_collection_config_raw["metatype"] != None:
        logger.debug(f'metatype : {data_collection_config_raw["metatype"]}')

        if  data_collection_config_raw["metatype"].lower() == "metadata":
            logger.debug("Metadata file detected")
            no_run_id = True


    if not no_run_id:
        df = df.with_columns(pl.lit(file_info.run_id).alias("depictio_run_id"))
        df = df.select(["depictio_run_id"] + raw_cols)

    # Update the file_info in MongoDB to mark it as processed
    files_collection.update_one(
        {"_id": ObjectId(file_info.id)},
        {
            "$set": {
                "aggregated": True,
                "data_collection.deltatable": deltaTable.mongo(),
            }
        },
    )
    return df


def upload_dir_to_s3(bucket_name, s3_folder, local_dir, s3_client):
    """
    Recursively uploads a directory to S3 preserving the directory structure.
    """
    for root, dirs, files in os.walk(local_dir):
        for filename in files:
            # construct the full local path
            local_path = os.path.join(root, filename)

            # construct the full S3 path
            relative_path = os.path.relpath(local_path, local_dir)
            s3_path = os.path.join(s3_folder, relative_path).replace("\\", "/")

            # upload the file
            logger.info(f"Uploading {local_path} to {bucket_name}/{s3_path}...")
            s3_client.upload_file(local_path, bucket_name, s3_path)


def precompute_columns_specs(aggregated_df: pl.DataFrame, agg_functions: dict, dc_data: dict):
    """
    Aggregate dataframes and return a list of dictionaries with column names, types and specs.
    """
    # TODO: performance improvement: use polars instead of pandas
    aggregated_df = aggregated_df.to_pandas()

    results = list()
    # For each column in the DataFrame
    dc_config = dc_data["config"]
    logger.info(f"dc_config : {dc_config}")
    logger.info(dc_config["dc_specific_properties"])
    if "columns_description" in dc_config["dc_specific_properties"]:
        logger.info(dc_config["dc_specific_properties"]["columns_description"])
        logger.info(list(dc_config["dc_specific_properties"]["columns_description"].keys()))
    for column in aggregated_df.columns:
        logger.info(f"Processing column: {column}")
        tmp_dict = collections.defaultdict(dict)
        tmp_dict["name"] = column
        column_description = None

        if "columns_description" in dc_config["dc_specific_properties"]:
            if column in list(dc_config["dc_specific_properties"]["columns_description"].keys()):
                column_description = dc_config["dc_specific_properties"]["columns_description"][column]

        tmp_dict["description"] = column_description
        # Identify the column data type
        col_type = str(aggregated_df[column].dtype).lower()
        # logger.info(col_type)
        tmp_dict["type"] = col_type.lower()
        # logger.info(agg_functions)
        # Check if the type exists in the agg_functions dict
        if col_type in agg_functions:
            methods = agg_functions[col_type]["card_methods"]

            # Initialize an empty dictionary to store results

            # For each method in the card_methods
            for method_name, method_info in methods.items():
                # logger.info(column, method_name)
                pandas_method = method_info["pandas"]
                # logger.info(pandas_method)
                # Check if the method is callable or a string
                if callable(pandas_method):
                    result = pandas_method(aggregated_df[column])
                    # logger.info(result)
                elif isinstance(pandas_method, str):
                    result = getattr(aggregated_df[column], pandas_method)()
                    # logger.info(result)
                else:
                    continue  # Skip if method is not available

                result = result.values if isinstance(result, np.ndarray) else result
                # logger.info(result)
                if method_name == "mode" and isinstance(result.values, np.ndarray):
                    result = result[0]
                tmp_dict["specs"][str(method_name)] = numpy_to_python(result)
        results.append(tmp_dict)
        logger.info(f"Column specs: {tmp_dict}")
    logger.info(f"Results: {results}")
    return results
