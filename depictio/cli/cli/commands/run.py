from typing import Annotated

import typer

from depictio.cli.cli.utils.api_calls import (
    api_get_project_from_name,
    api_login,
    api_sync_project_config_to_server,
)
from depictio.cli.cli.utils.common import load_depictio_config
from depictio.cli.cli.utils.config import validate_project_config_and_check_S3_storage
from depictio.cli.cli.utils.helpers import process_project_helper
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_section_separator,
)
from depictio.cli.cli.utils.scan import scan_project_files
from depictio.cli.cli_logging import logger
from depictio.models.s3_utils import S3_storage_checks
from depictio.models.utils import convert_model_to_dict


def register_run_command(app: typer.Typer):
    @app.command("run")
    def run(
        CLI_config_path: Annotated[
            str, typer.Option("--CLI-config-path", help="Path to the configuration file")
        ] = "~/.depictio/CLI.yaml",
        project_config_path: Annotated[
            str,
            typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
        ] = "",
        workflow_name: Annotated[
            str | None,
            typer.Option("--workflow-name", help="Name of the workflow to be scanned"),
        ] = None,
        data_collection_tag: Annotated[
            str | None,
            typer.Option("--data-collection-tag", help="Data collection tag to be processed"),
        ] = None,
        # Flow control options
        skip_server_check: bool = typer.Option(
            False, "--skip-server-check", help="Skip server accessibility check"
        ),
        skip_s3_check: bool = typer.Option(False, "--skip-s3-check", help="Skip S3 storage check"),
        skip_sync: bool = typer.Option(
            False, "--skip-sync", help="Skip syncing project config to server"
        ),
        skip_scan: bool = typer.Option(False, "--skip-scan", help="Skip data scanning step"),
        skip_process: bool = typer.Option(
            False, "--skip-process", help="Skip data processing step"
        ),
        # Sync options
        update_config: bool = typer.Option(
            False, "--update-config", help="Update the project configuration on the server"
        ),
        # Scan options
        rescan_folders: bool = typer.Option(
            False, "--rescan-folders", help="Reprocess all runs for the data collection"
        ),
        sync_files: bool = typer.Option(
            False, "--sync-files", help="Update files for the data collection"
        ),
        rich_tables: bool = typer.Option(
            False,
            "--rich-tables",
            help="Show detailed summary of the workflow execution",
        ),
        # Process options
        overwrite: bool = typer.Option(
            False, "--overwrite", help="Overwrite the workflow if it already exists"
        ),
        # General options
        continue_on_error: bool = typer.Option(
            False, "--continue-on-error", help="Continue execution even if a step fails"
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Show what would be executed without running it"
        ),
    ):
        """
        Run the complete Depictio workflow: validate, sync, scan, and process.

        This command executes the full depictio-cli pipeline:

        1. Check server accessibility

        2. Check S3 storage configuration

        3. Validate project configuration

        4. Sync project configuration to server

        5. Scan data files

        6. Process data collections
        """
        rich_print_command_usage("run")

        if dry_run:
            rich_print_checked_statement(
                "DRY RUN MODE - No actual operations will be performed", "info"
            )

        if sync_files:
            rescan_folders = True

        success_count = 0
        total_steps = 6

        # Step 1: Check server accessibility
        if not skip_server_check:
            rich_print_section_separator("Step 1/6: Checking server accessibility")
            try:
                if not dry_run:
                    api_login(CLI_config_path)
                rich_print_checked_statement("Server accessibility check passed", "success")
                success_count += 1
            except Exception as e:
                rich_print_checked_statement(f"Server accessibility check failed: {e}", "error")
                if not continue_on_error:
                    return
        else:
            rich_print_checked_statement("Skipping server accessibility check", "info")
            success_count += 1

        # Step 2: Check S3 storage
        if not skip_s3_check:
            rich_print_section_separator("Step 2/6: Checking S3 storage configuration")
            try:
                if not dry_run:
                    CLI_config = load_depictio_config(yaml_config_path=CLI_config_path)
                    S3_storage_checks(CLI_config.s3_storage)
                rich_print_checked_statement("S3 storage configuration check passed", "success")
                success_count += 1
            except Exception as e:
                rich_print_checked_statement(f"S3 storage check failed: {e}", "error")
                if not continue_on_error:
                    return
        else:
            rich_print_checked_statement("Skipping S3 storage check", "info")
            success_count += 1

        # Step 3: Validate project configuration
        rich_print_section_separator("Step 3/6: Validating project configuration")
        try:
            if not dry_run:
                CLI_config, validation_response = validate_project_config_and_check_S3_storage(
                    CLI_config_path=CLI_config_path, project_config_path=project_config_path
                )
                if not validation_response["success"]:
                    raise Exception("Project configuration validation failed")
                project_config = validation_response["project_config"]
            rich_print_checked_statement("Project configuration validation passed", "success")
            success_count += 1
        except Exception as e:
            rich_print_checked_statement(f"{e}", "error")
            if not continue_on_error:
                return

        # Step 4: Sync project configuration to server
        if not skip_sync:
            rich_print_section_separator("Step 4/6: Syncing project configuration to server")
            try:
                if not dry_run:
                    project_config_dict = convert_model_to_dict(project_config)
                    api_sync_project_config_to_server(
                        CLI_config=CLI_config,
                        ProjectConfig=project_config_dict,
                        update=update_config,
                    )
                rich_print_checked_statement("Project configuration sync completed", "success")
                success_count += 1
            except Exception as e:
                rich_print_checked_statement(f"Project configuration sync failed: {e}", "error")
                if not continue_on_error:
                    return
        else:
            rich_print_checked_statement("Skipping project configuration sync", "info")
            success_count += 1

        # Step 5: Scan data files
        if not skip_scan:
            rich_print_section_separator("Step 5/6: Scanning data files")
            try:
                if not dry_run:
                    # Get remote project configuration to compare hashes
                    remote_project_config = api_get_project_from_name(
                        str(project_config.name), CLI_config
                    )

                    if remote_project_config.status_code == 200:
                        # Compare hashes
                        local_hash = project_config.hash
                        remote_hash = remote_project_config.json().get("hash", None)
                        logger.info(f"Local & Remote hashes: {local_hash} & {remote_hash}")

                        if local_hash == remote_hash:
                            command_parameters = {
                                "rescan_folders": rescan_folders,
                                "sync_files": sync_files,
                                "rich_tables": rich_tables,
                            }

                            # Use the unified scanning function
                            result = scan_project_files(
                                project_config=project_config,
                                CLI_config=CLI_config,
                                workflow_name=workflow_name,
                                data_collection_tag=data_collection_tag,
                                command_parameters=command_parameters,
                            )

                            if result["result"] != "success":
                                raise Exception("Data scanning failed")

                        else:
                            raise Exception("Local and remote project configurations do not match")
                    else:
                        raise Exception("Failed to fetch remote project configuration")

                rich_print_checked_statement("Data scanning completed", "success")
                success_count += 1
            except Exception as e:
                rich_print_checked_statement(f"Data scanning failed: {e}", "error")
                if not continue_on_error:
                    return
        else:
            rich_print_checked_statement("Skipping data scanning", "info")
            success_count += 1

        # Step 6: Process data collections
        if not skip_process:
            rich_print_section_separator("Step 6/6: Processing data collections")
            try:
                if not dry_run:
                    # Get remote project configuration again for processing
                    remote_project_config = api_get_project_from_name(
                        str(project_config.name), CLI_config
                    )

                    if remote_project_config.status_code == 200:
                        # Compare hashes
                        local_hash = project_config.hash
                        remote_hash = remote_project_config.json().get("hash", None)

                        if local_hash == remote_hash:
                            command_parameters = {
                                "overwrite": overwrite,
                                "rich_tables": rich_tables,
                            }

                            process_project_helper(
                                CLI_config=CLI_config,
                                project_config=project_config,
                                mode="process",
                                command_parameters=command_parameters,
                            )
                        else:
                            raise Exception("Local and remote project configurations do not match")
                    else:
                        raise Exception("Failed to fetch remote project configuration")

                rich_print_checked_statement("Data processing completed", "success")
                success_count += 1
            except Exception as e:
                rich_print_checked_statement(f"Data processing failed: {e}", "error")
                if not continue_on_error:
                    return
        else:
            rich_print_checked_statement("Skipping data processing", "info")
            success_count += 1

        # Final summary
        rich_print_section_separator("Depictio-CLI Run Summary")
        if success_count == total_steps:
            rich_print_checked_statement(
                f"Depictio-CLI run completed successfully! ({success_count}/{total_steps} steps)",
                "success",
            )
        else:
            rich_print_checked_statement(
                f"Depictio-CLI run completed with some issues ({success_count}/{total_steps} steps)",
                "warning",
            )
