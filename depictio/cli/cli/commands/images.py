"""
Image management CLI commands.

Provides commands to scan, process, and push images to S3/MinIO storage
for use with the image component in depictio dashboards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from depictio.cli.cli.utils.rich_utils import (
    console,
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_section_separator,
)
from depictio.cli.cli_logging import logger

app = typer.Typer()

# Supported image extensions
SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".tiff",
    ".tif",
}


def _is_image_file(path: Path) -> bool:
    """Check if a file is a supported image format."""
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def _scan_directory_for_images(
    directory: Path,
    recursive: bool = True,
    extensions: set[str] | None = None,
) -> list[Path]:
    """
    Scan a directory for image files.

    Args:
        directory: Directory path to scan
        recursive: Whether to scan subdirectories
        extensions: Set of extensions to look for (defaults to all supported)

    Returns:
        List of image file paths found
    """
    if extensions is None:
        extensions = SUPPORTED_IMAGE_EXTENSIONS

    images: list[Path] = []

    if recursive:
        for ext in extensions:
            images.extend(directory.rglob(f"*{ext}"))
            # Also check uppercase extensions
            images.extend(directory.rglob(f"*{ext.upper()}"))
    else:
        for ext in extensions:
            images.extend(directory.glob(f"*{ext}"))
            images.extend(directory.glob(f"*{ext.upper()}"))

    # Remove duplicates and sort
    return sorted(set(images))


@app.command()
def scan(
    directory: Annotated[
        str,
        typer.Argument(help="Directory to scan for images"),
    ],
    recursive: bool = typer.Option(
        True, "--recursive/--no-recursive", "-r/-R", help="Scan subdirectories recursively"
    ),
    output_csv: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Output CSV file path for image listing"),
    ] = None,
    extensions: Annotated[
        str | None,
        typer.Option(
            "--extensions",
            "-e",
            help="Comma-separated list of extensions to scan (e.g., '.png,.jpg')",
        ),
    ] = None,
    show_stats: bool = typer.Option(
        True, "--stats/--no-stats", help="Show statistics about found images"
    ),
):
    """
    Scan a directory for image files.

    This command scans a directory for supported image formats and optionally
    outputs a CSV file listing all found images with their relative paths.

    Examples:
        # Scan current directory
        depictio images scan ./data/images

        # Scan with specific extensions
        depictio images scan ./data/images --extensions ".png,.jpg"

        # Output to CSV for data collection
        depictio images scan ./data/images --output images.csv
    """
    rich_print_command_usage("images scan")

    dir_path = Path(directory).expanduser().resolve()

    if not dir_path.exists():
        rich_print_checked_statement(f"Directory does not exist: {dir_path}", "error")
        raise typer.Exit(code=1)

    if not dir_path.is_dir():
        rich_print_checked_statement(f"Path is not a directory: {dir_path}", "error")
        raise typer.Exit(code=1)

    # Parse extensions if provided
    ext_set: set[str] | None = None
    if extensions:
        ext_set = {ext.strip().lower() for ext in extensions.split(",")}
        # Add leading dot if missing
        ext_set = {ext if ext.startswith(".") else f".{ext}" for ext in ext_set}

    rich_print_section_separator(f"Scanning: {dir_path}")

    # Scan for images
    images = _scan_directory_for_images(dir_path, recursive=recursive, extensions=ext_set)

    if not images:
        rich_print_checked_statement("No images found in directory", "warning")
        raise typer.Exit(code=0)

    console.print(f"\n[bold green]Found {len(images)} images[/bold green]\n")

    # Show statistics
    if show_stats:
        from collections import Counter

        ext_counts = Counter(img.suffix.lower() for img in images)

        from rich.table import Table

        table = Table(title="Image Statistics", show_header=True, header_style="bold cyan")
        table.add_column("Extension", style="dim")
        table.add_column("Count", justify="right")
        table.add_column("Percentage", justify="right")

        total = len(images)
        for ext, count in sorted(ext_counts.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total) * 100
            table.add_row(ext, str(count), f"{pct:.1f}%")

        console.print(table)
        console.print()

    # Show sample of images found
    console.print("[bold]Sample images found:[/bold]")
    for img in images[:10]:
        rel_path = img.relative_to(dir_path)
        console.print(f"  - {rel_path}")
    if len(images) > 10:
        console.print(f"  ... and {len(images) - 10} more")

    # Output to CSV if requested
    if output_csv:
        import csv

        output_path = Path(output_csv).expanduser().resolve()

        with output_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["relative_path", "filename", "extension", "size_bytes"])

            for img in images:
                rel_path = img.relative_to(dir_path)
                writer.writerow(
                    [
                        str(rel_path),
                        img.name,
                        img.suffix.lower(),
                        img.stat().st_size,
                    ]
                )

        console.print(f"\n[bold]Image listing saved to:[/bold] {output_path}")
        rich_print_checked_statement(f"Exported {len(images)} images to CSV", "success")

    rich_print_checked_statement(f"Scan complete: {len(images)} images found", "success")


@app.command()
def push(
    source_directory: Annotated[
        str,
        typer.Argument(help="Source directory containing images"),
    ],
    s3_destination: Annotated[
        str,
        typer.Argument(help="S3 destination path (e.g., s3://bucket/path/to/images/)"),
    ],
    recursive: bool = typer.Option(
        True, "--recursive/--no-recursive", "-r/-R", help="Include subdirectories"
    ),
    extensions: Annotated[
        str | None,
        typer.Option(
            "--extensions",
            "-e",
            help="Comma-separated list of extensions to upload (e.g., '.png,.jpg')",
        ),
    ] = None,
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be uploaded without actually uploading"
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing files in S3"),
    CLI_config_path: Annotated[
        str,
        typer.Option("--CLI-config-path", help="Path to the CLI configuration file"),
    ] = "~/.depictio/CLI.yaml",
):
    """
    Push images from a local directory to S3/MinIO storage.

    This command uploads image files to S3-compatible storage, preserving
    the directory structure relative to the source directory.

    Examples:
        # Push all images to S3
        depictio images push ./data/images s3://my-bucket/project/images/

        # Dry run to see what would be uploaded
        depictio images push ./data/images s3://my-bucket/images/ --dry-run

        # Push only specific extensions
        depictio images push ./data/images s3://my-bucket/images/ --extensions ".png,.jpg"
    """
    rich_print_command_usage("images push")

    # Resolve source directory
    source_path = Path(source_directory).expanduser().resolve()

    if not source_path.exists():
        rich_print_checked_statement(f"Source directory does not exist: {source_path}", "error")
        raise typer.Exit(code=1)

    if not source_path.is_dir():
        rich_print_checked_statement(f"Source path is not a directory: {source_path}", "error")
        raise typer.Exit(code=1)

    # Parse S3 destination
    if not s3_destination.startswith("s3://"):
        rich_print_checked_statement(
            "S3 destination must start with 's3://' (e.g., s3://bucket/path/)",
            "error",
        )
        raise typer.Exit(code=1)

    # Parse bucket and prefix from s3://bucket/prefix/
    s3_parts = s3_destination[5:].split("/", 1)
    bucket = s3_parts[0]
    prefix = s3_parts[1].rstrip("/") + "/" if len(s3_parts) > 1 else ""

    # Parse extensions if provided
    ext_set: set[str] | None = None
    if extensions:
        ext_set = {ext.strip().lower() for ext in extensions.split(",")}
        ext_set = {ext if ext.startswith(".") else f".{ext}" for ext in ext_set}

    rich_print_section_separator("Uploading images to S3")

    # Scan for images
    images = _scan_directory_for_images(source_path, recursive=recursive, extensions=ext_set)

    if not images:
        rich_print_checked_statement("No images found to upload", "warning")
        raise typer.Exit(code=0)

    console.print(f"[bold]Source:[/bold] {source_path}")
    console.print(f"[bold]Destination:[/bold] s3://{bucket}/{prefix}")
    console.print(f"[bold]Images found:[/bold] {len(images)}")

    if dry_run:
        console.print("\n[yellow][DRY RUN] Would upload:[/yellow]")
        for img in images[:20]:
            rel_path = img.relative_to(source_path)
            s3_key = f"{prefix}{rel_path}".replace("\\", "/")
            console.print(f"  {rel_path} → s3://{bucket}/{s3_key}")
        if len(images) > 20:
            console.print(f"  ... and {len(images) - 20} more")
        rich_print_checked_statement(
            f"Dry run complete: {len(images)} images would be uploaded", "success"
        )
        raise typer.Exit(code=0)

    # Load S3 configuration
    from depictio.cli.cli.utils.common import load_depictio_config

    CLI_config = load_depictio_config(CLI_config_path)

    # Initialize S3 client
    import boto3

    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=CLI_config.s3_storage.root_user,
            aws_secret_access_key=CLI_config.s3_storage.root_password,
            endpoint_url=CLI_config.s3_storage.url,
        )
    except Exception as e:
        rich_print_checked_statement(f"Failed to initialize S3 client: {e}", "error")
        raise typer.Exit(code=1)

    # Upload images with progress
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

    uploaded = 0
    skipped = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Uploading images...", total=len(images))

        for img in images:
            rel_path = img.relative_to(source_path)
            s3_key = f"{prefix}{rel_path}".replace("\\", "/")

            try:
                # Check if file exists (unless overwrite is set)
                if not overwrite:
                    try:
                        s3_client.head_object(Bucket=bucket, Key=s3_key)
                        skipped += 1
                        progress.update(task, advance=1)
                        continue
                    except s3_client.exceptions.ClientError:
                        pass  # File doesn't exist, proceed with upload

                # Upload the file
                s3_client.upload_file(
                    str(img),
                    bucket,
                    s3_key,
                    ExtraArgs={"ContentType": _get_content_type(img)},
                )
                uploaded += 1
                logger.debug(f"Uploaded: {rel_path} → s3://{bucket}/{s3_key}")

            except Exception as e:
                errors += 1
                logger.error(f"Failed to upload {rel_path}: {e}")

            progress.update(task, advance=1)

    # Print summary
    console.print()
    rich_print_section_separator("Upload Summary")

    from rich.table import Table

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Status", style="dim")
    table.add_column("Count", justify="right")

    table.add_row("[green]Uploaded[/green]", str(uploaded))
    table.add_row("[yellow]Skipped (existing)[/yellow]", str(skipped))
    table.add_row("[red]Errors[/red]", str(errors))
    table.add_row("[bold]Total[/bold]", str(len(images)))

    console.print(table)

    if errors > 0:
        rich_print_checked_statement(f"Upload completed with {errors} errors", "warning")
    else:
        rich_print_checked_statement(f"Successfully uploaded {uploaded} images", "success")


def _get_content_type(path: Path) -> str:
    """Get MIME content type for an image file."""
    import mimetypes

    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type or "application/octet-stream"


@app.command()
def list_bucket(
    s3_path: Annotated[
        str,
        typer.Argument(help="S3 path to list (e.g., s3://bucket/prefix/)"),
    ],
    CLI_config_path: Annotated[
        str,
        typer.Option("--CLI-config-path", help="Path to the CLI configuration file"),
    ] = "~/.depictio/CLI.yaml",
    max_items: int = typer.Option(100, "--max", "-m", help="Maximum number of items to list"),
):
    """
    List images in an S3 bucket/prefix.

    Examples:
        # List images in a bucket
        depictio images list-bucket s3://my-bucket/images/

        # List with limit
        depictio images list-bucket s3://my-bucket/images/ --max 50
    """
    rich_print_command_usage("images list-bucket")

    # Parse S3 path
    if not s3_path.startswith("s3://"):
        rich_print_checked_statement(
            "S3 path must start with 's3://' (e.g., s3://bucket/path/)",
            "error",
        )
        raise typer.Exit(code=1)

    s3_parts = s3_path[5:].split("/", 1)
    bucket = s3_parts[0]
    prefix = s3_parts[1] if len(s3_parts) > 1 else ""

    # Load S3 configuration
    from depictio.cli.cli.utils.common import load_depictio_config

    CLI_config = load_depictio_config(CLI_config_path)

    # Initialize S3 client
    import boto3

    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=CLI_config.s3_storage.root_user,
            aws_secret_access_key=CLI_config.s3_storage.root_password,
            endpoint_url=CLI_config.s3_storage.url,
        )
    except Exception as e:
        rich_print_checked_statement(f"Failed to initialize S3 client: {e}", "error")
        raise typer.Exit(code=1)

    rich_print_section_separator(f"Listing: s3://{bucket}/{prefix}")

    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

        from rich.table import Table

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Key", style="dim", max_width=80)
        table.add_column("Size", justify="right")
        table.add_column("Last Modified", style="dim")

        count = 0
        total_size = 0

        for page in pages:
            for obj in page.get("Contents", []):
                if count >= max_items:
                    break

                key = obj["Key"]
                size = obj["Size"]
                modified = obj["LastModified"].strftime("%Y-%m-%d %H:%M")

                # Only show image files
                if _is_image_file(Path(key)):
                    table.add_row(key, _format_size(size), modified)
                    count += 1
                    total_size += size

            if count >= max_items:
                break

        console.print(table)
        console.print(
            f"\n[dim]Showing {count} images (total size: {_format_size(total_size)})[/dim]"
        )

        if count >= max_items:
            console.print(
                f"[yellow]Listing truncated at {max_items} items. Use --max to show more.[/yellow]"
            )

    except Exception as e:
        rich_print_checked_statement(f"Failed to list bucket: {e}", "error")
        raise typer.Exit(code=1)


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
