

from datetime import datetime
from pathlib import PosixPath
# from dash import dcc

# import jsonschema
import numpy as np

import os
import re
from typing import List

from depictio.api.v1.endpoints.datacollections_endpoints.models import DataCollection
from depictio.api.v1.endpoints.files_endpoints.models import File
from depictio.api.v1.endpoints.workflow_endpoints.models import WorkflowConfig, WorkflowRun
from depictio.api.v1.models.top_structure import RootConfig
from depictio.api.v1.models_utils import get_config, validate_all_workflows, validate_config

# def return_user_from_id(token: str) -> dict:
#     try:
#         payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
#         user_id = payload.get("sub")
#         if user_id is None:
#             typer.echo("Token is invalid or expired.")
#             raise typer.Exit(code=1)
#         # Fetch user from the database or wherever it is stored
#         user = fetch_user_by_id(user_id)
#         return user
#     except JWTError as e:
#         typer.echo(f"Token verification failed: {e}")
#         raise typer.Exit(code=1)




# FIXME: update model & function using a list of dict instead of a dict
def construct_full_regex(files_regex, regex_config):
    """
    Construct the full regex using the wildcards defined in the config.
    """
    for wildcard in regex_config.wildcards:
        print("wildcard", wildcard)
        placeholder = f"{{{wildcard.name}}}"  # e.g. {date}
        regex_pattern = wildcard.wildcard_regex
        files_regex = files_regex.replace(placeholder, f"({regex_pattern})")
        print("files_regex", files_regex)
    return files_regex


def regex_match(root, file, full_regex, data_collection):
    # Normalize the regex pattern to match both types of path separators
    normalized_regex = full_regex.replace("/", "\/")
    print("normalized_regex")
    print(root, file, full_regex, data_collection, data_collection.config.regex.type.lower())
    # If regex pattern is file-based, match the file name directly
    if data_collection.config.regex.type.lower() == "file-based":
        if re.match(normalized_regex, file):
            print("MATCH - file-based")
            return True, re.match(normalized_regex, file)
    elif data_collection.config.regex.type.lower() == "path-based":
        # If regex pattern is path-based, match the full path
        file_location = os.path.join(root, file)
        if re.match(normalized_regex, file_location):
            return True, re.match(normalized_regex, file)
    return False, None


def scan_files(run_location: str, run_id: str, data_collection: DataCollection) -> List[File]:
    """
    Scan the files for a given workflow.
    """
    # Get the workflow's parent_runs_location

    print(f"Scanning files in {run_location}")

    if not os.path.exists(run_location):
        raise ValueError(f"The directory '{run_location}' does not exist.")
    if not os.path.isdir(run_location):
        raise ValueError(f"'{run_location}' is not a directory.")

    file_list = list()

    # Construct the full regex using the wildcards defined in the config
    if data_collection.config.regex.wildcards:
        full_regex = construct_full_regex(data_collection.config.regex.pattern, data_collection.config.regex)
    else:
        full_regex = data_collection.config.regex.pattern

    # Scan the files
    for root, dirs, files in os.walk(run_location):
        for file in files:
            print("root", root, "file", file, "full_regex", full_regex, "data_collection", data_collection)
            match, result = regex_match(root, file, full_regex, data_collection)
            print("match", match, "result", result)
            if match:
                file_location = os.path.join(root, file)
                filename = file
                creation_time_float = os.path.getctime(file_location)
                modification_time_float = os.path.getmtime(file_location)

                # Convert the float values to datetime objects
                creation_time_dt = datetime.fromtimestamp(creation_time_float)
                modification_time_dt = datetime.fromtimestamp(modification_time_float)

                # Convert the datetime objects to ISO formatted strings
                creation_time_iso = creation_time_dt.strftime("%Y-%m-%d %H:%M:%S")
                modification_time_iso = modification_time_dt.strftime("%Y-%m-%d %H:%M:%S")

                file_instance = File(
                    filename=filename,
                    file_location=file_location,
                    creation_time=creation_time_iso,
                    modification_time=modification_time_iso,
                    data_collection=data_collection,
                    run_id=run_id,
                )
                if data_collection.config.regex.wildcards and data_collection.config.type == "JBrowse2":
                    wildcards_list = list()
                    for j, wildcard in enumerate(data_collection.config.regex.wildcards, start=1):
                        wildcards_list.append({"name": wildcard.name, "value": result.group(j), "wildcard_regex": wildcard.wildcard_regex})
                    file_instance.wildcards = wildcards_list

                # print(file_instance)
                file_list.append(file_instance)
    print("file_list", file_list)
    return file_list


def scan_runs(
    parent_runs_location,
    workflow_config: WorkflowConfig,
    data_collection: DataCollection,
) -> List[WorkflowRun]:
    """
    Scan the runs for a given workflow.
    """

    if not os.path.exists(parent_runs_location):
        raise ValueError(f"The directory '{parent_runs_location}' does not exist.")
    if not os.path.isdir(parent_runs_location):
        raise ValueError(f"'{parent_runs_location}' is not a directory.")

    runs = list()

    for run in os.listdir(parent_runs_location):
        if os.path.isdir(os.path.join(parent_runs_location, run)):
            if re.match(workflow_config.runs_regex, run):
                run_location = os.path.join(parent_runs_location, run)
                files = scan_files(run_location=run_location, run_id=run, data_collection=data_collection)
                execution_time = datetime.fromtimestamp(os.path.getctime(run_location))

                workflow_run = WorkflowRun(
                    run_tag=run,
                    files=files,
                    workflow_config=workflow_config,
                    run_location=run_location,
                    execution_time=execution_time,
                    execution_profile=None,
                )
                runs.append(workflow_run)
    return runs


def populate_database(config_path: str, workflow_id: str, data_collection_id: str) -> List[WorkflowRun]:
    """
    Populate the database with files for a given workflow.
    """
    config_data = get_config(config_path)
    config = validate_config(config_data, RootConfig)
    validated_config = validate_all_workflows(config)

    config_dict = {f"{e.workflow_id}": e for e in validated_config.workflows}

    if workflow_id not in config_dict:
        raise ValueError(f"Workflow '{workflow_id}' not found in the config file.")

    if workflow_id is None:
        raise ValueError("Please provide a workflow name.")

    workflow = config_dict[workflow_id]
    workflow.runs = {}
    data_collection = workflow.data_collections[data_collection_id]

    runs_and_content = scan_runs(
        parent_runs_location=workflow.config.parent_runs_location,
        workflow_config=workflow.config,
        data_collection=data_collection,
    )

    return runs_and_content


def serialize_for_mongo(data):
    if hasattr(data, "dict"):
        data = data.dict()
    if isinstance(data, dict):
        return {k: serialize_for_mongo(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [serialize_for_mongo(v) for v in data]
    elif isinstance(data, PosixPath):
        return str(data)
    elif isinstance(data, datetime):
        return data  # MongoDB natively supports datetime
    else:
        return data


def numpy_to_python(value):
    """Converts numpy data types to native Python data types."""
    if isinstance(value, (np.int64, np.int32, np.int16, np.int8)):
        return int(value)
    elif isinstance(value, (np.float64, np.float32, np.float16)):
        return float(value)
    elif isinstance(value, np.bool_):
        return bool(value)
    return value


