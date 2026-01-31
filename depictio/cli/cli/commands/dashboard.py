"""
Dashboard CLI commands.

Provides commands for validating, converting, and importing dashboard YAML files
using DashboardDataLite Pydantic models.
"""

from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Dashboard management commands")
console = Console()


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

        # Format errors for display
        formatted_errors = []
        for error in errors:
            if isinstance(error, dict):
                # Pydantic ValidationError format
                loc = error.get("loc", ())
                msg = error.get("msg", str(error))
                field = ".".join(str(x) for x in loc) if loc else "-"
                formatted_errors.append(
                    {
                        "component_id": "-",
                        "field": field,
                        "message": msg,
                    }
                )
            else:
                formatted_errors.append(
                    {
                        "component_id": "-",
                        "field": "-",
                        "message": str(error),
                    }
                )

        return {
            "valid": is_valid,
            "errors": formatted_errors,
            "warnings": [],
        }

    except FileNotFoundError:
        return {
            "valid": False,
            "errors": [
                {"component_id": "-", "field": "-", "message": f"File not found: {yaml_file}"}
            ],
            "warnings": [],
        }
    except Exception as e:
        return {
            "valid": False,
            "errors": [{"component_id": "-", "field": "-", "message": str(e)}],
            "warnings": [],
        }


@app.command()
def validate(
    yaml_file: Annotated[Path, typer.Argument(help="Path to YAML dashboard file")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Validate a dashboard YAML file using DashboardDataLite schema."""
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


@app.command()
def validate_dir(
    directory: Annotated[Path, typer.Argument(help="Directory to validate")] = Path("."),
    recursive: Annotated[bool, typer.Option("--recursive", "-r")] = True,
) -> None:
    """Validate all YAML files in a directory."""
    pattern = "**/*.yaml" if recursive else "*.yaml"
    yaml_files = list(directory.glob(pattern))

    if not yaml_files:
        console.print(f"[yellow]No YAML files found in {directory}[/yellow]")
        raise typer.Exit(0)

    console.print(f"Found {len(yaml_files)} YAML files")
    console.print()

    valid_count = 0
    invalid_count = 0

    table = Table(title="Validation Results")
    table.add_column("File", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Errors", style="red")

    for yaml_file in yaml_files:
        result = validate_yaml_with_pydantic(yaml_file)

        if result["valid"]:
            valid_count += 1
            status = "[green]✓ Valid[/green]"
        else:
            invalid_count += 1
            status = "[red]✗ Invalid[/red]"

        table.add_row(yaml_file.name, status, str(len(result["errors"])))

    console.print(table)
    console.print(f"\nSummary: {valid_count} valid, {invalid_count} invalid")

    if invalid_count > 0:
        raise typer.Exit(1)


@app.command()
def schema(
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output file path for JSON schema")
    ] = None,
) -> None:
    """Print or save the JSON schema for dashboard YAML validation."""
    import json

    from depictio.models.models.dashboards import DashboardDataLite

    schema_dict = DashboardDataLite.model_json_schema()
    schema_json = json.dumps(schema_dict, indent=2)

    if output:
        output.write_text(schema_json, encoding="utf-8")
        console.print(f"[green]Schema written to: {output}[/green]")
    else:
        console.print(schema_json)


@app.command()
def export(
    dashboard_id: Annotated[str, typer.Argument(help="Dashboard ID to export")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Output file path")] = Path(
        "dashboard.yaml"
    ),
    api_url: Annotated[str, typer.Option("--api", help="API base URL")] = "http://localhost:8058",
) -> None:
    """Export a dashboard to YAML file via API."""
    import httpx

    url = f"{api_url}/depictio/api/v1/dashboards/{dashboard_id}/yaml"

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url)
            response.raise_for_status()

            output.write_text(response.text, encoding="utf-8")
            console.print(f"[green]Dashboard exported to: {output}[/green]")

    except httpx.HTTPStatusError as e:
        console.print(f"[red]Error: HTTP {e.response.status_code}[/red]")
        console.print(f"  {e.response.text}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def convert(
    json_file: Annotated[Path, typer.Argument(help="Path to JSON dashboard file")],
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output YAML file path")
    ] = None,
) -> None:
    """Convert dashboard JSON to minimal YAML format (~60 lines).

    This converts a full dashboard JSON export to the minimal DashboardDataLite
    YAML format, which is human-readable and version-controllable.

    Example:
        depictio dashboard convert dashboard.json
        depictio dashboard convert dashboard.json -o output.yaml
    """
    import json

    from depictio.models.models.dashboards import DashboardDataLite

    if not json_file.exists():
        console.print(f"[red]Error: File not found: {json_file}[/red]")
        raise typer.Exit(1)

    try:
        # Load JSON data
        with json_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Convert to lite format
        lite = DashboardDataLite.from_full(data)
        yaml_content = lite.to_yaml()

        # Determine output path
        if output is None:
            output = json_file.with_suffix(".yaml")

        # Write YAML
        output.write_text(yaml_content, encoding="utf-8")

        # Show stats
        line_count = yaml_content.count("\n") + 1
        component_count = len(lite.components)

        console.print("[green]✓ Converted to minimal YAML format[/green]")
        console.print(f"  Output: {output}")
        console.print(f"  Lines: {line_count}")
        console.print(f"  Components: {component_count}")

    except json.JSONDecodeError as e:
        console.print(f"[red]Error: Invalid JSON: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def from_yaml(
    yaml_file: Annotated[Path, typer.Argument(help="Path to YAML dashboard file")],
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output JSON file path")
    ] = None,
) -> None:
    """Convert minimal YAML format back to full dashboard JSON.

    This converts a DashboardDataLite YAML file to full dashboard JSON format,
    resolving data collection and workflow references from MongoDB.

    Example:
        depictio dashboard from-yaml dashboard.yaml
        depictio dashboard from-yaml dashboard.yaml -o output.json
    """
    import json

    from depictio.models.models.dashboards import DashboardDataLite

    if not yaml_file.exists():
        console.print(f"[red]Error: File not found: {yaml_file}[/red]")
        raise typer.Exit(1)

    try:
        # Load and convert
        lite = DashboardDataLite.from_yaml_file(yaml_file)
        full_data = lite.to_full()

        # Determine output path
        if output is None:
            output = yaml_file.with_suffix(".json")

        # Write JSON
        with output.open("w", encoding="utf-8") as f:
            json.dump(full_data, f, indent=2, default=str)

        console.print("[green]✓ Converted to full dashboard JSON[/green]")
        console.print(f"  Output: {output}")
        console.print(f"  Components: {len(full_data.get('stored_metadata', []))}")

    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command("import")
def import_yaml(
    yaml_file: Annotated[Path, typer.Argument(help="Path to YAML dashboard file")],
    project_id: Annotated[str, typer.Option("--project", "-p", help="Project ID to import into")],
    api_url: Annotated[str, typer.Option("--api", help="API base URL")] = "http://localhost:8058",
    config_path: Annotated[
        str, typer.Option("--config", "-c", help="Path to CLI config file")
    ] = "~/.depictio/cli.yaml",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate only, don't import")] = False,
) -> None:
    """Import a dashboard YAML file to the server.

    This command validates the YAML file locally, then uploads it to the API
    to create a new dashboard in the specified project.

    Example:
        depictio dashboard import dashboard.yaml --project 646b0f3c1e4a2d7f8e5b8c9a
        depictio dashboard import dashboard.yaml -p 646b0f3c1e4a2d7f8e5b8c9a --dry-run
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

    if dry_run:
        console.print("\n[yellow]Dry run mode - skipping import[/yellow]")
        raise typer.Exit(0)

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
    console.print(f"\n[cyan]Importing dashboard to project {project_id}...[/cyan]")

    url = f"{api_url}/depictio/api/v1/dashboards/import/yaml"

    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(
                url,
                params={"yaml_content": yaml_content, "project_id": project_id},
                headers=headers,
            )

            if response.status_code == 200:
                data = response.json()
                console.print("[green]✓ Dashboard imported successfully![/green]")
                console.print(f"  Dashboard ID: {data.get('dashboard_id')}")
                console.print(f"  Title: {data.get('title')}")
                console.print(f"  Project ID: {data.get('project_id')}")
                console.print(
                    f"\n[cyan]View at:[/cyan] {api_url.replace('/depictio/api/v1', '')}"
                    f"/dashboard/{data.get('dashboard_id')}"
                )
            else:
                console.print(f"[red]✗ Import failed: HTTP {response.status_code}[/red]")
                try:
                    error_detail = response.json().get("detail", response.text)
                except Exception:
                    error_detail = response.text
                console.print(f"  {error_detail}")
                raise typer.Exit(1)

    except httpx.ConnectError:
        console.print(f"[red]Error: Cannot connect to API at {api_url}[/red]")
        console.print("[yellow]Hint: Make sure the Depictio API server is running[/yellow]")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def list_projects(
    api_url: Annotated[str, typer.Option("--api", help="API base URL")] = "http://localhost:8058",
    config_path: Annotated[
        str, typer.Option("--config", "-c", help="Path to CLI config file")
    ] = "~/.depictio/cli.yaml",
) -> None:
    """List available projects to import dashboards into.

    Example:
        depictio dashboard list-projects
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
        raise typer.Exit(1)

    console.print(f"[cyan]Fetching projects from {api_url}...[/cyan]\n")

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{api_url}/depictio/api/v1/projects/list",
                headers=headers,
            )

            if response.status_code == 200:
                projects = response.json()
                if not projects:
                    console.print("[yellow]No projects found[/yellow]")
                    raise typer.Exit(0)

                table = Table(title="Available Projects")
                table.add_column("ID", style="cyan")
                table.add_column("Name", style="green")
                table.add_column("Public", style="yellow")

                for project in projects:
                    project_id = project.get("_id") or project.get("id", "-")
                    name = project.get("name", "-")
                    is_public = "Yes" if project.get("is_public") else "No"
                    table.add_row(str(project_id), name, is_public)

                console.print(table)
                console.print(
                    "\n[dim]Use --project <ID> with 'depictio dashboard import' command[/dim]"
                )
            else:
                console.print(f"[red]Error: HTTP {response.status_code}[/red]")
                console.print(f"  {response.text}")
                raise typer.Exit(1)

    except httpx.ConnectError:
        console.print(f"[red]Error: Cannot connect to API at {api_url}[/red]")
        raise typer.Exit(1)
