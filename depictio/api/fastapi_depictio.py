import os
import re
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
import pandas as pd
import pymongo
import redis
from pydantic import ValidationError
import yaml
from depictio.fastapi_backend.pydantic_models import Workflow, FileConfig, WorkflowConfig
import depictio.fastapi_backend.pydantic_models
from gridfs import GridFS
import hashlib
import uvicorn
from typing import Tuple, Type
from pydantic import BaseModel




def load_yaml(filename: str, pydantic_model: Type[BaseModel]) -> BaseModel:
    # Load and validate the YAML configuration
    try:
        with open(filename, "r") as stream:
            data = yaml.safe_load(stream)
            data_validated_config = pydantic_model(**data)

            return data_validated_config

    except yaml.YAMLError:
        raise Exception("Failed to load YAML configuration.")
    except ValidationError as e:
        raise Exception(f"Invalid config structure: {e}")


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

settings = load_yaml("config_backend.yaml", pydantic_model=pydantic_models.Settings)

client = pymongo.MongoClient(settings.mongo_url)
db = client[settings.mongo_db]
grid_fs = GridFS(db)
redis_cache = redis.Redis(
    host=settings.redis_host, port=settings.redis_port, db=settings.redis_db
)
THRESHOLD_SIZE_MB = 15  # set it to something a bit less than 16MB to be safe


data_validated_config = load_yaml("config.yaml", pydantic_model=pydantic_models.Config)

data_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]


@app.get("/locations/{workflow_id}")
async def get_file_locations(workflow_id: str):
    workflow = workflows_collection.find_one({"workflow_id": workflow_id})

    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    locations = {}

    if "data_collections" not in workflow:
        raise HTTPException(
            status_code=404,
            detail=f"No data collections found for workflow {workflow_id}",
        )

    else:
        if not workflow["data_collections"]:
            raise HTTPException(
                status_code=404,
                detail=f"No data collections found for workflow {workflow_id}",
            )
        else:
            for file_type, file_config in workflow["data_collections"].items():
                regex_pattern = file_config["metadata"]["regex"]

                # Search for files matching the regex pattern within the specified parent directory
                matched_files = []
                for root, dirs, files in os.walk(workflow["location"]):
                    for file in files:
                        if re.match(regex_pattern, file):
                            matched_files.append(os.path.join(root, file))

                # Augment the file list with the metadata
                locations[file_type] = {
                    "matched_files": matched_files,
                    "metadata": {
                        "regex": file_config["metadata"]["regex"],
                        "format": file_config["metadata"]["format"],
                        "pandas_kwargs": file_config["metadata"]["pandas_kwargs"],
                        "keep_columns": file_config["metadata"]["keep_columns"],
                    },
                }

            return {"workflow": workflow_id, "files": locations}


def calculate_file_hash(file_path: str) -> str:
    """Calculate a unique hash for a file based on its content."""
    # Implementation of hashing function
    with open(file_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()



def process_file_content(file_path: str, matched_file_config: FileConfig) -> dict:
    """
    Load the file using pandas and process it according to the configuration.

    Args:
        file_path: Complete path to the file.
        matched_file_config: Configuration details for the matched file.

    Returns:
        Processed file data in the form of a dictionary.
    """
    
    df = pd.read_csv(file_path, **matched_file_config.pandas_kwargs)
    if matched_file_config.keep_columns:
        df = df[matched_file_config.keep_columns]
    print(df)
    return df.to_dict("records")


def match_file_to_config(file_name: str, workflow_config: dict) -> Tuple[str, dict]:
    """
    Determine the file configuration based on matching regex patterns.

    Args:
        file_name: Name of the file.
        workflow_config: Configuration details of the workflow.

    Returns:
        Tuple containing the file_type and matching file configuration if found, else None.
    """
    for file_type, file_config in workflow_config.files.items():
        print(file_type, file_config.regex)
        if re.match(file_config.regex, file_name):
            print("MATCH")
            return file_type, file_config
    return None, None


@app.post("/process/{workflow_id}")
async def process_and_scan_data_for_workflow(workflow_id: str):
    """Endpoint to process and store files based on a workflow's configuration."""

    data_collection.drop()
    
    # Fetch the specific workflow's configuration from the database
    workflow_config = workflows_collection.find_one({"workflow_id": workflow_id})
    print(workflow_config)
    if not workflow_config:
        raise HTTPException(
            status_code=404, detail=f"Workflow with id {workflow_id} not found"
        )

    location = workflow_config["location"]

    # Iterate through directories and files in the specified location
    for root, dirs, files in os.walk(location):
        for file in files:
            print("\n\n\n\n")
            print(file, data_validated_config.workflows[workflow_id])
            print("\n\n\n\n")
            # Determine the file type based on matching regex patterns
            file_type, matched_file_config = match_file_to_config(
                file, data_validated_config.workflows[workflow_id]
            )
            print(file_type, matched_file_config)

            if not file_type or not matched_file_config:
                continue  # Skip to the next file if no match was found


            # If a matching configuration was found, process the file
            if matched_file_config:
                file_path = os.path.join(root, file)
                file_hash = calculate_file_hash(file_path)
                existing_document = data_collection.find_one(
                    {"filepath": file_path, "content_hash": file_hash}
                )

                if not existing_document:
                    data_json = process_file_content(file_path, matched_file_config)
                    workflow_oid = ObjectId(workflow_config["_id"])
                    document = {
                        "workflow_id": workflow_id,
                        "workflow_oid": workflow_oid,
                        "file_type": file_type,
                        "metadata": dict(matched_file_config),
                        "filepath": file_path,
                        "content_hash": file_hash,
                        "content": data_json,
                    }
                    print(document)
                    data_collection.insert_one(document)
                    print("File processed and stored successfully.")
                else:
                    print("File already exists in the data collection.")

    # Update the database indexes
    data_collection.create_index("workflow_id")
    data_collection.create_index("file_type")
    data_collection.create_index(
        [
            ("workflow_id", pymongo.ASCENDING),
            ("file_type", pymongo.ASCENDING),
            ("filepath", pymongo.ASCENDING),
            ("content_hash", pymongo.ASCENDING),
        ]
    )

    return {
        "status": f"Data processed and stored successfully for workflow {workflow_id}"
    }


async def get_workflow_id_by_name(workflow_name: str):
    # Query the Workflows collection (or whatever your collection's name is) for the given workflow_name
    workflow = db.Workflows.find_one(
        {"name": workflow_name}, {"_id": 1}
    )  # We only want the _id field
    print(workflow, type(workflow), workflow_name)

    # Return the ID if found, otherwise return None
    return workflow["_id"] if workflow else None


@app.get("/datacollection/{workflow_name}/{file_type}")
async def get_data_content(workflow_name: str, file_type: str):
    # Assuming you have a method to get workflow_id by workflow_name
    workflow_id = await get_workflow_id_by_name(workflow_name)

    # If no workflow_id found, raise a 404 error
    if not workflow_id:
        raise HTTPException(
            status_code=404, detail=f"No workflow found with name {workflow_name}"
        )

    # Using pymongo or your preferred library, fetch the content
    data_collection = db.data_collection.find_one(
        {"workflow_id": workflow_id, "file_type": file_type}
    )

    # If no data found, raise a 404 error
    if not data_collection:
        raise HTTPException(
            status_code=404,
            detail=f"No data found for workflow: {workflow_name}, file type: {file_type}",
        )

    return data_collection


@app.get("/workflows")
async def get_workflows():
    workflows = workflows_collection.find(
        {}
    )  # Find all workflows without any projection
    if not workflows:
        raise HTTPException(status_code=404, detail="No workflows found.")

    # Create the desired dictionary structure
    workflow_dict = {
        str(wf.get("workflow_id")): {
            "_id": str(wf["_id"]),
            "workflow_id": wf.get("workflow_id", None),
            "workflow_name": wf.get("workflow_name", None),
            "description": wf.get("description", None),
            "workflow_engine": wf.get("workflow_engine", None),
            "location": wf.get("location", None),
            "data_collections": wf.get("data_collections", []),
        }
        for wf in workflows
    }

    return workflow_dict


@app.post("/workflows/{workflow_engine}--{workflow_name}")
async def create_workflow(
    workflow_name: str, workflow_engine: str, description: str, location: str
):
    workflow = Workflow(
        workflow_name=workflow_name,
        workflow_engine=workflow_engine,
        description=description,
        workflow_location=location,
    )

    # Check if directory name matches the format `{workflow_engine}--{workflow_name}`
    expected_dir_name = f"{workflow_engine}--{workflow_name}"
    actual_dir_name = os.path.basename(location)

    if actual_dir_name != expected_dir_name:
        raise HTTPException(
            status_code=400,
            detail=f"The directory name '{actual_dir_name}' does not match the expected format '{expected_dir_name}'",
        )

    existing_workflow = workflows_collection.find_one({"workflow_name": workflow_name})
    if existing_workflow:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow with name '{workflow_name}' already exists.",
        )

    workflow_data = {
        "workflow_id": f"{workflow.workflow_engine}--{workflow.workflow_name}",
        "workflow_name": workflow.workflow_name,
        "description": workflow.description,
        "workflow_engine": workflow.workflow_engine,
        "location": workflow.workflow_location,
        "data_collections": [],
    }

    result = workflows_collection.insert_one(workflow_data)
    return {"workflow_id": str(result.inserted_id)}


@app.post("/scan_file_location/{workflow_id}")
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
