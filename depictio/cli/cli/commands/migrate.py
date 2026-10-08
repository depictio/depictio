"""
depictio migrate: project-scoped cross-instance migration

Exports one project from a source instance and upserts it into a target
instance.  Never wipes existing data on the target.

Usage examples:
    # Dry-run first (no changes anywhere)
    depictio migrate --project "my-project" \\
        --server local --to-server ~/.depictio/CLI_remote.yaml --dry-run

    # Full migration (MongoDB docs + S3 files)
    depictio migrate --project "my-project" \\
        --server local --to-server ~/.depictio/CLI_remote.yaml

    # Dashboard-only update, between two servers named by their CLI configurations
    depictio migrate --project "my-project" \\
        --server ~/.depictio/CLI_staging.yaml \\
        --to-server ~/.depictio/CLI_remote.yaml --mode dashboard
"""

from enum import Enum
from typing import Annotated

import httpx
import typer
from rich.markup import escape

from depictio.cli.cli.utils.api_calls import api_export_project, api_import_project, api_login
from depictio.cli.cli.utils.common import (
    cli_config_file,
    describe_api_target,
    env_overrides_ignored,
    load_depictio_config,
    report_login_failure,
    say_local_server_running,
)
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_json,
)
from depictio.cli.cli.utils.server_target import (
    DEFAULT_TARGET_CLI_CONFIG,
    SERVER_HELP,
    LegacyConfigPathOption,
    is_local_cli_config,
    resolve_server,
    resolve_target_server,
)

# A single command: `depictio migrate --project ...`, with no subcommand to name.
app = typer.Typer()


# An Enum, not click.Choice: typer runs its own copy of click, which would not turn a
# click.Choice rejection into a usage error (exit 2) but into a traceback.
class Mode(str, Enum):
    all = "all"
    metadata = "metadata"
    dashboard = "dashboard"
    files = "files"


# How the server words the fix for a conflict: for its API, not for this command.
_SERVER_OVERWRITE_FIX = "Set overwrite=true to replace it."


def _s3_errors_summary(count: int) -> str:
    """The closing line of a migration whose S3 copy failed for ``count`` files or paths."""
    errors = "1 S3 error" if count == 1 else f"{count} S3 errors"
    return (
        f"{errors} above left files out of the target. "
        "Fix the cause, then run this command again with --mode files"
    )


def _is_local_server(config_path: str) -> bool:
    """Whether ``config_path`` reaches the local server: named so, or by default."""
    return is_local_cli_config(cli_config_file(config_path))


def _login_as_admin(config_path: str, role: str, other_is_local: bool = False) -> None:
    """Log in with ``config_path``; exit 1 unless the server takes it for an administrator.

    api_login reports a failed login by returning success False, with no is_admin:
    checked first, so an expired token is not reported as missing admin rights.
    ``other_is_local``: the other server is the local one, so this one cannot be told
    to use it.
    """
    rich_print_checked_statement(f"Authenticating with {role.lower()} instance...", "info")
    try:
        auth = api_login(config_path)
    except httpx.HTTPError as exc:
        rich_print_checked_statement(f"{role}: cannot reach the server: {exc}", "error")
        rich_print_checked_statement(f"Tried {describe_api_target(config_path)}", "info")
        if not other_is_local:
            say_local_server_running(config_path, "--server" if role == "Source" else "--to-server")
        raise typer.Exit(1) from exc
    if not auth.get("success"):
        report_login_failure(config_path, auth, f"{role}: authentication failed")
        raise typer.Exit(1)
    if not auth.get("is_admin"):
        rich_print_checked_statement(f"{role}: admin access required", "error")
        raise typer.Exit(1)
    rich_print_checked_statement(f"{role}: authenticated as admin", "success")


@app.command()
def migrate(
    project: Annotated[str, typer.Option("--project", help="Project name to migrate")],
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            help=f"Server to migrate from. {SERVER_HELP} Formerly `--CLI-config-path`.",
            show_default=False,
        ),
    ] = None,
    CLI_config_path: LegacyConfigPathOption = None,
    to_server: Annotated[
        str | None,
        typer.Option(
            "--to-server",
            help="Server to migrate to, given the same way as --server. "
            f"Default: {DEFAULT_TARGET_CLI_CONFIG}. Formerly `--target-config`.",
            show_default=False,
        ),
    ] = None,
    # The target's option before --to-server. Still accepted, out of the help.
    target_config: Annotated[str | None, typer.Option("--target-config", hidden=True)] = None,
    mode_choice: Annotated[
        Mode,
        typer.Option("--mode", help="Migration scope, described below."),
    ] = Mode.all,
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

    The project is read from --server and written to --to-server.
    DEPICTIO_CLI_TOKEN and DEPICTIO_CLI_API_BASE_URL apply to --server only.

    Mode descriptions:
      all       : MongoDB docs + S3 files  (default, full first-time migration)
      metadata  : MongoDB docs only        (both instances share S3 storage)
      dashboard : Dashboards only          (project already exists on remote)
      files     : S3 files only            (metadata already migrated)
    """
    mode = mode_choice.value
    source_path = resolve_server(server, CLI_config_path)
    target_path = resolve_target_server(to_server, target_config)

    # Load configs --------------------------------------------------------
    # Labelled, and both always announced: even when they are one server, the
    # output says which one each side is.
    # With the local server on one side, "add --server local" said of the other would
    # make both sides one server.
    source_is_local, target_is_local = _is_local_server(source_path), _is_local_server(target_path)
    source_config = load_depictio_config(
        yaml_config_path=source_path, label="Source server", local_hint=not target_is_local
    )
    # The env overrides stand in for the one server a command talks to: here, the
    # source. Applied to the target too, both would point at the same server.
    with env_overrides_ignored():
        remote_config = load_depictio_config(
            yaml_config_path=target_path, option="--to-server", label="Target server"
        )

    _login_as_admin(source_path, "Source", other_is_local=target_is_local)
    with env_overrides_ignored():
        _login_as_admin(target_path, "Target", other_is_local=source_is_local)

    if dry_run:
        rich_print_checked_statement("DRY RUN mode: no data will be written", "info")

    # Build target S3 config for S3 copy.
    # Skip S3 copy when source and target point to the same API instance: the S3 data is
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
            "S3 copy skipped: source and target are the same instance", "info"
        )

    # Step 1: Export from source ------------------------------------------
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
            f"Export failed: {escape(str(bundle.get('message', 'unknown error')))}", "error"
        )
        raise typer.Exit(1)

    meta = bundle.get("migrate_metadata", {})
    doc_counts = meta.get("document_counts", {})
    rich_print_checked_statement(
        f"Export complete: project '{meta.get('project_name')}' (id={meta.get('project_id')})",
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
    # Files the target lacks: the migration is not complete, whatever the import does.
    # A dry run copies nothing, so its errors only warn.
    s3_errors = 0 if dry_run else len(s3_meta.get("errors") or [])

    # For files-only mode there is nothing to import into MongoDB
    if mode == "files":
        if dry_run:
            rich_print_checked_statement(
                "Files-only mode, dry run: no S3 file copied, no MongoDB import.", "success"
            )
        elif s3_errors:
            rich_print_checked_statement(
                f"Files-only mode: {_s3_errors_summary(s3_errors)}", "error"
            )
            raise typer.Exit(1)
        else:
            rich_print_checked_statement(
                "Files-only mode: S3 sync complete, no MongoDB import.", "success"
            )
        raise typer.Exit(0)

    # Step 2: Import into target ------------------------------------------
    rich_print_checked_statement(f"Importing bundle into target instance (mode={mode})...", "info")
    import_result = api_import_project(
        remote_config,
        bundle=bundle,
        dry_run=dry_run,
        overwrite=overwrite,
    )

    if import_result.get("conflict"):
        detail = import_result.get("message", "the project already exists on the target")
        detail = detail.replace(_SERVER_OVERWRITE_FIX, "").strip().rstrip(".")
        rich_print_checked_statement(
            f"Conflict: {detail}. Use --overwrite to replace it.",
            "error",
        )
        raise typer.Exit(1)

    if not import_result.get("success"):
        rich_print_checked_statement(
            f"Import failed: {escape(str(import_result.get('message', 'unknown error')))}", "error"
        )
        raise typer.Exit(1)

    action_label = "Would upsert" if dry_run else "Upserted"
    rich_print_checked_statement(f"{action_label} documents into target instance", "success")
    rich_print_json("Upserted per collection:", import_result.get("upserted", {}))

    if s3_errors:
        rich_print_checked_statement(
            f"Migration incomplete for project '{project}': {_s3_errors_summary(s3_errors)}",
            "error",
        )
        raise typer.Exit(1)
    rich_print_checked_statement(
        f"Migration {'dry run ' if dry_run else ''}complete for project '{project}'",
        "success",
    )
