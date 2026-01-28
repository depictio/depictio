import os
import re
from datetime import datetime
from pathlib import PosixPath

import numpy as np

from depictio import BASE_PATH
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.files import File
from depictio.models.models.workflows import WorkflowConfig, WorkflowRun


async def clean_screenshots() -> dict[str, bool | str]:
    """
    Clean up orphaned screenshot files from the screenshots directory.

    Removes screenshot files that no longer correspond to dashboards in the database.

    Returns:
        Dictionary with success status and message.
    """
    screenshots_dir = os.path.join(BASE_PATH, "dash", "static", "screenshots")

    if not os.path.exists(screenshots_dir):
        return {"success": False, "message": "Screenshots directory does not exist"}

    from depictio.api.v1.db import dashboards_collection

    dashboards = dashboards_collection.find({}, {"_id": 1})
    dashboard_ids = {str(dashboard["_id"]) for dashboard in dashboards.to_list(length=None)}

    for filename in os.listdir(screenshots_dir):
        if not filename.endswith(".png"):
            continue

        # Filename format is {dashboard_id}_{theme}.png or {dashboard_id}.png
        # Extract dashboard_id by removing .png and _dark/_light suffix
        base_name = filename.rsplit(".", 1)[0]  # Remove .png extension
        # Remove _dark or _light suffix if present
        if base_name.endswith("_dark"):
            dashboard_id = base_name[:-5]
        elif base_name.endswith("_light"):
            dashboard_id = base_name[:-6]
        else:
            dashboard_id = base_name

        if dashboard_id in dashboard_ids:
            continue

        file_path = os.path.join(screenshots_dir, filename)
        try:
            os.remove(file_path)
        except OSError:
            pass

    return {"success": True, "message": "Screenshots cleaned up"}


def construct_full_regex(files_regex, regex_config):
    """
    Construct the full regex using the wildcards defined in the config.

    Args:
        files_regex: Base regex pattern with placeholders.
        regex_config: Configuration containing wildcard definitions.

    Returns:
        Full regex pattern with wildcards replaced by their regex patterns.
    """
    for wildcard in regex_config.wildcards:
        placeholder = f"{{{wildcard.name}}}"
        regex_pattern = wildcard.wildcard_regex
        files_regex = files_regex.replace(placeholder, f"({regex_pattern})")
    return files_regex


def regex_match(root, file, full_regex, data_collection):
    """
    Match a file against a regex pattern.

    Args:
        root: Directory path containing the file.
        file: Filename to match.
        full_regex: Regex pattern to use for matching.
        data_collection: Data collection configuration with regex type.

    Returns:
        Tuple of (matched: bool, match_result: re.Match | None).
    """
    normalized_regex = full_regex.replace("/", "\\/")
    if data_collection.config.regex.type.lower() == "file-based":
        match = re.match(normalized_regex, file)
        if match:
            return True, match
    return False, None


def scan_files(run_location: str, run_id: str, data_collection: DataCollection) -> list[File]:
    """
    Scan the files for a given workflow.

    Args:
        run_location: Directory path to scan for files.
        run_id: Identifier for the workflow run.
        data_collection: Data collection configuration with regex patterns.

    Returns:
        List of File instances matching the regex pattern.

    Raises:
        ValueError: If run_location does not exist or is not a directory.
    """
    if not os.path.exists(run_location):
        raise ValueError(f"The directory '{run_location}' does not exist.")
    if not os.path.isdir(run_location):
        raise ValueError(f"'{run_location}' is not a directory.")

    file_list: list[File] = []

    if data_collection.config.regex.wildcards:  # type: ignore[unresolved-attribute]
        full_regex = construct_full_regex(
            data_collection.config.regex.pattern,  # type: ignore[unresolved-attribute]
            data_collection.config.regex,  # type: ignore[unresolved-attribute]
        )
    else:
        full_regex = data_collection.config.regex.pattern  # type: ignore[unresolved-attribute]

    for root, _dirs, files in os.walk(run_location):
        for file in files:
            match, result = regex_match(root, file, full_regex, data_collection)
            if not match:
                continue

            file_location = os.path.join(root, file)
            creation_time_dt = datetime.fromtimestamp(os.path.getctime(file_location))
            modification_time_dt = datetime.fromtimestamp(os.path.getmtime(file_location))

            file_instance = File(  # type: ignore[unknown-argument]
                filename=file,
                file_location=file_location,
                creation_time=creation_time_dt.strftime("%Y-%m-%d %H:%M:%S"),
                modification_time=modification_time_dt.strftime("%Y-%m-%d %H:%M:%S"),
                data_collection=data_collection,  # type: ignore[unknown-argument]
                run_id=run_id,
            )

            if (
                data_collection.config.regex.wildcards  # type: ignore[unresolved-attribute]
                and data_collection.config.type == "JBrowse2"
            ):
                wildcards_list = [
                    {
                        "name": wildcard.name,
                        "value": result.group(j),
                        "wildcard_regex": wildcard.wildcard_regex,
                    }
                    for j, wildcard in enumerate(data_collection.config.regex.wildcards, start=1)  # type: ignore[unresolved-attribute]
                ]
                file_instance.wildcards = wildcards_list  # type: ignore[unresolved-attribute]

            file_list.append(file_instance)
    return file_list


def scan_runs(
    parent_runs_location,
    workflow_config: WorkflowConfig,
    data_collection: DataCollection,
    workflow_id: str,
) -> list[WorkflowRun]:
    """
    Scan the runs for a given workflow.

    Args:
        parent_runs_location: Parent directory containing workflow runs.
        workflow_config: Workflow configuration with runs_regex pattern.
        data_collection: Data collection configuration.
        workflow_id: Identifier for the workflow.

    Returns:
        List of WorkflowRun instances matching the runs_regex pattern.

    Raises:
        ValueError: If parent_runs_location does not exist or is not a directory.
    """
    if not os.path.exists(parent_runs_location):
        raise ValueError(f"The directory '{parent_runs_location}' does not exist.")
    if not os.path.isdir(parent_runs_location):
        raise ValueError(f"'{parent_runs_location}' is not a directory.")

    runs: list[WorkflowRun] = []

    for run in os.listdir(parent_runs_location):
        run_location = os.path.join(parent_runs_location, run)
        if not os.path.isdir(run_location):
            continue
        if not re.match(workflow_config.runs_regex, run):  # type: ignore[unresolved-attribute]
            continue

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
