"""Commands and options renamed in 1.12, still accepted under their former names.

Scripts, CI and the Nextflow hooks installed from older releases still call the
former names, so these keep working. Each use says what the name is now.
"""

from __future__ import annotations

import typer

from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement


def note_renamed(former: str, current: str) -> None:
    """Say that ``former`` is now ``current``, on stderr so a script's output stays the same."""
    rich_print_checked_statement(
        f"[bold]{former}[/] is now [bold]{current}[/]: the old name still works, for now.",
        "warning",
        stderr=True,
    )


def note_if_called_as(ctx: typer.Context, former: str, current: str) -> None:
    """note_renamed, when the running command was called by its former name.

    ``former`` is the command path after the program name, such as
    ``local export-compose``: a command registered under both names cannot tell
    which one was typed otherwise.
    """
    if f" {ctx.command_path}".endswith(f" {former}"):
        note_renamed(former, current)
