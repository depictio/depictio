import os

os.environ["DEPICTIO_CONTEXT"] = "CLI"

import typer
from typer.main import get_command
from depictio.cli.cli.commands.config import app as config
from depictio.cli.cli.commands.data import app as data
from depictio.cli.logging import setup_logging


app = typer.Typer()


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
    setup_logging(verbose, verbose_level)


app.add_typer(config, name="config")
app.add_typer(data, name="data")
depictiocli = get_command(app)


def main():
    # rich print welcome statement
    from rich import print
    from rich.panel import Panel
    from rich.text import Text

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
