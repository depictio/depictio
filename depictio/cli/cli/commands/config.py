from typing import Annotated

import typer

from depictio.cli.cli.utils.api_calls import (
    api_get_project_from_name,
    api_login,
    api_sync_project_config_to_server,
)
from depictio.cli.cli.utils.common import load_depictio_config
from depictio.cli.cli.utils.config import validate_project_config_and_check_S3_storage
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_json,
)
from depictio.cli.cli_logging import logger
from depictio.models.s3_utils import S3_storage_checks
from depictio.models.utils import convert_model_to_dict

app = typer.Typer()


@app.command()
def show(
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="Path to the configuration file")
    ] = "~/.depictio/CLI.yaml",
    project_name: Annotated[
        str | None,
        typer.Option(
            "--project-name",
            help="Also show this project's metadata as registered on the server",
        ),
    ] = None,
):
    """
    Show the current Depictio CLI configuration.

    With --project-name, additionally fetch and print that project's metadata as
    registered on the server.
    """
    rich_print_command_usage("config show")
    try:
        cli_config = load_depictio_config(yaml_config_path=CLI_config_path)
        rich_print_json("Current Depictio CLI Configuration: ", cli_config.model_dump())
        if project_name:
            metadata = api_get_project_from_name(project_name, cli_config).json()
            rich_print_json(f"Server metadata for project '{project_name}': ", metadata)
    except Exception as e:
        rich_print_checked_statement(f"Unable to load configuration - {e}", "error")


@app.command()
def nextflow(
    print_: Annotated[
        bool,
        typer.Option(
            "--print",
            help="Write the snippet's contents to stdout instead of its path.",
        ),
    ] = False,
):
    """
    Print the path of the bundled Nextflow onComplete snippet.

    Meant to be substituted straight into a Nextflow command, which is the whole
    reason it exists: the snippet lives inside the installed package, and that is
    not a path anyone should have to type or keep in sync.

        nextflow run nf-core/ampliseq --outdir results -c $(depictio-cli config nextflow)

    For an nf-core pipeline that is the entire setup. The snippet reads the
    pipeline's own manifest and hands it to the CLI as --pipeline-id, which
    resolves the bundled template, so there is nothing else to configure.

    Use --print to read the snippet, or to copy it somewhere you can edit:

        depictio-cli config nextflow --print > depictio.config
    """
    # Deliberately no rich_print_command_usage and no decoration: the only
    # useful form of this output is a bare path on stdout, inside $(...).
    # Anything else printed here ends up in the Nextflow command line.
    from pathlib import Path

    import depictio.cli

    snippet = Path(depictio.cli.__file__).parent / "configs" / "nextflow" / "depictio.config"
    if not snippet.is_file():
        # Shipped as package data. An install predating that, or one assembled by
        # hand, simply will not have it, and a bare traceback would not say so.
        rich_print_checked_statement(
            f"The bundled Nextflow snippet is missing from this installation "
            f"(expected at {snippet}). Upgrade depictio-cli, or take the file "
            f"from depictio/cli/configs/nextflow/depictio.config in the repository.",
            "error",
        )
        raise typer.Exit(code=1)

    if print_:
        print(snippet.read_text(), end="")
    else:
        print(snippet)


@app.command()
def check(
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="Path to the configuration file")
    ] = "~/.depictio/CLI.yaml",
    project_config_path: Annotated[
        str,
        typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
    ] = "",
):
    """
    Run Depictio preflight checks.

    Without --project-config-path: verify server accessibility and S3 storage
    (the environment the CLI talks to).

    With --project-config-path: validate that project configuration (this also
    exercises the S3 storage check it depends on).
    """
    rich_print_command_usage("config check")

    # Project-config validation mode (folds the former validate-project-config).
    if project_config_path:
        _, response = validate_project_config_and_check_S3_storage(
            CLI_config_path=CLI_config_path, project_config_path=project_config_path
        )
        if response["success"]:
            rich_print_checked_statement("Depictio Project configuration validated", "success")
            project_config = convert_model_to_dict(response["project_config"])
            rich_print_json("Validated Depictio Project Configuration: ", project_config)
        else:
            rich_print_checked_statement(
                "Pipeline configuration invalid, use --verbose for more details.", "error"
            )
        return

    # Environment doctor: server accessibility + S3 storage.
    try:
        login_result = api_login(CLI_config_path)
        logger.info(f"Login result: {login_result}")
        if login_result.get("success"):
            user_info = []
            if login_result.get("email"):
                user_info.append(f"User: {login_result['email']}")
            if login_result.get("is_admin"):
                user_info.append("Admin privileges: Yes")
            suffix = f" - {', '.join(user_info)}" if user_info else ""
            rich_print_checked_statement(f"Server accessible{suffix}", "success")
        else:
            rich_print_checked_statement(
                "Server check failed - Invalid credentials or token expired", "error"
            )
    except Exception as e:
        rich_print_checked_statement(f"Unable to access server - {e}", "error")

    try:
        cli_config = load_depictio_config(yaml_config_path=CLI_config_path)
        S3_storage_checks(cli_config.s3_storage)
        rich_print_checked_statement("S3 storage configuration is valid", "success")
    except Exception as e:
        rich_print_checked_statement(f"Unable to check S3 storage - {e}", "error")


@app.command()
def sync(
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="Path to the configuration file")
    ] = "~/.depictio/CLI.yaml",
    project_config_path: Annotated[
        str,
        typer.Option("--project-config-path", help="Path to the pipeline configuration file"),
    ] = "",
    update: Annotated[
        bool,
        typer.Option("--update", help="Update the project configuration on the server"),
    ] = False,
):
    """
    Validate the Depictio project configuration and sync it to the server.
    """
    rich_print_command_usage("config sync")
    CLI_config, validation_response = validate_project_config_and_check_S3_storage(
        CLI_config_path=CLI_config_path, project_config_path=project_config_path
    )
    if not validation_response["success"]:
        rich_print_checked_statement(
            "Pipeline configuration invalid, use --verbose for more details.", "error"
        )
        return
    rich_print_checked_statement("Pipeline configuration validated", "success")
    project_config = convert_model_to_dict(validation_response["project_config"])
    sync_verdict = api_sync_project_config_to_server(
        CLI_config=CLI_config, ProjectConfig=project_config, update=update
    )
    # The sync reports "exists" instead of raising, so this caller has to speak up:
    # otherwise refusing to touch an existing project looks exactly like success.
    if sync_verdict.get("action") == "exists":
        rich_print_checked_statement(
            f"Project '{project_config.get('name')}' already exists on this server. "
            "Re-run with --update to refresh its configuration.",
            "error",
        )
        raise typer.Exit(code=2)
