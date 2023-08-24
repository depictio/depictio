import sys

sys.path.append("/Users/tweber/Gits/depictio")

import json
import httpx
import typer
import yaml
from pydantic import BaseModel, ValidationError
from typing import List, Dict, Any

from fastapi_backend.configs.models import Workflow, RootConfig
from fastapi_backend.utils import get_config, validate_all_workflows, validate_config

app = typer.Typer()

API_BASE_URL = "http://localhost:8058"  # replace with your FastAPI server URL


@app.command()
def create_workflow(
    config_path: str = typer.Option(
        ...,
        "--config_path",
        help="Path to the YAML configuration file",
    ),
    workflow_id: str = typer.Option(
        ..., "--workflow_id", help="Workflow name to be created"
    ),
):
    """
    Create a new workflow from a given YAML configuration file.
    """
    config_data = get_config(config_path)
    # print(config_data)
    config = validate_config(config_data, RootConfig)
    validated_config = validate_all_workflows(config)

    config_dict = {f"{e.workflow_id}": e for e in validated_config.workflows}

    if workflow_id not in config_dict:
        raise ValueError(
            f"Workflow '{validated_config.workflow_name}' not found in the config file."
        )

    # # print(validated_config.workflows[workflow_name].dict())
    config_dict_wf = config_dict[workflow_id].dict()

    response = httpx.post(
        f"{API_BASE_URL}/workflows/create_workflow",
        json=config_dict_wf,
    )

    if response.status_code == 200:
        typer.echo(f"Workflow successfully created! : {response.json()}")
    else:
        typer.echo(f"Error: {response.text}")


@app.command()
def list_workflows():
    """
    List all workflows.
    """
    workflows = httpx.get(f"{API_BASE_URL}/workflows/get_workflows")
    workflows_json = workflows.json()
    pretty_workflows = json.dumps(workflows_json, indent=4)
    typer.echo(pretty_workflows)
    return workflows_json


@app.command()
def scan_data_collections(
    config_path: str = typer.Option(
        ...,
        "--config_path",
        help="Path to the YAML configuration file",
    ),
    workflow_id: str = typer.Option(
        ..., "--workflow_id", help="Workflow name to be created"
    ),
    data_collection_id: str = typer.Option(
        None,  # Default to None (not specified)
        "--data_collection_id",
        help="Optionally specify a data collection to be scanned alone",
    ),
):
    """
    Scan files for a given workflow.
    """

    config_data = get_config(config_path)
    # print(config_data)
    config = validate_config(config_data, RootConfig)
    validated_config = validate_all_workflows(config)

    # print(validated_config)

    config_dict = {f"{e.workflow_id}": e for e in validated_config.workflows}

    if workflow_id not in config_dict:
        raise ValueError(f"Workflow '{workflow_id}' not found in the config file.")

    if workflow_id is None:
        raise ValueError("Please provide a workflow id.")

    workflow = config_dict[workflow_id]

    # If a specific data_collection_id is given, use that, otherwise default to all data_collections
    data_collections_to_process = []
    if data_collection_id:
        if data_collection_id not in workflow.data_collections:
            raise ValueError(
                f"Data collection '{data_collection_id}' not found for the given workflow."
            )
        data_collections_to_process.append(
            workflow.data_collections[data_collection_id]
        )
    else:
        data_collections_to_process = list(workflow.data_collections.values())

    for data_collection in data_collections_to_process:
        data_payload = {
            "workflow": workflow.dict(),
            "data_collection": data_collection.dict(),
        }
        print("\n\n")
        print(data_payload["data_collection"])
        response = httpx.post(f"{API_BASE_URL}/datacollections/scan", json=data_payload)
        print(response)
        print(response.text)
        print(response.status_code)
        print("\n\n")
    # if response.status_code == 200:
    #     typer.echo("Files successfully scanned!")
    # else:
    #     typer.echo(f"Error: {response.text}")


@app.command()
def aggregate_workflow_data_collections(
    config_path: str = typer.Option(
        ...,
        "--config_path",
        help="Path to the YAML configuration file",
    ),
    workflow_id: str = typer.Option(
        ...,
        "--workflow_id",
        help="Workflow name to aggregate data for",
    ),
    data_collection_id: str = typer.Option(
        None,  # Default to None (not specified)
        "--data_collection_id",
        help="Optionally specify a data collection to be aggregated alone",
    ),
):
    """
    Aggregate data files for a given workflow.
    """

    config_data = get_config(config_path)
    config = validate_config(config_data, RootConfig)
    validated_config = validate_all_workflows(config)

    config_dict = {f"{e.workflow_id}": e for e in validated_config.workflows}

    if workflow_id not in config_dict:
        raise ValueError(f"Workflow '{workflow_id}' not found in the config file.")

    if workflow_id is None:
        raise ValueError("Please provide a workflow id.")

    workflow = config_dict[workflow_id]

    # If a specific data_collection_id is given, use that, otherwise default to all data_collections
    data_collections_to_process = []
    if data_collection_id:
        if data_collection_id not in workflow.data_collections:
            raise ValueError(
                f"Data collection '{data_collection_id}' not found for the given workflow."
            )
        data_collections_to_process.append(
            workflow.data_collections[data_collection_id]
        )
    else:
        data_collections_to_process = list(workflow.data_collections.values())

    for data_collection in data_collections_to_process:
        data_payload = data_collection.dict()
        print(data_payload["description"])

        response = httpx.post(
            f"{API_BASE_URL}/datacollections/aggregate_workflow_data", json=data_payload
        )
        print(response)
        print(response.text)
        print(response.status_code)
        print("\n\n")

        # if response.status_code == 200:
        #     typer.echo(
        #         f"Data successfully aggregated for data collection {data_collection.data_collection_id}!"
        #     )
        # else:
        #     typer.echo(
        #         f"Error for data collection {data_collection.data_collection_id}: {response.text}"
        #     )


if __name__ == "__main__":
    app()
