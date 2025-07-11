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

        return result
    else:
        # If not a dict, list, or str, return the template as is.
        return template


def update_jbrowse_config(config_path, new_tracks=[]):
    # TODO: output a complete and a light minimal config + add a "load full data" to speed up the process
    try:
        with open(config_path) as file:
            config = json.load(file)
    except FileNotFoundError:
        logger.warning(f"Config file {config_path} not found.")

        # Use default JSON config for JBrowse2
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
        logger.info("updating config...")
        # plogger.info(config)
        logger.debug(config_path)

        with open(config_path, "w") as file:
            json.dump(config, file, indent=4)

        # FIXME: create a lite version of the config
        lite_config = config.copy()
        lite_config["tracks"] = lite_config["tracks"][:5]

        with open(config_path.replace(".json", "_lite.json"), "w") as file:
            json.dump(lite_config, file, indent=4)

        return {"message": "JBrowse config updated successfully.", "type": "success"}
    except Exception as e:
        # Log the error

        logger.error(f"Failed to save JBrowse config: {e}")
        return {"message": f"Failed to save JBrowse config: {e}", "type": "error"}


# def export_track_config_to_file(track_config, track_id, workflow_id, data_collection_id):
#     # Define a directory where you want to save the track configuration files
#     config_dir = f"jbrowse2/configs/{workflow_id}/{data_collection_id}"  # Ensure this directory exists
#     os.makedirs(config_dir, exist_ok=True)
#     file_path = os.path.join(config_dir, f"{track_id}.json")

#     with open(file_path, "w") as f:
#         json.dump(track_config, f, indent=4)

#     return file_path


def upload_file_to_s3(bucket_name, file_location, s3_key):
    logger.debug(f"S3 client: {s3_client}")
    logger.debug(f"List buckets: {s3_client.list_buckets()}")
    logger.debug(f"List objects: {s3_client.list_objects_v2(Bucket=bucket_name, Prefix=s3_key)}")
    logger.debug(f"File location: {file_location}, Bucket name: {bucket_name}, S3 key: {s3_key}")

    # check if the file exists
    if not os.path.exists(file_location):
        logger.debug(f"File {file_location} does not exist.")
        return {"error": f"File {file_location} does not exist."}

    # check if file already exists in S3
    skip_upload = False
    if s3_client.list_objects_v2(Bucket=bucket_name, Prefix=s3_key).get("Contents"):
        logger.warning(f"File {s3_key} already exists in S3.")
        skip_upload = True

    if skip_upload is False:
        try:
            with open(file_location, "rb") as data:
                s3_client.upload_fileobj(data, bucket_name, s3_key)
            logger.debug(f"File {file_location} uploaded to {s3_key}")
        except NoCredentialsError:
            return {"error": "S3 credentials not available"}
        except Exception as e:
            logger.error(f"Error uploading {file_location}: {e}")
            return {"error": f"Failed to upload {file_location}"}


def handle_jbrowse_tracks(file, user_id, workflow_id, data_collection):
    if not isinstance(file, dict):
        file = file.mongo()

    logger.debug(f"Handling JBrowse tracks for file: {file}")

    # endpoint_url = "http://0.0.0.0"
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

    # # Prepare the regex wildcards
    # regex_wildcards_list = data_collection.config.dc_specific_properties.regex.wildcards_regex
    # full_regex = construct_full_regex(data_collection.config.regex.pattern, regex_wildcards_list)

    # # Extract the wildcards from the file name
    # wildcards_dict = dict()
    # if regex_wildcards_list:
    #     for i, wc in enumerate(data_collection.config.dc_specific_properties.regex_wildcards):
    #         match = re.match(full_regex, file.filename).group(i + 1)
    #         wildcards_dict[regex_wildcards_list[i]["name"]] = match

    # # Update the track details with the wildcards if any
    # if wildcards_dict:
    #     track_details.update(wildcards_dict)

    file_index = data_collection.config.dc_specific_properties.index_extension

    # Upload the file to S3
    # upload_file_to_s3(bucket_name, file_location, s3_key)

    # Update the file mongo document with the S3 key
    # FIXME: find another way to access internally and externally (jbrowse) files registered
    file["S3_location"] = trackid
    file["trackId"] = s3_key_hash

    # check if file is dict or object
    # if not isinstance(file, dict):
    #     file = file.mongo()

    # Update into the database
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
        track_config["category"] = track_details["category"] + [run_id]
        return track_config

    else:
        return


def construct_jbrowse_url(block, tracks):
    assembly_name = block.assemblyName
    ref_name = block.refName
    start = int(block.start)
    end = int(block.end)
    track_list = ",".join(tracks)

    url = f"assembly={assembly_name}&loc={ref_name}:{start}..{end}&tracks={track_list}"
    return url


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

    # Retrieve the files associated with the data collection
    query_files = {
        "data_collection._id": data_collection_oid,
    }
    files = list(files_collection.find(query_files))
    logger.debug(f"Files: {files}")

    new_tracks = list()

    for file in files:
        file = File(**file)  # type: ignore[missing-argument]

        track_config = handle_jbrowse_tracks(file, current_user.id, workflow_id, data_collection)  # type: ignore[possibly-unbound-attribute]
        if track_config:
            new_tracks.append(track_config)

    # Update the JBrowse configuration
    jbrowse_config_dir = settings.jbrowse.config_dir  # type: ignore[possibly-unbound-attribute]

    config_path = os.path.join(jbrowse_config_dir, f"{current_user.id}_{data_collection_oid}.json")  # type: ignore[possibly-unbound-attribute]

    payload = update_jbrowse_config(config_path, new_tracks)
    if payload["type"] == "error":
        raise HTTPException(status_code=404, detail=f"{payload['message']}")
    logger.info("JBrowse configuration updated.")
    return {"message": "JBrowse configuration updated."}


@jbrowse_endpoints_router.post("/log")
async def log_message(log_data: LogData):
    logger.debug(f"{datetime.now()}, {log_data}")  # Or store it in a database/file
    logger.debug(settings)

    if log_data.coarseDynamicBlocks and log_data.selectedTracks:
        # Extract the first block and tracks
        block = log_data.coarseDynamicBlocks[0][0]  # Assuming the first block of the first array
        tracks = [
            t for track in log_data.selectedTracks for t in track.tracks
        ]  # Flatten track list

        # jbrowse_url_args = construct_jbrowse_url(block, tracks)
        # logger.info(jbrowse_url_args)

        start = round(int(block.start), 0)
        end = round(int(block.end), 0)

        dict_jbrowse_url_args = {
            "assembly": block.assemblyName,
            "loc": f"chr{block.refName}:{start}-{end}",
            "tracks": tracks,
        }
        current_timestamp = int(datetime.now().timestamp() * 1000)  # Current time in milliseconds

    else:
        dict_jbrowse_url_args = {}

        # connection = pika.BlockingConnection(pika.ConnectionParameters(settings.rabbitmq.host))
        # channel = connection.channel()

        # # Declare a topic exchange
        # channel.exchange_declare(exchange=settings.rabbitmq.exchange, exchange_type="topic", durable=True)

        # # Declare a queue named 'my_queue' with a message TTL of 300000 milliseconds (5 minutes)
        # args = {"x-message-ttl": 30000}
        # channel.queue_declare(queue=settings.rabbitmq.queue, durable=True, arguments=args)

        # # Bind the queue to the exchange with the routing key 'latest_status'
        # channel.queue_bind(exchange=settings.rabbitmq.exchange, queue=settings.rabbitmq.queue, routing_key=settings.rabbitmq.routing_key)

        # # Fetch the current timestamp

        # # Publish the message to the exchange with the 'latest_status' routing key
        # channel.basic_publish(
        #     exchange=settings.rabbitmq.exchange,
        #     routing_key=settings.rabbitmq.routing_key,
        #     body=json.dumps(dict_jbrowse_url_args),
        #     properties=pika.BasicProperties(
        #         delivery_mode=2,  # make message persistent
        #         timestamp=current_timestamp,  # set timestamp
        #     ),
        # )

    # Write the message to mongoDB
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
    # else:
    #     return {"Status": "No data to log."}


@jbrowse_endpoints_router.get("/last_status")
async def get_jbrowse_logs():
    # Check if message exists in the queue
    # connection = pika.BlockingConnection(pika.ConnectionParameters(settings.rabbitmq.host))
    # channel = connection.channel()

    # # Fetch the message without auto acknowledgment
    # method_frame, header_frame, body = channel.basic_get(queue=settings.rabbitmq.queue, auto_ack=False)

    # if method_frame:
    #     # Extract the timestamp from the header frame

    #     # # Acknowledge the message after processing
    #     channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
    #     connection.close()
    #     data = json.loads(body.decode("utf-8"))
    #     if data == {}:
    #         return {"message": "RabbitMQ queue empty and DB is empty"}
    #     else:
    #         logger.info("RabbitMQ queue NOT empty and message is NOT empty")
    #         return data

    # # Else if no message in the queue, check the database
    # else:
    if jbrowse_collection.find_one():
        log = jbrowse_collection.find_one()
        log.pop("_id", None)  # type: ignore[possibly-unbound-attribute]
        return log
    else:
        return {"message": "No logs available."}


@jbrowse_endpoints_router.get("/map_tracks_using_wildcards/{workflow_id}/{data_collection_id}")
async def map_tracks_using_wildcards(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    # workflow_oid = ObjectId(workflow_id)
    data_collection_oid = ObjectId(data_collection_id)

    # Constructing the nested dictionary
    import collections

    nested_dict = collections.defaultdict(lambda: collections.defaultdict(dict))

    files = files_collection.find({"data_collection._id": data_collection_oid})

    for file in files:
        # logger.info(file)
        if file["filename"].endswith(
            file["data_collection"]["config"]["dc_specific_properties"]["index_extension"]
        ):
            continue
        for wildcard in file["wildcards"]:
            # if file["trackId"]:
            nested_dict[data_collection_id][wildcard["name"]][wildcard["value"]] = file["trackId"]
    logger.debug(len(nested_dict[data_collection_id]["cell"]))
    return nested_dict


@jbrowse_endpoints_router.post("/filter_config")
async def filter_config(
    filter_params: dict,
    current_user: str = Depends(get_current_user),
):
    tracks = filter_params.get("tracks", [])
    logger.debug(f"Filtering tracks: {tracks}")
    # Update the JBrowse configuration
    jbrowse_config_dir = settings.jbrowse.config_dir  # type: ignore[possibly-unbound-attribute]
    data_collection_oid = filter_params.get("data_collection_id")

    default_config_path = os.path.join(
        jbrowse_config_dir,
        f"{current_user.id}_{data_collection_oid}.json",  # type: ignore[possibly-unbound-attribute]
    )
    # lite_config_path = default_config_path.replace(".json", "_lite.json")
    dashboard_id = filter_params.get("dashboard_id")

    logger.debug(f"Filtering tracks: {tracks}")
    logger.debug(f"Default config path: {default_config_path}")
    logger.debug(f"Dashboard ID: {dashboard_id}")
    logger.debug(f"Current user: {current_user.id}")  # type: ignore[possibly-unbound-attribute]
    logger.debug(f"Len tracks: {len(tracks)}")

    if not tracks:
        return {"message": "No tracks provided.", "session": None}

    if not default_config_path:
        return {"message": "No default config provided.", "session": None}

    if not dashboard_id:
        return {"message": "No dashboard ID provided."}

    # Load the default config
    config = json.load(open(default_config_path))

    filtered_track_ids = list()
    filtered_tracks = list()
    for track in config["tracks"]:
        if track["trackId"] in tracks:
            if track["trackId"] not in filtered_track_ids:
                filtered_track_ids.append(track["trackId"])
                filtered_tracks.append(track)
                logger.debug(f"Track ID: {track['trackId']}")

    logger.debug(f"Filtered tracks: {filtered_tracks}")
    config["tracks"] = filtered_tracks

    # Construct the filtered config
    output_path = default_config_path.replace(".json", f"_filtered_{dashboard_id}.json")
    logger.debug(f"Output path: {output_path}")

    output_return_path = output_path.replace(f"{settings.jbrowse.config_dir}/", "")  # type: ignore[possibly-unbound-attribute]

    with open(output_path, "w") as file:
        json.dump(config, file, indent=4)

    return {
        "message": "Filtered config saved successfully.",
        "session": output_return_path,
    }


@jbrowse_endpoints_router.post("/dynamic_mapping_dict")
async def dynamic_mapping_dict(
    mapping_dict: dict,
    current_user: str = Depends(get_current_user),
):
    mapping_dict = mapping_dict
    logger.debug(mapping_dict)

    # Constructing the nested dictionary
    return {"message": "Mapping dictionary received."}
