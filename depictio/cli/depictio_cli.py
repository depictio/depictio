import os

os.environ["DEPICTIO_CONTEXT"] = "CLI"

import typer
from typer.main import get_command

from depictio.cli.cli.commands.config import app as config
from depictio.cli.cli.commands.data import app as data
from depictio.cli.cli.commands.run import register_run_command
from depictio.cli.cli.commands.standalone import register_standalone_commands
from depictio.cli.cli.utils.rich_utils import add_rich_display_to_polars
from depictio.cli.cli_logging import setup_logging as setup_cli_logging
from depictio.models.logging import setup_logging as setup_models_logging

app = typer.Typer()

# Register standalone commands (version, status, etc.)
register_standalone_commands(app)

# Register the run command
register_run_command(app)


@app.callback()
def verbose_callback(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging", is_eager=True
    ),
    verbose_level=typer.Option(
        "INFO",
        "--verbose-level",
        "-vl",
        help="Set verbose logging level",
        is_eager=True,
    ),
):
    """Set up logging for all commands"""
    # Set up both CLI and models logging with the same verbose settings
    setup_cli_logging(verbose, verbose_level)
    setup_models_logging(verbose, verbose_level)


app.add_typer(config, name="config")
app.add_typer(data, name="data")
depictiocli = get_command(app)


def main():
    # rich print welcome statement
    from rich import print
    from rich.panel import Panel
    from rich.text import Text

    # Add rich display support for Polars DataFrames
    add_rich_display_to_polars()

    # Define text with colors inspired by the logo
    welcome_text = Text()
    welcome_text.append("Welcome to Depictio CLI!")

    # Create panel with border color to match logo theme
    print(
        Panel.fit(
            welcome_text,
            border_style="bright_blue",
            title="✨ Depictio CLI ✨",
            title_align="center",
        )
    )
    app()
