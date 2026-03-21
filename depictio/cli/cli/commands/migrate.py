"""
depictio migrate — project-scoped cross-instance migration

Exports one project from a source instance and upserts it into a target
instance.  Never wipes existing data on the target.

Usage examples:
    # Dry-run first (no changes anywhere)
    depictio migrate --project "my-project" \\
        --CLI-config-path ~/.depictio/CLI_local.yaml \\
        --target-config ~/.depictio/CLI_remote.yaml --dry-run

    # Full migration (MongoDB docs + S3 files)
    depictio migrate --project "my-project" \\
        --CLI-config-path ~/.depictio/CLI_local.yaml \\
        --target-config ~/.depictio/CLI_remote.yaml

    # Dashboard-only update
    depictio migrate --project "my-project" \\
        --CLI-config-path ~/.depictio/CLI_local.yaml \\
        --target-config ~/.depictio/CLI_remote.yaml --mode dashboard
"""

from typing import Annotated

import typer

from depictio.cli.cli.utils.api_calls import api_export_project, api_import_project, api_login
from depictio.cli.cli.utils.common import load_depictio_config
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_json,
)

app = typer.Typer()

_MODES = ["all", "metadata", "dashboard", "files"]


@app.command()
def migrate(
    project: Annotated[str, typer.Option("--project", help="Project name to migrate")],
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="Source CLI config (local instance)")
    ] = "~/.depictio/CLI.yaml",
    target_config: Annotated[
        str, typer.Option("--target-config", help="Target CLI config (remote instance)")
    ] = "~/.depictio/CLI_remote.yaml",
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Migration scope: all | metadata | dashboard | files",
        ),
    ] = "all",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview changes without writing anything")
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            help="Replace the project on the target if it already exists",
        ),
    ] = False,
):
    """
    Migrate a project from one Depictio instance to another (non-destructive).

    Mode descriptions:
      all       – MongoDB docs + S3 files  (default, full first-time migration)
      metadata  – MongoDB docs only        (both instances share S3 storage)
      dashboard – Dashboards only          (project already exists on remote)
      files     – S3 files only            (metadata already migrated)
    """
    if mode not in _MODES:
        rich_print_checked_statement(
            f"Invalid mode '{mode}'. Choose from: {', '.join(_MODES)}", "error"
        )
        raise typer.Exit(1)

    # Load configs --------------------------------------------------------
    source_config = load_depictio_config(yaml_config_path=CLI_config_path)
    remote_config = load_depictio_config(yaml_config_path=target_config)

    # Authenticate source
    rich_print_checked_statement("Authenticating with source instance...", "info")
    auth_source = api_login(CLI_config_path)
    if not auth_source.get("is_admin"):
        rich_print_checked_statement("Source: admin access required", "error")
        raise typer.Exit(1)
    rich_print_checked_statement("Source: authenticated as admin", "success")

    # Authenticate target
    rich_print_checked_statement("Authenticating with target instance...", "info")
    auth_target = api_login(target_config)
    if not auth_target.get("is_admin"):
        rich_print_checked_statement("Target: admin access required", "error")
        raise typer.Exit(1)
    rich_print_checked_statement("Target: authenticated as admin", "success")

    if dry_run:
        rich_print_checked_statement("DRY RUN mode — no data will be written", "info")

    # Build target S3 config for S3 copy.
    # Skip S3 copy when source and target point to the same API instance — the S3 data is
    # already there and the external endpoint URL sent by the CLI would be unreachable from
    # inside the backend container (e.g. localhost:9000 vs minio:9000 in Docker).
    target_s3_config: dict | None = None
    same_instance = source_config.api_base_url == remote_config.api_base_url
    if mode in ("all", "files") and not same_instance:
        s3 = remote_config.s3_storage
        target_s3_config = {
            "endpoint_url": s3.endpoint_url,
            "aws_access_key_id": s3.aws_access_key_id,
            "aws_secret_access_key": s3.aws_secret_access_key,
            "bucket": s3.bucket,
            "region_name": "us-east-1",
        }
        rich_print_checked_statement(
            f"S3 target: {target_s3_config['endpoint_url']} / {target_s3_config['bucket']}", "info"
        )
    elif mode in ("all", "files") and same_instance:
        rich_print_checked_statement(
            "S3 copy skipped — source and target are the same instance", "info"
        )

    # Step 1 – Export from source -----------------------------------------
    rich_print_checked_statement(
        f"Exporting project '{project}' (mode={mode}) from source...", "info"
    )
    bundle = api_export_project(
        source_config,
        project_name=project,
        mode=mode,
        target_s3_config=target_s3_config,
        dry_run=dry_run,
    )

    if "success" in bundle and not bundle["success"]:
        rich_print_checked_statement(
            f"Export failed: {bundle.get('message', 'unknown error')}", "error"
        )
        raise typer.Exit(1)

    meta = bundle.get("migrate_metadata", {})
    doc_counts = meta.get("document_counts", {})
    rich_print_checked_statement(
        f"Export complete — project '{meta.get('project_name')}' (id={meta.get('project_id')})",
        "success",
    )
    if doc_counts:
        rich_print_json("Document counts:", doc_counts)

    s3_meta = bundle.get("s3_migrate_metadata", {})
    if s3_meta:
        action = "Would copy" if dry_run else "Copied"
        rich_print_checked_statement(
            f"S3: {action} {s3_meta.get('total_files', 0)} files "
            f"({s3_meta.get('total_bytes', 0)} bytes) "
            f"from {len(s3_meta.get('paths', []))} locations",
            "success" if not s3_meta.get("errors") else "warning",
        )
        if s3_meta.get("errors"):
            for err in s3_meta["errors"]:
                rich_print_checked_statement(f"  S3 error: {err}", "warning")

    # For files-only mode there is nothing to import into MongoDB
    if mode == "files":
        rich_print_checked_statement(
            "Files-only mode: S3 sync complete, no MongoDB import.", "success"
        )
        raise typer.Exit(0)

    # Step 2 – Import into target -----------------------------------------
    rich_print_checked_statement(f"Importing bundle into target instance (mode={mode})...", "info")
    import_result = api_import_project(
        remote_config,
        bundle=bundle,
        dry_run=dry_run,
        overwrite=overwrite,
    )

    if import_result.get("conflict"):
        rich_print_checked_statement(
            f"Conflict: {import_result.get('message', 'project already exists')}. "
            "Use --overwrite to replace it.",
            "error",
        )
        raise typer.Exit(1)

    if not import_result.get("success"):
        rich_print_checked_statement(
            f"Import failed: {import_result.get('message', 'unknown error')}", "error"
        )
        raise typer.Exit(1)

    action_label = "Would upsert" if dry_run else "Upserted"
    rich_print_checked_statement(f"{action_label} documents into target instance", "success")
    rich_print_json("Upserted per collection:", import_result.get("upserted", {}))

    rich_print_checked_statement(
        f"Migration {'dry-run' if dry_run else ''} complete for project '{project}'",
        "success",
    )
