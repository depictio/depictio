from pathlib import Path
from typing import Annotated

import typer

from depictio.cli.cli.utils.api_calls import (
    api_create_magic_link,
    api_get_project_from_name,
    api_login,
    api_monitoring_ingestion_finish,
    api_monitoring_ingestion_start,
    api_monitoring_ingestion_step,
    api_provision_user,
    api_sync_project_config_to_server,
)
from depictio.cli.cli.utils.common import (
    cli_version,
    generate_api_headers,
    get_http_client,
    load_depictio_config,
)
from depictio.cli.cli.utils.config import validate_project_config_and_check_S3_storage
from depictio.cli.cli.utils.helpers import process_project_helper
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_section_separator,
)
from depictio.cli.cli.utils.scan import scan_project_files
from depictio.cli.cli.utils.step_reporter import (
    StepReporter,
    ingestion_data_collections,
    redacted_command_line,
)
from depictio.cli.cli_logging import logger
from depictio.models.s3_utils import S3_storage_checks
from depictio.models.utils import convert_model_to_dict

#: Moved to cli.utils.common so the Delta commit-metadata builder can stamp the
#: same value without importing from a command module.
_cli_version = cli_version


def _write_provisioned_cli_config(base_raw_config: dict, provision: dict) -> str:
    """Write a temporary CLI config that runs the pipeline as the provisioned user.

    Takes the operator's *raw* CLI config dict (as read from YAML) and swaps in
    only the provisioned user's identity and run token — ``api_base_url`` and
    ``s3_storage`` are preserved verbatim, so the real S3 secret (a SecretStr on
    the parsed model, which would be masked by ``model_dump``) is kept intact.
    Pointing the rest of the run at this file makes every step (sync, scan,
    process, dashboard import) own its resources as that user, with no changes
    to downstream code. The file holds a token, so it is created 0600 and
    removed on process exit.
    """
    import atexit
    import os
    import tempfile

    import yaml

    tok = provision["token"]
    temp_cfg = dict(base_raw_config)  # shallow copy; only `user` is replaced
    temp_cfg["user"] = {
        "id": provision["user_id"],
        "email": provision["email"],
        "is_admin": provision["is_admin"],
        "token": {
            "user_id": provision["user_id"],
            "access_token": tok["access_token"],
            "refresh_token": tok["refresh_token"],
            "token_type": tok["token_type"],
            "token_lifetime": tok["token_lifetime"],
            "expire_datetime": tok["expire_datetime"],
            "refresh_expire_datetime": tok["refresh_expire_datetime"],
            "name": tok["name"],
        },
    }

    fd, path = tempfile.mkstemp(prefix="depictio-cli-provisioned-", suffix=".yaml")
    with os.fdopen(fd, "w") as fh:
        yaml.safe_dump(temp_cfg, fh)
    os.chmod(path, 0o600)
    atexit.register(lambda: os.path.exists(path) and os.unlink(path))
    return path


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
        dashboard_name: Annotated[
            str | None,
            typer.Option(
                "--dashboard-name",
                help="Custom title for the template's main dashboard "
                "(defaults to the title defined in the dashboard YAML). Child tabs keep their titles.",
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
        # Provisioning options
        user: Annotated[
            str | None,
            typer.Option(
                "--user",
                help=(
                    "Provision (create-or-get) this user's account and run the pipeline as "
                    "them, then emit a passwordless login link to their dashboard. "
                    "Requires --provisioning-key."
                ),
            ),
        ] = None,
        provisioning_key: Annotated[
            str | None,
            typer.Option(
                "--provisioning-key",
                help=(
                    "Shared provisioning secret used with --user "
                    "(or set DEPICTIO_AUTH_PROVISIONING_API_KEY)."
                ),
                envvar="DEPICTIO_AUTH_PROVISIONING_API_KEY",
            ),
        ] = None,
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
        sync_changed: bool = typer.Option(
            False,
            "--sync-changed",
            help=(
                "Re-upload only files whose metadata hash moved since the last scan. "
                "Narrower than --sync-files, which re-uploads every registered file."
            ),
        ),
        legacy_scan_depth: bool = typer.Option(
            False,
            "--legacy-scan-depth",
            help=(
                "Ignore each data collection's scan max_depth/ignore, as releases before "
                "1.2.2 did. Deprecated escape hatch; will be removed."
            ),
        ),
        state_cache: bool = typer.Option(
            True,
            "--state-cache/--no-state-cache",
            help=(
                "Use the local scan-state cache to skip runs whose file tree is unchanged "
                "since the last successful scan. Only applies when rescanning."
            ),
        ),
        concurrency: int = typer.Option(
            4,
            "--concurrency",
            "-c",
            help="Parallel HTTP requests for file uploads and cleanup deletes",
        ),
        upload_chunk_size: int = typer.Option(
            1000, "--upload-chunk-size", help="Files per /files/upsert_batch request"
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
        write_mode: str = typer.Option(
            "overwrite",
            "--write-mode",
            help=(
                "overwrite: rewrite the whole table (historical behaviour). "
                "replace-runs: partition by run and rewrite only the runs present in "
                "this batch, leaving the others untouched."
            ),
        ),
        incremental_write: bool = typer.Option(
            False,
            "--incremental-write",
            help=(
                "With --write-mode replace-runs, rewrite only the runs that changed instead of "
                "rebuilding the whole table. Falls back to a full rebuild whenever that cannot "
                "be done safely (run removed, table not partitioned by run, column type changed)."
            ),
        ),
        skip_unchanged: bool = typer.Option(
            False,
            "--skip-unchanged",
            help=(
                "Leave a data collection's Delta table untouched when the scan found no new, "
                "changed or removed file for it. Off by default so that re-running is always "
                "a way to rebuild a project that drifted."
            ),
        ),
        preview_recipes: bool = typer.Option(
            False,
            "--preview-recipes",
            help="Show recipe input sources and transformed output before writing to Delta Lake",
        ),
        repartition: bool = typer.Option(
            False,
            "--repartition",
            help=(
                "Allow --write-mode replace-runs to adopt run partitioning on a table "
                "that does not have it yet. This rewrites every row, so it is never "
                "done implicitly — and never by the watcher."
            ),
        ),
        async_upsert: bool = typer.Option(
            False,
            "--async-upsert",
            help=(
                "Ask the server to profile the written table in the background and poll "
                "until it finishes, instead of holding one long HTTP request open. "
                "Ignored by servers without offloading enabled — the upsert then just "
                "completes inline as before."
            ),
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

        # Size the shared connection pool before the first request: it is created
        # lazily and honours this only on the first call.
        get_http_client(concurrency=concurrency)

        if write_mode not in ("overwrite", "replace-runs"):
            rich_print_checked_statement(f"Invalid --write-mode '{write_mode}'", "error")
            raise typer.Exit(code=1)

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

        # Any re-upload flag needs every run walked again; without this, runs
        # already registered are skipped before a single file is looked at.
        if sync_files or sync_changed or overwrite:
            rescan_folders = True

        if user and not provisioning_key:
            rich_print_checked_statement(
                "--user requires --provisioning-key "
                "(or the DEPICTIO_AUTH_PROVISIONING_API_KEY environment variable).",
                "error",
            )
            raise typer.Exit(code=1)

        # Track whether we're in template mode
        is_template_mode = template is not None
        template_resolved_config: dict | None = None
        template_dashboard_paths: list[Path] = []
        # First dashboard imported for the provisioned user — target of the
        # passwordless login link emitted at the end of the run.
        provisioned_dashboard_id: str | None = None

        success_count = 0
        total_steps = 8 if is_template_mode else 7
        # What the scan found, handed to the process step. Empty when the scan
        # was skipped, which correctly reads as "no information" downstream.
        scan_signal: dict = {}

        # Server-side monitoring record for this ingestion run (best-effort).
        ingestion_run_id: str | None = None
        # Per-phase step ledger. Populated by ``_rec`` from the very start so
        # successful phases that ran before the record is opened (server / S3 /
        # validate) are still reported, and mirrored to the server as the run
        # proceeds once a run_id exists. The local list stays authoritative and
        # is sent in full at finish, so a run whose live updates were all
        # dropped still reports a complete history.
        #
        # Rebound to a live reporter right after the record is opened; until
        # then it only accumulates.
        reporter = StepReporter(send=lambda *_: True, run_id=None, enabled=False)
        # Server-side project id, resolved once available (post-sync); patched onto
        # the monitoring record at finish.
        resolved_project_id: str | None = None

        def _rec(name: str, status: str, detail: str | None = None, **extra) -> None:
            reporter.record(name, status, detail, **extra)

        def _rec_start(name: str, detail: str | None = None, **extra) -> None:
            """Announce a phase as it begins.

            This is what makes the monitoring UI show anything *during* a run
            rather than only after it: without a `running` record, a long scan
            or process phase is indistinguishable from a hung CLI.
            """
            reporter.start(name, detail, **extra)

        # Step 0a (provisioning only): create-or-get the user and switch the run
        # to act as them by pointing CLI_config_path at a temporary per-user
        # config. Everything downstream then owns its resources as that user.
        if user and not dry_run:
            rich_print_section_separator("Provisioning user account")
            try:
                import os

                from depictio.models.utils import get_config

                base_config = load_depictio_config(yaml_config_path=CLI_config_path)
                base_raw_config = get_config(os.path.expanduser(CLI_config_path))
                provision = api_provision_user(
                    str(base_config.api_base_url), user, provisioning_key
                )
                CLI_config_path = _write_provisioned_cli_config(base_raw_config, provision)
                action = "Created account for" if provision.get("created") else "Reusing account"
                rich_print_checked_statement(
                    f"{action} {provision['email']} — running pipeline as this user",
                    "success",
                )
                _rec("provisioning", "success", f"{action} {provision.get('email')}")
            except Exception as e:
                rich_print_checked_statement(f"User provisioning failed: {e}", "error")
                _rec("provisioning", "failed", str(e))
                raise typer.Exit(code=1)

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
                _rec(
                    "template_resolve",
                    "success",
                    f"template '{template_metadata.template_id}' loaded",
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
                _rec("template_resolve", "failed", str(e))
                if not continue_on_error:
                    raise typer.Exit(code=1)

        # Step 1: Check server accessibility
        if not skip_server_check:
            rich_print_section_separator(f"Step 1/{total_steps}: Checking server accessibility")
            try:
                if not dry_run:
                    api_login(CLI_config_path)
                rich_print_checked_statement("Server accessibility check passed", "success")
                success_count += 1
                _rec("server_check", "success", "server reachable")
            except Exception as e:
                rich_print_checked_statement(f"Server accessibility check failed: {e}", "error")
                _rec("server_check", "failed", str(e))
                if not continue_on_error:
                    raise typer.Exit(code=1)
        else:
            rich_print_checked_statement("Skipping server accessibility check", "info")
            success_count += 1
            _rec("server_check", "skipped")

        # Step 2: Check S3 storage
        if not skip_s3_check:
            rich_print_section_separator(f"Step 2/{total_steps}: Checking S3 storage configuration")
            try:
                if not dry_run:
                    CLI_config = load_depictio_config(yaml_config_path=CLI_config_path)
                    S3_storage_checks(CLI_config.s3_storage)
                rich_print_checked_statement("S3 storage configuration check passed", "success")
                success_count += 1
                _rec("s3_check", "success", "S3 storage reachable")
            except Exception as e:
                rich_print_checked_statement(f"S3 storage check failed: {e}", "error")
                _rec("s3_check", "failed", str(e))
                if not continue_on_error:
                    raise typer.Exit(code=1)
        else:
            rich_print_checked_statement("Skipping S3 storage check", "info")
            success_count += 1
            _rec("s3_check", "skipped")

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
            _rec("validate_config", "success", "config valid")
        except Exception as e:
            rich_print_checked_statement(f"{e}", "error")
            _rec("validate_config", "failed", str(e))
            if not continue_on_error:
                raise typer.Exit(code=1)

        # Open the monitoring ingestion record now that CLI_config is validated.
        # Best-effort: a monitoring outage must never affect the ingestion.
        if not dry_run:
            try:
                _proj = locals().get("project_config")
                ingestion_run_id = api_monitoring_ingestion_start(
                    CLI_config=CLI_config,
                    command="run",
                    project_name=getattr(_proj, "name", None),
                    cli_version=_cli_version(),
                    command_line=redacted_command_line(),
                    cli_config_path=str(CLI_config_path) if CLI_config_path else None,
                    project_config_path=str(project_config_path) or None,
                    data_root=str(data_root) if data_root else None,
                    # `depictio run` is by definition a person typing a command.
                    # The watcher opens its own record with trigger="watch".
                    trigger="manual",
                )
            except Exception:
                ingestion_run_id = None

            # Switch the reporter to live mode, carrying over the steps already
            # recorded before the record existed, so the server sees the whole
            # run rather than only the phases after this point.
            if ingestion_run_id:
                previous = reporter.steps
                reporter = StepReporter(
                    send=lambda run_id, step, current: api_monitoring_ingestion_step(
                        CLI_config, run_id, step, current
                    ),
                    run_id=ingestion_run_id,
                    enabled=True,
                )
                reporter.replay(previous)

        # Step 4: Sync project configuration to server
        if not skip_sync:
            rich_print_section_separator(
                f"Step 4/{total_steps}: Syncing project configuration to server"
            )
            try:
                if not dry_run:
                    project_config_dict = convert_model_to_dict(project_config)
                    # Provisioned (per-user) runs must stay private: templates
                    # often ship `is_public: true` for showcase visibility, but
                    # that would expose one user's project to everyone on the
                    # instance — defeating the per-user separation --user is for.
                    if user:
                        project_config_dict["is_public"] = False
                    api_sync_project_config_to_server(
                        CLI_config=CLI_config,
                        ProjectConfig=project_config_dict,
                        update=update_config,
                    )
                rich_print_checked_statement("Project configuration sync completed", "success")

                # Resolve tag-based link IDs now that the server has assigned real DC IDs
                if is_template_mode and not dry_run:
                    try:
                        from depictio.cli.cli.utils.api_calls import (
                            api_get_project_from_id,
                            api_update_project,
                        )

                        # Use name lookup first, fall back to ID-based fetch
                        remote = api_get_project_from_name(str(project_config.name), CLI_config)
                        if remote.status_code != 200:
                            # Name lookup may fail with special chars; try by scanning
                            # the project list or use the project_config's id if available
                            pid = getattr(project_config, "id", None)
                            if pid:
                                remote = api_get_project_from_id(pid, CLI_config)
                        if remote.status_code == 200:
                            proj_data = remote.json()
                            resolved_project_id = (
                                str(proj_data.get("_id") or proj_data.get("id") or "")
                                or resolved_project_id
                            )
                            tag_to_id: dict[str, str] = {}
                            for wf in proj_data.get("workflows", []):
                                for dc in wf.get("data_collections", []):
                                    tag = dc.get("data_collection_tag")
                                    dc_id = dc.get("_id")
                                    if tag and dc_id:
                                        tag_to_id[tag] = str(dc_id)

                            links_updated = False
                            for link in proj_data.get("links", []):
                                for field, tag_field in [
                                    ("source_dc_id", "source_dc_tag"),
                                    ("target_dc_id", "target_dc_tag"),
                                ]:
                                    tag = link.get(tag_field)
                                    if (
                                        tag
                                        and tag in tag_to_id
                                        and str(link.get(field, "")).startswith("tag:")
                                    ):
                                        link[field] = tag_to_id[tag]
                                        links_updated = True

                            if links_updated:
                                resp = api_update_project(proj_data, CLI_config)
                                rich_print_checked_statement(
                                    f"Resolved link tags to DC IDs ({resp.status_code})", "success"
                                )
                            else:
                                rich_print_checked_statement(
                                    "Links already have DC IDs (no tag: placeholders)", "info"
                                )
                    except Exception as e:
                        logger.warning(f"Link tag resolution failed (non-blocking): {e}")

                success_count += 1
                _rec("sync_project", "success", "project synced")
            except Exception as e:
                rich_print_checked_statement(f"Project configuration sync failed: {e}", "error")
                _rec("sync_project", "failed", str(e))
                if not continue_on_error:
                    raise typer.Exit(code=1)
        else:
            rich_print_checked_statement("Skipping project configuration sync", "info")
            success_count += 1
            _rec("sync_project", "skipped")

        # Step 5: Scan data files
        if not skip_scan:
            rich_print_section_separator(f"Step 5/{total_steps}: Scanning data files")
            _rec_start("scan")
            try:
                if not dry_run:
                    # Get remote project configuration to compare hashes
                    remote_project_config = api_get_project_from_name(
                        str(project_config.name), CLI_config
                    )

                    if remote_project_config.status_code == 200:
                        # Compare hashes
                        remote_json = remote_project_config.json()
                        local_hash = project_config.hash
                        remote_hash = remote_json.get("hash", None)
                        resolved_project_id = (
                            str(remote_json.get("_id") or remote_json.get("id") or "")
                            or resolved_project_id
                        )
                        logger.info(f"Local & Remote hashes: {local_hash} & {remote_hash}")

                        if local_hash == remote_hash:
                            command_parameters = {
                                "rescan_folders": rescan_folders,
                                "sync_files": sync_files,
                                "sync_changed": sync_changed,
                                "legacy_scan_depth": legacy_scan_depth,
                                "dry_run": dry_run,
                                "state_cache": state_cache,
                                "concurrency": concurrency,
                                "upload_chunk_size": upload_chunk_size,
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

                            # Which collections and runs moved. The process step
                            # below uses it to scope writes, and — only when
                            # asked — to leave untouched collections alone.
                            scan_signal = result

                        else:
                            raise Exception("Local and remote project configurations do not match")
                    else:
                        raise Exception("Failed to fetch remote project configuration")

                rich_print_checked_statement("Data scanning completed", "success")
                success_count += 1
                _rec("scan", "success", "data files scanned")
            except Exception as e:
                rich_print_checked_statement(f"Data scanning failed: {e}", "error")
                _rec("scan", "failed", str(e))
                if not continue_on_error:
                    raise typer.Exit(code=1)
        else:
            rich_print_checked_statement("Skipping data scanning", "info")
            success_count += 1
            _rec("scan", "skipped")

        # Step 6: Process data collections
        if not skip_process:
            rich_print_section_separator(f"Step 6/{total_steps}: Processing data collections")
            _rec_start("process")
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
                                "write_mode": write_mode,
                                "rich_tables": rich_tables,
                                "preview_recipes": preview_recipes,
                                "project_id": str(project_config.id),
                                "ingestion_run_id": ingestion_run_id,
                                "trigger": "cli",
                                "async_upsert": async_upsert,
                                "repartition": repartition,
                                "scan_signal": scan_signal,
                                "incremental_write": incremental_write,
                                # Off by default: an explicit `depictio run` is
                                # how someone rebuilds a project that drifted,
                                # so it must not quietly decide to do nothing.
                                "skip_unchanged": skip_unchanged,
                            }

                            process_result = process_project_helper(
                                CLI_config=CLI_config,
                                project_config=project_config,
                                mode="process",
                                command_parameters=command_parameters,
                            )
                            # Surface per-DC processing failures: a data collection
                            # that fails to process must not be reported as overall
                            # success (otherwise CI/automation can't detect it).
                            if process_result and process_result.get("total_failed", 0) > 0:
                                raise Exception(
                                    f"{process_result['total_failed']} data collection(s) "
                                    f"failed to process: "
                                    f"{', '.join(process_result.get('failed_tags', []))}"
                                )
                        else:
                            raise Exception("Local and remote project configurations do not match")
                    else:
                        raise Exception("Failed to fetch remote project configuration")

                rich_print_checked_statement("Data processing completed", "success")
                success_count += 1
                _proc = locals().get("process_result") or {}
                _n_ok = _proc.get("total_processed")
                _rec(
                    "process",
                    "success",
                    f"{_n_ok} data collection(s) processed"
                    if _n_ok is not None
                    else "data collections processed",
                )
            except Exception as e:
                rich_print_checked_statement(f"Data processing failed: {e}", "error")
                _rec("process", "failed", str(e))
                if not continue_on_error:
                    raise typer.Exit(code=1)
        else:
            rich_print_checked_statement("Skipping data processing", "info")
            success_count += 1
            _rec("process", "skipped")

        # Step 7: Execute table joins
        if not skip_join:
            rich_print_section_separator(f"Step 7/{total_steps}: Executing table joins")
            _rec_start("joins")
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
                _join = locals().get("join_result") or {}
                _n_join = len(_join.get("processed") or [])
                _n_join_err = len(_join.get("errors") or [])
                _rec(
                    "joins",
                    "success",
                    f"{_n_join} processed / {_n_join_err} failed" if _join else "no joins defined",
                )
            except Exception as e:
                rich_print_checked_statement(f"Join execution failed: {e}", "error")
                _rec("joins", "failed", str(e))
                if not continue_on_error:
                    raise typer.Exit(code=1)
        else:
            rich_print_checked_statement("Skipping join execution", "info")
            success_count += 1
            _rec("joins", "skipped")

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
                        resolved_project_id = str(project_id or "") or resolved_project_id

                    results = import_dashboards_from_template(
                        dashboard_paths=template_dashboard_paths,
                        api_url=api_url,
                        headers=headers,
                        project_id=project_id,
                        overwrite=overwrite,
                        variables=template_variables,
                        dashboard_name=dashboard_name,
                    )

                    imported, failed = [], []
                    for r in results:
                        (imported if r["success"] else failed).append(r)

                    if user and imported and provisioned_dashboard_id is None:
                        provisioned_dashboard_id = imported[0].get("dashboard_id")

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
                # `imported`/`failed` are only bound in the non-dry-run branch above.
                _imp = locals().get("imported") or []
                _fld = locals().get("failed") or []
                _rec("dashboard_import", "success", f"{len(_imp)} imported / {len(_fld)} failed")
            except Exception as e:
                rich_print_checked_statement(f"Dashboard import failed: {e}", "error")
                _rec("dashboard_import", "failed", str(e))
                if not continue_on_error:
                    raise typer.Exit(code=1)
        elif is_template_mode and skip_dashboard_import:
            rich_print_checked_statement(
                "Skipping dashboard import (--skip-dashboard-import)", "info"
            )
            success_count += 1
            _rec("dashboard_import", "skipped")
        elif is_template_mode and not template_dashboard_paths:
            rich_print_checked_statement("No dashboards defined in template", "info")
            success_count += 1
            _rec("dashboard_import", "skipped", "no dashboards in template")

        # Passwordless login link for the provisioned user. Minted now (not at
        # provisioning time) so the short-lived ticket's clock starts when the
        # link is handed out, not when a long pipeline began.
        if user and not dry_run and provisioned_dashboard_id:
            rich_print_section_separator("Passwordless login link")
            try:
                magic_config = load_depictio_config(yaml_config_path=CLI_config_path)
                magic = api_create_magic_link(magic_config)
                login_url = f"{magic['login_url']}&next=/dashboard/{provisioned_dashboard_id}"
                rich_print_checked_statement(f"One-time login link for {user}:", "info")
                rich_print_checked_statement(login_url, "success")
            except Exception as e:
                rich_print_checked_statement(f"Could not create login link: {e}", "warning")

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

        # Close the monitoring ingestion record (best-effort).
        if ingestion_run_id:
            final_status = "success" if success_count == total_steps else "partial"
            # Stop the background reporter first, with a short bounded wait: the
            # complete ledger goes out below regardless, so blocking the user's
            # command to re-send what the next call already carries is pointless.
            reporter.close(timeout=2.0)
            # Send the per-phase step ledger recorded throughout the run. The
            # overall status rides on ``status`` (shown as the header badge in
            # the admin UI), so no separate summary row is needed.
            api_monitoring_ingestion_finish(
                CLI_config=CLI_config,
                run_id=ingestion_run_id,
                status=final_status,
                steps=reporter.steps,
                project_id=resolved_project_id,
                data_collections=ingestion_data_collections(locals().get("project_config")),
            )

        # A run that did not complete every step is a failure for automation
        # purposes — exit non-zero so CI can detect it (even under
        # --continue-on-error, which only suppresses the early aborts above).
        if success_count != total_steps:
            raise typer.Exit(code=1)
