
import collections
from bson import ObjectId
import numpy as np
from depictio.api.v1.configs.config import settings, logger
import polars as pl
import os
from depictio.api.v1.db import workflows_collection, data_collections_collection, runs_collection, files_collection
from depictio.api.v1.utils import numpy_to_python


def read_table_for_DC_table(file_info, data_collection_config_raw, deltaTable):
    """
    Read a table file and return a Polars DataFrame.
    """
    # logger.info("file_info")
    # logger.info(file_info)
    # logger.info("data_collection_config")
    # logger.info(data_collection_config)
    # if file_info.aggregated == True:
    #     continue  # Skip already processed files

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
    logger.info(f"data_collection_config : {data_collection_config_raw}")
    if "metatype" in data_collection_config_raw:
        logger.info(f'metatype : {data_collection_config_raw["metatype"]}')

        if data_collection_config_raw["metatype"].lower() == "metadata":
            logger.info("Metadata file detected")
            no_run_id = True
    if not no_run_id:
        df = df.with_columns(pl.lit(file_info.run_id).alias("depictio_run_id"))
        df = df.select(["depictio_run_id"] + raw_cols)
    # data_frames.append(df)

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
    # logger.info("Updated file_info in MongoDB")
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


def precompute_columns_specs(aggregated_df: pl.DataFrame, agg_functions: dict):
    """
    Aggregate dataframes and return a list of dictionaries with column names, types and specs.
    """
    # TODO: performance improvement: use polars instead of pandas
    aggregated_df = aggregated_df.to_pandas()

    results = list()
    # For each column in the DataFrame
    for column in aggregated_df.columns:
        tmp_dict = collections.defaultdict(dict)
        tmp_dict["name"] = column
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
    logger.info(results)
    return results
