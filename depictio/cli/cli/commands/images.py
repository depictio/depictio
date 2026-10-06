"""The `depictio images` group, out of the help and kept for scripts.

`images push` is `depictio data push-images` under its former name (the benchmark
runner calls it), and `images list-bucket` lists the images under an S3 path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from depictio.cli.cli.commands.data import push_images
from depictio.cli.cli.utils.image_upload import is_image_file, s3_client
from depictio.cli.cli.utils.rich_utils import (
    console,
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_section_separator,
)
from depictio.cli.cli.utils.server_target import (
    LegacyConfigPathOption,
    ServerOption,
    resolve_server,
)

app = typer.Typer()

app.command("push")(push_images)


@app.command()
def list_bucket(
    s3_path: Annotated[
        str,
        typer.Argument(help="S3 path to list (e.g., s3://bucket/prefix/)"),
    ],
    max_items: int = typer.Option(100, "--max", "-m", help="Maximum number of items to list"),
    server: ServerOption = None,
    CLI_config_path: LegacyConfigPathOption = None,
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

    CLI_config = load_depictio_config(resolve_server(server, CLI_config_path))

    try:
        client = s3_client(CLI_config)
    except Exception as e:
        rich_print_checked_statement(f"Failed to initialize S3 client: {e}", "error")
        raise typer.Exit(code=1)

    rich_print_section_separator(f"Listing: s3://{bucket}/{prefix}")

    try:
        paginator = client.get_paginator("list_objects_v2")
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
                if is_image_file(Path(key)):
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


def _format_size(size_bytes: float) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
