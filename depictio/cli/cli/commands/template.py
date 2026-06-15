"""
depictio template — export an existing project as a reusable template.

Produces a ZIP bundle (``template.yaml`` + ``dashboards/*.yaml``) in the layout
the template engine consumes, so a colleague can instantiate it with::

    depictio run --template <bundle> --data-root /their/data

Config and dashboards travel with the bundle; data does not. Filesystem data
paths are re-parameterized to ``{DATA_ROOT}`` on export.

Usage examples:
    # Export a project to the current directory
    depictio template export --project "my-project" \\
        --CLI-config-path ~/.depictio/CLI.yaml

    # Choose an output path and a template id/version
    depictio template export --project "my-project" -o ./my-template.zip \\
        --template-id "user/my-project/1.0.0" --version 1.0.0
"""

from pathlib import Path
from typing import Annotated

import typer

from depictio.cli.cli.utils.api_calls import api_export_template, api_login
from depictio.cli.cli.utils.common import load_depictio_config
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement

app = typer.Typer(help="Template management commands")


@app.command()
def export(
    project: Annotated[
        str | None, typer.Option("--project", help="Project name to export as a template")
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", help="Project ID to export (alternative to --project)"),
    ] = None,
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output path: a .zip file or a directory")
    ] = ".",
    template_id: Annotated[
        str | None,
        typer.Option("--template-id", help="Template id (default: 'user/<slug>/<version>')"),
    ] = None,
    version: Annotated[str, typer.Option("--version", help="Template version (semver)")] = "1.0.0",
    description: Annotated[
        str | None, typer.Option("--description", help="Human-readable template description")
    ] = None,
    CLI_config_path: Annotated[
        str, typer.Option("--CLI-config-path", help="CLI config path")
    ] = "~/.depictio/CLI.yaml",
) -> None:
    """Export a project (config + dashboards) as a template ZIP bundle."""
    if not project and not project_id:
        rich_print_checked_statement("Provide --project or --project-id", "error")
        raise typer.Exit(1)

    config = load_depictio_config(yaml_config_path=CLI_config_path)

    rich_print_checked_statement("Authenticating...", "info")
    api_login(CLI_config_path)

    target = project or project_id
    rich_print_checked_statement(f"Exporting project '{target}' as a template...", "info")
    result = api_export_template(
        config,
        project_name=project,
        project_id=project_id,
        template_id=template_id,
        version=version,
        description=description,
    )

    if not result.get("success"):
        rich_print_checked_statement(result.get("message", "Template export failed"), "error")
        raise typer.Exit(1)

    out = Path(output).expanduser()
    if out.is_dir() or output.endswith(("/", "\\")):
        out = out / result["filename"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result["content"])

    rich_print_checked_statement(f"Template written to {out}", "success")
