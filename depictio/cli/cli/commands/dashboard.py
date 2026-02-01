"""
Dashboard CLI commands.

Provides three simple commands for dashboard YAML management:
- validate: Validate a YAML file locally
- import: Import YAML to server (project from YAML or --project override)
- export: Export dashboard from server to YAML
"""

from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console

app = typer.Typer(help="Dashboard management commands")
console = Console()


def _format_validation_error(error: Any) -> dict[str, str]:
    """Format a single validation error for display."""
    if isinstance(error, dict):
        loc = error.get("loc", ())
        msg = error.get("msg", str(error))
        field = ".".join(str(x) for x in loc) if loc else "-"
        return {"component_id": "-", "field": field, "message": msg}
    return {"component_id": "-", "field": "-", "message": str(error)}


def _make_error_result(message: str) -> dict[str, Any]:
    """Create a validation result for a single error."""
    return {
        "valid": False,
        "errors": [{"component_id": "-", "field": "-", "message": message}],
        "warnings": [],
    }


def validate_yaml_with_pydantic(yaml_file: Path) -> dict[str, Any]:
    """Validate a YAML file using DashboardDataLite Pydantic model.

    Args:
        yaml_file: Path to YAML file

    Returns:
        Dict with 'valid', 'errors', 'warnings' keys
    """
    from depictio.models.models.dashboards import DashboardDataLite

    try:
        content = yaml_file.read_text(encoding="utf-8")
        is_valid, errors = DashboardDataLite.validate_yaml(content)
        formatted_errors = [_format_validation_error(e) for e in errors]
        return {"valid": is_valid, "errors": formatted_errors, "warnings": []}
    except FileNotFoundError:
        return _make_error_result(f"File not found: {yaml_file}")
    except Exception as e:
        return _make_error_result(str(e))


@app.command()
def validate(
    yaml_file: Annotated[Path, typer.Argument(help="Path to YAML dashboard file")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Validate a dashboard YAML file locally.

    Uses DashboardDataLite Pydantic schema to validate the YAML structure.
    This is a local-only operation that doesn't require server connection.

    Example:
        depictio dashboard validate dashboard.yaml
        depictio dashboard validate dashboard.yaml --verbose
    """
    from rich.table import Table

    if not yaml_file.exists():
        console.print(f"[red]Error: File not found: {yaml_file}[/red]")
        raise typer.Exit(1)

    console.print(f"Validating: {yaml_file}")

    result = validate_yaml_with_pydantic(yaml_file)

    if result["valid"]:
        console.print("[green]✓ Validation passed[/green]")
        console.print(f"  Errors: {len(result['errors'])}")
        console.print(f"  Warnings: {len(result['warnings'])}")

        if verbose and result["warnings"]:
            console.print("\n[yellow]Warnings:[/yellow]")
            for warning in result["warnings"]:
                console.print(f"  - {warning['message']}")

        raise typer.Exit(0)
    else:
        console.print("[red]✗ Validation failed[/red]")
        console.print(f"  Errors: {len(result['errors'])}")
        console.print(f"  Warnings: {len(result['warnings'])}")

        # Show errors in table
        if result["errors"]:
            table = Table(title="Validation Errors")
            table.add_column("Component", style="cyan")
            table.add_column("Field", style="magenta")
            table.add_column("Message", style="red")

            for error in result["errors"]:
                table.add_row(
                    error.get("component_id") or "-",
                    error.get("field") or "-",
                    error["message"],
                )

            console.print(table)

        raise typer.Exit(1)


@app.command("import")
def import_yaml(
    yaml_file: Annotated[Path, typer.Argument(help="Path to YAML dashboard file")],
    config_path: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to CLI config file (required unless --dry-run)"),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option("--project", "-p", help="Project ID (overrides project_tag in YAML)"),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Overwrite existing dashboard with same title in project"),
    ] = False,
    api_url: Annotated[str, typer.Option("--api", help="API base URL")] = "http://localhost:8058",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate only, don't import")] = False,
) -> None:
    """Import a dashboard YAML file to the server.

    The project is determined in this order:
    1. --project option (if provided)
    2. project_tag field in the YAML file

    Requires --config for server import (not needed for --dry-run validation).

    Example:
        # Validate without server (no config needed)
        depictio dashboard import dashboard.yaml --dry-run

        # Import with config file
        depictio dashboard import dashboard.yaml --config admin_config.yaml

        # Overwrite existing dashboard with same title
        depictio dashboard import dashboard.yaml --config admin_config.yaml --overwrite

        # Override with explicit project ID
        depictio dashboard import dashboard.yaml --config admin_config.yaml --project 646b0f3c1e4a2d7f8e5b8c9a
    """
    from depictio.models.models.dashboards import DashboardDataLite

    if not yaml_file.exists():
        console.print(f"[red]Error: File not found: {yaml_file}[/red]")
        raise typer.Exit(1)

    # Step 1: Validate locally
    console.print(f"[cyan]Validating:[/cyan] {yaml_file}")
    result = validate_yaml_with_pydantic(yaml_file)

    if not result["valid"]:
        console.print("[red]✗ Validation failed[/red]")
        for error in result["errors"]:
            console.print(f"  [red]- {error['message']}[/red]")
        raise typer.Exit(1)

    console.print("[green]✓ Validation passed[/green]")

    # Load YAML content
    yaml_content = yaml_file.read_text(encoding="utf-8")
    lite = DashboardDataLite.from_yaml(yaml_content)

    console.print(f"  Title: {lite.title}")
    console.print(f"  Components: {len(lite.components)}")

    # Show project source
    if project:
        console.print(f"  Project: {project} (from --project)")
    elif lite.project_tag:
        console.print(f"  Project: {lite.project_tag} (from YAML project_tag)")
    else:
        console.print(
            "[yellow]  Warning: No project specified. "
            "Use --project or add project_tag to YAML.[/yellow]"
        )

    if dry_run:
        console.print("\n[yellow]Dry run mode - skipping import[/yellow]")
        raise typer.Exit(0)

    # Config is required for server import
    if not config_path:
        console.print("[red]Error: --config is required for server import[/red]")
        console.print("[yellow]Hint: Use --dry-run for local validation without config[/yellow]")
        raise typer.Exit(1)

    # Step 2: Load CLI config for authentication
    console.print("\n[cyan]Loading CLI configuration...[/cyan]")
    try:
        from depictio.cli.cli.utils.common import generate_api_headers, load_depictio_config

        cli_config = load_depictio_config(yaml_config_path=config_path)
        headers = generate_api_headers(cli_config)
        # Use API URL from config if not overridden
        if api_url == "http://localhost:8058":
            api_url = str(cli_config.api_base_url)
        console.print("[green]✓ Configuration loaded[/green]")
        console.print(f"  API URL: {api_url}")
    except Exception as e:
        console.print(f"[red]Error loading CLI config: {e}[/red]")
        console.print("[yellow]Hint: Run 'depictio config' to set up authentication[/yellow]")
        raise typer.Exit(1)

    # Step 3: Import to API
    project_display = project or lite.project_tag or "server lookup"
    action = "Updating" if overwrite else "Importing"
    console.print(f"\n[cyan]{action} dashboard (project: {project_display})...[/cyan]")

    url = f"{api_url}/depictio/api/v1/dashboards/import/yaml"

    try:
        # Build params - only include project_id if explicitly provided
        params: dict[str, str | bool] = {"yaml_content": yaml_content}
        if project:
            params["project_id"] = project
        if overwrite:
            params["overwrite"] = True

        with httpx.Client(timeout=60) as client:
            response = client.post(
                url,
                params=params,
                headers=headers,
            )

            if response.status_code != 200:
                console.print(f"[red]✗ Import failed: HTTP {response.status_code}[/red]")
                try:
                    error_detail = response.json().get("detail", response.text)
                except Exception:
                    error_detail = response.text
                console.print(f"  {error_detail}")
                raise typer.Exit(1)

            data = response.json()
            action_done = "updated" if data.get("updated") else "imported"
            console.print(f"[green]✓ Dashboard {action_done} successfully![/green]")
            console.print(f"  Dashboard ID: {data.get('dashboard_id')}")
            console.print(f"  Title: {data.get('title')}")
            console.print(f"  Project ID: {data.get('project_id')}")
            base_url = api_url.replace("/depictio/api/v1", "")
            console.print(
                f"\n[cyan]View at:[/cyan] {base_url}/dashboard/{data.get('dashboard_id')}"
            )

    except httpx.ConnectError:
        console.print(f"[red]Error: Cannot connect to API at {api_url}[/red]")
        console.print("[yellow]Hint: Make sure the Depictio API server is running[/yellow]")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def export(
    dashboard_id: Annotated[str, typer.Argument(help="Dashboard ID to export")],
    config_path: Annotated[str, typer.Option("--config", "-c", help="Path to CLI config file")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Output file path")] = Path(
        "dashboard.yaml"
    ),
    api_url: Annotated[str, typer.Option("--api", help="API base URL")] = "http://localhost:8058",
) -> None:
    """Export a dashboard from the server to a YAML file.

    Downloads the dashboard configuration and saves it as a minimal YAML file
    suitable for version control and re-import.

    Requires --config for authentication.

    Example:
        depictio dashboard export 6824cb3b89d2b72169309737 --config admin_config.yaml
        depictio dashboard export 6824cb3b89d2b72169309737 --config admin_config.yaml -o my-dashboard.yaml
    """
    # Load CLI config for authentication
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

    url = f"{api_url}/depictio/api/v1/dashboards/{dashboard_id}/yaml"
    console.print(f"[cyan]Exporting dashboard {dashboard_id}...[/cyan]")

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()

            output.write_text(response.text, encoding="utf-8")
            console.print(f"[green]✓ Dashboard exported to: {output}[/green]")

    except httpx.HTTPStatusError as e:
        console.print(f"[red]Error: HTTP {e.response.status_code}[/red]")
        console.print(f"  {e.response.text}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
