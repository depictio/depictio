from pathlib import Path
from typing import Annotated

import typer

from depictio.cli.cli.utils.api_calls import (
    api_get_project_from_name,
    api_login,
    api_sync_project_config_to_server,
)
from depictio.cli.cli.utils.common import generate_api_headers, load_depictio_config
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
        # Template options
        template: Annotated[
            str | None,
            typer.Option(
                "--template",
                help="Template ID to use (e.g., nf-core/ampliseq/2.16.0). "
                "Mutually exclusive with --project-config-path.",
            ),
        ] = None,
        data_root: Annotated[
            str | None,
            typer.Option(
                "--data-root",
                help="Root directory containing data for template. Required when --template is used.",
            ),
        ] = None,
        project_name: Annotated[
            str | None,
            typer.Option(
                "--project-name",
                help="Custom project name (auto-generated from template if omitted).",
            ),
        ] = None,
        var: Annotated[
            list[str],
            typer.Option(
                "--var",
                help=(
                    "Extra template variable as KEY=VALUE. Repeatable. "
                    "Example: --var SAMPLESHEET_FILE=/path/to/samplesheet.csv "
                    "--var METADATA_FILE=/path/to/metadata.tsv"
                ),
            ),
        ] = [],
        dashboard: Annotated[
            list[str] | None,
            typer.Option(
                "--dashboard",
                help=(
                    "Override template default dashboards with custom YAML file paths. "
                    "Can be specified multiple times."
                ),
            ),
        ] = None,
        skip_dashboard_import: bool = typer.Option(
            False,
            "--skip-dashboard-import",
            help="Skip automatic dashboard import from template.",
        ),
        # Existing options
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
        skip_join: bool = typer.Option(False, "--skip-join", help="Skip join execution step"),
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
        preview_recipes: bool = typer.Option(
            False,
            "--preview-recipes",
            help="Show recipe input sources and transformed output without writing to Delta Lake",
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
        Run the complete Depictio workflow: validate, sync, scan, process, and join.

        This command executes the full depictio-cli pipeline:

        1. Check server accessibility

        2. Check S3 storage configuration

        3. Validate project configuration (or resolve template)

        4. Sync project configuration to server

        5. Scan data files

        6. Process data collections

        7. Execute table joins (if defined in project config)

        Template mode:
            depictio-cli run --template nf-core/ampliseq/2.16.0 --data-root /path/to/data
        """
        rich_print_command_usage("run")

        # Validate template/project-config-path mutual exclusivity
        if template and project_config_path:
            rich_print_checked_statement(
                "--template and --project-config-path are mutually exclusive. "
                "Use one or the other.",
                "error",
            )
            raise typer.Exit(code=1)

        if template and not data_root:
            rich_print_checked_statement("--data-root is required when using --template.", "error")
            raise typer.Exit(code=1)

        if dry_run:
            rich_print_checked_statement(
                "DRY RUN MODE - No actual operations will be performed", "info"
            )

        if sync_files:
            rescan_folders = True

        # Track whether we're in template mode
        is_template_mode = template is not None
        template_resolved_config: dict | None = None
        template_dashboard_paths: list[Path] = []

        success_count = 0
        total_steps = 8 if is_template_mode else 7

        # Step 0 (template only): Resolve template and validate data
        if is_template_mode:
            rich_print_section_separator("Step 0: Resolving project template")
            try:
                from depictio.cli.cli.utils.templates import resolve_template

                # Check data root exists before doing anything
                if not Path(data_root).is_dir():  # type: ignore[arg-type]
                    rich_print_checked_statement(
                        f"--data-root does not exist or is not a directory: {data_root}",
                        "error",
                    )
                    raise typer.Exit(code=1)

                # Parse --var KEY=VALUE pairs into extra_vars dict
                extra_vars: dict[str, str] = {}
                for v in var:
                    if "=" not in v:
                        rich_print_checked_statement(
                            f"--var must be KEY=VALUE format, got: {v!r}", "error"
                        )
                        raise typer.Exit(code=1)
                    k, val = v.split("=", 1)
                    extra_vars[k.strip()] = val.strip()

                # Resolve template
                (
                    resolved_config,
                    template_metadata,
                    template_origin,
                    default_dashboard_paths,
                    template_variables,
                ) = resolve_template(
                    template_id=template,  # type: ignore[arg-type]
                    data_root=data_root,  # type: ignore[arg-type]
                    project_name=project_name,
                    extra_vars=extra_vars or None,
                )

                rich_print_checked_statement(
                    f"Template '{template_metadata.template_id}' loaded successfully",
                    "success",
                )

                template_resolved_config = resolved_config

                # Resolve dashboard paths: CLI --dashboard overrides template defaults
                if dashboard:
                    template_dashboard_paths = [Path(p).resolve() for p in dashboard]
                    rich_print_checked_statement(
                        f"Using {len(template_dashboard_paths)} dashboard(s) from --dashboard override",
                        "info",
                    )
                else:
                    template_dashboard_paths = default_dashboard_paths
                    if template_dashboard_paths:
                        rich_print_checked_statement(
                            f"Template provides {len(template_dashboard_paths)} default dashboard(s)",
                            "info",
                        )

                if dry_run:
                    import json

                    rich_print_checked_statement("Resolved template configuration:", "info")
                    # Print a summary, not the full config
                    summary = {
                        "name": resolved_config.get("name"),
                        "template_origin": {
                            "template_id": template_origin.template_id,
                            "template_version": template_origin.template_version,
                            "data_root": template_origin.data_root,
                        },
                        "workflows": [
                            {
                                "name": w.get("name"),
                                "data_collections": [
                                    dc.get("data_collection_tag")
                                    for dc in w.get("data_collections", [])
                                ],
                            }
                            for w in resolved_config.get("workflows", [])
                        ],
                    }
                    logger.info(f"Template config summary: {json.dumps(summary, indent=2)}")

            except typer.Exit:
                raise
            except Exception as e:
                rich_print_checked_statement(f"Template resolution failed: {e}", "error")
                if not continue_on_error:
                    return

        # Step 1: Check server accessibility
        if not skip_server_check:
            rich_print_section_separator(f"Step 1/{total_steps}: Checking server accessibility")
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
            rich_print_section_separator(f"Step 2/{total_steps}: Checking S3 storage configuration")
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
        rich_print_section_separator(f"Step 3/{total_steps}: Validating project configuration")
        try:
            if not dry_run:
                if is_template_mode and template_resolved_config is not None:
                    # Template mode: use resolved config dict
                    from depictio.cli.cli.utils.config import validate_template_project_config

                    CLI_config, validation_response = validate_template_project_config(
                        CLI_config_path=CLI_config_path,
                        resolved_config=template_resolved_config,
                    )
                else:
                    # Standard mode: load from YAML file
                    CLI_config, validation_response = validate_project_config_and_check_S3_storage(
                        CLI_config_path=CLI_config_path,
                        project_config_path=project_config_path,
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
            rich_print_section_separator(
                f"Step 4/{total_steps}: Syncing project configuration to server"
            )
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
            rich_print_section_separator(f"Step 5/{total_steps}: Scanning data files")
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
            rich_print_section_separator(f"Step 6/{total_steps}: Processing data collections")
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
                                "preview_recipes": preview_recipes,
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

        # Step 7: Execute table joins
        if not skip_join:
            rich_print_section_separator(f"Step 7/{total_steps}: Executing table joins")
            try:
                if not dry_run:
                    # Check if project has joins defined
                    if hasattr(project_config, "joins") and project_config.joins:
                        from depictio.cli.cli.utils.joins import process_project_joins

                        command_parameters = {
                            "overwrite": overwrite,
                            "rich_tables": rich_tables,
                        }

                        join_result = process_project_joins(
                            project=project_config,
                            CLI_config=CLI_config,
                            join_name=None,  # Process all joins
                            preview_only=False,
                            overwrite=overwrite,
                            auto_process_dependencies=True,
                        )

                        if join_result.get("result") not in ["success", "partial"]:
                            raise Exception("Join execution failed")

                        # Show summary
                        if join_result.get("processed"):
                            rich_print_checked_statement(
                                f"Processed {len(join_result['processed'])} join(s)", "success"
                            )
                        if join_result.get("errors"):
                            rich_print_checked_statement(
                                f"Failed {len(join_result['errors'])} join(s)", "warning"
                            )
                    else:
                        rich_print_checked_statement("No joins defined in project config", "info")

                rich_print_checked_statement("Join execution completed", "success")
                success_count += 1
            except Exception as e:
                rich_print_checked_statement(f"Join execution failed: {e}", "error")
                if not continue_on_error:
                    return
        else:
            rich_print_checked_statement("Skipping join execution", "info")
            success_count += 1

        # Step 8 (template only): Import dashboards
        if is_template_mode and not skip_dashboard_import and template_dashboard_paths:
            rich_print_section_separator(
                f"Step {total_steps}/{total_steps}: Importing template dashboards"
            )
            try:
                if not dry_run:
                    from depictio.cli.cli.utils.templates import (
                        import_dashboards_from_template,
                    )

                    headers = generate_api_headers(CLI_config)
                    api_url = str(CLI_config.api_base_url)

                    # Resolve the project ID from the server
                    project_id: str | None = None
                    remote_project = api_get_project_from_name(str(project_config.name), CLI_config)
                    if remote_project.status_code == 200:
                        remote_project_data = remote_project.json()
                        project_id = remote_project_data.get("_id") or remote_project_data.get("id")

                    results = import_dashboards_from_template(
                        dashboard_paths=template_dashboard_paths,
                        api_url=api_url,
                        headers=headers,
                        project_id=project_id,
                        overwrite=overwrite,
                        variables=template_variables,
                    )

                    imported, failed = [], []
                    for r in results:
                        (imported if r["success"] else failed).append(r)

                    for r in imported:
                        action = "updated" if r.get("updated") else "imported"
                        rich_print_checked_statement(
                            f"Dashboard {action}: {r.get('title', 'unknown')}", "success"
                        )
                        if r.get("dash_url"):
                            rich_print_checked_statement(
                                f"  View at: {r['dash_url']}/dashboard/{r.get('dashboard_id')}",
                                "info",
                            )

                    for r in failed:
                        rich_print_checked_statement(
                            f"Dashboard failed: {Path(r['path']).name} - {r.get('error', 'unknown')}",
                            "error",
                        )

                    if failed and not continue_on_error:
                        raise Exception(f"{len(failed)} dashboard(s) failed to import")

                rich_print_checked_statement("Dashboard import completed", "success")
                success_count += 1
            except Exception as e:
                rich_print_checked_statement(f"Dashboard import failed: {e}", "error")
                if not continue_on_error:
                    return
        elif is_template_mode and skip_dashboard_import:
            rich_print_checked_statement(
                "Skipping dashboard import (--skip-dashboard-import)", "info"
            )
            success_count += 1
        elif is_template_mode and not template_dashboard_paths:
            rich_print_checked_statement("No dashboards defined in template", "info")
            success_count += 1

        # Final summary
        rich_print_section_separator("Depictio-CLI Run Summary")
        if is_template_mode:
            rich_print_checked_statement(f"Template used: {template}", "info")
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
