

# FIXME: fix ciruclar import between utils & config related to logger load
from datetime import datetime
import hashlib
import json
from pathlib import Path, PosixPath
import dash_mantine_components as dmc
from dash import dcc

# import jsonschema
import numpy as np
from jose import jwt, JWTError

import os
import re
from typing import Dict, Type, List, Tuple, Optional, Any
from pydantic import BaseModel, ValidationError
import yaml

from depictio.api.v1.endpoints.datacollections_endpoints.models import DataCollection
from depictio.api.v1.endpoints.files_endpoints.models import File
from depictio.api.v1.endpoints.user_endpoints.models import Permission, User
from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow, WorkflowConfig, WorkflowRun
from depictio.api.v1.models.top_structure import RootConfig

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


def get_config(filename: str):
    """
    Get the config file.
    """
    if not filename.endswith(".yaml"):
        raise ValueError("Invalid config file. Must be a YAML file.")
    if not os.path.exists(filename):
        raise ValueError(f"The file '{filename}' does not exist.")
    if not os.path.isfile(filename):
        raise ValueError(f"'{filename}' is not a file.")
    else:
        with open(filename, "r") as f:
            yaml_data = yaml.safe_load(f)
        return yaml_data


def validate_config(config: Dict, pydantic_model: Type[BaseModel]) -> BaseModel:
    """
    Load and validate the YAML configuration
    """
    if not isinstance(config, dict):
        raise ValueError("Invalid config. Must be a dictionary.")
    try:
        data = pydantic_model(**config)
    except ValidationError as e:
        raise ValueError(f"Invalid config: {e}")
    return data


def populate_file_models(workflow: Workflow) -> List[DataCollection]:
    """
    Returns a list of DataCollection models for a given workflow.
    """

    datacollections_models = []
    for metadata in workflow.data_collections:
        data_collection_tag = metadata.data_collection_tag
        datacollection_instance = DataCollection(
            data_collection_tag=data_collection_tag,
            description=metadata.description,
            config=metadata.config,
            workflow_tag=workflow.workflow_tag,
        )
        # datacollection_instance.config.data_collection_id = datacollection_id
        # datacollection_instance.config.workflow_id = workflow.workflow_id
        datacollections_models.append(datacollection_instance)

    return datacollections_models


def validate_worfklow(workflow: Workflow, config: RootConfig, user: User) -> dict:
    """
    Validate the workflow.
    """
    # workflow_config = config.workflows[workflow_name]
    # print(workflow_config)

    # datacollection_models = populate_file_models(workflow)

    # Create a dictionary of validated datacollections with datacollection_id as the key
    # validated_datacollections = {
    #     datacollection.data_collection_tag: datacollection
    #     for datacollection in datacollection_models
    # }

    # # print(validated_datacollections)
    # # Update the workflow's files attribute in the main config
    # workflow.data_collections = validated_datacollections
    # workflow.runs = {}

    # Create the permissions using the decoded user
    permissions = Permission(owners=[user])
    workflow.permissions = permissions

    return workflow


def validate_all_workflows(config: RootConfig, user: User) -> RootConfig:
    """
    Validate all workflows in the config.
    """
    for workflow in config.workflows:
        validate_worfklow(workflow, config, user)

    return config


def calculate_file_hash(file_path: str) -> str:
    """Calculate a unique hash for a file based on its content."""
    # Implementation of hashing function
    with open(file_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()




# FIXME: updat model & function using a list of dict instead of a dict
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


agg_functions = {
    "int64": {
        "title": "Integer",
        "input_methods": {
            "Slider": {
                "component": dcc.Slider,
                "description": "Single value slider",
            },
            "RangeSlider": {
                "component": dcc.RangeSlider,
                "description": "Two values slider",
            },
        },
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "unique": {
                "pandas": "nunique",
                "numpy": None,
                "description": "Number of distinct elements",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "average": {
                "pandas": "mean",
                "numpy": "mean",
                "description": "Mean of non-NA values",
            },
            "median": {
                "pandas": "median",
                "numpy": "median",
                "description": "Arithmetic median of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
            "range": {
                "pandas": lambda df: df.max() - df.min(),
                "numpy": "ptp",
                "description": "Range of non-NA values",
            },
            "variance": {
                "pandas": "var",
                "numpy": "var",
                "description": "Variance of non-NA values",
            },
            "std_dev": {
                "pandas": "std",
                "numpy": "std",
                "description": "Standard Deviation of non-NA values",
            },
            "percentile": {
                "pandas": "quantile",
                "numpy": "percentile",
                "description": "Percentiles of non-NA values",
            },
            "skewness": {
                "pandas": "skew",
                "numpy": None,
                "description": "Skewness of non-NA values",
            },
            "kurtosis": {
                "pandas": "kurt",
                "numpy": None,
                "description": "Kurtosis of non-NA values",
            },
            # "cumulative_sum": {
            #     "pandas": "cumsum",
            #     "numpy": "cumsum",
            #     "description": "Cumulative sum of non-NA values",
            # },
        },
    },
    "float64": {
        "title": "Floating Point",
        "input_methods": {
            "Slider": {
                "component": dcc.Slider,
                "description": "Single value slider",
            },
            "RangeSlider": {
                "component": dcc.RangeSlider,
                "description": "Two values slider",
            },
        },
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "unique": {
                "pandas": "nunique",
                "numpy": None,
                "description": "Number of distinct elements",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "average": {
                "pandas": "mean",
                "numpy": "mean",
                "description": "Mean of non-NA values",
            },
            "median": {
                "pandas": "median",
                "numpy": "median",
                "description": "Arithmetic median of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
            "range": {
                "pandas": lambda df: df.max() - df.min(),
                "numpy": "ptp",
                "description": "Range of non-NA values",
            },
            "variance": {
                "pandas": "var",
                "numpy": "var",
                "description": "Variance of non-NA values",
            },
            "std_dev": {
                "pandas": "std",
                "numpy": "std",
                "description": "Standard Deviation of non-NA values",
            },
            "percentile": {
                "pandas": "quantile",
                "numpy": "percentile",
                "description": "Percentiles of non-NA values",
            },
            "skewness": {
                "pandas": "skew",
                "numpy": None,
                "description": "Skewness of non-NA values",
            },
            "kurtosis": {
                "pandas": "kurt",
                "numpy": None,
                "description": "Kurtosis of non-NA values",
            },
            # "cumulative_sum": {
            #     "pandas": "cumsum",
            #     "numpy": "cumsum",
            #     "description": "Cumulative sum of non-NA values",
            # },
        },
    },
    "bool": {
        "title": "Boolean",
        "description": "Boolean values",
        "input_methods": {
            "Checkbox": {
                "component": dmc.Checkbox,
                "description": "Checkbox",
            },
            "Switch": {
                "component": dmc.Switch,
                "description": "Switch",
            },
        },
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "datetime": {
        "title": "Datetime",
        "description": "Date and time values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "timedelta": {
        "title": "Timedelta",
        "description": "Differences between two datetimes",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "category": {
        "title": "Category",
        "description": "Finite list of text values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "mode": {
                "pandas": "mode",
                "numpy": None,
                "description": "Most common value",
            },
        },
    },
    "object": {
        "title": "Object",
        "input_methods": {
            "TextInput": {
                "component": dmc.TextInput,
                "description": "Text input box",
            },
            "Select": {
                "component": dmc.Select,
                "description": "Select",
            },
            "MultiSelect": {
                "component": dmc.MultiSelect,
                "description": "MultiSelect",
            },
            "SegmentedControl": {
                "component": dmc.SegmentedControl,
                "description": "SegmentedControl",
            },
        },
        "description": "Text or mixed numeric or non-numeric values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "mode": {
                "pandas": "mode",
                "numpy": None,
                "description": "Most common value",
            },
            "nunique": {
                "pandas": "nunique",
                "numpy": None,
                "description": "Number of distinct elements",
            },
        },
    },
    "utf8": {
        "title": "Object",
        "input_methods": {
            "TextInput": {
                "component": dmc.TextInput,
                "description": "Text input box",
            },
            "Select": {
                "component": dmc.Select,
                "description": "Select",
            },
            "MultiSelect": {
                "component": dmc.MultiSelect,
                "description": "MultiSelect",
            },
            "SegmentedControl": {
                "component": dmc.SegmentedControl,
                "description": "SegmentedControl",
            },
        },
        "description": "Text or mixed numeric or non-numeric values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "mode": {
                "pandas": "mode",
                "numpy": None,
                "description": "Most common value",
            },
            "nunique": {
                "pandas": "nunique",
                "numpy": None,
                "description": "Number of distinct elements",
            },
        },
    },
}
