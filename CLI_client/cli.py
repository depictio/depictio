import os
from pathlib import Path
import sys

sys.path.append("/Users/tweber/Gits/depictio")

import json
import httpx
import typer
import yaml
from pydantic import BaseModel, ValidationError
from typing import List, Dict, Any, Optional
from jose import JWTError, jwt  # Use python-jose to decode JWT tokens

from depictio.api.v1.configs.models import Permission, User, Workflow, RootConfig
from depictio.api.v1.utils import get_config, validate_all_workflows, validate_config

app = typer.Typer()

API_BASE_URL = "http://localhost:8058"  # replace with your FastAPI server URL


public_key_path = "dev/token/public_key.pem"
token_path = "dev/token/token.txt"


def decode_token(
    token: Optional[str] = None,
    token_path: Optional[str] = None,
    public_key_path: str = public_key_path,
) -> User:
    # Determine the source of the token
    if token is None:
        if token_path is None:
            # Default token path
            token_path = os.path.join(Path.home(), ".depictio", "config")
        # Read the token from a file
        try:
            with open(token_path, "r") as f:
                token = f.read().strip()
        except IOError as e:
            raise IOError(f"Unable to read token file: {e}")

    # Read the public key
    try:
        with open(public_key_path, "rb") as f:
            public_key = f.read()
    except IOError as e:
        raise IOError(f"Unable to read public key file: {e}")

    # Verify and decode the JWT
    try:
        decoded = jwt.decode(token, public_key, algorithms=["RS256"])
    except JWTError as e:
        raise JWTError(f"Token verification failed: {e}")

    # Instantiate a User object from the decoded token
    try:
        user = User(**decoded)
        return user
    except ValidationError as e:
        raise ValidationError(f"Decoded token is not valid for the User model: {e}")


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

    workflow_data_dict = workflow_data.dict()

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    response = httpx.post(
        f"{API_BASE_URL}/api/v1/workflows", json=workflow_data_dict, headers=headers
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
        response = httpx.post(
            f"{API_BASE_URL}/api/v1/datacollections/scan", json=data_payload
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
            f"{API_BASE_URL}/api/v1/datacollections/aggregate_workflow_data",
            json=data_payload,
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
