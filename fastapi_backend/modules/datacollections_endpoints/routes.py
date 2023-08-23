import os
import re
from fastapi import HTTPException
from fastapi import APIRouter
from typing import List

from configs.config import settings
from db import db
# from modules.datacollections_endpoints.models import File
# from modules.workflow_endpoints.models import Workflow
from configs.models import Workflow, File, DataCollection
from fastapi_backend.utils import scan_runs

datacollections_endpoint_router = APIRouter()

data_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]



# @app.get("/datacollection/{workflow_name}/{file_type}")
# async def get_data_content(workflow_name: str, file_type: str):
#     # Assuming you have a method to get workflow_id by workflow_name
#     workflow_id = await get_workflow_id_by_name(workflow_name)

#     # If no workflow_id found, raise a 404 error
#     if not workflow_id:
#         raise HTTPException(
#             status_code=404, detail=f"No workflow found with name {workflow_name}"
#         )

#     # Using pymongo or your preferred library, fetch the content
#     data_collection = db.data_collection.find_one(
#         {"workflow_id": workflow_id, "file_type": file_type}
#     )

#     # If no data found, raise a 404 error
#     if not data_collection:
#         raise HTTPException(
#             status_code=404,
#             detail=f"No data found for workflow: {workflow_name}, file type: {file_type}",
#         )

#     return data_collection



@datacollections_endpoint_router.post("/scan_files_tmp")
async def scan_files_temp(
    workflow: Workflow, 
    data_collection: DataCollection
):
    print(workflow)
    location = workflow.workflow_config.parent_runs_location

    scan_runs(location, workflow.workflow_config, data_collection)

    # # # This will hold our found files and their configurations
    # data_collections = {}

    # # Iterate through expected files based on your structure
    # for file_type, file_config in data_collection.get("files", {}).items():
    #     regex_pattern = file_config["regex"]

    #     # Search for files matching the regex pattern within the specified parent directory
    #     matched_files = []
    #     for root, dirs, files in os.walk(workflow.parent_runs_location):
    #         for file in files:
    #             if re.match(regex_pattern, file):
    #                 matched_files.append(os.path.join(root, file))
    #     print(matched_files)

    #     # If any matched files were found, store their information
    #     if matched_files:
    #         data_collections[file_type] = {
    #             "matched_files": matched_files,
    #             "metadata": {
    #                 "regex": file_config["regex"],
    #                 "format": file_config["format"],
    #                 "pandas_kwargs": file_config["pandas_kwargs"],
    #                 "keep_columns": file_config.get("keep_columns", []),
    #             },
    #         }
    # print(data_collections)
    # expected_dir_name = f"{workflow.workflow_engine}--{workflow.workflow_name}"
    # actual_dir_name = os.path.basename(workflow.parent_runs_location)

    # if actual_dir_name != expected_dir_name:
    #     raise HTTPException(
    #         status_code=400,
    #         detail=f"The directory name '{actual_dir_name}' does not match the expected format '{expected_dir_name}'",
    #     )

    # existing_workflow = workflows_collection.find_one(
    #     {"workflow_id": workflow.workflow_id}
    # )
    # if existing_workflow:
    #     raise HTTPException(
    #         status_code=400,
    #         detail=f"Workflow with name '{workflow.workflow_id}' already exists.",
    #     )

    # result = workflows_collection.insert_one(dict(workflow))
    # return {"workflow_id": str(result.inserted_id)}



# @datacollections_endpoint_router.get("/scan_files/{workflow_id}")
# @datacollections_endpoint_router.get("/scan_files/{workflow}")
# # @datacollections_endpoint_router.get("/scan_files/{workflow_engine}/{workflow_name}")
# async def scan_files_for_workflow(workflow_engine: str, workflow_name: str):
#     # Get the specific workflow
#     workflow_id = f"{workflow_engine}/{workflow_name}"
#     workflow = workflows_collection.find_one({"workflow_id": workflow_id})
#     print(workflow)



#     if not workflow:
#         raise HTTPException(
#             status_code=404, detail=f"Workflow with id {workflow_id} not found"
#         )

#     location = workflow["parent_runs_location"]
#     print(location)

#     # # This will hold our found files and their configurations
#     data_collections = {}

#     # Iterate through expected files based on your structure
#     for file_type, file_config in workflow.get("files", {}).items():
#         regex_pattern = file_config["regex"]

#         # Search for files matching the regex pattern within the specified parent directory
#         matched_files = []
#         for root, dirs, files in os.walk(location):
#             for file in files:
#                 if re.match(regex_pattern, file):
#                     matched_files.append(os.path.join(root, file))
#         print(matched_files)

#         # If any matched files were found, store their information
#         if matched_files:
#             data_collections[file_type] = {
#                 "matched_files": matched_files,
#                 "metadata": {
#                     "regex": file_config["regex"],
#                     "format": file_config["format"],
#                     "pandas_kwargs": file_config["pandas_kwargs"],
#                     "keep_columns": file_config.get("keep_columns", []),
#                 },
#             }
#     print(data_collections)

#     # # Update the workflow's data_collections with the found files and their configurations
#     # workflows_collection.update_one(
#     #     {"workflow_id": workflow_id}, {"$set": {"data_collections": data_collections}}
#     # )

#     # return {
#     #     "status": f"File locations scanned and data collections updated for workflow {workflow_id}."
#     # }
