import collections
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import PosixPath
import re
from bson import ObjectId
from deltalake import DeltaTable
from fastapi import HTTPException, Depends, APIRouter
from typing import List

import pandas as pd
import polars as pl
import numpy as np
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db, grid_fs
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.models.pydantic_models import (
    Aggregation,
    DeltaTableAggregated,
    DeltaTableQuery,
    User,
    Workflow,
    File,
    DataCollection,
    WorkflowRun,
)
from depictio.api.v1.models.pydantic_models import GridFSFileInfo
from depictio.api.v1.utils import (
    # decode_token,
    # public_key_path,
    numpy_to_python,
    scan_runs,
    serialize_for_mongo,
    agg_functions,
)


deltatables_endpoint_router = APIRouter()

data_collections_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]
runs_collection = db[settings.collections.runs_collection]
files_collection = db[settings.collections.files_collection]
users_collection = db["users"]




@deltatables_endpoint_router.get("/get/{workflow_id}/{data_collection_id}")
# @datacollections_endpoint_router.get("/files/{workflow_id}/{data_collection_id}", response_model=List[GridFSFileInfo])
async def list_registered_files(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Fetch all files registered from a Data Collection registered into a workflow.
    """



    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
         workflows_collection, current_user.user_id, workflow_id, data_collection_id, 
    )

    # Query to find deltatable associated with the data collection
    query = {"_id": workflow_oid, "data_collections._id": data_collection_oid}
    deltatable_cursor = workflows_collection.find(query, {"data_collections.$": 1})
    deltatable = list(deltatable_cursor)[0]["data_collections"][0]["deltaTable"]
    # print(deltatable)


    return convert_objectid_to_str(deltatable)


@deltatables_endpoint_router.post(
    "/create/{workflow_id}/{data_collection_id}"
)
async def aggregate_data(
    # data_collection: DataCollection,
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    # data_collections_collection.drop()

    # Use the utility function to validate and retrieve necessary info
    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
         workflows_collection, current_user.user_id, workflow_id, data_collection_id, 
    )

    data_collection_config = data_collection.config

    # Using the config, find relevant files
    files = list(files_collection.find({"data_collection._id": data_collection_oid}))
    print(files)
    assert isinstance(files, list)
    assert len(files) > 0
    files = [File.from_mongo(file) for file in files]


    # TODO: Move to S3
    # Define the path to your Delta table
    delta_table_path = f"/Users/tweber/Gits/depictio/data/delta_lake/{user_oid}/{workflow_oid}/{data_collection_oid}"
    print(delta_table_path)
    # os.remove(delta_table_path)
    user = User.from_mongo(users_collection.find_one({"_id": user_oid}))
    # fix this below
    deltaTable = DeltaTableAggregated(
        delta_table_location=delta_table_path,
        aggregation=[
            Aggregation(
                aggregation_time=datetime.now(),
                aggregation_by=user,
                aggregation_version=1,
            )
        ],
    )

    data_frames = []

    for file_info in files:
        print(file_info)
        # if file_info.aggregated == True:
        #     continue  # Skip already processed files

        file_path = file_info.file_location
        df = pl.read_csv(
            file_path,
            **dict(data_collection_config.polars_kwargs),
        )
        print(df)
        raw_cols = df.columns
        df = df.with_columns(pl.lit(file_info.run_id).alias("depictio_run_id"))
        df = df.select(["depictio_run_id"] + raw_cols)
        data_frames.append(df)

        # Update the file_info in MongoDB to mark it as processed
        files_collection.update_one(
            {"_id": ObjectId(file_info.id)},
            {
                "$set": {
                    "aggregated": True,
                    "data_collection.deltaTable": deltaTable.mongo(),
                }
            },
        )
        print("Updated file_info in MongoDB")
        print("\n")

    # Aggregate data
    if data_frames:
        aggregated_df = pl.concat(data_frames)
        print(aggregated_df)
        # Write aggregated dataframe to Delta Lake
        aggregated_df.write_delta(delta_table_path, mode="overwrite")

    # data_frames = []

    # for file_info in files:
    #     file_path = file_info["file_location"]

    #     # Read the file using pandas and the given config
    #     with open(file_path, "r") as file:
    #         df = pd.read_csv(
    #             file,
    #             **data_collection_config["pandas_kwargs"],
    #         )
    #         raw_cols = df.columns.tolist()
    #         df["depictio_run_id"] = file_info["run_id"]
    #         df = df[["depictio_run_id"] + raw_cols]
    #         data_frames.append(df)

    # # Aggregate data
    # aggregated_df = pd.concat(data_frames, axis=0, ignore_index=True)

    # # Convert aggregated dataframe to bytes and save to GridFS
    # output = BytesIO()
    # aggregated_df.to_parquet(output)
    # output.seek(0)  # Rewind to the start

    # # Using a naming convention for directories in GridFS
    # filename_structure = f"aggregates/{data_collection.workflow_id}/{data_collection.data_collection_id}.pkl"
    # file_id = grid_fs.put(output, filename=filename_structure)

    results = list()

    # TODO: performance improvement: use polars instead of pandas
    aggregated_df = aggregated_df.to_pandas()

    # For each column in the DataFrame
    for column in aggregated_df.columns:
        tmp_dict = collections.defaultdict(dict)
        tmp_dict["name"] = column
        # Identify the column data type
        col_type = str(aggregated_df[column].dtype).lower()
        print(col_type)
        tmp_dict["type"] = col_type.lower()
        print(agg_functions)
        # Check if the type exists in the agg_functions dict
        if col_type in agg_functions:
            methods = agg_functions[col_type]["card_methods"]

            # Initialize an empty dictionary to store results

            # For each method in the card_methods
            for method_name, method_info in methods.items():
                print(column, method_name)
                pandas_method = method_info["pandas"]
                print(pandas_method)
                # Check if the method is callable or a string
                if callable(pandas_method):
                    result = pandas_method(aggregated_df[column])
                    print(result)
                elif isinstance(pandas_method, str):
                    result = getattr(aggregated_df[column], pandas_method)()
                    print(result)
                else:
                    continue  # Skip if method is not available

                result = result.values if isinstance(result, np.ndarray) else result
                print(result)
                if method_name == "mode" and isinstance(result.values, np.ndarray):
                    result = result[0]
                tmp_dict["specs"][str(method_name)] = numpy_to_python(result)
        results.append(tmp_dict)
    print(results)
    


    # Update the data_collection_config with the GridFS file_id
    workflows_collection.update_one(
        {"_id": workflow_oid},
        {
            "$set": {
                "data_collections.$[elem].deltaTable": deltaTable.mongo(),
                "data_collections.$[elem].columns": serialize_for_mongo(results),
            }
        },
        array_filters=[{"elem._id": data_collection_oid}],
    )
    # data_collections_collection.create_index(
    #     [("data_collection_id", 1), ("workflow_id", 1)]
    # )

    return {
        "message": f"Data successfully aggregated and saved for data_collection: {data_collection_id} of workflow: {workflow_id}, aggregation id: {deltaTable.id}",
    }



# @deltatables_endpoint_router.get("/query/{workflow_id}/{data_collection_id}")
# async def query_data(
#     workflow_id: str,
#     data_collection_id: str,
#     query: DeltaTableQuery,
#     current_user: str = Depends(get_current_user),
# ):
#     """
#     Query the aggregated data from Delta Lake.
#     """

#     (
#         workflow_oid,
#         data_collection_oid,
#         workflow,
#         data_collection,
#         user_oid,
#     ) = validate_workflow_and_collection(
#          workflows_collection, current_user.user_id, workflow_id, data_collection_id, 
#     )

#     deltatable_location = data_collection.deltaTable.delta_table_location
#     print(deltatable_location, type(deltatable_location))
#     print(query.columns)




#     # Lazily read the Delta table & perform the query
#     df = pl.scan_delta(str(deltatable_location))
#     df = df.select(query.columns)


#     # Build and apply combined filter expressions
#     filter_expressions = []
#     for col, condition in query.filters.items():
#         col_filter = None
#         if condition.above is not None:
#             col_filter = (pl.col(col) > condition.above)
#         if condition.equal is not None:
#             col_filter = col_filter & (pl.col(col) == condition.equal) if col_filter else (pl.col(col) == condition.equal)
#         if condition.under is not None:
#             col_filter = col_filter & (pl.col(col) < condition.under) if col_filter else (pl.col(col) < condition.under)

#         if col_filter is not None:
#             filter_expressions.append(col_filter)
#         print(col_filter)

#     print(filter_expressions)
#     if filter_expressions:
#         combined_filter = filter_expressions[0]
#         for expr in filter_expressions[1:]:
#             combined_filter = combined_filter & expr

#         print(combined_filter)
#         df = df.filter(combined_filter)


#     return df.collect().to_dict()

    



@deltatables_endpoint_router.delete("/delete/{workflow_id}/{data_collection_id}")
async def delete_deltatable(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),

):
    """
    Delete all files from GridFS.
    """

    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(current_user.user_id)  # This should be the ObjectId
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)
    # Construct the query
    query = {
        "_id": workflow_oid,
        "permissions.owners.user_id": user_oid,
        "data_collections._id": data_collection_oid,
    }
    print(query)
    if not workflows_collection.find_one(query):
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {workflow_oid} found for the current user.",
        )
    
    # Query to find files associated with the data collection
    query_files = {"data_collection_id": data_collection_oid}
    
    # Batch delete the files
    delete_result = files_collection.delete_many(query_files)

    # Optionally, update the workflow document to reflect the deletion
    workflows_collection.update_one(
        {"_id": workflow_oid},
        {"$pull": {"data_collections": {"_id": data_collection_oid}}}
    )
    
    return {"message": f"Deleted {delete_result.deleted_count} files successfully"}
