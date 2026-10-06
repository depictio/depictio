"""Template authoring commands.

``depictio template export`` freezes an existing project + its dashboards into
a reusable template bundle (the inverse of ``depictio ingest --template``). The
server does the heavy lifting (sanitization, re-parameterization, tag-based
dashboard export, round-trip check); the CLI unpacks the returned archive into
a ``<template_id>/`` directory ready to drop into ``depictio/projects/``.

``depictio template compose`` writes one offline from what the catalog
recognises in a results directory: what ``depictio ingest`` composes by itself
when no bundled template fits a run.
"""

import io
import re
import zipfile
from pathlib import Path
from typing import Annotated, Optional

import httpx
import typer
from rich.console import Console

from depictio.cli.cli.utils.renamed import pick_renamed
from depictio.cli.cli.utils.server_target import ServerOption, resolve_server

app = typer.Typer()
console = Console()

_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _members_within(archive: zipfile.ZipFile, target: Path) -> list[str]:
    """Names in ``archive`` once every one is confirmed to land inside ``target``.

    Raises ``ValueError`` naming the first member that would not: an absolute
    name, a ``..`` segment, or a resolved path that leaves the directory
    (zip-slip). Checked before any byte is written, so a hostile bundle
    leaves nothing behind.
    """
    root = target.resolve()
    names = archive.namelist()
    for name in names:
        parts = [p for p in re.split(r"[\\/]+", name) if p]
        if (
            not parts
            or name.startswith(("/", "\\"))
            or _DRIVE_PREFIX_RE.match(name)
            or ".." in parts
            or not (root / Path(*parts)).resolve().is_relative_to(root)
        ):
            raise ValueError(f"member '{name}' would be written outside {target}")
    return names


TEMPLATE_PANEL = "Template"
OUTPUT_PANEL = "Output"

# The options these commands took before --server and --data-dir. Still accepted, out of the help.
LegacyConfigOption = Annotated[str | None, typer.Option("--config", "-c", hidden=True)]
ApiUrlOption = Annotated[str | None, typer.Option("--api", hidden=True)]
LegacyDataRootOption = Annotated[str | None, typer.Option("--data-root", hidden=True)]


@app.command()
def export(
    project_id: Annotated[str, typer.Argument(help="Project ID to export")],
    template_id: Annotated[
        str,
        typer.Option(
            "--template-id",
            "-t",
            help="Template id, e.g. 'my-lab/rnaseq-qc/1'",
            rich_help_panel=TEMPLATE_PANEL,
        ),
    ],
    server: ServerOption = None,
    config_path: LegacyConfigOption = None,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory to unpack the bundle into",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = Path("."),
    version: Annotated[
        str,
        typer.Option("--version", help="Template version", rich_help_panel=TEMPLATE_PANEL),
    ] = "1.0.0",
    description: Annotated[
        Optional[str],
        typer.Option("--description", help="Template description", rich_help_panel=TEMPLATE_PANEL),
    ] = None,
    data_dir: Annotated[
        Optional[str],
        typer.Option(
            "--data-dir",
            help="Local path prefix to re-parameterize as {DATA_ROOT} in the template",
            rich_help_panel=TEMPLATE_PANEL,
        ),
    ] = None,
    data_root: LegacyDataRootOption = None,
    api_url: ApiUrlOption = None,
) -> None:
    """Export a project + its dashboards as a template bundle.

    The inverse of `depictio ingest --template`: the bundle can be ingested on
    another dataset.

    Example:
        depictio template export 6824cb3b89d2b72169309737 \\
          --template-id my-lab/rnaseq-qc/1 --server admin_config.yaml -o depictio/projects
    """
    data_dir = pick_renamed(data_dir, data_root, "--data-dir", "--data-root")
    console.print("[cyan]Loading CLI configuration...[/cyan]")
    config_file = resolve_server(server, config_path, legacy_option="--config")
    try:
        from depictio.cli.cli.utils.common import generate_api_headers, load_depictio_config

        cli_config = load_depictio_config(yaml_config_path=config_file)
        headers = generate_api_headers(cli_config)
        if api_url is None:
            api_url = str(cli_config.api_base_url)
    except Exception as e:
        console.print(f"[red]Error loading CLI config: {e}[/red]")
        console.print("[yellow]Hint: pass --server local or a CLI configuration file[/yellow]")
        raise typer.Exit(1)

    url = f"{api_url}/depictio/api/v1/projects/{project_id}/export_template"
    payload = {
        "template_id": template_id,
        "version": version,
        "description": description,
        "data_root": data_dir,
    }
    console.print(f"[cyan]Exporting project {project_id} as template '{template_id}'...[/cyan]")

    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        console.print(f"[red]Error: HTTP {e.response.status_code}[/red]")
        console.print(f"  {e.response.text}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    target = output_dir / template_id
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            # Validate every member before creating anything: a bundle that
            # tries to escape the target directory must leave no trace.
            names = _members_within(archive, target)
            target.mkdir(parents=True, exist_ok=True)
            archive.extractall(target)
    except zipfile.BadZipFile:
        console.print("[red]Error: the server response is not a valid zip bundle[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]Refusing to unpack the bundle: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ Template bundle written to: {target}[/green]")
    for name in sorted(names):
        console.print(f"  - {name}")
    console.print(
        "[cyan]Drop the directory into depictio/projects/ (or a template search path) "
        "and it is auto-discovered.[/cyan]"
    )


@app.command("compose")
def compose(
    data_root: Annotated[Path, typer.Argument(help="Results directory to compose a dashboard for")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write the template here, to edit it and ingest with it: `depictio ingest "
            "<dir> --template <out>`. Default: where `depictio ingest` keeps composed templates",
        ),
    ] = None,
    include_unknown: Annotated[
        bool,
        typer.Option(
            "--include-unknown",
            help="Also include the tabular files the catalog does not recognise",
        ),
    ] = False,
    include: Annotated[
        list[str] | None,
        typer.Option(
            "--include",
            help="Include the unrecognised files matching this glob (relative to the "
            "directory); repeatable",
        ),
    ] = None,
    project_name: Annotated[
        str | None, typer.Option("--project", help="Name of the project to create")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="List everything left out, with the reason")
    ] = False,
):
    """Compose a template from the files the catalog recognises in a results directory.

    Offline: nothing is ingested. Prints what was recognised, the tabs and key
    metrics of the dashboard, what was left out and why, and the tabular files
    nothing recognised with what each could show. This is what `depictio ingest
    <dir>` does by itself when no bundled template fits the run.
    """
    from depictio.cli.cli.utils.compose import ComposedTemplate, compose_template, print_report
    from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
    from depictio.models.models.run_info import read_run_info

    if not data_root.is_dir():
        rich_print_checked_statement(f"{data_root} is not a directory", "error")
        raise typer.Exit(code=1)
    info = read_run_info(data_root)
    result = compose_template(
        data_root,
        out_dir=output,
        include_unknown=include_unknown,
        include=include or (),
        project_name=project_name,
        pipeline_name=info.pipeline_name if info else None,
        pipeline_version=info.pipeline_version if info else None,
        engine=info.engine if info else None,
    )
    print_report(result, verbose=verbose)
    if not isinstance(result, ComposedTemplate):
        rich_print_checked_statement(
            f"Nothing in {data_root} is recognised by the catalog: no template written.",
            "warning",
        )
        raise typer.Exit(code=1)
    rich_print_checked_statement(f"Template written to {result.template_dir}", "success")
    rich_print_checked_statement(
        f"Ingest it: depictio ingest {data_root} --template {result.template_dir}",
        "info",
    )
