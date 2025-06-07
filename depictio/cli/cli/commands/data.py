from typing import Annotated

import typer

from depictio.cli.cli.utils.api_calls import api_get_project_from_id, api_get_project_from_name
from depictio.cli.cli.utils.config import validate_project_config_and_check_S3_storage
from depictio.cli.cli.utils.helpers import process_project_helper
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_section_separator,
)
from depictio.cli.cli_logging import logger

app = typer.Typer()


@app.command()
def scan(
    CLI_config_path: Annotated[
        str,
        typer.Option("--CLI-config-path", help="Path to the CLI configuration file"),
    ] = "~/.depictio/CLI.yaml",
    project_config_path: Annotated[
        str,
        typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
    ] = "",
    workflow_name: Annotated[
        str | None,  # Now explicitly Optional
        typer.Option("--workflow-name", help="Name of the workflow to be scanned"),
    ] = None,
    data_collection_tag: Annotated[
        str | None,  # Also make this Optional if its default is None
        typer.Option("--data-collection-tag", help="Data collection tag to be scanned"),
    ] = None,
    rescan_folders: bool = typer.Option(
        False, "--rescan-folders", help="Reprocess all runs for the data collection"
    ),
    sync_files: bool = typer.Option(
        False, "--sync-files", help="Update files for the data collection"
    ),
    rich_tables: bool = typer.Option(
        False, "--rich-tables", help="Display rich tables in the output"
    ),
):
    """
    Scan files.

    Args:
        CLI_config_path (Annotated[str, typer.Option, optional): _description_. Defaults to "Path to the CLI configuration file")]="~/.depictio/CLI.yaml".
        project_config_path (Annotated[str, typer.Option, optional): _description_. Defaults to "Path to the pipeline configuration file")]="".
        workflow_name (Annotated[str, typer.Option, optional): _description_. Defaults to "Name of the workflow to be scanned")]="",
        data_collection_tag (Optional[str], optional): _description_. Defaults to typer.Option(None, "--data-collection-tag", help="Data collection tag to be scanned").
        rescan_folders (Annotated[bool, typer.Option, optional): _description_. Defaults to "Reprocess all runs for the data collection")]=False.
        update_files (Annotated[bool, typer.Option, optional): _description_. Defaults to "Update files for the data collection. rescan-folders will be enabled if used.")]=False.
    """
    rich_print_command_usage("scan")

    if sync_files:
        rescan_folders = True

    logger.info(f"Reprocessing runs: {rescan_folders}")
    logger.info(f"Updating files: {sync_files}")

    # Validate configurations and prepare headers
    CLI_config, response = validate_project_config_and_check_S3_storage(
        CLI_config_path=CLI_config_path, project_config_path=project_config_path
    )

    if response["success"]:
        rich_print_checked_statement("Depictio Project configuration validated", "success")

        # Get the validated project configuration
        project_config = response["project_config"]

        # Get remote project configuration
        # remote_project_config = api_get_project_from_id(
        #     str(project_config.id), CLI_config
        # )
        remote_project_config = api_get_project_from_name(str(project_config.name), CLI_config)

        if remote_project_config.status_code == 200:
            logger.info("Remote project configuration fetched successfully.")
            rich_print_checked_statement(
                "Remote project configuration fetched successfully.", "success"
            )

            # project_config = project_config.mongo()

            # Compare hashes
            local_hash = project_config.hash
            remote_hash = remote_project_config.json().get("hash", None)
            logger.info(f"Local & Remote hashes: {local_hash} & {remote_hash}")
            comparison_result = local_hash == remote_hash

            if comparison_result:
                rich_print_checked_statement(
                    "Local and remote project configurations match.", "success"
                )

                rich_print_section_separator("Scanning files")

                command_parameters = {
                    "rescan_folders": rescan_folders,
                    "sync_files": sync_files,
                    "rich_tables": rich_tables,
                }

                # Process project
                process_project_helper(
                    CLI_config=CLI_config,
                    project_config=project_config,
                    workflow_name=workflow_name,
                    data_collection_tag=data_collection_tag,
                    command_parameters=command_parameters,
                    mode="scan",
                )

            else:
                rich_print_checked_statement(
                    "Local and remote project configurations do not match.", "error"
                )
        else:
            rich_print_checked_statement(
                "Error fetching remote project configuration. Please create the project first if it does not exist.",
                "error",
            )

    else:
        rich_print_checked_statement("Depictio Project configuration validation failed", "error")

    # Step 2: Process project
    # process_project_helper(cli_config, project_config, headers, update, scan_files, data_collection_tag)

    # remote_upload_files(response["CLI_config"], project_config_path, data_collection_tag)


@app.command()
def process(
    CLI_config_path: Annotated[
        str,
        typer.Option("--CLI-config-path", help="Path to the CLI configuration file"),
    ] = "~/.depictio/CLI.yaml",
    project_config_path: Annotated[
        str,
        typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
    ] = "",
    # update: Optional[bool] = typer.Option(False, "--update", help="Update the workflow if it already exists"),
    overwrite: bool | None = typer.Option(
        False, "--overwrite", help="Overwrite the workflow if it already exists"
    ),
    # data_collection_tag: Optional[str] = typer.Option(None, "--data-collection-tag", help="Data collection tag to be processed"),
    rich_tables: bool = typer.Option(
        False, "--rich-tables", help="Display rich tables in the output"
    ),
):
    """
    Process data collections for a specific tag.
    """
    rich_print_command_usage("process")

    # Validate configurations and prepare headers
    CLI_config, response = validate_project_config_and_check_S3_storage(
        CLI_config_path=CLI_config_path, project_config_path=project_config_path
    )

    if response["success"]:
        rich_print_checked_statement("Depictio Project configuration validated", "success")

        # Get the validated project configuration
        project_config = response["project_config"]

        # Get remote project configuration
        remote_project_config = api_get_project_from_id(project_config.id, CLI_config)

        if remote_project_config.status_code == 200:
            logger.info("Remote project configuration fetched successfully.")
            rich_print_checked_statement(
                "Remote project configuration fetched successfully.", "success"
            )

            # project_config = project_config.mongo()

            # Compare hashes
            local_hash = project_config.hash
            remote_hash = remote_project_config.json().get("hash", None)
            logger.info(f"Local & Remote hashes: {local_hash} & {remote_hash}")
            comparison_result = local_hash == remote_hash

            if comparison_result:
                rich_print_checked_statement(
                    "Local and remote project configurations match.", "success"
                )

                command_parameters = {
                    "overwrite": overwrite,
                    "rich_tables": rich_tables,
                }

                rich_print_section_separator("Processing files")
                logger.info("Processing files")
                logger.info(f"Command parameters: {command_parameters}")
                process_project_helper(
                    CLI_config=CLI_config,
                    project_config=project_config,
                    mode="process",
                    command_parameters=command_parameters,
                )
            else:
                rich_print_checked_statement(
                    "Local and remote project configurations do not match.", "error"
                )
