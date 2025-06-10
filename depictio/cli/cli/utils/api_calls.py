import httpx
import typer
from pydantic import validate_call

from depictio.cli.cli.utils.common import generate_api_headers, load_depictio_config
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli_logging import logger
from depictio.models.models.base import BaseModel, PyObjectId, convert_objectid_to_str
from depictio.models.models.files import File
from depictio.models.models.users import CLIConfig
from depictio.models.models.workflows import WorkflowRun
from depictio.models.utils import convert_model_to_dict


@validate_call
def api_login(yaml_config_path: str = "~/.depictio/CLI.yaml") -> dict:
    """
    Login to the Depictio API using the CLI configuration.
    """
    depictio_CLI_config = load_depictio_config(yaml_config_path=yaml_config_path)
    depictio_CLI_config = convert_objectid_to_str(depictio_CLI_config.model_dump())
    logger.info(f"Depictio CLI configuration loaded: {depictio_CLI_config}")
    rich_print_checked_statement("Checking server accessibility...", "info")

    # Connect to depictio API
    response = httpx.post(
        f"{depictio_CLI_config['base_url']}/depictio/api/v1/cli/validate_cli_config",
        json=depictio_CLI_config,
    )
    if response.status_code == 200:
        logger.info("Depictio CLI configuration is valid.")
        rich_print_checked_statement("Depictio CLI configuration is valid.", "success")
        return {"success": True, "CLI_config": depictio_CLI_config}
    else:
        logger.error(f"Depictio CLI configuration is invalid: {response.text}")
        rich_print_checked_statement(
            f"Depictio CLI configuration is invalid: {response.text}", "error"
        )
        return {"success": False}


@validate_call
def api_get_project_from_id(project_id: PyObjectId, CLI_config: CLIConfig):
    """
    Get a project from the server using the project ID.
    """
    # First check if the project exists on the server DB for existing IDs and if the same metadata hash is used
    logger.info(f"Getting project with ID: {project_id}")
    response = httpx.get(
        f"{CLI_config.base_url}/depictio/api/v1/projects/get/from_id",
        params={"project_id": project_id},
        headers=generate_api_headers(CLI_config),
    )
    return response


@validate_call
def api_get_project_from_name(project_name: str, CLI_config: CLIConfig):
    """
    Get a project from the server using the project ID.
    """
    # First check if the project exists on the server DB for existing IDs and if the same metadata hash is used
    response = httpx.get(
        f"{CLI_config.base_url}/depictio/api/v1/projects/get/from_name/{project_name}",
        # params={"project_name": project_name},
        headers=generate_api_headers(CLI_config),
    )
    return response


@validate_call
def api_create_project(project_config: dict, CLI_config: CLIConfig):
    """
    Create a project on the server.
    """
    logger.info("Creating project on server...")

    response = httpx.post(
        f"{CLI_config.base_url}/depictio/api/v1/projects/create",
        json=project_config,
        headers=generate_api_headers(CLI_config),
    )

    return response


@validate_call
def api_update_project(project_config: dict, CLI_config: CLIConfig):
    """
    Update a project on the server.
    """
    logger.info("Updating project on server...")
    logger.debug(f"Project configuration: {project_config}")

    response = httpx.put(
        f"{CLI_config.base_url}/depictio/api/v1/projects/update",
        json=project_config,
        headers=generate_api_headers(CLI_config),
    )

    return response


@validate_call
def api_sync_project_config_to_server(
    CLI_config: CLIConfig, ProjectConfig: dict, update: bool = False
):
    """
    Sync the pipeline configuration to the server.
    """
    rich_print_checked_statement("Syncing pipeline configuration to server...", "info")

    # Check if the project exists on the server
    logger.info(f"Project configuration: {ProjectConfig}")
    project_config = ProjectConfig

    response = api_get_project_from_name(str(ProjectConfig["name"]), CLI_config)
    # response = api_get_project_from_id(str(ProjectConfig.id), CLI_config)
    # project_config = convert_objectid_to_str(ProjectConfig.mongo())
    logger.info(f"Project configuration: {project_config}")

    if response.status_code == 200:
        rich_print_checked_statement("Project configuration found on server", "info")
        logger.info(f"Project configuration found on server: {response.json()}")

        # If update flag is False, exit
        if not update:
            logger.error(
                "Project configuration already exists on server, use --update flag to update."
            )
            rich_print_checked_statement(
                "Project configuration already exists on server, use --update flag to update.",
                "error",
            )
            raise typer.Exit(code=0)

        # If update flag is True, update the project on the server
        rich_print_checked_statement(
            "--update flag set, updating project configuration on server...", "info"
        )
        logger.debug(f"Updating project configuration on server: {project_config}")
        response = api_update_project(project_config, CLI_config)
        if response.status_code == 200:
            rich_print_checked_statement("Project updated on server", "success")
            logger.info(f"Project updated on server: {response.json()}")
        else:
            rich_print_checked_statement(
                f"Failed to update project on server: {response.text}", "error"
            )
            logger.error(f"Failed to update project on server: {response.text}")
            raise typer.Exit(code=1)

    elif response.status_code == 404:
        logger.info("Project configuration not found on server.")
        rich_print_checked_statement(
            "Project configuration not found on server, creating project...", "info"
        )
        # Create the project on the server
        response = api_create_project(project_config, CLI_config)
        if response.status_code == 200:
            logger.info(f"Project created on server: {response.json()}")
            rich_print_checked_statement("Project created on server", "success")
        else:
            logger.error(f"Failed to create project on server: {response.text}")
            rich_print_checked_statement(
                f"Failed to create project on server: {response.text}", "error"
            )
            raise typer.Exit(code=1)


@validate_call
def api_create_files(
    files: list[File], CLI_config: "CLIConfig", update: bool = False
) -> httpx.Response:
    """
    Create or update files on the server using a bulk upsert.

    Args:
        files (List[dict]): A list of file dictionaries to send.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.
        update (bool, optional): If True, update existing files; otherwise, insert only new ones. Defaults to False.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info("Uploading files to the server...")

    files = [convert_model_to_dict(f) for f in files]

    payload = {"files": files, "update": update}
    logger.debug(f"Files: {files[:2]}")  # Log only the first two files for brevity
    light_payload = {"files": files[:2], "update": update}
    logger.debug(f"Light Payload: {light_payload}")  # Log only the first two files for brevity
    url = f"{CLI_config.base_url}/depictio/api/v1/files/upsert_batch"

    logger.debug(f"Payload: {payload}")

    response = httpx.post(url, json=payload, headers=generate_api_headers(CLI_config))
    return response


# @validate_call
def api_get_files_by_dc_id(dc_id: str, CLI_config: CLIConfig) -> httpx.Response:
    """
    Get files from the server using the data collection ID.

    Args:
        dc_id (str): Data collection ID to filter files by.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Getting files for data collection ID: {dc_id}")
    logger.info(f"{CLI_config.base_url}/depictio/api/v1/files/list/{dc_id}")
    logger.info(generate_api_headers(CLI_config))
    response = httpx.get(
        f"{CLI_config.base_url}/depictio/api/v1/files/list/{dc_id}",
        headers=generate_api_headers(CLI_config),
        timeout=60.0,  # Increase timeout to 60 seconds
    )
    return response


# Optionally, if you also need to push runs, you could create a similar function:


@validate_call
def api_get_runs_by_wf_id(wf_id: str, CLI_config: CLIConfig) -> httpx.Response:
    """
    Get runs from the server using the workflow ID.

    Args:
        wf_id (str): Workflow ID to filter runs by.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Getting runs for workflow ID: {wf_id}")

    url = f"{CLI_config.base_url}/depictio/api/v1/runs/list/{wf_id}"
    response = httpx.get(url, headers=generate_api_headers(CLI_config))
    return response


class UpsertWorkflowRun(BaseModel):
    runs: list[WorkflowRun]
    update: bool = False


@validate_call
def api_upsert_runs_batch(
    runs: list[WorkflowRun], CLI_config: CLIConfig, update: bool = False
) -> httpx.Response:
    """
    Create or update runs on the server using a bulk upsert.

    Args:
        runs (List[dict]): A list of run dictionaries to send.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.
        update (bool, optional): If True, update existing runs; otherwise, insert only new ones. Defaults to False.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info("Uploading runs to the server...")
    logger.debug(f"Runs: {runs[:2]}")
    runs = [convert_model_to_dict(r) for r in runs]
    logger.debug(f"Runs: {runs[:2]}")

    # payload = {"runs": {}, "update": update}
    payload = {"runs": runs, "update": update}
    logger.debug(f"Payload runs upsert batch: {payload}")
    url = f"{CLI_config.base_url}/depictio/api/v1/runs/upsert_batch"

    response = httpx.post(url, json=payload, headers=generate_api_headers(CLI_config))
    return response


@validate_call
def api_delete_run(run_id: str, CLI_config: CLIConfig) -> httpx.Response:
    """
    Delete a run from the server using the run ID.

    Args:
        run_id (str): Run ID to delete.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Deleting run with ID: {run_id}")

    url = f"{CLI_config.base_url}/depictio/api/v1/runs/delete/{run_id}"
    response = httpx.delete(url, headers=generate_api_headers(CLI_config))
    return response


@validate_call
def api_get_run(run_id: str, CLI_config: CLIConfig) -> httpx.Response:
    """
    Get a run from the server using the run ID.

    Args:
        run_id (str): Run ID to retrieve.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Getting run with ID: {run_id}")

    url = f"{CLI_config.base_url}/depictio/api/v1/runs/get/{run_id}"
    response = httpx.get(url, headers=generate_api_headers(CLI_config))
    return response


@validate_call
def api_delete_file(file_id: str, CLI_config: CLIConfig) -> httpx.Response:
    """
    Delete a file from the server using the file ID.

    Args:
        file_id (str): File ID to delete.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Deleting file with ID: {file_id}")

    url = f"{CLI_config.base_url}/depictio/api/v1/files/delete/{file_id}"
    response = httpx.delete(url, headers=generate_api_headers(CLI_config))
    return response


@validate_call
def api_upsert_deltatable(
    data_collection_id: str,
    delta_table_location: str,
    CLI_config: CLIConfig,
    update: bool = False,
) -> httpx.Response:
    """
    Create or update a Delta Table on the server using a bulk upsert.

    Args:
        deltaTable (UpsertDeltaTableAggregated): Delta Table to send.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info("Uploading Delta Table to the server...")

    payload = {
        "data_collection_id": data_collection_id,
        "delta_table_location": delta_table_location,
        "update": update,
    }

    url = f"{CLI_config.base_url}/depictio/api/v1/deltatables/upsert"

    logger.debug(f"Payload: {payload}")

    response = httpx.post(url, json=payload, headers=generate_api_headers(CLI_config))
    return response


@validate_call
def api_get_deltatable_by_dc_id(dc_id: str, CLI_config: CLIConfig) -> httpx.Response:
    """
    Get Delta Table from the server using the data collection ID.

    Args:
        dc_id (str): Data collection ID to filter Delta Tables by.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Getting Delta Table for data collection ID: {dc_id}")

    response = httpx.get(
        f"{CLI_config.base_url}/depictio/api/v1/deltatables/get/{dc_id}",
        headers=generate_api_headers(CLI_config),
    )
    return response


@validate_call
def api_delete_deltatable(delta_table_id: str, CLI_config: CLIConfig) -> httpx.Response:
    """
    Delete a Delta Table from the server using the Delta Table ID.

    Args:
        delta_table_id (str): Delta Table ID to delete.
        CLI_config (CLIConfig): Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Deleting Delta Table with ID: {delta_table_id}")

    url = f"{CLI_config.base_url}/depictio/api/v1/deltatables/delete/{delta_table_id}"
    response = httpx.delete(url, headers=generate_api_headers(CLI_config))
    return response
