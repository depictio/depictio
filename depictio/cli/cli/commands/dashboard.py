"""
Dashboard validation CLI commands.

Provides commands for validating dashboard YAML files using DashboardDataLite
Pydantic models.
"""

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Dashboard validation commands")
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
