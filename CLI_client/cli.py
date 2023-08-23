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
    validated_config = validate_config(config_data, RootConfig)
    # print(validated_config)

    config_dict = {f"{e.workflow_id}": e for e in validated_config.workflows}

    if workflow_id not in config_dict:
        raise ValueError(f"Workflow '{workflow_name}' not found in the config file.")

    # # print(validated_config.workflows[workflow_name].dict())
    config_dict_wf = config_dict[workflow_id].dict()
    config_dict_wf["runs"] = {}
    config_dict_wf["data_collections"] = {}

    response = httpx.post(
        f"{API_BASE_URL}/workflows/create_workflow",
        json=config_dict_wf,
    )

    if response.status_code == 200:
        typer.echo("Workflow successfully created!")
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
def scan_files_for_workflow(
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
    Scan files for a given workflow.
    """

    config_data = get_config(config_path)
    # print(config_data)
    config = validate_config(config_data, RootConfig)
    validated_config = validate_all_workflows(config)

    # print(validated_config)

    config_dict = {f"{e.workflow_id}": e for e in validated_config.workflows}

    if workflow_id not in config_dict:
        raise ValueError(f"Workflow '{workflow_name}' not found in the config file.")

    if workflow_id is None:
        raise ValueError("Please provide a workflow name.")

    workflow = config_dict[workflow_id]
    workflow.runs = {}
    data_collection = workflow.data_collections[
        list(workflow.data_collections.keys())[1]
    ]
    print(workflow)
    # print(workflow.data_collections.keys()[0])

    # workflows = list_workflows()
    # print(workflows)
    # workflow = [Workflow(**w) for w in workflows][0]
    # workflow = workflow[0]

    # if workflow_id not in workflows_dict:
    #     raise ValueError(f"Workflow '{workflow_id}' not found.")

    # workflow = workflows_dict[workflow_id]
    # print(Workflow(workflow[wo]))

    data_payload = {
        "workflow": workflow.dict(),
        "data_collection": data_collection.dict()
    }

    response = httpx.post(
        f"{API_BASE_URL}/datacollections/scan_files_tmp",
        json=data_payload
    )
    print(response.text)


    # if response.status_code == 200:
    #     typer.echo("Files successfully scanned!")
    # else:
    #     typer.echo(f"Error: {response.text}")


if __name__ == "__main__":
    app()
