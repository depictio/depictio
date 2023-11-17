import os
from pathlib import Path
import sys

import json
from bson import ObjectId
import httpx
import typer
import yaml
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Any, Optional
from jose import JWTError, jwt  # Use python-jose to decode JWT tokens

from depictio.api.v1.models.pydantic_models import (
    Permission,
    User,
    Workflow,
    RootConfig,
)

from depictio.api.v1.models.base import (
    CustomJSONEncoder,
    PyObjectId,
    convert_objectid_to_str,
)

from depictio.api.v1.endpoints.user_endpoints.auth import (
    ALGORITHM,
    PUBLIC_KEY,
    fetch_user_from_id,
)
from depictio.api.v1.utils import (
    get_config,
    validate_all_workflows,
    validate_config,
)

app = typer.Typer()

API_BASE_URL = "http://localhost:8058"  # replace with your FastAPI server URL


def return_user_from_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            typer.echo("Token is invalid or expired.")
            raise typer.Exit(code=1)
        # Fetch user from the database or wherever it is stored
        user = fetch_user_from_id(user_id)
        return user
    except JWTError as e:
        typer.echo(f"Token verification failed: {e}")
        raise typer.Exit(code=1)


@app.command()
def create_workflow(
    config_path: str = typer.Option(
        ...,
        "--config_path",
        help="Path to the YAML configuration file",
    ),
    workflow_tag: Optional[str] = typer.Option(
        None, "--workflow_tag", help="Workflow name to be created"
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
    assert workflow_tag is not None

    if not token:
        typer.echo("A valid token must be provided for authentication.")
        raise typer.Exit(code=1)

    user = return_user_from_token(token)  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    # Get the config data (assuming get_config returns a dictionary)
    config_data = get_config(config_path)

    config = validate_config(config_data, RootConfig)

    validated_config = validate_all_workflows(config, user=user)

    # config_dict = {f"{e.workflow_tag}": e for e in validated_config.workflows}

    if workflow_tag not in [w.workflow_tag for w in validated_config.workflows]:
        typer.echo(f"Workflow '{workflow_tag}' not found in the config file.")
        raise typer.Exit(code=1)

    
    workflow_data = [w for w in validated_config.workflows if w.workflow_tag == workflow_tag][0]


    workflow_data_raw = workflow_data.dict(by_alias=True, exclude_none=True)
    workflow_data_dict = convert_objectid_to_str(workflow_data_raw)



    response = httpx.post(
        f"{API_BASE_URL}/api/v1/workflows/create",
        json=workflow_data_dict,
        headers=headers,
    )

    if response.status_code == 200:
        typer.echo(f"Workflow successfully created! : {response.json()}")
    else:
        typer.echo(f"Error: {response.text}")




@app.command()
def list_workflows(

    token: str = typer.Option(
        None,  # Default to None (not specified)
        "--token",
        help="Optionally specify a token to be used for authentication",
    ),
):
    """
    List all workflows.
    """


    if not token:
        typer.echo("A valid token must be provided for authentication.")
        raise typer.Exit(code=1)

    user = return_user_from_token(token)  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory


    workflows = httpx.get(f"{API_BASE_URL}/api/v1/workflows/get", headers=headers)
    workflows_json = workflows.json()
    pretty_workflows = json.dumps(workflows_json, indent=4)
    typer.echo(pretty_workflows)
    return workflows_json


@app.command()
def scan_files_from_data_collection(
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
    Scan files for a given data collection of a workflow.
    """

    if not token:
        typer.echo("A valid token must be provided for authentication.")
        raise typer.Exit(code=1)

    user = return_user_from_token(token)  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    config_data = get_config(config_path)
    # print(config_data)
    config = validate_config(config_data, RootConfig)
    assert isinstance(config, RootConfig)
    print(config)

    # validated_config = validate_all_workflows(config, user=user)


    # config_dict = {f"{e.id}": e for e in validated_config.workflows}

    # if workflow_id not in config_dict:
    #     raise ValueError(f"Workflow '{workflow_id}' not found in the config file.")

    # if workflow_id is None:
    #     raise ValueError("Please provide a workflow id.")

    # workflow = config_dict[workflow_id]

    # If a specific data_collection_id is given, use that, otherwise default to all data_collections
    # data_collections_to_process = []
    # if data_collection_id:
    #     if data_collection_id not in workflow.data_collections:
    #         raise ValueError(
    #             f"Data collection '{data_collection_id}' not found for the given workflow."
    #         )
    #     data_collections_to_process.append(
    #         workflow.data_collections[data_collection_id]
    #     )
    # else:
    #     data_collections_to_process = list(workflow.data_collections.values())

    # Assuming workflow and data_collection are Pydantic models and have .dict() method
    # data_payload = {
    #     "workflow_id": workflow_id,
    #     "data_collection_id": data_collection_id,
    # }

    # Convert the payload to JSON using the custom encoder
    # print(data_payload, type(data_payload))

    # data_payload_json = convert_objectid_to_str(data_payload)

    # print(data_payload_json, type(data_payload_json))

    # workflow_data_dict = workflow_data.dict()

    print("\n\n")
    # print(data_payload_json)
    # print(data_payload["data_collection"])
    response = httpx.post(
        f"{API_BASE_URL}/api/v1/files/scan/{workflow_id}/{data_collection_id}",
        # json=data_payload_json,
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
def create_deltatable(
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

    user = return_user_from_token(token)  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    config_data = get_config(config_path)
    # print(config_data)
    config = validate_config(config_data, RootConfig)
    assert isinstance(config, RootConfig)
    print(config)

    # config_data = get_config(config_path)
    # config = validate_config(config_data, RootConfig)
    # validated_config = validate_all_workflows(config, user=user)

    # config_dict = {f"{e.workflow_id}": e for e in validated_config.workflows}

    # if workflow_id not in config_dict:
    #     raise ValueError(f"Workflow '{workflow_id}' not found in the config file.")

    # if workflow_id is None:
    #     raise ValueError("Please provide a workflow id.")

    # workflow = config_dict[workflow_id]

    # # If a specific data_collection_id is given, use that, otherwise default to all data_collections
    # data_collections_to_process = []
    # if data_collection_id:
    #     if data_collection_id not in workflow.data_collections:
    #         raise ValueError(
    #             f"Data collection '{data_collection_id}' not found for the given workflow."
    #         )
    #     data_collections_to_process.append(
    #         workflow.data_collections[data_collection_id]
    #     )
    # else:
    #     data_collections_to_process = list(workflow.data_collections.values())

    # Assuming workflow and data_collection are Pydantic models and have .dict() method
    # for data_collection in data_collections_to_process:
    # data_payload = data_collection.dict(by_alias=True, exclude_none=True)

    # Convert the payload to JSON using the custom encoder
    # print(data_payload, type(data_payload))
    # data_payload_json = json.loads(json.dumps(data_payload, cls=CustomJSONEncoder))
    # print(data_payload_json, type(data_payload_json))

    response = httpx.post(
        f"{API_BASE_URL}/api/v1/deltatables/create/{workflow_id}/{data_collection_id}",
        # json=data_payload_json,
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
def list_files_for_data_collection(
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
    List files registered for a data collection related to a workflow.
    """

    if not token:
        typer.echo("A valid token must be provided for authentication.")
        raise typer.Exit(code=1)

    user = return_user_from_token(token)  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    response = httpx.get(
        f"{API_BASE_URL}/api/v1/files/list/{workflow_id}/{data_collection_id}",
        # json=data_payload_json,
        headers=headers,
    )
    print(json.dumps(response.json(), indent=4))


@app.command()
def delete_files_for_data_collection(
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
    List files registered for a data collection related to a workflow.
    """

    if not token:
        typer.echo("A valid token must be provided for authentication.")
        raise typer.Exit(code=1)

    user = return_user_from_token(token)  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    response = httpx.get(
        f"{API_BASE_URL}/api/v1/files/list/{workflow_id}/{data_collection_id}",
        # json=data_payload_json,
        headers=headers,
    )
    print(json.dumps(response.json(), indent=4))

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
            f"{API_BASE_URL}/api/v1/deltatables/get",
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
