"""
Dashboard validation CLI commands.

Provides commands for validating dashboard YAML files before deployment.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Dashboard validation commands")
console = Console()


@app.command()
def validate(
    yaml_file: Annotated[Path, typer.Argument(help="Path to YAML dashboard file")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    check_columns: Annotated[bool, typer.Option("--check-columns/--no-check-columns")] = True,
    check_types: Annotated[bool, typer.Option("--check-types/--no-check-types")] = True,
) -> None:
    """Validate a dashboard YAML file."""
    from depictio.models.yaml_serialization.validation import validate_yaml_file

    if not yaml_file.exists():
        console.print(f"[red]Error: File not found: {yaml_file}[/red]")
        raise typer.Exit(1)

    console.print(f"Validating: {yaml_file}")
    if check_columns:
        console.print("  [dim]Including column name validation[/dim]")
    if check_types:
        console.print("  [dim]Including component type validation[/dim]")

    result = validate_yaml_file(
        str(yaml_file), check_column_names=check_columns, check_component_types=check_types
    )

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
    check_columns: Annotated[bool, typer.Option("--check-columns/--no-check-columns")] = True,
    check_types: Annotated[bool, typer.Option("--check-types/--no-check-types")] = True,
) -> None:
    """Validate all YAML files in a directory."""
    from depictio.models.yaml_serialization.validation import validate_yaml_file

    pattern = "**/*.yaml" if recursive else "*.yaml"
    yaml_files = list(directory.glob(pattern))

    if not yaml_files:
        console.print(f"[yellow]No YAML files found in {directory}[/yellow]")
        raise typer.Exit(0)

    console.print(f"Found {len(yaml_files)} YAML files")
    if check_columns:
        console.print("  [dim]Including column name validation[/dim]")
    if check_types:
        console.print("  [dim]Including component type validation[/dim]")
    console.print()

    valid_count = 0
    invalid_count = 0

    table = Table(title="Validation Results")
    table.add_column("File", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Errors", style="red")

    for yaml_file in yaml_files:
        result = validate_yaml_file(
            str(yaml_file), check_column_names=check_columns, check_component_types=check_types
        )

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
