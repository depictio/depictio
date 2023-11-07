import os
from pathlib import Path
import sys

import json
import httpx
import typer
import yaml
from pydantic import BaseModel, ValidationError
from typing import List, Dict, Any, Optional
from jose import JWTError, jwt  # Use python-jose to decode JWT tokens

from depictio.api.v1.configs.models import (
    Permission,
    User,
    Workflow,
    RootConfig,
    CustomJSONEncoder,
)
from depictio.api.v1.utils import (
    decode_token,
    public_key_path,
    get_config,
    validate_all_workflows,
    validate_config,
)

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
    token: str = typer.Option(
        None,  # Default to None (not specified)
        "--token",
        help="Optionally specify a token to be used for authentication",
    ),
):
    """
    Create a new workflow from a given YAML configuration file.
    """

    if not token:
        typer.echo("A valid token must be provided for authentication.")
        raise typer.Exit(code=1)

    user = decode_token(
        token, public_key_path
    )  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    # Get the config data (assuming get_config returns a dictionary)
    config_data = get_config(config_path)

    config = validate_config(config_data, RootConfig)

    validated_config = validate_all_workflows(config, user=user)

    config_dict = {f"{e.workflow_id}": e for e in validated_config.workflows}

    if workflow_id not in config_dict:
        typer.echo(f"Workflow '{workflow_id}' not found in the config file.")
        raise typer.Exit(code=1)

    # Prepare the workflow data
    workflow_data = config_dict[workflow_id]

    print("PREPOST")

    # workflow_data_dict = workflow_data.dict()
    workflow_data_dict = json.loads(
        json.dumps(
            workflow_data.dict(by_alias=True, exclude_none=True), cls=CustomJSONEncoder
        )
    )
    print(workflow_data_dict)

    response = httpx.post(
        f"{API_BASE_URL}/api/v1/workflows/create_workflow",
        json=workflow_data_dict,
        headers=headers,
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
    workflows = httpx.get(f"{API_BASE_URL}/api/v1/workflows/get_workflows")
    print(workflows)
    workflows_json = workflows.json()
    print(workflows_json)
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
    token: str = typer.Option(
        None,  # Default to None (not specified)
        "--token",
        help="Optionally specify a token to be used for authentication",
    ),
):
    """
    Scan files for a given workflow.
    """

    if not token:
        typer.echo("A valid token must be provided for authentication.")
        raise typer.Exit(code=1)

    user = decode_token(
        token, public_key_path
    )  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    config_data = get_config(config_path)
    # print(config_data)
    config = validate_config(config_data, RootConfig)
    validated_config = validate_all_workflows(config, user=user)

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

    # Assuming workflow and data_collection are Pydantic models and have .dict() method
    for data_collection in data_collections_to_process:
        data_payload = {
            "workflow": workflow.dict(by_alias=True, exclude_none=True),
            "data_collection": data_collection.dict(by_alias=True, exclude_none=True),
        }

        # Convert the payload to JSON using the custom encoder
        print(data_payload, type(data_payload))
        data_payload_json = json.loads(json.dumps(data_payload, cls=CustomJSONEncoder))
        print(data_payload_json, type(data_payload_json))

        # workflow_data_dict = workflow_data.dict()

        print("\n\n")
        print(data_payload_json)
        # print(data_payload["data_collection"])
        response = httpx.post(
            f"{API_BASE_URL}/api/v1/datacollections/scan",
            json=data_payload_json,
            headers=headers,
        )
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
    token: str = typer.Option(
        None,  # Default to None (not specified)
        "--token",
        help="Optionally specify a token to be used for authentication",
    ),
):
    """
    Aggregate data files for a given workflow.
    """

    if not token:
        typer.echo("A valid token must be provided for authentication.")
        raise typer.Exit(code=1)

    user = decode_token(
        token, public_key_path
    )  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    config_data = get_config(config_path)
    config = validate_config(config_data, RootConfig)
    validated_config = validate_all_workflows(config, user=user)

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


    # Assuming workflow and data_collection are Pydantic models and have .dict() method
    for data_collection in data_collections_to_process:
        data_payload = data_collection.dict(by_alias=True, exclude_none=True)

        # Convert the payload to JSON using the custom encoder
        print(data_payload, type(data_payload))
        data_payload_json = json.loads(json.dumps(data_payload, cls=CustomJSONEncoder))
        print(data_payload_json, type(data_payload_json))


        response = httpx.post(
            f"{API_BASE_URL}/api/v1/datacollections/aggregate_workflow_data",
            json=data_payload_json,
            headers=headers,
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


@app.command()
def get_aggregated_file(
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

        response = httpx.get(
            f"{API_BASE_URL}/api/v1/datacollections/get_aggregated_file",
            params=data_payload,
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
