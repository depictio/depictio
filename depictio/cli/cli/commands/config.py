import re
from typing import Annotated

import httpx
import typer

from depictio.cli.cli.utils.api_calls import (
    api_get_project_from_name,
    api_login,
    api_sync_project_config_to_server,
)
from depictio.cli.cli.utils.common import (
    describe_api_target,
    load_depictio_config,
    report_unreachable,
    say_local_server_running,
)
from depictio.cli.cli.utils.config import validate_project_config_and_check_S3_storage
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_json,
)
from depictio.cli.cli.utils.server_target import (
    LegacyConfigPathOption,
    ServerOption,
    resolve_server,
)
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig
from depictio.models.s3_utils import S3_storage_checks
from depictio.models.utils import convert_model_to_dict

app = typer.Typer()


@app.command()
def show(
    server: ServerOption = None,
    CLI_config_path: LegacyConfigPathOption = None,
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
    config_path = resolve_server(server, CLI_config_path)
    try:
        cli_config = load_depictio_config(yaml_config_path=config_path)
    except typer.Exit:
        # load_depictio_config already said which file it could not use, and why.
        raise
    except Exception as e:
        rich_print_checked_statement(f"Unable to load configuration - {e}", "error")
        raise typer.Exit(code=1)
    # mode="json" masks the SecretStr fields. The tokens are plain strings but
    # credentials all the same: masked too, so the output can be shared.
    shown = cli_config.model_dump(mode="json")
    token = (shown.get("user") or {}).get("token") or {}
    for key in ("access_token", "refresh_token"):
        if token.get(key):
            token[key] = "**********"
    rich_print_json("Current Depictio CLI Configuration: ", shown)
    if project_name:
        _show_project(project_name, cli_config, config_path)


def _show_project(project_name: str, cli_config: CLIConfig, config_path: str) -> None:
    """Print the server's metadata for ``project_name``, or exit 1 saying why there is none.

    The configuration is on screen by then, so a failure here is the project's or
    the server's, never the configuration's.
    """
    try:
        response = api_get_project_from_name(project_name, cli_config)
    except httpx.HTTPError as exc:
        report_unreachable(config_path, exc)
        raise typer.Exit(code=1) from exc
    if response.status_code == 404:
        rich_print_checked_statement(
            f"No project named '{project_name}' on {cli_config.api_base_url}", "error"
        )
        raise typer.Exit(code=1)
    if response.status_code != 200:
        rich_print_checked_statement(
            f"Cannot fetch project '{project_name}' from {cli_config.api_base_url}: "
            f"HTTP {response.status_code} {response.text}",
            "error",
        )
        raise typer.Exit(code=1)
    rich_print_json(f"Server metadata for project '{project_name}': ", response.json())


@app.command()
def nextflow(
    ctx: typer.Context,
    print_: Annotated[
        bool,
        typer.Option(
            "--print",
            help="Write the snippet's contents to stdout instead of its path.",
        ),
    ] = False,
    install: Annotated[
        bool,
        typer.Option(
            "--install",
            help="Enable the trigger for every pipeline on this machine, once.",
        ),
    ] = False,
    uninstall: Annotated[
        bool,
        typer.Option(
            "--uninstall",
            help="Undo --install, leaving any other Nextflow settings alone.",
        ),
    ] = False,
    default_enabled: Annotated[
        bool,
        typer.Option(
            "--default-enabled/--default-disabled",
            help=(
                "With --install: whether a pipeline that sets no --depictio_enabled "
                "triggers Depictio (default) or stays opt-in."
            ),
        ),
    ] = True,
):
    """
    Print the path of the bundled Nextflow onComplete snippet.

    Meant to be substituted straight into a Nextflow command, which is the whole
    reason it exists: the snippet lives inside the installed package, and that is
    not a path anyone should have to type or keep in sync.

        nextflow run nf-core/ampliseq --outdir results -c $(depictio config nextflow)

    For an nf-core pipeline that is the entire setup. The snippet reads the
    pipeline's own manifest and hands it to the CLI as --pipeline-id, which
    resolves the bundled template, so there is nothing else to configure.

    Use --print to read the snippet, or to copy it somewhere you can edit:

        depictio config nextflow --print > depictio.config

    Use --install to stop repeating the -c, once per machine:

        depictio config nextflow --install

    Every later `nextflow run` then triggers Depictio with no extra flag, and
    `--uninstall` reverses it. Add --default-disabled to install it opt-in
    instead: pipelines then need `--depictio_enabled true` to trigger. Either
    way, `--depictio_enabled true/false` on a given `nextflow run` always wins.
    """
    # Usage errors (exit code 2), refused rather than one of the options silently dropped.
    if install and uninstall:
        ctx.fail("--install and --uninstall are opposites: pass only one.")
    if print_ and (install or uninstall):
        other = "--install" if install else "--uninstall"
        ctx.fail(
            f"--print writes the snippet to stdout, {other} changes the Nextflow "
            "configuration: pass only one."
        )
    if not default_enabled and not install:
        ctx.fail("--default-disabled only applies with --install.")

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
            f"(expected at {snippet}). Upgrade depictio, or take the file "
            f"from depictio/cli/configs/nextflow/depictio.config in the repository.",
            "error",
        )
        raise typer.Exit(code=1)

    if install or uninstall:
        _apply_nextflow_install(snippet, enable=install, default_enabled=default_enabled)
        return

    if print_:
        print(snippet.read_text(), end="")
    else:
        print(snippet)


# Fenced so the block can be found and replaced on a re-install, and removed on
# --uninstall, without touching whatever else the user keeps in this file. It still
# says `depictio-cli`: the marker is matched exactly, and a reworded one would no
# longer find the blocks earlier releases installed.
_NXF_BEGIN = "// >>> depictio (managed by `depictio-cli config nextflow --install`) >>>"
_NXF_END = "// <<< depictio <<<"


def _strip_managed_block(text: str) -> str:
    """Drop the depictio block from a Nextflow config, leaving the rest intact."""
    out, skipping = [], False
    for line in text.splitlines():
        if line.strip() == _NXF_BEGIN:
            skipping = True
            continue
        if skipping:
            if line.strip() == _NXF_END:
                skipping = False
            continue
        out.append(line)
    return "\n".join(out).strip("\n")


# Matches the one line in the bundled snippet that supplies the fallback used
# when a run sets no `--depictio_enabled`/`params.depictio_enabled`. Templated
# in `_render_snippet` rather than left as a placeholder in the source file, so
# `--print` and `--install` (no flag) still show plain, valid Groovy.
_ENABLED_DEFAULT_RE = re.compile(r"(cfg\.call\('depictio_enabled',\s*)(?:true|false)(\))")


def _render_snippet(snippet, default_enabled: bool) -> str:
    """Return the bundled snippet's text, with its opt-out default swapped in."""
    text = snippet.read_text()
    templated, count = _ENABLED_DEFAULT_RE.subn(
        rf"\g<1>{'true' if default_enabled else 'false'}\g<2>", text
    )
    if count != 1:
        # The snippet is Depictio's own package data, not user input: a mismatch
        # here means the source moved and this function needs updating with it,
        # not a value some caller passed in.
        raise RuntimeError(
            f"Expected exactly one depictio_enabled default in {snippet}, found {count}."
        )
    return templated


def _apply_nextflow_install(snippet, enable: bool, default_enabled: bool = True) -> None:
    """Add or remove the global include in ``$NXF_HOME/config``.

    Nextflow reads that file before every run, which is what removes the
    per-run ``-c``.

    The include deliberately does **not** point at ``snippet``. That path lives
    inside the Python environment, and a stale ``includeConfig`` is not a soft
    failure: Nextflow refuses to parse the config at all, so a later
    ``pip uninstall`` or a switch of virtualenv would break every pipeline on
    the machine, Depictio-related or not. The snippet is copied to a stable
    location under ``~/.depictio`` instead, which survives all of that. If the
    CLI then disappears the handler simply reports it and leaves the pipeline's
    own result untouched.

    ``default_enabled`` only changes the *fallback* used when a run sets no
    ``--depictio_enabled``/``params.depictio_enabled``: the handler reads that
    param lazily at completion time regardless of what was installed, so a
    per-run override always wins either way.
    """
    import os
    from pathlib import Path

    installed = Path("~/.depictio/nextflow.config").expanduser()
    nxf_config = Path(os.environ.get("NXF_HOME", "~/.nextflow")).expanduser() / "config"

    existing = nxf_config.read_text() if nxf_config.is_file() else ""
    remainder = _strip_managed_block(existing)

    if not enable:
        if _NXF_BEGIN not in existing:
            rich_print_checked_statement(
                f"Nothing to remove: no depictio block in {nxf_config}", "info"
            )
            return
        nxf_config.write_text(remainder + "\n" if remainder else "")
        rich_print_checked_statement(f"Removed the depictio block from {nxf_config}", "success")
        rich_print_checked_statement(
            f"{installed} was left in place; delete it by hand if you want it gone.", "info"
        )
        return

    # Refresh on every --install so an upgraded CLI ships its updated handler.
    installed.parent.mkdir(parents=True, exist_ok=True)
    installed.write_text(_render_snippet(snippet, default_enabled))

    block = f"{_NXF_BEGIN}\nincludeConfig '{installed}'\n{_NXF_END}"
    nxf_config.parent.mkdir(parents=True, exist_ok=True)
    nxf_config.write_text(f"{remainder}\n\n{block}\n" if remainder else f"{block}\n")

    rich_print_checked_statement(f"Copied the handler to {installed}", "success")
    if default_enabled:
        rich_print_checked_statement(f"Enabled it for every pipeline in {nxf_config}", "success")
        rich_print_checked_statement(
            "`nextflow run <pipeline>` now triggers Depictio with no extra flag. "
            "Add --depictio_enabled false to skip a given run, "
            "or undo with: depictio config nextflow --uninstall",
            "info",
        )
    else:
        rich_print_checked_statement(
            f"Installed opt-in in {nxf_config}: pipelines stay silent by default.", "success"
        )
        rich_print_checked_statement(
            "Add --depictio_enabled true to a `nextflow run` to trigger Depictio for it, "
            "or undo the install with: depictio config nextflow --uninstall",
            "info",
        )


@app.command()
def check(
    server: ServerOption = None,
    CLI_config_path: LegacyConfigPathOption = None,
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
    config_path = resolve_server(server, CLI_config_path)

    # Project-config validation mode (folds the former validate-project-config).
    if project_config_path:
        _, response = validate_project_config_and_check_S3_storage(
            CLI_config_path=config_path, project_config_path=project_config_path
        )
        if not response["success"]:
            rich_print_checked_statement(
                "Pipeline configuration invalid, use --verbose for more details.", "error"
            )
            raise typer.Exit(code=1)
        rich_print_checked_statement("Depictio Project configuration validated", "success")
        project_config = convert_model_to_dict(response["project_config"])
        rich_print_json("Validated Depictio Project Configuration: ", project_config)
        return

    # Environment doctor: server accessibility + S3 storage. The S3 check runs even
    # when the server check failed, so one run reports both; the exit code says
    # whether either failed, for a script gating a pipeline on this command.
    failed = False
    try:
        login_result = api_login(config_path)
    except typer.Exit:
        # load_depictio_config said what is wrong with the configuration, and the S3
        # check reads the same file: nothing else to report.
        raise
    except Exception as e:
        # This is the command the docs tell you to run before trusting a long
        # pipeline to the trigger, so a bare "Connection refused" is the one
        # answer it must not give: it says nothing about which instance was
        # tried, which is the thing that is usually wrong.
        if isinstance(e, httpx.HTTPError):
            report_unreachable(config_path, e)
        else:
            rich_print_checked_statement(f"Unable to access server - {e}", "error")
            rich_print_checked_statement(f"Tried {describe_api_target(config_path)}", "info")
            say_local_server_running(config_path)
        failed = True
    else:
        # The verdict only: the result embeds the configuration, access token included.
        logger.info(f"Login successful: {login_result.get('success')}")
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
            rich_print_checked_statement(f"Tried {describe_api_target(config_path)}", "info")
            failed = True

    try:
        # Announced, and read quietly: probing an unreachable endpoint blocks
        # until it times out, and the second "Loading Depictio configuration..."
        # this used to print was the last thing on screen during that wait, so
        # the command looked like it had died mid-load.
        rich_print_checked_statement("Checking S3 storage configuration...", "loading")
        cli_config = load_depictio_config(yaml_config_path=config_path, quiet=True)
        S3_storage_checks(cli_config.s3_storage)
        rich_print_checked_statement("S3 storage configuration is valid", "success")
    except typer.Exit:
        raise
    except Exception as e:
        rich_print_checked_statement(f"Unable to check S3 storage - {e}", "error")
        failed = True

    if failed:
        raise typer.Exit(code=1)


@app.command()
def sync(
    ctx: typer.Context,
    server: ServerOption = None,
    CLI_config_path: LegacyConfigPathOption = None,
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
    config_path = resolve_server(server, CLI_config_path)
    if not project_config_path:
        ctx.fail("config sync needs --project-config-path: the project configuration to sync.")
    CLI_config, validation_response = validate_project_config_and_check_S3_storage(
        CLI_config_path=config_path,
        project_config_path=project_config_path,
    )
    if not validation_response["success"]:
        rich_print_checked_statement(
            "Pipeline configuration invalid, use --verbose for more details.", "error"
        )
        raise typer.Exit(code=1)
    rich_print_checked_statement("Pipeline configuration validated", "success")
    project_config = convert_model_to_dict(validation_response["project_config"])
    try:
        sync_verdict = api_sync_project_config_to_server(
            CLI_config=CLI_config, ProjectConfig=project_config, update=update
        )
    except httpx.HTTPError as exc:
        report_unreachable(config_path, exc)
        raise typer.Exit(code=1) from exc
    # The sync reports "exists" instead of raising, so this caller has to speak up:
    # otherwise refusing to touch an existing project looks exactly like success.
    if sync_verdict.get("action") == "exists":
        rich_print_checked_statement(
            f"Project '{project_config.get('name')}' already exists on this server. "
            "Re-run with --update to refresh its configuration.",
            "error",
        )
        raise typer.Exit(code=2)
