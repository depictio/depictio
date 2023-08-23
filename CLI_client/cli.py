import sys

sys.path.append("/Users/tweber/Gits/depictio")

import httpx
import typer
import yaml
from pydantic import BaseModel, ValidationError
from typing import List, Dict, Any

from fastapi_backend.configs.models import Workflow, RootConfig
from fastapi_backend.utils import get_config, validate_config

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
    print(config_dict)

    if workflow_id not in config_dict:
        raise ValueError(f"Workflow '{workflow_name}' not found in the config file.")

    # # print(validated_config.workflows[workflow_name].dict())
    print(config_dict[workflow_id].dict())
    config_dict_wf = config_dict[workflow_id].dict()
    config_dict_wf["runs"] = {}
    config_dict_wf["data_collections"] = {}
    print(config_dict_wf)

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
    print(workflows.json())


if __name__ == "__main__":
    app()
