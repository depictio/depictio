import json
import sys

from pydantic import validate_call
from rich import print, print_json
from rich.console import Console
from rich.panel import Panel

console = Console(force_terminal=True)


@validate_call
def handle_error(message: str, exit: bool = False):
    """Print an error message and raise a ValueError."""
    print(f"• [bold red]:x: {message}[/bold red]")
    if exit:
        sys.exit()


@validate_call
def rich_print_command_usage(command: str):
    """
    Print the command usage in a styled panel.
    """
    console.print(
        Panel.fit(
            f"[bold magenta]{command}[/]",
            title="[cyan]Command Used[/]",
            border_style="bright_blue",
            title_align="center",
        )
    )


@validate_call
def rich_print_section_separator(title: str):
    """
    Print a section separator.
    """
    # get number of characters in title to determine length of separator
    console.print(
        Panel.fit(
            f"[bold magenta]{title}[/]",
            # title="[cyan]Section Separator[/]",
            border_style="bright_blue",
            title_align="center",
        )
    )


@validate_call
# json can be a dict or a list of dicts
def rich_print_json(statement: str, json_obj: dict | list[dict]):
    """
    Pretty print JSON object.
    """
    print(f"• [bold magenta]{statement}[/]")
    print_json(json.dumps(json_obj, indent=4))


@validate_call
def rich_print_checked_statement(statement: str, mode: str, exit: bool = False):
    """
    Print a statement with a check mark or cross.
    """
    if mode not in ["loading", "success", "error", "info", "warning"]:
        handle_error(f"Invalid mode: {mode}", exit=exit)
    if mode == "loading":
        print(f"• [bold yellow]:hourglass: {statement}[/bold yellow]")
    elif mode == "success":
        print(f"• [bold green]:white_check_mark: {statement}[/bold green]")
    elif mode == "error":
        print(f"• [bold red]:x: {statement}[/bold red]")
    elif mode == "info":
        print(f"• [bold blue]:information_source: {statement}[/bold blue]")
    elif mode == "warning":
        print(f"• [bold orange1]:warning: {statement}[/bold orange1]")
