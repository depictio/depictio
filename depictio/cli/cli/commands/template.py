"""Template authoring commands.

``depictio template export`` freezes an existing project + its dashboards into
a reusable template bundle (the inverse of ``depictio run --template``). The
server does the heavy lifting (sanitization, re-parameterization, tag-based
dashboard export, round-trip check); the CLI unpacks the returned archive into
a ``<template_id>/`` directory ready to drop into ``depictio/projects/``.
"""

import io
import zipfile
from pathlib import Path
from typing import Annotated, Optional

import httpx
import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.command()
def export(
    project_id: Annotated[str, typer.Argument(help="Project ID to export")],
    template_id: Annotated[
        str, typer.Option("--template-id", "-t", help="Template id, e.g. 'my-lab/rnaseq-qc/1'")
    ],
    config_path: Annotated[str, typer.Option("--config", "-c", help="Path to CLI config file")],
    output_dir: Annotated[
        Path, typer.Option("--output-dir", "-o", help="Directory to unpack the bundle into")
    ] = Path("."),
    version: Annotated[str, typer.Option("--version", help="Template version")] = "1.0.0",
    description: Annotated[
        Optional[str], typer.Option("--description", help="Template description")
    ] = None,
    data_root: Annotated[
        Optional[str],
        typer.Option(
            "--data-root",
            help="Local path prefix to re-parameterize as {DATA_ROOT} in the template",
        ),
    ] = None,
    api_url: Annotated[str, typer.Option("--api", help="API base URL")] = "http://localhost:8058",
) -> None:
    """Export a project + its dashboards as a template bundle.

    Example:
        depictio template export 6824cb3b89d2b72169309737 \\
          --template-id my-lab/rnaseq-qc/1 --config admin_config.yaml -o depictio/projects
    """
    console.print("[cyan]Loading CLI configuration...[/cyan]")
    try:
        from depictio.cli.cli.utils.common import generate_api_headers, load_depictio_config

        cli_config = load_depictio_config(yaml_config_path=config_path)
        headers = generate_api_headers(cli_config)
        if api_url == "http://localhost:8058":
            api_url = str(cli_config.api_base_url)
    except Exception as e:
        console.print(f"[red]Error loading CLI config: {e}[/red]")
        console.print("[yellow]Hint: Run 'depictio config' to set up authentication[/yellow]")
        raise typer.Exit(1)

    url = f"{api_url}/depictio/api/v1/projects/{project_id}/export_template"
    payload = {
        "template_id": template_id,
        "version": version,
        "description": description,
        "data_root": data_root,
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
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(target)
        names = archive.namelist()
    console.print(f"[green]✓ Template bundle written to: {target}[/green]")
    for name in sorted(names):
        console.print(f"  - {name}")
    console.print(
        "[cyan]Drop the directory into depictio/projects/ (or a template search path) "
        "and it is auto-discovered.[/cyan]"
    )
