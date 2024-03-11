import getpass
import json
from pprint import pprint
import sys

# from pprint import pprint
import httpx
import jsonschema
import typer
from typing import Dict, Optional, Tuple
from jose import JWTError, jwt  # Use python-jose to decode JWT tokens
from devtools import debug
from depictio.api.v1.endpoints.datacollections_endpoints.models import DataCollection
from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow


from depictio.api.v1.models.base import convert_objectid_to_str

# from depictio.api.v1.endpoints.user_endpoints.auth import (
#     ALGORITHM,
#     PUBLIC_KEY,
#     fetch_user_from_id,
# )
from depictio.api.v1.models.top_structure import RootConfig
import httpx


from depictio.api.v1.utils import (
    get_config,
    # load_json_schema,
    validate_all_workflows,
    validate_config,
    validate_worfklow,
    # validate_config_using_jsonschema,
)


app = typer.Typer()

cli_config = get_config("CLI_client/CLI_config.yaml")

API_BASE_URL = cli_config["DEPICTIO_API"]


def load_json_schema(schema_path):
    """Load JSON Schema."""
    with open(schema_path, "r") as f:
        return json.load(f)


def validate_config_using_jsonschema(config, schema):
    """Validate YAML configuration against the JSON Schema."""
    try:
        jsonschema.validate(instance=config, schema=schema)
        print("Validation successful. The configuration is valid.")
    except jsonschema.ValidationError as e:
        sys.exit(f"{e}")


def return_user_from_token(token: str) -> dict:
    try:
        headers = {"Authorization": f"Bearer {token}"}
        user = httpx.get(f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user", headers=headers).json()
        return user
    except JWTError as e:
        typer.echo(f"Token verification failed: {e}")
        raise typer.Exit(code=1)


@app.command()
def get_access_token(
    username: Optional[str] = typer.Option(None, "--username", help="Username to be used for authentication"),
    password: Optional[str] = typer.Option(None, "--password", help="Password to be used for authentication"),
):
    """
    Get an access token for the given username and password.
    """
    if not username:
        username = input("Enter username: ")
    if not password:
        password = getpass.getpass("Enter password: ")

    # Data to be sent to the endpoint
    form_data = {
        "username": username,
        "password": password,
    }

    # Make the HTTP POST request
    response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/token", data=form_data)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the token from the response
        token_data = response.json()
        access_token = token_data["access_token"]
        print("Access token retrieved successfully!")
        print(f"Token: {access_token}")
        return access_token
    else:
        # Handle errors
        print(f"Failed to retrieve access token: {response.text}")


def check_workflow_exists(workflow_tag: str, headers: dict) -> Tuple[bool, Optional[Dict]]:
    """
    Check if the workflow exists and return its details if it does.
    """
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/workflows/get?workflow_tag={workflow_tag}",
        headers=headers,
        timeout=30.0,
    )
    if response.status_code == 200:
        return True, response.json()
    return False, None


def find_differences(dict_a: dict, dict_b: dict):
    """
    Find differences between two Pydantic model objects.

    Args:
        model_a (BaseModel): The first model object to compare.
        model_b (BaseModel): The second model object to compare.

    Returns:
        Dict[str, Dict[str, Any]]: A dictionary containing the differences,
        with keys being the attribute names and values being a dictionary
        showing the values from each model for that attribute.
    """
    differences = {}

    all_keys = set(dict_a.keys()) | set(dict_b.keys())

    for key in all_keys:
        if dict_a.get(key) != dict_b.get(key):
            differences[key] = {"model_a": dict_a.get(key), "model_b": dict_b.get(key)}

    return differences


def compare_models(workflow_yaml: dict, workflow_db: dict, user) -> bool:
    """
    Compare the workflow data dictionary with the retrieved workflow JSON.
    """
    # Compare the workflow data dictionary with the retrieved workflow JSON - excluding dynamic fields
    set_checks = []
    workflow_yaml_only = Workflow(**workflow_yaml)
    workflow_yaml_only = workflow_yaml_only.dict(exclude={"registration_time"})
    workflow_db_only = Workflow(**workflow_db)
    workflow_db_only = workflow_db_only.dict(exclude={"registration_time"})
    set_checks.append(workflow_yaml_only == workflow_db_only)

    # Compare the data collections
    for dc_yaml, dc_db in zip(workflow_yaml["data_collections"], workflow_db["data_collections"]):
        dc_yaml = DataCollection(**dc_yaml)
        dc_yaml_only = dc_yaml.dict(exclude={"registration_time"})
        dc_db = DataCollection(**dc_db)
        dc_db_only = dc_db.dict(exclude={"registration_time"})
        set_checks.append(dc_yaml_only == dc_db_only)

    # Check if workflow and data collections are the same between the YAML and the DB
    return set(set_checks) == {True}


def send_workflow_request(endpoint: str, workflow_data_dict: dict, headers: dict) -> None:
    """
    Send a request to the workflow API to create, update, or delete a workflow, based on the specified method.
    """
    print("Workflow data dict: ", workflow_data_dict)
    method_dict = {
        "create": "post",
        "update": "put",
        "delete": "delete",
    }
    method = method_dict[endpoint]

    # Dynamically select the HTTP method
    # Simplify by directly using the httpx.request method
    request_method = method.upper()  # Ensure method is in uppercase
    url = f"{API_BASE_URL}/depictio/api/v1/workflows/{endpoint}"
    json_body = None if request_method == "DELETE" else workflow_data_dict

    response = httpx.request(
        method=request_method,
        url=url,
        headers=headers,
        json=json_body,
        timeout=30.0,
    )
    # print(response.json() if response.status_code != 204 else "")

    # Check response status
    if response.status_code in [200, 204]:  # 204 for successful DELETE requests
        typer.echo(f"Workflow {workflow_data_dict.get('workflow_tag', 'N/A')} successfully {endpoint}d! : {response.json() if response.status_code != 204 else ''}")
        return response.json() if response.status_code != 204 else None
    else:
        typer.echo(f"Error during {endpoint}d: {response.text}")
        raise httpx.HTTPStatusError(message=f"Error during {endpoint}d: {response.text}", request=response.request, response=response)


def create_update_delete_workflow(
    workflow_data_dict: dict,
    headers: dict,
    user,
    update: bool = False,
) -> None:
    """
    Create or update a workflow based on the update flag.
    """

    endpoint = "update" if update else "create"

    print('workflow_data_dict["workflow_tag"]', workflow_data_dict["workflow_tag"])

    exists, _ = check_workflow_exists(workflow_data_dict["workflow_tag"], headers)

    # Check if the workflow exists
    if exists:
        # If the workflow exists, check if there is a conflict with the existing workflow
        check_modif = compare_models(workflow_data_dict, _, user)

        # If the workflow exists but there is a conflict, check if the user wants to update the existing workflow
        if not check_modif:
            # If the user does not want to update the existing workflow, exit
            if not update:
                sys.exit(
                    f"Workflow {workflow_data_dict['workflow_tag']} already exists but with different configuration. Please use the --update flag to update the existing workflow."
                )

            # If the user wants to update the existing workflow, update it
            else:
                typer.echo(f"Workflow {workflow_data_dict['workflow_tag']} already exists, updating it.")
                return send_workflow_request(endpoint, workflow_data_dict, headers)

        # If the workflow exists and there is no conflict, skip the creation
        else:
            typer.echo(f"Workflow {workflow_data_dict['workflow_tag']} already exists, skipping creation.")
            return_dict = {str(_["_id"]): [str(data_collection["_id"]) for data_collection in _["data_collections"]]}
            return return_dict

    # If the workflow does not exist, create it
    typer.echo(f"Workflow {workflow_data_dict['workflow_tag']} does not exist, creating it.")
    workflow_json = send_workflow_request(endpoint, workflow_data_dict, headers)
    return workflow_json


# TODO: change logic to just initiate the scan and not wait for the completion (thousands of files can take a long time)
def scan_files_for_data_collection(workflow_id: str, data_collection_id: str, headers: dict) -> None:
    """
    Scan files for a given data collection of a workflow.
    """
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/files/scan/{workflow_id}/{data_collection_id}",
        headers=headers,
        timeout=5 * 60,  # Increase the timeout as needed
    )
    if response.status_code == 200:
        typer.echo(f"Files successfully scanned for data collection {data_collection_id}!")
    else:
        typer.echo(f"Error for data collection {data_collection_id}: {response.text}")


def create_deltatable_request(workflow_id: str, data_collection_id: str, headers: dict) -> None:
    """
    Create a delta table for a given data collection of a workflow.
    """
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/deltatables/create/{workflow_id}/{data_collection_id}",
        headers=headers,
        timeout=60.0 * 5,  # Increase the timeout as needed
    )
    if response.status_code == 200:
        typer.echo(f"Data successfully aggregated for data collection {data_collection_id}!")
    else:
        typer.echo(f"Error for data collection {data_collection_id}: {response.text}")


@app.command()
def setup(
    config_path: str = typer.Option(
        ...,
        "--config_path",
        help="Path to the YAML configuration file",
    ),
    # workflow_tag: Optional[str] = typer.Option(None, "--workflow_tag", help="Workflow name to be created"),
    update: Optional[bool] = typer.Option(False, "--update", help="Update the workflow if it already exists"),
    token: Optional[str] = typer.Option(
        None,  # Default to None (not specified)
        "--token",
        help="Optionally specify a token to be used for authentication",
    ),
):
    """
    Create a new workflow from a given YAML configuration file.
    """
    # assert workflow_tag is not None

    response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/workflows/drop_all_collections")
    print(response.json())

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

    # TODO: select strategy to validate the config data - JSON Schema or Pydantic models or both

    # Validate the config data using JSON Schema
    # json_schema = load_json_schema("CLI_client/depictio_json_schema.json")
    # validate_config_using_jsonschema(config_data, json_schema)

    print(f"Initializing Workflow model with data: {config_data}")

    # Validate the config data using Pydantic models
    config = validate_config(config_data, RootConfig)
    print(config)
    validated_config = validate_all_workflows(config, user=user)
    print(validate_config)

    # TMP: to print the validated config
    debug(validated_config)

    # Populate DB with the validated config for each workflow
    for workflow in validated_config.workflows:
        workflow_data_raw = workflow.dict(by_alias=True, exclude_none=True)
        workflow_data_dict = convert_objectid_to_str(workflow_data_raw)
        response_body = create_update_delete_workflow(workflow_data_dict, headers, user, update)
        wf_id = response_body["_id"]
        for dc in response_body["data_collections"][:1]:
            if dc["config"]["type"].lower() == "table":
                print("scan_files_for_data_collection")
                print(wf_id, dc["id"], headers)

                scan_files_for_data_collection(wf_id, dc["id"], headers)
                # TODO: clean & refactor jbrowse part in files endpoint
                # TODO: add a jbrowse endpoint to create a TrackSet for each data collection of type Genome Browser

                # Retrieve the data collection details

                print("create_deltatable")
                # print(wf, dc, headers)
                create_deltatable_request(wf_id, dc["id"], headers)
                


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

    # print(token)
    user = return_user_from_token(token)  # Decode the token to get the user information
    if not user:
        typer.echo("Invalid token or unable to decode user information.")
        raise typer.Exit(code=1)

    # Set permissions with the user as both owner and viewer
    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    # print(token)
    workflows = httpx.get(f"{API_BASE_URL}/depictio/api/v1/workflows/get", headers=headers)
    workflows_json = workflows.json()
    pretty_workflows = json.dumps(workflows_json, indent=4)
    # typer.echo(pretty_workflows)
    return workflows_json


@app.command()
def scan_files_from_data_collection(
    config_path: str = typer.Option(
        ...,
        "--config_path",
        help="Path to the YAML configuration file",
    ),
    workflow_id: str = typer.Option(..., "--workflow_id", help="Workflow name to be created"),
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

    headers = {"Authorization": f"Bearer {token}"}  # Token is now mandatory

    config_data = get_config(config_path)
    # print(config_data)
    config = validate_config(config_data, RootConfig)
    assert isinstance(config, RootConfig)

    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/files/scan/{workflow_id}/{data_collection_id}",
        # json=data_payload_json,
        headers=headers,
        # TODO: find a fix for this timeout
        timeout=5 * 60,  # Increase the timeout as needed
    )


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

    # user = return_user_from_token(token)  # Decode the token to get the user information
    # if not user:
    #     typer.echo("Invalid token or unable to decode user information.")
    #     raise typer.Exit(code=1)

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
        f"{API_BASE_URL}/depictio/api/v1/deltatables/create/{workflow_id}/{data_collection_id}",
        # json=data_payload_json,
        headers=headers,
        timeout=60.0 * 5,  # Increase the timeout as needed
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
        f"{API_BASE_URL}/depictio/api/v1/files/list/{workflow_id}/{data_collection_id}",
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
        f"{API_BASE_URL}/depictio/api/v1/files/list/{workflow_id}/{data_collection_id}",
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
            raise ValueError(f"Data collection '{data_collection_id}' not found for the given workflow.")
        data_collections_to_process.append(workflow.data_collections[data_collection_id])
    else:
        data_collections_to_process = list(workflow.data_collections.values())

    for data_collection in data_collections_to_process:
        data_payload = data_collection.dict()

        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/deltatables/get",
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
