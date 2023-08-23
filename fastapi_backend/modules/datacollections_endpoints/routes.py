import os
from fastapi import HTTPException
from fastapi import APIRouter
from typing import List

from configs.config import settings
from db import db
# from modules.datacollections_endpoints.models import File
# from modules.workflow_endpoints.models import Workflow
from configs.models import Workflow, File

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



@datacollections_endpoint_router.get("/scan_file_location/{workflow_id}")
async def scan_file_location_for_workflow(workflow_id: str):
    # Get the specific workflow
    workflow = workflows_collection.find_one({"workflow_id": workflow_id})

    if not workflow:
        raise HTTPException(
            status_code=404, detail=f"Workflow with id {workflow_id} not found"
        )

    location = workflow["location"]

    # This will hold our found files and their configurations
    data_collections = {}

    # Iterate through expected files based on your structure
    for file_type, file_config in workflow.get("files", {}).items():
        regex_pattern = file_config["regex"]

        # Search for files matching the regex pattern within the specified parent directory
        matched_files = []
        for root, dirs, files in os.walk(location):
            for file in files:
                if re.match(regex_pattern, file):
                    matched_files.append(os.path.join(root, file))

        # If any matched files were found, store their information
        if matched_files:
            data_collections[file_type] = {
                "matched_files": matched_files,
                "metadata": {
                    "regex": file_config["regex"],
                    "format": file_config["format"],
                    "pandas_kwargs": file_config["pandas_kwargs"],
                    "keep_columns": file_config.get("keep_columns", []),
                },
            }

    # Update the workflow's data_collections with the found files and their configurations
    workflows_collection.update_one(
        {"workflow_id": workflow_id}, {"$set": {"data_collections": data_collections}}
    )

    return {
        "status": f"File locations scanned and data collections updated for workflow {workflow_id}."
    }
