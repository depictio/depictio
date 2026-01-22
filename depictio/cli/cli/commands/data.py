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


@app.command()
def join(
    CLI_config_path: Annotated[
        str,
        typer.Option("--CLI-config-path", help="Path to the CLI configuration file"),
    ] = "~/.depictio/CLI.yaml",
    project_config_path: Annotated[
        str,
        typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
    ] = "",
    join_name: Annotated[
        str | None,
        typer.Option(
            "--join-name",
            "-j",
            help="Name of a specific join to process (processes all if not specified)",
        ),
    ] = None,
    preview: bool = typer.Option(
        False, "--preview", "-p", help="Preview join results without persisting"
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing joined tables"),
    no_auto_process: bool = typer.Option(
        False, "--no-auto-process", help="Don't auto-process missing source data collections"
    ),
    rich_tables: bool = typer.Option(
        False, "--rich-tables", help="Display rich tables in the output"
    ),
):
    """
    Execute table joins defined in the project configuration.

    This command processes the top-level 'joins' configuration in your project YAML,
    joining data collections on the client side and optionally persisting the results
    as Delta tables.

    Examples:
        # Preview all joins without persisting
        depictio data join --project-config-path project.yaml --preview

        # Execute a specific join
        depictio data join --project-config-path project.yaml --join-name my_join

        # Execute all joins and overwrite existing
        depictio data join --project-config-path project.yaml --overwrite
    """
    from depictio.cli.cli.utils.joins import process_project_joins

    rich_print_command_usage("join")

    # Validate configurations and prepare headers
    CLI_config, response = validate_project_config_and_check_S3_storage(
        CLI_config_path=CLI_config_path, project_config_path=project_config_path
    )

    if not response["success"]:
        rich_print_checked_statement("Depictio Project configuration validation failed", "error")
        raise typer.Exit(code=1)

    rich_print_checked_statement("Depictio Project configuration validated", "success")

    # Get the validated project configuration
    project_config = response["project_config"]

    # Check if project has any joins defined
    if not project_config.joins:
        rich_print_checked_statement(
            "No joins defined in project configuration. Add a 'joins:' section to your YAML.",
            "warning",
        )
        raise typer.Exit(code=0)

    # Get remote project configuration
    remote_project_config = api_get_project_from_name(str(project_config.name), CLI_config)

    if remote_project_config.status_code != 200:
        rich_print_checked_statement(
            "Error fetching remote project configuration. Please create the project first.",
            "error",
        )
        raise typer.Exit(code=1)

    logger.info("Remote project configuration fetched successfully.")
    rich_print_checked_statement("Remote project configuration fetched successfully.", "success")

    # Compare hashes
    local_hash = project_config.hash
    remote_hash = remote_project_config.json().get("hash", None)
    logger.info(f"Local & Remote hashes: {local_hash} & {remote_hash}")

    if local_hash != remote_hash:
        rich_print_checked_statement(
            "Local and remote project configurations do not match. "
            "Please sync your project configuration first.",
            "error",
        )
        raise typer.Exit(code=1)

    rich_print_checked_statement("Local and remote project configurations match.", "success")

    rich_print_section_separator("Processing Table Joins")

    # List available joins
    from depictio.cli.cli.utils.rich_utils import console

    console.print("\n[bold]Available joins in project:[/bold]")
    for j in project_config.joins:
        persist_status = "[green]persist[/green]" if j.persist else "[dim]preview only[/dim]"
        console.print(f"  - {j.name}: {j.left_dc} + {j.right_dc} ({persist_status})")

    # Process joins
    result = process_project_joins(
        project=project_config,
        CLI_config=CLI_config,
        join_name=join_name,
        preview_only=preview,
        overwrite=overwrite,
        auto_process_dependencies=not no_auto_process,
    )

    # Print summary
    rich_print_section_separator("Join Processing Summary")

    if result.get("processed"):
        console.print(
            f"\n[green]Successfully processed: {len(result['processed'])} join(s)[/green]"
        )
        for item in result["processed"]:
            mode = item.get("mode", "unknown")
            rows = item.get("rows", 0)
            console.print(f"  - {item['join']}: {rows} rows ({mode})")

    if result.get("skipped"):
        console.print(f"\n[yellow]Skipped: {len(result['skipped'])} join(s)[/yellow]")
        for item in result["skipped"]:
            console.print(f"  - {item['join']}: {item.get('reason', 'unknown')}")

    if result.get("errors"):
        console.print(f"\n[red]Errors: {len(result['errors'])} join(s)[/red]")
        for item in result["errors"]:
            for error in item.get("errors", []):
                console.print(f"  - {item['join']}: {error}")
        raise typer.Exit(code=1)

    rich_print_checked_statement("Join processing complete", "success")


# Link subcommands
link_app = typer.Typer(help="Manage DC links for cross-DC filtering")
app.add_typer(link_app, name="link")


@link_app.command("list")
def link_list(
    CLI_config_path: Annotated[
        str,
        typer.Option("--CLI-config-path", help="Path to the CLI configuration file"),
    ] = "~/.depictio/CLI.yaml",
    project_config_path: Annotated[
        str,
        typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
    ] = "",
    target_dc: Annotated[
        str | None,
        typer.Option("--target-dc", help="Filter links by target DC ID"),
    ] = None,
    source_dc: Annotated[
        str | None,
        typer.Option("--source-dc", help="Filter links by source DC ID"),
    ] = None,
):
    """
    List all DC links for a project.

    Examples:
        # List all links in a project
        depictio data link list --project-config-path project.yaml

        # List links targeting a specific DC
        depictio data link list --project-config-path project.yaml --target-dc multiqc_dc_id
    """
    from depictio.cli.cli.utils.links import (
        api_get_links_for_source_dc,
        api_get_links_for_target_dc,
        api_get_project_links,
        format_link_for_display,
    )
    from depictio.cli.cli.utils.rich_utils import console

    rich_print_command_usage("link list")

    # Validate configurations
    CLI_config, response = validate_project_config_and_check_S3_storage(
        CLI_config_path=CLI_config_path, project_config_path=project_config_path
    )

    if not response["success"]:
        rich_print_checked_statement("Depictio Project configuration validation failed", "error")
        raise typer.Exit(code=1)

    project_config = response["project_config"]
    project_id = str(project_config.id)

    # Fetch links based on filters
    if target_dc:
        api_response = api_get_links_for_target_dc(project_id, target_dc, CLI_config)
    elif source_dc:
        api_response = api_get_links_for_source_dc(project_id, source_dc, CLI_config)
    else:
        api_response = api_get_project_links(project_id, CLI_config)

    if api_response.status_code != 200:
        rich_print_checked_statement(f"Failed to fetch links: {api_response.text}", "error")
        raise typer.Exit(code=1)

    links = api_response.json()

    if not links:
        console.print("\n[yellow]No links found for this project.[/yellow]")
        console.print("Use [bold]depictio data link create[/bold] to create a link between DCs.")
        raise typer.Exit(code=0)

    # Display links
    console.print(f"\n[bold]DC Links for project '{project_config.name}':[/bold]\n")

    from rich.table import Table

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=24)
    table.add_column("Source DC")
    table.add_column("Source Column")
    table.add_column("Target DC")
    table.add_column("Target Type")
    table.add_column("Resolver")
    table.add_column("Enabled")

    for link in links:
        formatted = format_link_for_display(link)
        table.add_row(
            formatted["id"][:24],
            formatted["source_dc_id"][:20],
            formatted["source_column"],
            formatted["target_dc_id"][:20],
            formatted["target_type"],
            formatted["resolver"],
            "✓" if formatted["enabled"] else "✗",
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(links)} link(s)[/dim]")


@link_app.command("create")
def link_create(
    CLI_config_path: Annotated[
        str,
        typer.Option("--CLI-config-path", help="Path to the CLI configuration file"),
    ] = "~/.depictio/CLI.yaml",
    project_config_path: Annotated[
        str,
        typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
    ] = "",
    source_dc: Annotated[
        str,
        typer.Option("--source-dc", help="Source data collection ID"),
    ] = "",
    source_column: Annotated[
        str,
        typer.Option("--source-column", help="Column in source DC to link from"),
    ] = "",
    target_dc: Annotated[
        str,
        typer.Option("--target-dc", help="Target data collection ID"),
    ] = "",
    target_type: Annotated[
        str,
        typer.Option("--target-type", help="Target DC type (table, multiqc)"),
    ] = "table",
    resolver: Annotated[
        str,
        typer.Option(
            "--resolver",
            help="Resolver type (direct, sample_mapping, pattern, regex, wildcard)",
        ),
    ] = "direct",
    description: Annotated[
        str | None,
        typer.Option("--description", help="Optional description for the link"),
    ] = None,
):
    """
    Create a new DC link for cross-DC filtering.

    Examples:
        # Create a direct link between two table DCs
        depictio data link create \\
            --project-config-path project.yaml \\
            --source-dc metadata_table \\
            --source-column sample_id \\
            --target-dc variants_table \\
            --target-type table \\
            --resolver direct

        # Create a sample_mapping link to a MultiQC DC
        depictio data link create \\
            --project-config-path project.yaml \\
            --source-dc metadata_table \\
            --source-column sample_id \\
            --target-dc multiqc_general_stats \\
            --target-type multiqc \\
            --resolver sample_mapping
    """
    from depictio.cli.cli.utils.links import api_create_link
    from depictio.cli.cli.utils.rich_utils import console

    rich_print_command_usage("link create")

    # Validate required options
    if not source_dc or not source_column or not target_dc:
        rich_print_checked_statement(
            "Missing required options: --source-dc, --source-column, --target-dc", "error"
        )
        raise typer.Exit(code=1)

    # Validate target_type
    valid_target_types = ["table", "multiqc"]
    if target_type not in valid_target_types:
        rich_print_checked_statement(
            f"Invalid target type: {target_type}. Valid types: {valid_target_types}", "error"
        )
        raise typer.Exit(code=1)

    # Validate resolver
    valid_resolvers = ["direct", "sample_mapping", "pattern", "regex", "wildcard"]
    if resolver not in valid_resolvers:
        rich_print_checked_statement(
            f"Invalid resolver: {resolver}. Valid resolvers: {valid_resolvers}", "error"
        )
        raise typer.Exit(code=1)

    # Validate configurations
    CLI_config, response = validate_project_config_and_check_S3_storage(
        CLI_config_path=CLI_config_path, project_config_path=project_config_path
    )

    if not response["success"]:
        rich_print_checked_statement("Depictio Project configuration validation failed", "error")
        raise typer.Exit(code=1)

    project_config = response["project_config"]
    project_id = str(project_config.id)

    # Build link data
    link_data = {
        "source_dc_id": source_dc,
        "source_column": source_column,
        "target_dc_id": target_dc,
        "target_type": target_type,
        "link_config": {
            "resolver": resolver,
        },
        "enabled": True,
    }

    if description:
        link_data["description"] = description

    console.print("\n[bold]Creating link:[/bold]")
    console.print(f"  Source DC: {source_dc}")
    console.print(f"  Source Column: {source_column}")
    console.print(f"  Target DC: {target_dc}")
    console.print(f"  Target Type: {target_type}")
    console.print(f"  Resolver: {resolver}")

    # Create the link
    api_response = api_create_link(project_id, link_data, CLI_config)

    if api_response.status_code == 201:
        result = api_response.json()
        rich_print_checked_statement(
            f"Link created successfully! ID: {result.get('id', 'N/A')}", "success"
        )
    else:
        rich_print_checked_statement(f"Failed to create link: {api_response.text}", "error")
        raise typer.Exit(code=1)


@link_app.command("resolve")
def link_resolve(
    CLI_config_path: Annotated[
        str,
        typer.Option("--CLI-config-path", help="Path to the CLI configuration file"),
    ] = "~/.depictio/CLI.yaml",
    project_config_path: Annotated[
        str,
        typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
    ] = "",
    source_dc: Annotated[
        str,
        typer.Option("--source-dc", help="Source data collection ID"),
    ] = "",
    source_column: Annotated[
        str,
        typer.Option("--source-column", help="Column in source DC to filter on"),
    ] = "",
    target_dc: Annotated[
        str,
        typer.Option("--target-dc", help="Target data collection ID"),
    ] = "",
    filter_values: Annotated[
        str,
        typer.Option("--filter", help="Comma-separated values to resolve (e.g., 'S1,S2,S3')"),
    ] = "",
):
    """
    Test link resolution by resolving filter values from source to target DC.

    This command tests the link resolution API by mapping source values
    to target identifiers using the configured resolver.

    Examples:
        # Resolve sample IDs to MultiQC sample names
        depictio data link resolve \\
            --project-config-path project.yaml \\
            --source-dc metadata_table \\
            --source-column sample_id \\
            --target-dc multiqc_general_stats \\
            --filter "S1,S2,S3"
    """
    from depictio.cli.cli.utils.links import api_resolve_link
    from depictio.cli.cli.utils.rich_utils import console

    rich_print_command_usage("link resolve")

    # Validate required options
    if not source_dc or not source_column or not target_dc or not filter_values:
        rich_print_checked_statement(
            "Missing required options: --source-dc, --source-column, --target-dc, --filter",
            "error",
        )
        raise typer.Exit(code=1)

    # Parse filter values
    values_list = [v.strip() for v in filter_values.split(",") if v.strip()]

    if not values_list:
        rich_print_checked_statement("No valid filter values provided", "error")
        raise typer.Exit(code=1)

    # Validate configurations
    CLI_config, response = validate_project_config_and_check_S3_storage(
        CLI_config_path=CLI_config_path, project_config_path=project_config_path
    )

    if not response["success"]:
        rich_print_checked_statement("Depictio Project configuration validation failed", "error")
        raise typer.Exit(code=1)

    project_config = response["project_config"]
    project_id = str(project_config.id)

    console.print("\n[bold]Resolving link:[/bold]")
    console.print(f"  Source DC: {source_dc}")
    console.print(f"  Source Column: {source_column}")
    console.print(f"  Target DC: {target_dc}")
    console.print(f"  Filter Values: {values_list}")

    # Resolve the link
    api_response = api_resolve_link(
        project_id, source_dc, source_column, values_list, target_dc, CLI_config
    )

    if api_response.status_code == 200:
        result = api_response.json()
        console.print("\n[bold green]Resolution successful![/bold green]")
        console.print(f"  Link ID: {result.get('link_id', 'N/A')}")
        console.print(f"  Resolver Used: {result.get('resolver_used', 'N/A')}")
        console.print(f"  Target Type: {result.get('target_type', 'N/A')}")
        console.print(f"  Match Count: {result.get('match_count', 0)}")

        resolved = result.get("resolved_values", [])
        unmapped = result.get("unmapped_values", [])

        if resolved:
            console.print(f"\n[bold]Resolved Values ({len(resolved)}):[/bold]")
            for v in resolved[:20]:  # Limit display
                console.print(f"    - {v}")
            if len(resolved) > 20:
                console.print(f"    ... and {len(resolved) - 20} more")

        if unmapped:
            console.print(f"\n[yellow]Unmapped Values ({len(unmapped)}):[/yellow]")
            for v in unmapped:
                console.print(f"    - {v}")

        rich_print_checked_statement("Link resolution test complete", "success")
    elif api_response.status_code == 404:
        rich_print_checked_statement(
            f"No link found between {source_dc} and {target_dc}. "
            "Create a link first using 'depictio data link create'.",
            "error",
        )
        raise typer.Exit(code=1)
    else:
        rich_print_checked_statement(f"Link resolution failed: {api_response.text}", "error")
        raise typer.Exit(code=1)


@link_app.command("delete")
def link_delete(
    CLI_config_path: Annotated[
        str,
        typer.Option("--CLI-config-path", help="Path to the CLI configuration file"),
    ] = "~/.depictio/CLI.yaml",
    project_config_path: Annotated[
        str,
        typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
    ] = "",
    link_id: Annotated[
        str,
        typer.Option("--link-id", help="ID of the link to delete"),
    ] = "",
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt"),
    ] = False,
):
    """
    Delete a DC link.

    Examples:
        # Delete a link with confirmation
        depictio data link delete --project-config-path project.yaml --link-id abc123

        # Delete without confirmation
        depictio data link delete --project-config-path project.yaml --link-id abc123 --force
    """
    from depictio.cli.cli.utils.links import api_delete_link
    from depictio.cli.cli.utils.rich_utils import console

    rich_print_command_usage("link delete")

    # Validate required options
    if not link_id:
        rich_print_checked_statement("Missing required option: --link-id", "error")
        raise typer.Exit(code=1)

    # Validate configurations
    CLI_config, response = validate_project_config_and_check_S3_storage(
        CLI_config_path=CLI_config_path, project_config_path=project_config_path
    )

    if not response["success"]:
        rich_print_checked_statement("Depictio Project configuration validation failed", "error")
        raise typer.Exit(code=1)

    project_config = response["project_config"]
    project_id = str(project_config.id)

    # Confirm deletion
    if not force:
        console.print(f"\n[yellow]Warning: You are about to delete link ID: {link_id}[/yellow]")
        confirm = typer.confirm("Are you sure you want to delete this link?")
        if not confirm:
            console.print("[dim]Deletion cancelled.[/dim]")
            raise typer.Exit(code=0)

    # Delete the link
    api_response = api_delete_link(project_id, link_id, CLI_config)

    if api_response.status_code == 204:
        rich_print_checked_statement(f"Link {link_id} deleted successfully", "success")
    elif api_response.status_code == 404:
        rich_print_checked_statement(f"Link {link_id} not found", "error")
        raise typer.Exit(code=1)
    else:
        rich_print_checked_statement(f"Failed to delete link: {api_response.text}", "error")
        raise typer.Exit(code=1)
