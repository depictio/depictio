import os
import re
from datetime import datetime
from pathlib import PosixPath

import numpy as np

from depictio import BASE_PATH
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.files import File
from depictio.models.models.workflows import WorkflowConfig, WorkflowRun


async def clean_screenshots():
    """
    Clean up screenshots directory if it exists.
    """
    screenshots_dir = os.path.join(BASE_PATH, "dash", "static", "screenshots")

    # Get list of all dashboards in DB
    from depictio.api.v1.db import dashboards_collection

    # project to only retrieve the _id field
    dashboards = dashboards_collection.find({}, {"_id": 1})
    # Get all dashboards
    dashboards_list = dashboards.to_list(length=None)
    # Get all dashboard IDs
    dashboard_ids = [str(dashboard["_id"]) for dashboard in dashboards_list]

    if os.path.exists(screenshots_dir):
        for filename in os.listdir(screenshots_dir):
            if filename.endswith(".png"):
                file_path = os.path.join(screenshots_dir, filename)
                logger.debug(f"Checking file: {file_path}")
                # Extract the dashboard ID from the filename
                dashboard_id = filename.split(".")[0]
                # Check if the dashboard ID is in the list of dashboard IDs
                if dashboard_id not in dashboard_ids:
                    logger.debug(
                        f"Dashboard ID {dashboard_id} not found in DB. Removing file: {file_path}"
                    )
                    try:
                        os.remove(file_path)
                        logger.debug(f"Removed file: {file_path}")
                    except Exception as e:
                        logger.debug(f"Error removing file {file_path}: {e}")
    else:
        logger.debug(f"Directory {screenshots_dir} does not exist.")
        return {"success": False, "message": "No project found in the database"}
    return {"success": True, "message": "Screenshots cleaned up"}


# FIXME: update model & function using a list of dict instead of a dict
def construct_full_regex(files_regex, regex_config):
    """
    Construct the full regex using the wildcards defined in the config.
    """
    for wildcard in regex_config.wildcards:
        logger.debug(f"Wildcard: {wildcard}")
        placeholder = f"{{{wildcard.name}}}"  # e.g. {date}
        regex_pattern = wildcard.wildcard_regex
        files_regex = files_regex.replace(placeholder, f"({regex_pattern})")
        logger.debug(f"Files Regex: {files_regex}")
    return files_regex


def regex_match(root, file, full_regex, data_collection):
    # Normalize the regex pattern to match both types of path separators
    normalized_regex = full_regex.replace("/", "\\/")
    logger.debug(
        f"Root: {root}, File: {file}, Full Regex: {full_regex}, Data Collection type: {data_collection.config.regex.type.lower()}"  # type: ignore[unresolved-attribute]
    )
    # If regex pattern is file-based, match the file name directly
    if data_collection.config.regex.type.lower() == "file-based":  # type: ignore[unresolved-attribute]
        if re.match(normalized_regex, file):
            logger.debug(f"Matched file - file-based: {file}")
            return True, re.match(normalized_regex, file)
    # elif data_collection.config.regex.type.lower() == "path-based":
    #     # If regex pattern is path-based, match the full path
    #     file_location = os.path.join(root, file)
    #     if re.match(normalized_regex, file_location):
    #         return True, re.match(normalized_regex, file)
    return False, None


def scan_files(run_location: str, run_id: str, data_collection: DataCollection) -> list[File]:
    """
    Scan the files for a given workflow.
    """
    # Get the workflow's parent_runs_location

    logger.debug(f"Scanning files in {run_location}")

    if not os.path.exists(run_location):
        raise ValueError(f"The directory '{run_location}' does not exist.")
    if not os.path.isdir(run_location):
        raise ValueError(f"'{run_location}' is not a directory.")

    file_list = list()

    logger.debug(f"Data Collection: {data_collection}")
    logger.debug(f"Regex Pattern: {data_collection.config.regex.pattern}")  # type: ignore[unresolved-attribute]
    logger.debug(f"Wildcards: {data_collection.config.regex.wildcards}")  # type: ignore[unresolved-attribute]

    # Construct the full regex using the wildcards defined in the config
    full_regex = None
    if data_collection.config.regex.wildcards:  # type: ignore[unresolved-attribute]
        full_regex = construct_full_regex(
            data_collection.config.regex.pattern,  # type: ignore[unresolved-attribute]
            data_collection.config.regex,  # type: ignore[unresolved-attribute]
        )
    else:
        full_regex = data_collection.config.regex.pattern  # type: ignore[unresolved-attribute]

    logger.debug(f"Full Regex: {full_regex}")

    # Scan the files
    for root, dirs, files in os.walk(run_location):
        for file in files:
            match, result = regex_match(root, file, full_regex, data_collection)
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

                file_instance = File(  # type: ignore[unknown-argument]
                    filename=filename,
                    file_location=file_location,
                    creation_time=creation_time_iso,
                    modification_time=modification_time_iso,
                    data_collection=data_collection,  # type: ignore[unknown-argument]
                    run_id=run_id,
                )
                logger.debug(f"File Instance: {file_instance}")

                if (
                    data_collection.config.regex.wildcards  # type: ignore[unresolved-attribute]
                    and data_collection.config.type == "JBrowse2"
                ):
                    wildcards_list = list()
                    for j, wildcard in enumerate(data_collection.config.regex.wildcards, start=1):  # type: ignore[unresolved-attribute]
                        wildcards_list.append(
                            {
                                "name": wildcard.name,
                                "value": result.group(j),
                                "wildcard_regex": wildcard.wildcard_regex,
                            }
                        )
                    file_instance.wildcards = wildcards_list  # type: ignore[unresolved-attribute]

                file_list.append(file_instance)

    logger.debug(f"File List: {file_list}")
    return file_list


def scan_runs(
    parent_runs_location,
    workflow_config: WorkflowConfig,
    data_collection: DataCollection,
    workflow_id: str,
) -> list[WorkflowRun]:
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
            if re.match(workflow_config.runs_regex, run):  # type: ignore[unresolved-attribute]
                run_location = os.path.join(parent_runs_location, run)
                files = scan_files(
                    run_location=run_location,
                    run_id=run,
                    data_collection=data_collection,
                )
                execution_time = datetime.fromtimestamp(os.path.getctime(run_location))

                workflow_run = WorkflowRun(  # type: ignore[missing-argument,invalid-argument-type,unknown-argument]
                    workflow_id=workflow_id,  # type: ignore[invalid-argument-type]
                    run_tag=run,
                    files=files,  # type: ignore[unknown-argument]
                    workflow_config=workflow_config,  # type: ignore[unknown-argument]
                    run_location=run_location,
                    execution_time=execution_time,  # type: ignore[unknown-argument]
                    execution_profile=None,  # type: ignore[unknown-argument]
                )
                runs.append(workflow_run)
    return runs


# def populate_database(config_path: str, workflow_id: str, data_collection_id: str) -> List[WorkflowRun]:
#     """
#     Populate the database with files for a given workflow.
#     """
#     config_data = get_config(config_path)
#     config = validate_config(config_data, RootConfig)
#     validated_config = validate_all_workflows(config)

#     config_dict = {f"{e.workflow_id}": e for e in validated_config.workflows}

#     if workflow_id not in config_dict:
#         raise ValueError(f"Workflow '{workflow_id}' not found in the config file.")

#     if workflow_id is None:
#         raise ValueError("Please provide a workflow name.")

#     workflow = config_dict[workflow_id]
#     workflow.runs = {}
#     data_collection = workflow.data_collections[data_collection_id]

#     runs_and_content = scan_runs(
#         parent_runs_location=workflow.config.parent_runs_location,
#         workflow_config=workflow.config,
#         data_collection=data_collection,
#         workflow_id=workflow_id,
#     )

#     return runs_and_content


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
    if isinstance(value, np.int64 | np.int32 | np.int16 | np.int8):
        return int(value)
    elif isinstance(value, np.float64 | np.float32 | np.float16):
        return float(value)
    elif isinstance(value, np.bool_):
        return bool(value)
    return value


agg_functions = {
    "int64": {
        "title": "Integer",
        "input_methods": {
            "Slider": {
                "component": "dcc.Slider",
                "description": "Single value slider",
            },
            "RangeSlider": {
                "component": "dcc.RangeSlider",
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
                "component": "dcc.Slider",
                "description": "Single value slider",
            },
            "RangeSlider": {
                "component": "dcc.RangeSlider",
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
                "component": "dmc.Checkbox",
                "description": "Checkbox",
            },
            "Switch": {
                "component": "dmc.Switch",
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
                "component": "dmc.TextInput",
                "description": "Text input box",
            },
            "Select": {
                "component": "dmc.Select",
                "description": "Select",
            },
            "MultiSelect": {
                "component": "dmc.MultiSelect",
                "description": "MultiSelect",
            },
            "SegmentedControl": {
                "component": "dmc.SegmentedControl",
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
                "component": "dmc.TextInput",
                "description": "Text input box",
            },
            "Select": {
                "component": "dmc.Select",
                "description": "Select",
            },
            "MultiSelect": {
                "component": "dmc.MultiSelect",
                "description": "MultiSelect",
            },
            "SegmentedControl": {
                "component": "dmc.SegmentedControl",
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
