"""The `depictio images` group, out of the help and kept for scripts.

`images push` is `depictio data push-images` under its former name (the benchmark
runner calls it), and `images list-bucket` lists the images under an S3 path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from depictio.cli.cli.commands.data import push_images
from depictio.cli.cli.utils.image_upload import image_storage, is_image_file, parse_s3_folder
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

# Its own help, not push_images's docstring: that is data push-images's help, which
# says "Formerly `images push`".
app.command(
    "push",
    help=(
        "The former name of `depictio data push-images`, kept for compatibility: it "
        "takes the same arguments and options and does the same. "
        "See `depictio data push-images --help`."
    ),
)(push_images)


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
    try:
        bucket, prefix = parse_s3_folder(s3_path)
    except ValueError:
        rich_print_checked_statement(
            "S3 path must start with 's3://' (e.g., s3://bucket/path/)",
            "error",
        )
        raise typer.Exit(code=1)

    # Load S3 configuration
    from depictio.cli.cli.utils.common import load_depictio_config

    CLI_config = load_depictio_config(resolve_server(server, CLI_config_path))

    try:
        storage = image_storage(CLI_config)
    except Exception as e:
        rich_print_checked_statement(f"Failed to initialize S3 client: {e}", "error")
        raise typer.Exit(code=1)
    if storage.key_of(s3_path) is None:
        rich_print_checked_statement(
            f"{s3_path} is not in the server's bucket ({storage.url()})", "error"
        )
        raise typer.Exit(code=1)

    rich_print_section_separator(f"Listing: {storage.url(prefix)}")

    try:
        from rich.table import Table

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Key", style="dim", max_width=80)
        table.add_column("Size", justify="right")
        table.add_column("Last Modified", style="dim")

        count = 0
        total_size = 0

        for obj in storage.list_objects(prefix):
            if count >= max_items:
                break

            modified = obj.last_modified.strftime("%Y-%m-%d %H:%M") if obj.last_modified else ""

            # Only show image files
            if is_image_file(Path(obj.key)):
                table.add_row(obj.key, _format_size(obj.size), modified)
                count += 1
                total_size += obj.size

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
