import collections
import json
import os
import re
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter
import subprocess

from botocore.exceptions import NoCredentialsError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db
from depictio.api.v1.s3 import s3_client
from depictio.api.v1.endpoints.files_endpoints.models import File
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.endpoints.workflow_endpoints.models import WorkflowRun
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.utils import (
    # decode_token,
    # public_key_path,
    construct_full_regex,
    scan_runs,
    serialize_for_mongo,
)


files_endpoint_router = APIRouter()

# Define the collections from the settings
data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db["users"]

# Define the MinIO endpoint and bucket name from the settings
endpoint_url = settings.minio.endpoint
bucket_name = settings.minio.bucket


def generate_track_config(track_type, track_details, data_collection_config):
    # Extract common JBrowse parameters from data collection config
    category = data_collection_config.get("jbrowse_params", {}).get("category", "Uncategorized")
    assemblyName = data_collection_config.get("jbrowse_params", {}).get("assemblyName", "hg38")

    # Base configuration common to all tracks
    track_config = {
        "trackId": track_details.get("uri"),
        "name": track_details.get("name", "Unnamed Track"),
        "assemblyNames": [assemblyName],
        "category": category.split(",") + [track_details["run_id"]],
    }
    track_details.pop("run_id", None)

    # Configure adapter based on track type and data collection config
    if track_type == "FeatureTrack":
        adapter_type = "BedTabixAdapter" if data_collection_config.get("format") == "BED" else "UnknownAdapter"
        uri = track_details.get("uri")
        index_uri = f"{uri}.{data_collection_config.get('index_extension', 'tbi')}"

        track_config.update(
            {
                "type": "FeatureTrack",
                "adapter": {
                    "type": adapter_type,
                    "bedGzLocation" if adapter_type == "BedTabixAdapter" else "location": {"locationType": "UriLocation", "uri": uri},
                    "index": {"location": {"locationType": "UriLocation", "uri": index_uri}},
                },
            }
        )

    # Logic for other track types can be similarly extended using elif blocks

    return track_config


def populate_template_recursive(template, values):
    """
    Recursively populate a template with values.

    Args:
        template (dict | list | str): The template to populate.
        values (dict): The values to populate the template with.

    Returns:
        The populated template.
    """
    if isinstance(template, dict):
        # For dictionaries, recursively populate each value.
        return {k: populate_template_recursive(v, values) for k, v in template.items()}
    elif isinstance(template, list):
        # For lists, recursively populate each element.
        return [populate_template_recursive(item, values) for item in template]
    elif isinstance(template, str):
        # For strings, replace placeholders with actual values.
        result = template
        for key, value in values.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        print(result)

        return result
    else:
        # If not a dict, list, or str, return the template as is.
        return template


def update_jbrowse_config(config_path, new_tracks=[]):
    try:
        with open(config_path, "r") as file:
            config = json.load(file)
    except FileNotFoundError:
        print(f"Config file {config_path} not found.")
    except json.JSONDecodeError:
        print(f"Error decoding JSON from {config_path}.")

    if "tracks" not in config:
        config["tracks"] = []

    config["tracks"] = list()
    config["tracks"] = [track for track in config["tracks"] if f"{endpoint_url}/{bucket_name}" not in track["trackId"]]

    print(config["tracks"])
    print(new_tracks)

    config["tracks"].extend(new_tracks)

    try:
        with open(config_path, "w") as file:
            json.dump(config, file, indent=4)
    except Exception as e:
        print(f"Failed to save JBrowse config: {e}")


def export_track_config_to_file(track_config, track_id, workflow_id, data_collection_id):
    # Define a directory where you want to save the track configuration files
    config_dir = f"jbrowse2/configs/{workflow_id}/{data_collection_id}"  # Ensure this directory exists
    os.makedirs(config_dir, exist_ok=True)
    file_path = os.path.join(config_dir, f"{track_id}.json")

    with open(file_path, "w") as f:
        json.dump(track_config, f, indent=4)

    return file_path


def add_track_to_jbrowse(track_json_path):
    # Use npx to run the JBrowse CLI command directly
    command = [
        "npx",
        "@jbrowse/cli",
        "add-track-json",
        track_json_path,
        "--out",
        "/Users/tweber/Gits/jbrowse-watcher-plugin/config.json",  # Adjust as necessary
        "--update",
    ]

    # Execute the command
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to add track: {e}")


def prepare_and_add_track(track_config, workflow_id, data_collection_id):
    # Generate track configuration

    # Export the track configuration to a standard file
    track_id = track_config["trackId"]
    # track_json_path = export_track_config_to_file(track_config, track_id, workflow_id, data_collection_id)

    # Use the path to the JSON file to add the track to JBrowse
    # add_track_to_jbrowse(track_json_path)


@files_endpoint_router.get("/list/{workflow_id}/{data_collection_id}")
# @datacollections_endpoint_router.get("/files/{workflow_id}/{data_collection_id}", response_model=List[GridFSFileInfo])
async def list_registered_files(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    Fetch all files registered from a Data Collection registered into a workflow.
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

    query_files = {
        "data_collection._id": data_collection_oid,
    }
    files = list(files_collection.find(query_files))
    return convert_objectid_to_str(files)


def upload_file_to_s3(file_location, s3_key):
    try:
        with open(file_location, "rb") as data:
            s3_client.upload_fileobj(data, bucket_name, s3_key)
        print(f"File {file_location} uploaded to {s3_key}")
    except NoCredentialsError:
        return {"error": "S3 credentials not available"}
    except Exception as e:
        print(f"Error uploading {file_location}: {e}")
        return {"error": f"Failed to upload {file_location}"}


def handle_jbrowse_tracks(file, user_id, workflow_id, data_collection):
    file_location = file.mongo()["file_location"]
    run_id = file.mongo()["run_id"]

    # Extract the path suffix from the file location
    path_suffix = file_location.split(f"{run_id}/")[1]

    # Construct the S3 key respecting the structure
    s3_key = f"{user_id}/{workflow_id}/{data_collection.id}/{run_id}/{path_suffix}"

    # Prepare the track details
    track_details = {
        "trackId": f"{endpoint_url}/{bucket_name}/{s3_key}",
        "name": file.filename,
        "uri": f"{endpoint_url}/{bucket_name}/{s3_key}",
        "indexUri": f"{endpoint_url}/{bucket_name}/{s3_key}.tbi",
        "run_id": run_id,
    }

    # Prepare the regex wildcards
    regex_wildcards_list = [e.dict() for e in data_collection.config.dc_specific_properties.regex_wildcards]
    full_regex = construct_full_regex(data_collection.config.files_regex, regex_wildcards_list)

    # Extract the wildcards from the file name
    wildcards_dict = dict()
    if regex_wildcards_list:
        for i, wc in enumerate(data_collection.config.dc_specific_properties.regex_wildcards):
            match = re.match(full_regex, file.filename).group(i + 1)
            wildcards_dict[regex_wildcards_list[i]["name"]] = match

    # Update the track details with the wildcards if any
    if wildcards_dict:
        track_details.update(wildcards_dict)

    # Generate the track configuration
    track_config = generate_track_config(
        "FeatureTrack",
        track_details,
        data_collection.mongo()["config"],
    )

    file_index = data_collection.config.index_extension

    # Check if the file is an index and skip if it is
    if not file_location.endswith(file_index):
        # Prepare the JBrowse template
        jbrowse_template_location = data_collection.config.jbrowse_template_location
        jbrowse_template_json = json.load(open(jbrowse_template_location))
        track_config = populate_template_recursive(jbrowse_template_json, track_details)
        track_config["category"] = track_config["category"] + [run_id]

    # Upload the file to S3
    upload_file_to_s3(file_location, s3_key)

    return track_config


@files_endpoint_router.post("/scan/{workflow_id}/{data_collection_id}")
async def scan_data_collection(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    # print(workflow_id)
    # print(data_collection_id)

    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.user_id,
        workflow_id,
        data_collection_id,
    )

    user_id = str(current_user.user_id)

    # Retrieve the workflow_config from the workflow
    locations = workflow.config.parent_runs_location

    print(locations)

    # Scan the runs and retrieve the files

    new_tracks = []

    for location in locations:
        print(location)
        runs_and_content = scan_runs(location, workflow.config, data_collection)
        runs_and_content = serialize_for_mongo(runs_and_content)

        # Check if the scan was successful and the result is a list of dictionaries
        if isinstance(runs_and_content, list) and all(isinstance(item, dict) for item in runs_and_content):
            return_dict = {workflow.id: collections.defaultdict(list)}
            # Sort the runs by location
            runs_and_content = sorted(runs_and_content, key=lambda x: x["run_location"])
            for run in runs_and_content:
                files = run.pop("files", [])

                # Insert the run into runs_collection and retrieve its id
                run = WorkflowRun(**run)
                inserted_run = runs_collection.insert_one(run.mongo())
                run_id = inserted_run.inserted_id

                # Add run_id to each file before inserting
                for file in sorted(files, key=lambda x: x["file_location"]):
                    file = File(**file)
                    # print(data_collection.config.type)

                    # if data_collection.config.type == "Genome Browser":
                    #     # print(data_collection.config)
                    #     handle_jbrowse_tracks(file, user_id, workflow.id, data_collection)

                    # Check if the file already exists in the database
                    existing_file = files_collection.find_one({"file_location": file.mongo()["file_location"]})
                    if not existing_file:
                        # If the file does not exist, add it to the database
                        files_collection.insert_one(file.mongo())
                    else:
                        print(f"File already exists: {file.mongo()['file_location']}")

        return {"message": f"Files successfully scanned and created for data_collection: {data_collection.id} of workflow: {workflow.id}"}
    else:
        return {"Warning: runs_and_content is not a list of dictionaries."}


@files_endpoint_router.get("/create_trackset/{workflow_id}/{data_collection_id}")
async def create_trackset(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(current_user.user_id)
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)
    query = {
        "_id": workflow_oid,
        "permissions.owners.user_id": user_oid,
        "data_collections._id": data_collection_oid,
    }
    print(query)
    if not workflows_collection.find_one(query):
        raise HTTPException(
            status_code=404,
            detail=f"No data collection with id {data_collection_id} for workflow {workflow_id} found for the current user.",
        )

    # Retrieve the files associated with the data collection
    query_files = {
        "data_collection_id": data_collection_oid,
    }
    files = list(files_collection.find(query_files))

    new_tracks = list()

    for file in files:
        file = File(**file)
        track_config = handle_jbrowse_tracks(file, current_user.user_id, workflow_id, data_collection_id)
        new_tracks.append(track_config)

    # Update the JBrowse configuration
    jbrowse_config_dir = settings.jbrowse.config_dir
    # Join on user, workflow, and data collection IDs
    config_path = os.path.join(jbrowse_config_dir, f"{current_user.user_id}_{workflow_id}_{data_collection_id}.json")

    update_jbrowse_config(config_path, new_tracks)
    print("JBrowse configuration updated.")


@files_endpoint_router.delete("/delete/{workflow_id}/{data_collection_id}")
async def delete_files(
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
        {"$pull": {"data_collections": {"_id": data_collection_oid}}},
    )

    return {"message": f"Deleted {delete_result.deleted_count} files successfully"}
