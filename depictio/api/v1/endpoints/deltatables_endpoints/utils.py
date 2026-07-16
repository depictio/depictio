import collections
import os

import numpy as np
import polars as pl
from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import files_collection
from depictio.api.v1.s3 import s3_client
from depictio.api.v1.utils import numpy_to_python

# Cap on how many distinct categorical values we sample into ``specs`` for the
# card-builder preview. Kept small so specs stay compact in Mongo.
_UNIQUE_VALUES_PREVIEW_CAP = 20


def get_s3_folder_size(bucket_name, prefix):
    """
    Calculate the total size of all objects within a given S3 folder (prefix).

    Args:
        bucket_name: Name of the S3 bucket
        prefix: Prefix (path) of the folder in the bucket

    Returns:
        Total size of all objects in bytes

    Raises:
        HTTPException: If folder is empty, doesn't exist, or on error
    """
    total_size = 0
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        response_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

        objects_found = False
        for page in response_iterator:
            if "Contents" in page:
                objects_found = True
                for obj in page["Contents"]:
                    total_size += obj["Size"]

        if not objects_found:
            raise HTTPException(status_code=404, detail="Folder is empty or does not exist.")

        return total_size
    except ClientError as e:
        logger.error(f"Error listing objects in folder '{prefix}': {str(e)}")
        raise HTTPException(status_code=500, detail="Error listing folder contents.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error calculating folder size: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Unexpected error occurred while calculating folder size.",
        )


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

    raw_cols = df.columns
    no_run_id = False

    if data_collection_config_raw.get("metatype"):
        if data_collection_config_raw["metatype"].lower() == "metadata":
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
    """Recursively upload a directory to S3 preserving the directory structure."""
    for root, dirs, files in os.walk(local_dir):
        for filename in files:
            local_path = os.path.join(root, filename)
            relative_path = os.path.relpath(local_path, local_dir)
            s3_path = os.path.join(s3_folder, relative_path).replace("\\", "/")
            s3_client.upload_file(local_path, bucket_name, s3_path)


def precompute_columns_specs(aggregated_df: pl.DataFrame, agg_functions: dict, dc_data: dict):
    """Aggregate dataframes and return a list of dictionaries with column names, types and specs."""
    aggregated_df = aggregated_df.to_pandas()  # type: ignore[invalid-assignment]

    results = list()
    dc_config = dc_data["config"]

    for column in aggregated_df.columns:
        tmp_dict = collections.defaultdict(dict)
        tmp_dict["name"] = column
        column_description = None

        if "columns_description" in dc_config["dc_specific_properties"]:
            if column in list(dc_config["dc_specific_properties"]["columns_description"].keys()):
                column_description = dc_config["dc_specific_properties"]["columns_description"][
                    column
                ]

        tmp_dict["description"] = column_description
        # Identify the column data type
        col_type = str(aggregated_df[column].dtype).lower()
        # logger.info(col_type)

        # Normalize pandas dtypes to match allowed values
        if col_type.startswith("datetime64"):
            normalized_type = "datetime"
        elif col_type.startswith("timedelta64"):
            normalized_type = "time"
        elif col_type in ["int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"]:
            normalized_type = "int64"
        elif col_type in ["float16", "float32", "float64"]:
            normalized_type = "float64"
        elif col_type in ["bool", "boolean"]:
            normalized_type = "bool"
        elif col_type == "str" or col_type.startswith("string") or col_type == "large_string":
            # pandas 3.0 infers a dedicated string dtype (str(dtype) == "str");
            # pandas <3 represented strings as object. Normalize to "object" so
            # the validator, agg_functions lookup and downstream type maps behave
            # exactly as they did on pandas 2.x.
            normalized_type = "object"
        else:
            normalized_type = col_type.lower()

        tmp_dict["type"] = normalized_type

        # ``agg_functions`` is keyed by *normalized* type names (``int64``,
        # ``float64``, ``datetime``, ``bool``, …) — not the raw pandas dtype.
        # Looking up by ``col_type`` worked for int64/float64/object only by
        # coincidence (their normalized names happen to equal the raw dtype);
        # ``datetime64[ns]`` / ``int32`` etc. silently fell off the path so
        # min/max never landed in specs and the React DatePicker showed
        # "No date bounds available". Use ``normalized_type`` instead.
        lookup_key = normalized_type if normalized_type in agg_functions else col_type
        if lookup_key in agg_functions:
            methods = agg_functions[lookup_key]["card_methods"]

            for method_name, method_info in methods.items():
                pandas_method = method_info["pandas"]
                if callable(pandas_method):
                    result = pandas_method(aggregated_df[column])
                elif isinstance(pandas_method, str):
                    result = getattr(aggregated_df[column], pandas_method)()
                else:
                    continue

                # Normalize the pandas method's return:
                # - .mode() returns a pd.Series (possibly empty, possibly with
                #   a non-RangeIndex when the aggregated df was reindexed); we
                #   want the first tied mode by position.
                # - .mean() / .median() / .min() / .max() etc. return scalars.
                # - .unique() returns an ndarray.
                # Previous code did ``result[0]`` for the mode branch, which is
                # LABEL-based indexing on a pd.Series and raised KeyError(0)
                # any time the Series index didn't contain 0 — e.g. viralrecon
                # pangolin_lineages, which has sparse string columns whose
                # aggregated-df modes carry a non-default index. The whole
                # deltatable upsert aborted, leaving every dashboard tile
                # bound to that DC stuck on 404.
                if hasattr(result, "iloc"):  # pd.Series
                    if len(result) == 0:
                        continue  # nothing to record for this method
                    result = result.iloc[0]
                elif isinstance(result, np.ndarray):
                    if result.size == 0:
                        continue
                    result = result.flat[0]
                tmp_dict["specs"][str(method_name)] = numpy_to_python(result)

        # Categorical columns: record a small, frequency-ordered sample of the
        # actual distinct values so the React card-builder preview can show real
        # category names in top-N / concentration strips instead of placeholder
        # "Bucket N" labels. The saved card recomputes the true distribution from
        # live data via bulk_compute_cards(); this only makes the design-time
        # preview representative. Capped to keep specs compact.
        if normalized_type in ("object", "bool", "category") or normalized_type.startswith(
            "string"
        ):
            try:
                value_counts = aggregated_df[column].value_counts(dropna=True)
                unique_values = [
                    str(v) for v in value_counts.index.tolist()[:_UNIQUE_VALUES_PREVIEW_CAP]
                ]
                if unique_values:
                    tmp_dict["specs"]["unique_values"] = unique_values
            except Exception as exc:  # never let preview metadata abort an upsert
                logger.debug(f"unique_values sample failed for column {column!r}: {exc}")

        results.append(tmp_dict)

    return results
