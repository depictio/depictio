#!/usr/bin/env python3
"""
Migration Script: YAML to JSON Dashboard Conversion

This script converts existing YAML dashboard files to the simpler JSON format.
Run once during transition from YAML system to JSON system.

Usage:
    python scripts/migrate_yaml_to_json.py --yaml-dir dashboards/local --output-dir dashboards/json

Features:
- Converts all 3 YAML formats (legacy, compact, MVP) to standard JSON
- Preserves dashboard structure and data
- Creates backup before conversion
- Validates JSON output against Pydantic schema
- Generates migration report
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from rich.console import Console
from rich.progress import track
from rich.table import Table

console = Console()


def convert_yaml_to_json(yaml_path: Path) -> dict[str, Any]:
    """
    Convert YAML dashboard to JSON format.

    Handles all 3 YAML formats automatically.
    """
    from depictio.models.yaml_serialization import import_dashboard_from_file

    # Use existing YAML loader (works for all formats)
    dashboard_dict = import_dashboard_from_file(yaml_path)

    return dashboard_dict


def validate_json_dashboard(data: dict) -> tuple[bool, list[str]]:
    """
    Validate JSON dashboard against Pydantic schema.

    Returns:
        (is_valid, errors)
    """
    from depictio.models.models.dashboards import DashboardData
    from pydantic import ValidationError

    try:
        DashboardData.model_validate(data)
        return True, []
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        return False, errors


def save_json_dashboard(data: dict, output_path: Path) -> None:
    """Save dashboard as JSON file with BSON type markers."""
    # Convert ObjectId instances to BSON JSON format
    from bson import json_util

    with open(output_path, "w") as f:
        # Use json_util to handle ObjectId serialization
        json.dump(data, f, indent=2, default=json_util.default)


def create_backup(yaml_dir: Path, backup_dir: Path) -> None:
    """Create backup of YAML directory before migration."""
    if not yaml_dir.exists():
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"yaml_backup_{timestamp}"

    console.print(f"[yellow]Creating backup: {backup_path}[/yellow]")
    shutil.copytree(yaml_dir, backup_path)
    console.print(f"[green]✓ Backup created[/green]")


def migrate_directory(
    yaml_dir: Path,
    output_dir: Path,
    validate: bool = True,
) -> dict[str, Any]:
    """
    Migrate all YAML files in directory to JSON.

    Returns:
        Migration statistics
    """
    stats = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "errors": [],
    }

    # Find all YAML files
    yaml_files = list(yaml_dir.rglob("*.yaml")) + list(yaml_dir.rglob("*.yml"))
    stats["total"] = len(yaml_files)

    if stats["total"] == 0:
        console.print(f"[yellow]No YAML files found in {yaml_dir}[/yellow]")
        return stats

    console.print(f"\n[cyan]Found {stats['total']} YAML files[/cyan]")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert each file
    for yaml_path in track(yaml_files, description="Converting..."):
        try:
            # Convert YAML to JSON
            dashboard_data = convert_yaml_to_json(yaml_path)

            # Validate if requested
            if validate:
                is_valid, errors = validate_json_dashboard(dashboard_data)
                if not is_valid:
                    console.print(f"[red]✗ Validation failed: {yaml_path.name}[/red]")
                    for error in errors:
                        console.print(f"  [red]- {error}[/red]")
                    stats["failed"] += 1
                    stats["errors"].append({
                        "file": str(yaml_path),
                        "errors": errors,
                    })
                    continue

            # Determine output path (preserve directory structure)
            relative_path = yaml_path.relative_to(yaml_dir)
            output_path = output_dir / relative_path.with_suffix(".json")
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Save JSON
            save_json_dashboard(dashboard_data, output_path)

            stats["success"] += 1

        except Exception as e:
            console.print(f"[red]✗ Failed: {yaml_path.name}[/red]")
            console.print(f"  [red]Error: {str(e)}[/red]")
            stats["failed"] += 1
            stats["errors"].append({
                "file": str(yaml_path),
                "errors": [str(e)],
            })

    return stats


def print_migration_report(stats: dict[str, Any]) -> None:
    """Print migration report table."""
    console.print("\n" + "=" * 80)
    console.print("[bold cyan]Migration Report[/bold cyan]")
    console.print("=" * 80)

    # Summary table
    table = Table(show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="green")

    table.add_row("Total Files", str(stats["total"]))
    table.add_row("Successful", str(stats["success"]))
    table.add_row("Failed", str(stats["failed"]))

    console.print(table)

    # Error details
    if stats["errors"]:
        console.print("\n[bold red]Errors:[/bold red]")
        for error in stats["errors"]:
            console.print(f"\n[red]File: {error['file']}[/red]")
            for err_msg in error["errors"]:
                console.print(f"  [red]- {err_msg}[/red]")

    # Success message
    if stats["failed"] == 0:
        console.print("\n[bold green]✓ All files migrated successfully![/bold green]")
    else:
        console.print(f"\n[yellow]⚠ {stats['failed']} files failed migration[/yellow]")


def generate_size_comparison(yaml_dir: Path, json_dir: Path) -> None:
    """Compare total size of YAML vs JSON files."""
    yaml_size = sum(f.stat().st_size for f in yaml_dir.rglob("*.yaml"))
    yaml_size += sum(f.stat().st_size for f in yaml_dir.rglob("*.yml"))

    json_size = sum(f.stat().st_size for f in json_dir.rglob("*.json"))

    if yaml_size == 0:
        return

    reduction_pct = ((yaml_size - json_size) / yaml_size) * 100

    console.print("\n[bold cyan]Size Comparison:[/bold cyan]")
    console.print(f"  YAML total:  {yaml_size / 1024:.2f} KB")
    console.print(f"  JSON total:  {json_size / 1024:.2f} KB")
    console.print(f"  Reduction:   {reduction_pct:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate YAML dashboards to JSON format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate local dashboards
  python scripts/migrate_yaml_to_json.py --yaml-dir dashboards/local --output-dir dashboards/json

  # Migrate templates
  python scripts/migrate_yaml_to_json.py --yaml-dir dashboards/templates --output-dir dashboards/templates_json

  # Skip validation (faster)
  python scripts/migrate_yaml_to_json.py --yaml-dir dashboards/local --output-dir dashboards/json --no-validate

  # Skip backup (not recommended)
  python scripts/migrate_yaml_to_json.py --yaml-dir dashboards/local --output-dir dashboards/json --no-backup
        """,
    )

    parser.add_argument(
        "--yaml-dir",
        type=Path,
        required=True,
        help="Directory containing YAML dashboard files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for JSON files",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("backups/yaml_migration"),
        help="Backup directory (default: backups/yaml_migration)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating backup before migration",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip Pydantic validation (faster but less safe)",
    )

    args = parser.parse_args()

    # Header
    console.print("\n" + "=" * 80)
    console.print("[bold cyan]YAML to JSON Dashboard Migration[/bold cyan]")
    console.print("=" * 80)

    # Create backup
    if not args.no_backup:
        create_backup(args.yaml_dir, args.backup_dir)

    # Migrate
    stats = migrate_directory(
        yaml_dir=args.yaml_dir,
        output_dir=args.output_dir,
        validate=not args.no_validate,
    )

    # Report
    print_migration_report(stats)

    # Size comparison
    if stats["success"] > 0:
        generate_size_comparison(args.yaml_dir, args.output_dir)

    # Next steps
    if stats["success"] > 0:
        console.print("\n[bold cyan]Next Steps:[/bold cyan]")
        console.print("1. Review migrated JSON files")
        console.print("2. Test import via API: POST /api/v1/dashboards/import/json")
        console.print("3. Update application configuration to use JSON format")
        console.print("4. Archive YAML files after confirming migration success")

    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    exit(main())
