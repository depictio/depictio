import collections
import json
import os
import re
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter
import subprocess
import boto3
from botocore.exceptions import NoCredentialsError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db
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

data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db["users"]


def generate_track_config(track_type, track_details, data_collection_config):
    # Extract common JBrowse parameters from data collection config
    category = data_collection_config.get("jbrowse_params", {}).get(
        "category", "Uncategorized"
    )
    assemblyName = data_collection_config.get("jbrowse_params", {}).get(
        "assemblyName", "hg38"
    )

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
        adapter_type = (
            "BedTabixAdapter"
            if data_collection_config.get("format") == "BED"
            else "UnknownAdapter"
        )
        uri = track_details.get("uri")
        index_uri = f"{uri}.{data_collection_config.get('index_extension', 'tbi')}"

        track_config.update(
            {
                "type": "FeatureTrack",
                "adapter": {
                    "type": adapter_type,
                    "bedGzLocation"
                    if adapter_type == "BedTabixAdapter"
                    else "location": {"locationType": "UriLocation", "uri": uri},
                    "index": {
                        "location": {"locationType": "UriLocation", "uri": index_uri}
                    },
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
            placeholder = f'{{{key}}}'
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

    endpoint_url = "http://localhost:9000"
    bucket_name = "depictio-bucket"

    config["tracks"] = list()
    config["tracks"] = [
        track
        for track in config["tracks"]
        if f"{endpoint_url}/{bucket_name}" not in track["trackId"]
    ]

    print(config["tracks"])
    print(new_tracks)

    config["tracks"].extend(new_tracks)

    try:
        with open(config_path, "w") as file:
            json.dump(config, file, indent=4)
    except Exception as e:
        print(f"Failed to save JBrowse config: {e}")


def export_track_config_to_file(
    track_config, track_id, workflow_id, data_collection_id
):
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
    locations = workflow.workflow_config.parent_runs_location

    print(locations)

    # Initialize your S3 client outside of your endpoint function
    aws_access_key_id = "minio"
    aws_secret_access_key = "minio123"
    region_name = "us-east-1"
    endpoint_url = "http://localhost:9000"
    bucket_name = "depictio-bucket"

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region_name,
        endpoint_url=endpoint_url,
    )

    # Scan the runs and retrieve the files

    new_tracks = []

    for location in locations:
        print(location)
        runs_and_content = scan_runs(
            location, workflow.workflow_config, data_collection
        )
        runs_and_content = serialize_for_mongo(runs_and_content)

        if isinstance(runs_and_content, list) and all(
            isinstance(item, dict) for item in runs_and_content
        ):
            return_dict = {workflow.id: collections.defaultdict(list)}
            for run in sorted(runs_and_content, key=lambda x: x["run_location"]):
            # for run in runs_and_content[:1]:
                files = run.pop("files", [])

                run = WorkflowRun(**run)

                # Insert the run into runs_collection and retrieve its id
                inserted_run = runs_collection.insert_one(run.mongo())
                # run_id = inserted_run.inserted_id

                # Add run_id to each file before inserting
                # for file in files:
                print(files)
                for file in sorted(files, key=lambda x: x["file_location"]):
                    file = File(**file)
                    print(data_collection.config.type)
                    if data_collection.config.type == "Genome Browser":
                        print("Genome Browser")
                        file_location = file.mongo()["file_location"]

                        run_id = file.mongo()["run_id"]
                        # Extract the path structure after "/Data/"
                        print(file_location)
                        print(run_id)
                        path_suffix = file_location.split(f"{run_id}/")[1]

                        # Construct the S3 key respecting the structure
                        s3_key = f"{user_id}/{workflow_id}/{data_collection_id}/{run_id}/{path_suffix}"
                        print(s3_key)

                        track_details = {
                            "trackId": f"{endpoint_url}/{bucket_name}/{s3_key}",
                            "name": file.filename,
                            "uri": f"{endpoint_url}/{bucket_name}/{s3_key}",
                            "indexUri": f"{endpoint_url}/{bucket_name}/{s3_key}.tbi",
                            "run_id": run_id,

                        }
                        print(track_details)

                        regex_wildcards_list = [e.dict() for e in data_collection.config.regex_wildcards]
                        full_regex = construct_full_regex(data_collection.config.files_regex, regex_wildcards_list)

                        print(regex_wildcards_list)
                        print(full_regex)
                        wildcards_dict = dict()
                        if regex_wildcards_list:
                            for i, wc in enumerate(data_collection.config.regex_wildcards):
                                match = re.match(full_regex, file.filename).group(i+1)
                                print(match)
                                wildcards_dict[regex_wildcards_list[i]["name"]] = match
                            print(wildcards_dict)

                        if wildcards_dict:
                            track_details.update(wildcards_dict)
                                
                                


                        # print(data_collection.config)
                        
                        
                        track_config = generate_track_config(
                            "FeatureTrack",
                            track_details,
                            data_collection.mongo()["config"],
                        )
                        # print(track_config)

                        file_index = data_collection.config.index_extension
                        if not file_location.endswith(file_index):

                            jbrowse_template_location = data_collection.config.jbrowse_template_location
                            print(jbrowse_template_location)
                            print(os.path.exists(jbrowse_template_location))
                            jbrowse_template_json = json.load(open(jbrowse_template_location))
                            print(jbrowse_template_json)
                            track_config = populate_template_recursive(jbrowse_template_json, track_details)

                            print(track_config)
                            track_config["category"] =  track_config["category"] + [run_id]
                            print(track_config)

                            new_tracks.append(track_config)

                            # break
                        



                        # check if index

                        # prepare_and_add_track(track_config, workflow_id, data_collection_id)

                        try:
                            # Upload the file to S3
                            with open(file_location, "rb") as data:
                                s3_client.upload_fileobj(data, bucket_name, s3_key)
                            print(f"File {file_location} uploaded to {s3_key}")
                        except NoCredentialsError:
                            return {"error": "S3 credentials not available"}
                        except Exception as e:
                            print(f"Error uploading {file_location}: {e}")
                            return {"error": f"Failed to upload {file_location}"}

                    # Check if the file already exists in the database
                    existing_file = files_collection.find_one(
                        {"file_location": file.mongo()["file_location"]}
                    )
                    if not existing_file:
                        # If the file does not exist, add it to the database
                        files_collection.insert_one(file.mongo())
                    else:
                        print(f"File already exists: {file.mongo()['file_location']}")

                    # file["run_id"] = run.get("run_id")
                    # files_collection.insert_one(file.mongo())
                    # return_dict[workflow.id][run.get("run_id")].append(
                    #     file.get("file_location")
                    # )

        # # return_dict = json.dumps(return_dict, indent=4)

        # # Update the JBrowse configuration
        config_path = "/Users/tweber/Gits/jbrowse-watcher-plugin/config.json"
        update_jbrowse_config(config_path, new_tracks)
        print("JBrowse configuration updated.")

        return {
            "message": f"Files successfully scanned and created for data_collection: {data_collection.id} of workflow: {workflow.id}"
        }
    else:
        return {"Warning: runs_and_content is not a list of dictionaries."}


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
