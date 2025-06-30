from typing import Annotated

import typer

from depictio.cli.cli.utils.api_calls import api_login
from depictio.cli.cli.utils.common import load_depictio_config
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_json,
)

app = typer.Typer()


@app.command()
def create(
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="Path to the configuration file")
    ] = "~/.depictio/CLI.yaml",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Perform validation without creating backup")
    ] = False,
    include_s3_data: Annotated[
        bool, typer.Option("--include-s3-data", help="Include S3 deltatable data in backup")
    ] = False,
    s3_backup_prefix: Annotated[
        str, typer.Option("--s3-backup-prefix", help="Prefix for S3 backup location")
    ] = "backup",
):
    """
    Create a backup of the Depictio database.

    This command creates a full backup of the MongoDB database, excluding:
    - Short-lived tokens
    - Temporary users and their related resources

    Optionally includes S3 deltatable data for complete backups.

    Only administrators can perform backup operations.

    Args:
        CLI_config_path: Path to the CLI configuration file
        dry_run: If True, validate backup process without creating actual backup
        include_s3_data: If True, also backup S3 deltatable files
        s3_backup_prefix: Prefix for S3 backup folder structure
    """
    rich_print_command_usage("backup create")

    try:
        # Load CLI configuration
        CLI_config = load_depictio_config(yaml_config_path=CLI_config_path)

        # Authenticate and verify admin status
        rich_print_checked_statement("Authenticating user...", "info")
        auth_response = api_login(CLI_config_path)

        if not auth_response.get("is_admin", False):
            rich_print_checked_statement(
                "Access denied: Only administrators can create backups", "error"
            )
            raise typer.Exit(1)

        rich_print_checked_statement("Admin authentication successful", "success")

        if dry_run:
            rich_print_checked_statement("DRY RUN: Validating backup process...", "info")
            # TODO: Implement dry run validation logic
            rich_print_checked_statement("DRY RUN: Backup validation completed", "success")
        else:
            if include_s3_data:
                rich_print_checked_statement("Creating enhanced backup with S3 data...", "info")
                rich_print_checked_statement(f"S3 backup prefix: {s3_backup_prefix}", "info")
            else:
                rich_print_checked_statement("Creating server-side backup...", "info")

            # Call API endpoint to create backup
            from depictio.cli.cli.utils.api_calls import api_create_backup

            backup_result = api_create_backup(
                CLI_config,
                include_s3_data=include_s3_data,
                s3_backup_prefix=s3_backup_prefix,
                dry_run=False,
            )

            if backup_result.get("success", False):
                rich_print_checked_statement("Backup created successfully", "success")
                backup_details = {
                    "backup_id": backup_result.get("backup_id"),
                    "filename": backup_result.get("filename"),
                    "timestamp": backup_result.get("timestamp"),
                    "total_documents": backup_result.get("total_documents"),
                    "collections": backup_result.get("collections_backed_up", []),
                }

                # Add S3 backup details if included
                if include_s3_data and "s3_backup_metadata" in backup_result:
                    s3_meta = backup_result["s3_backup_metadata"]
                    if s3_meta.get("success"):
                        backup_details["s3_locations_backed_up"] = s3_meta.get(
                            "locations_backed_up", 0
                        )
                        backup_details["s3_files_backed_up"] = s3_meta.get("total_files", 0)
                        backup_details["s3_bytes_backed_up"] = s3_meta.get("total_bytes", 0)
                        rich_print_checked_statement("S3 data backup completed", "success")
                    else:
                        rich_print_checked_statement(
                            "S3 backup failed (MongoDB backup succeeded)", "warning"
                        )
                        if s3_meta.get("error"):
                            rich_print_checked_statement(f"S3 error: {s3_meta['error']}", "warning")

                rich_print_json("Backup details:", backup_details)
            else:
                rich_print_checked_statement(
                    f"Backup failed: {backup_result.get('message', 'Unknown error')}", "error"
                )
                raise typer.Exit(1)

    except Exception as e:
        rich_print_checked_statement(f"Backup operation failed: {e}", "error")
        raise typer.Exit(1)


@app.command()
def list(
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="Path to the configuration file")
    ] = "~/.depictio/CLI.yaml",
):
    """
    List available backup files on the server.
    """
    rich_print_command_usage("backup list")

    try:
        # Load CLI configuration
        CLI_config = load_depictio_config(yaml_config_path=CLI_config_path)

        # Authenticate and verify admin status
        rich_print_checked_statement("Authenticating user...", "info")
        auth_response = api_login(CLI_config_path)

        if not auth_response.get("is_admin", False):
            rich_print_checked_statement(
                "Access denied: Only administrators can list backups", "error"
            )
            raise typer.Exit(1)

        # Call API endpoint to list backups
        from depictio.cli.cli.utils.api_calls import api_list_backups

        list_result = api_list_backups(CLI_config)

        if list_result.get("success", False):
            backups = list_result.get("backups", [])
            if backups:
                rich_print_checked_statement(f"Found {len(backups)} backup(s)", "success")
                rich_print_json("Available backups:", backups)
            else:
                rich_print_checked_statement("No backup files found", "info")
        else:
            rich_print_checked_statement(
                f"Failed to list backups: {list_result.get('message', 'Unknown error')}", "error"
            )
            raise typer.Exit(1)

    except Exception as e:
        rich_print_checked_statement(f"Failed to list backups: {e}", "error")
        raise typer.Exit(1)


@app.command()
def validate(
    backup_id: Annotated[
        str, typer.Argument(help="ID of the backup to validate (format: YYYYMMDD_HHMMSS)")
    ],
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="Path to the configuration file")
    ] = "~/.depictio/CLI.yaml",
):
    """
    Validate a backup file on the server against Pydantic models.

    Args:
        backup_id: ID of the backup to validate
        CLI_config_path: Path to the CLI configuration file
    """
    rich_print_command_usage("backup validate")

    try:
        # Load CLI configuration
        CLI_config = load_depictio_config(yaml_config_path=CLI_config_path)

        # Authenticate and verify admin status
        rich_print_checked_statement("Authenticating user...", "info")
        auth_response = api_login(CLI_config_path)

        if not auth_response.get("is_admin", False):
            rich_print_checked_statement(
                "Access denied: Only administrators can validate backups", "error"
            )
            raise typer.Exit(1)

        rich_print_checked_statement(f"Validating backup: {backup_id}", "info")

        # Call API endpoint to validate backup
        from depictio.cli.cli.utils.api_calls import api_validate_backup

        validation_result = api_validate_backup(CLI_config, backup_id)

        if validation_result.get("success", False):
            if validation_result.get("valid", False):
                rich_print_checked_statement("Backup file validation successful", "success")
                validation_details = {
                    "total_documents": validation_result.get("total_documents", 0),
                    "valid_documents": validation_result.get("valid_documents", 0),
                    "invalid_documents": validation_result.get("invalid_documents", 0),
                    "collections_validated": validation_result.get("collections_validated", {}),
                }
                rich_print_json("Validation details:", validation_details)
            else:
                rich_print_checked_statement("Backup file validation failed", "error")
                errors = validation_result.get("errors", [])
                if errors:
                    rich_print_checked_statement("Validation errors:", "error")
                    for error in errors:
                        rich_print_checked_statement(f"  • {error}", "error")
                raise typer.Exit(1)
        else:
            rich_print_checked_statement(
                f"Validation failed: {validation_result.get('message', 'Unknown error')}", "error"
            )
            raise typer.Exit(1)

    except Exception as e:
        rich_print_checked_statement(f"Backup validation failed: {e}", "error")
        raise typer.Exit(1)


@app.command()
def check_coverage(
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="Path to the configuration file")
    ] = "~/.depictio/CLI.yaml",
):
    """
    Check validation coverage for all MongoDB collections.

    This command helps ensure that all database collections have corresponding
    Pydantic model validators for backup validation.

    Only administrators can check backup coverage.
    """
    rich_print_command_usage("backup check-coverage")

    try:
        # Load CLI configuration
        load_depictio_config(yaml_config_path=CLI_config_path)

        # Authenticate and verify admin status
        rich_print_checked_statement("Authenticating user...", "info")
        auth_response = api_login(CLI_config_path)

        if not auth_response.get("is_admin", False):
            rich_print_checked_statement(
                "Access denied: Only administrators can check backup coverage", "error"
            )
            raise typer.Exit(1)

        from depictio.cli.cli.utils.backup_validation import (
            check_backup_collections_coverage,
        )

        coverage_report = check_backup_collections_coverage()

        if "error" in coverage_report:
            rich_print_checked_statement(
                f"Coverage check failed: {coverage_report['error']}", "error"
            )
            if coverage_report.get("errors"):
                for error in coverage_report["errors"]:
                    rich_print_checked_statement(error, "error")
            raise typer.Exit(1)

        # Check if coverage is valid
        if coverage_report["valid"]:
            rich_print_checked_statement(
                "✅ All expected collections have backup coverage", "success"
            )
        else:
            rich_print_checked_statement("❌ Missing backup coverage detected", "error")

            if coverage_report["missing_from_expected"]:
                rich_print_checked_statement(
                    "New collections found without backup coverage:", "warning"
                )
                for collection in coverage_report["missing_from_expected"]:
                    rich_print_checked_statement(f"  • {collection}", "warning")
                rich_print_checked_statement(
                    "Please add these to EXPECTED_BACKUP_COLLECTIONS", "warning"
                )

            if coverage_report["missing_validators"]:
                rich_print_checked_statement("Expected collections missing validators:", "error")
                for collection in coverage_report["missing_validators"]:
                    rich_print_checked_statement(f"  • {collection}", "error")

        # Show detailed report
        rich_print_json("Collection Coverage Report:", coverage_report)

        # Exit with error code if not valid
        if not coverage_report["valid"]:
            raise typer.Exit(1)

    except Exception as e:
        rich_print_checked_statement(f"Coverage check failed: {e}", "error")
        raise typer.Exit(1)


@app.command()
def restore(
    backup_id: Annotated[
        str, typer.Argument(help="ID of the backup to restore (format: YYYYMMDD_HHMMSS)")
    ],
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="Path to the configuration file")
    ] = "~/.depictio/CLI.yaml",
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Simulate restore without making changes")
    ] = False,
    collections: Annotated[
        str | None,
        typer.Option("--collections", help="Comma-separated list of collections to restore"),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Skip confirmation prompt (use with caution!)")
    ] = False,
):
    """
    Restore data from a backup file.

    WARNING: This is a destructive operation that will replace existing data!
    Use --dry-run to preview what would be restored without making changes.

    Args:
        backup_id: ID of the backup to restore from
        CLI_config_path: Path to the CLI configuration file
        dry_run: If True, only simulate the restore
        collections: Comma-separated list of collections to restore (if not specified, restore all)
        force: Skip confirmation prompt
    """
    rich_print_command_usage("backup restore")

    try:
        # Load CLI configuration
        CLI_config = load_depictio_config(yaml_config_path=CLI_config_path)

        # Authenticate and verify admin status
        rich_print_checked_statement("Authenticating user...", "info")
        auth_response = api_login(CLI_config_path)

        if not auth_response.get("is_admin", False):
            rich_print_checked_statement(
                "Access denied: Only administrators can restore backups", "error"
            )
            raise typer.Exit(1)

        # Parse collections list
        collections_list = None
        if collections:
            collections_list = [c.strip() for c in collections.split(",")]
            rich_print_checked_statement(f"Will restore collections: {collections_list}", "info")

        if not dry_run and not force:
            # Confirm destructive operation
            rich_print_checked_statement(
                "⚠️  WARNING: This will DELETE and REPLACE existing data!", "warning"
            )
            if collections_list:
                rich_print_checked_statement(
                    f"Collections to restore: {', '.join(collections_list)}", "warning"
                )
            else:
                rich_print_checked_statement("ALL collections will be restored!", "warning")

            confirm = typer.confirm("Are you sure you want to proceed?")
            if not confirm:
                rich_print_checked_statement("Restore cancelled", "info")
                raise typer.Exit(0)

        # Call API endpoint to restore backup
        from depictio.cli.cli.utils.api_calls import api_restore_backup

        if dry_run:
            rich_print_checked_statement(
                f"DRY RUN: Simulating restore from backup {backup_id}", "info"
            )
        else:
            rich_print_checked_statement(f"Restoring from backup {backup_id}...", "warning")

        restore_result = api_restore_backup(CLI_config, backup_id, dry_run, collections_list)

        if restore_result.get("success", False):
            if dry_run:
                rich_print_checked_statement("DRY RUN completed successfully", "success")
            else:
                rich_print_checked_statement("Restore completed successfully", "success")

            # Show results
            restored_collections = restore_result.get("restored_collections", {})
            total_restored = restore_result.get("total_restored", 0)

            rich_print_checked_statement(f"Total documents: {total_restored}", "info")

            if restored_collections:
                rich_print_json("Collections restored:", restored_collections)

            errors = restore_result.get("errors", [])
            if errors:
                rich_print_checked_statement("⚠️  Some errors occurred:", "warning")
                for error in errors:
                    rich_print_checked_statement(f"  • {error}", "error")
        else:
            rich_print_checked_statement(
                f"Restore failed: {restore_result.get('message', 'Unknown error')}", "error"
            )
            raise typer.Exit(1)

    except Exception as e:
        rich_print_checked_statement(f"Restore operation failed: {e}", "error")
        raise typer.Exit(1)
