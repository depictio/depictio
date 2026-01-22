import collections
import hashlib
import json
import os
from datetime import datetime

from botocore.exceptions import NoCredentialsError
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import files_collection, jbrowse_collection, workflows_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.s3 import s3_client
from depictio.models.models.files import File
from depictio.models.models.jbrowse import LogData

jbrowse_endpoints_router = APIRouter()


def generate_track_config(track_type, track_details, data_collection_config):
    """Generate JBrowse track configuration from track details and data collection config."""
    category = data_collection_config.get("jbrowse_params", {}).get("category", "Uncategorized")
    assemblyName = data_collection_config.get("jbrowse_params", {}).get("assemblyName", "hg38")

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
            "BedTabixAdapter" if data_collection_config.get("format") == "BED" else "UnknownAdapter"
        )
        uri = track_details.get("uri")
        index_uri = f"{uri}.{data_collection_config.get('index_extension', 'tbi')}"

        track_config.update(
            {
                "type": "FeatureTrack",
                "adapter": {
                    "type": adapter_type,
                    ("bedGzLocation" if adapter_type == "BedTabixAdapter" else "location"): {
                        "locationType": "UriLocation",
                        "uri": uri,
                    },
                    "index": {"location": {"locationType": "UriLocation", "uri": index_uri}},
                },
            }
        )

    return track_config


def populate_template_recursive(template, values):
    """
    Recursively populate a template with values.

    Args:
        template: The template to populate (dict, list, or str).
        values: The values to populate the template with.

    Returns:
        The populated template.
    """
    if isinstance(template, dict):
        return {k: populate_template_recursive(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [populate_template_recursive(item, values) for item in template]
    if isinstance(template, str):
        result = template
        for key, value in values.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        return result
    return template


def update_jbrowse_config(config_path, new_tracks=[]):
    """Update JBrowse configuration with new tracks."""
    try:
        with open(config_path) as file:
            config = json.load(file)
    except FileNotFoundError:
        default_jbrowse_config_path = "/app/data/jbrowse2/config.json"
        config = json.load(open(default_jbrowse_config_path))
    except json.JSONDecodeError:
        logger.warning(f"Error decoding JSON from {config_path}.")

    if "tracks" not in config:
        config["tracks"] = []

    config["tracks"] = list()
    config["tracks"] = [
        track
        for track in config["tracks"]
        if f"{settings.minio.endpoint_url}{settings.minio.port}:/{settings.minio.bucket_name}"  # type: ignore[possibly-unbound-attribute]
        not in track["trackId"]
    ]

    config["tracks"].extend(new_tracks)

    try:
        with open(config_path, "w") as file:
            json.dump(config, file, indent=4)

        lite_config = config.copy()
        lite_config["tracks"] = lite_config["tracks"][:5]
        with open(config_path.replace(".json", "_lite.json"), "w") as file:
            json.dump(lite_config, file, indent=4)

        return {"message": "JBrowse config updated successfully.", "type": "success"}
    except Exception as e:
        logger.error(f"Failed to save JBrowse config: {e}")
        return {"message": f"Failed to save JBrowse config: {e}", "type": "error"}


def upload_file_to_s3(bucket_name, file_location, s3_key):
    """Upload a file to S3 if it doesn't already exist."""
    if not os.path.exists(file_location):
        return {"error": f"File {file_location} does not exist."}

    if s3_client.list_objects_v2(Bucket=bucket_name, Prefix=s3_key).get("Contents"):
        return None

    try:
        with open(file_location, "rb") as data:
            s3_client.upload_fileobj(data, bucket_name, s3_key)
    except NoCredentialsError:
        return {"error": "S3 credentials not available"}
    except Exception as e:
        logger.error(f"Error uploading {file_location}: {e}")
        return {"error": f"Failed to upload {file_location}"}


def handle_jbrowse_tracks(file, user_id, workflow_id, data_collection):
    """Handle JBrowse track creation for a file."""
    if not isinstance(file, dict):
        file = file.mongo()

    endpoint_url = settings.minio.external_endpoint  # type: ignore[possibly-unbound-attribute]
    port = settings.minio.port
    bucket_name = settings.minio.bucket

    file_location = file["file_location"]
    run_id = file["run_id"]

    # Extract the path suffix from the file location
    path_suffix = file_location.split(f"{run_id}/")[1]

    # Get workflow tag from workflow_id
    wf_tag = workflows_collection.find_one({"_id": ObjectId(workflow_id)})["workflow_tag"]  # type: ignore[non-subscriptable]

    # Construct the S3 key respecting the structure
    s3_key = f"{user_id}/{workflow_id}/{data_collection.id}/{run_id}/{path_suffix}"
    trackid = f"{endpoint_url}:{port}/{bucket_name}/{s3_key}"

    # NOTE: trial using hash instead of path to avoid long path - 16 characters using sha256
    s3_key_hash = hashlib.sha256(s3_key.encode("utf-8")).hexdigest()[:16]

    # Design categories
    categories = [
        f"{wf_tag} - {workflow_id}",
        f"{data_collection.data_collection_tag} - {data_collection.id}",
    ]

    # Prepare the track details
    track_details = {
        "trackId": s3_key_hash,
        "name": file["filename"],
        "uri": f"{endpoint_url}:{port}/{bucket_name}/{s3_key}",
        "indexUri": f"{endpoint_url}:{port}/{bucket_name}/{s3_key}.tbi",
        "run_id": run_id,
        "category": categories,
    }

    file_index = data_collection.config.dc_specific_properties.index_extension

    file["S3_location"] = trackid
    file["trackId"] = s3_key_hash
    files_collection.update_one({"_id": file["_id"]}, {"$set": file})

    # Check if the file is an index and skip if it is
    if not file_location.endswith(file_index):
        # Generate the track configuration
        track_config = generate_track_config(
            "FeatureTrack",
            track_details,
            data_collection.mongo()["config"],
        )

        # Prepare the JBrowse template
        jbrowse_template_location = (
            data_collection.config.dc_specific_properties.jbrowse_template_location
        )
        jbrowse_template_json = json.load(open(jbrowse_template_location))

        track_config = populate_template_recursive(jbrowse_template_json, track_details)
        # Ensure category is a list before appending
        category = track_details["category"]
        if isinstance(category, list):
            track_config["category"] = category + [run_id]
        else:
            track_config["category"] = [str(category), run_id] if category else [run_id]
        return track_config

    return None


def construct_jbrowse_url(block, tracks):
    """Construct a JBrowse URL from block and track information."""
    track_list = ",".join(tracks)
    return f"assembly={block.assemblyName}&loc={block.refName}:{int(block.start)}..{int(block.end)}&tracks={track_list}"


@jbrowse_endpoints_router.post("/create_trackset/{workflow_id}/{data_collection_id}")
async def create_trackset(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)
    user_oid = ObjectId(current_user.id)  # type: ignore[possibly-unbound-attribute]
    assert isinstance(workflow_oid, ObjectId)
    assert isinstance(data_collection_oid, ObjectId)
    assert isinstance(user_oid, ObjectId)

    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.id,  # type: ignore[possibly-unbound-attribute]
        workflow_id,
        data_collection_id,
    )

    files = list(files_collection.find({"data_collection._id": data_collection_oid}))

    new_tracks = list()

    for file in files:
        file = File(**file)  # type: ignore[missing-argument]

        track_config = handle_jbrowse_tracks(file, current_user.id, workflow_id, data_collection)  # type: ignore[possibly-unbound-attribute]
        if track_config:
            new_tracks.append(track_config)

    jbrowse_config_dir = settings.jbrowse.config_dir  # type: ignore[possibly-unbound-attribute]
    config_path = os.path.join(jbrowse_config_dir, f"{current_user.id}_{data_collection_oid}.json")  # type: ignore[possibly-unbound-attribute]

    payload = update_jbrowse_config(config_path, new_tracks)
    if payload["type"] == "error":
        raise HTTPException(status_code=404, detail=f"{payload['message']}")
    return {"message": "JBrowse configuration updated."}


@jbrowse_endpoints_router.post("/log")
async def log_message(log_data: LogData):
    """Log JBrowse navigation data."""
    current_timestamp = int(datetime.now().timestamp() * 1000)

    if log_data.coarseDynamicBlocks and log_data.selectedTracks:
        block = log_data.coarseDynamicBlocks[0][0]
        tracks = [t for track in log_data.selectedTracks for t in track.tracks]

        dict_jbrowse_url_args = {
            "assembly": block.assemblyName,
            "loc": f"chr{block.refName}:{round(int(block.start))}:{round(int(block.end))}",
            "tracks": tracks,
        }
    else:
        dict_jbrowse_url_args = {}

    dict_jbrowse_url_args["timestamp"] = current_timestamp
    dict_jbrowse_url_args["dashboard_id"] = "1"  # Replace with actual dashboard ID
    # Update or insert the message into the database
    if jbrowse_collection.find_one():
        document = jbrowse_collection.find_one({"dashboard_id": "1"})
        document.update(dict_jbrowse_url_args)  # type: ignore[union-attr]
        jbrowse_collection.update_one(
            {"_id": ObjectId(document["_id"])},  # type: ignore[non-subscriptable]
            {"$set": document},
            upsert=True,  # type: ignore[non-subscriptable]
        )
    else:
        jbrowse_collection.insert_one(dict_jbrowse_url_args)

    return {"Status": "Logged successfully."}


@jbrowse_endpoints_router.get("/last_status")
async def get_jbrowse_logs():
    """Get the last JBrowse navigation status."""
    log = jbrowse_collection.find_one()
    if log:
        log.pop("_id", None)
        return log
    return {"message": "No logs available."}


@jbrowse_endpoints_router.get("/map_tracks_using_wildcards/{workflow_id}/{data_collection_id}")
async def map_tracks_using_wildcards(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """Map tracks using wildcards for filtering."""
    data_collection_oid = ObjectId(data_collection_id)
    nested_dict = collections.defaultdict(lambda: collections.defaultdict(dict))

    files = files_collection.find({"data_collection._id": data_collection_oid})
    for file in files:
        if file["filename"].endswith(
            file["data_collection"]["config"]["dc_specific_properties"]["index_extension"]
        ):
            continue
        for wildcard in file["wildcards"]:
            nested_dict[data_collection_id][wildcard["name"]][wildcard["value"]] = file["trackId"]

    return nested_dict


@jbrowse_endpoints_router.post("/filter_config")
async def filter_config(
    filter_params: dict,
    current_user: str = Depends(get_current_user),
):
    """Filter JBrowse config to include only specified tracks."""
    tracks = filter_params.get("tracks", [])
    jbrowse_config_dir = settings.jbrowse.config_dir  # type: ignore[possibly-unbound-attribute]
    data_collection_oid = filter_params.get("data_collection_id")
    dashboard_id = filter_params.get("dashboard_id")

    default_config_path = os.path.join(
        jbrowse_config_dir,
        f"{current_user.id}_{data_collection_oid}.json",  # type: ignore[possibly-unbound-attribute]
    )

    if not tracks:
        return {"message": "No tracks provided.", "session": None}
    if not default_config_path:
        return {"message": "No default config provided.", "session": None}
    if not dashboard_id:
        return {"message": "No dashboard ID provided."}

    config = json.load(open(default_config_path))

    filtered_track_ids = set()
    filtered_tracks = []
    for track in config["tracks"]:
        if track["trackId"] in tracks and track["trackId"] not in filtered_track_ids:
            filtered_track_ids.add(track["trackId"])
            filtered_tracks.append(track)

    config["tracks"] = filtered_tracks

    output_path = default_config_path.replace(".json", f"_filtered_{dashboard_id}.json")
    output_return_path = output_path.replace(f"{settings.jbrowse.config_dir}/", "")  # type: ignore[possibly-unbound-attribute]

    with open(output_path, "w") as file:
        json.dump(config, file, indent=4)

    return {"message": "Filtered config saved successfully.", "session": output_return_path}


@jbrowse_endpoints_router.post("/dynamic_mapping_dict")
async def dynamic_mapping_dict(
    mapping_dict: dict,
    current_user: str = Depends(get_current_user),
):
    """Receive a dynamic mapping dictionary."""
    return {"message": "Mapping dictionary received."}
