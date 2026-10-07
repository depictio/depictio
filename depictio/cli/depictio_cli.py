import logging
import os
from itertools import groupby

os.environ["DEPICTIO_CONTEXT"] = "CLI"

import typer
from rich.console import Console, Group
from rich.style import Style
from rich.table import Table
from rich.text import Text
from typer.core import TyperGroup
from typer.main import get_command

from depictio.cli.cli.commands.backup import app as backup
from depictio.cli.cli.commands.catalog import app as catalog
from depictio.cli.cli.commands.config import app as config
from depictio.cli.cli.commands.dashboard import app as dashboard
from depictio.cli.cli.commands.data import app as data
from depictio.cli.cli.commands.dev import app as dev
from depictio.cli.cli.commands.images import app as images
from depictio.cli.cli.commands.local import app as local
from depictio.cli.cli.commands.migrate import app as migrate
from depictio.cli.cli.commands.run import register_run_command
from depictio.cli.cli.commands.standalone import register_standalone_commands
from depictio.cli.cli.utils import logo_art
from depictio.cli.cli.utils.renamed import note_renamed
from depictio.cli.cli.utils.rich_utils import add_rich_display_to_polars
from depictio.cli.cli.utils.rich_utils import console as default_console
from depictio.cli.cli_logging import setup_logging as setup_cli_logging
from depictio.models.logging import setup_logging as setup_models_logging

DOCS_URL = "https://depictio.github.io/depictio-docs/latest/"
TAGLINE = "Interactive dashboards for bioinformatics data"

# The panels of `depictio --help`, in display order, with their commands.
HELP_PANELS = {
    "Get started": ("local", "ingest"),
    "Projects and data": ("config", "data", "dashboard"),
    "Administration": ("migrate", "backup"),
    "Reference": ("catalog", "commands", "version"),
}
# Each command's panel, and its rank in the order HELP_PANELS lists them.
_PANEL_OF = {name: panel for panel, names in HELP_PANELS.items() for name in names}
_COMMAND_ORDER = {name: rank for rank, name in enumerate(_PANEL_OF)}


class _PanelOrderGroup(TyperGroup):
    """The root group, listing its commands in HELP_PANELS order.

    Rich help draws the panels in the order their first command is listed, and Typer
    lists plain commands (ingest, version, commands) before groups, which would put
    Reference second.
    """

    def list_commands(self, ctx) -> list[str]:
        return sorted(
            super().list_commands(ctx),
            key=lambda name: _COMMAND_ORDER.get(name, len(_COMMAND_ORDER)),
        )


app = typer.Typer(
    cls=_PanelOrderGroup,
    help=f"Depictio: {TAGLINE.lower()}.",
    epilog=f"Run depictio with no command for a quick start.\n\nDocumentation: {DOCS_URL}",
    # Rich markup, not Markdown: Markdown would reflow the indented examples in the
    # commands' help and drop <placeholders> such as '<name>/<version>'.
    rich_markup_mode="rich",
)

register_standalone_commands(app)
register_run_command(app)


def _version_callback(value: bool) -> None:
    """Print the version and exit, for ``--version``/``-V``.

    Complements the existing ``depictio-cli version`` sub-command; the flag is what
    people (and our own tooling) reach for first.
    """
    if not value:
        return
    from depictio.cli.cli.utils.telemetry import cli_version

    typer.echo(f"Depictio CLI version: {cli_version()}")
    raise typer.Exit()


def _log_level(verbose: int, explicit: str | None) -> str | None:
    """The logging level -v/-vv/--log-level ask for, or None to stay quiet."""
    if explicit:
        level = explicit.upper()
        if level not in logging.getLevelNamesMapping():
            raise typer.BadParameter(f"unknown level {explicit!r}", param_hint="--log-level")
        return level
    return {0: None, 1: "INFO"}.get(verbose, "DEBUG")


# invoke_without_command: `depictio` alone runs this callback and shows the landing,
# where Click would otherwise fail with "Missing command".
@app.callback(invoke_without_command=True)
def verbose_callback(
    ctx: typer.Context,
    verbose: int = typer.Option(
        0,
        "--verbose",
        "-v",
        count=True,
        help="Show logs: -v for INFO, -vv for DEBUG",
        metavar="",
        show_default=False,
        is_eager=True,
    ),
    log_level: str | None = typer.Option(
        None,
        "--log-level",
        help="Show logs from this level up (DEBUG, INFO, WARNING, ERROR); no -v needed",
        is_eager=True,
    ),
    # The former spelling, which only took effect together with -v. Kept for scripts.
    verbose_level: str | None = typer.Option(
        None, "--verbose-level", "-vl", hidden=True, is_eager=True
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the Depictio CLI version and exit",
        is_eager=True,
        callback=_version_callback,
    ),
):
    if verbose_level:
        note_renamed("-vl/--verbose-level", "--log-level")
    # The CLI and the models log at the same level.
    level = _log_level(verbose, log_level or verbose_level)
    setup_cli_logging(level is not None, level or "INFO")
    setup_models_logging(level is not None, level or "INFO")
    if ctx.invoked_subcommand is None:
        print_landing()


app.add_typer(
    local, name="local", help="Run a complete Depictio server on this machine, without Docker."
)
app.add_typer(
    config,
    name="config",
    help="Check the CLI setup, sync project configurations, hook Depictio into Nextflow.",
)
app.add_typer(
    data,
    name="data",
    help="Run one ingestion step at a time: scan files, process data collections, join "
    "tables, upload images.",
)
app.add_typer(dashboard, name="dashboard", help="Validate, import and export dashboard YAML files.")
# Out of the help: `images push` is `data push-images` now, kept for the scripts that
# call it, and `images list-bucket` with it.
app.add_typer(images, name="images", hidden=True)
# No help here: migrate's own docstring, which also describes its modes, is shown.
app.add_typer(migrate, name="migrate")
app.add_typer(
    backup,
    name="backup",
    help="Create, list, validate and restore server database backups (admins only).",
)
app.add_typer(
    catalog,
    name="catalog",
    help="Browse the supported tools and the dashboard components their outputs become.",
)
# Maintainer / CI tooling (catalog authoring, recipe test harness, backup
# coverage). Hidden from the user-facing help; still callable as `depictio dev …`.
app.add_typer(dev, name="dev", hidden=True)

# Set here rather than where each command is registered, so HELP_PANELS is the one
# place that says which panel a command is in.
for _entry in (*app.registered_commands, *app.registered_groups):
    if _entry.name in _PANEL_OF:
        _entry.rich_help_panel = _PANEL_OF[_entry.name]

depictiocli = get_command(app)


# Depictio brand colours, as in the web app (depictio-react-core's brandColors).
DEPICTIO_COLORS = {
    "purple": "#9966CC",
    "violet": "#7A5DC7",
    "blue": "#6495ED",
    "orange": "#F68B33",
    "yellow": "#F9CB40",
    "green": "#8BC34A",
    "teal": "#45B8AC",
    "pink": "#E6779F",
}
# The landing's text colours, chosen to read on light and dark terminals alike. A
# colour can only reach a contrast of about 4.1:1 against both white and near black
# (#1E1E1E); these two come close.
# - Brand purple, for the name and headings: 4.1 on white, 4.1 on #1E1E1E.
ACCENT_COLOR = DEPICTIO_COLORS["purple"]
# - Mantine's blue 7, the web app's primary colour, for what to type: 4.2 and 4.0.
#   The brand blue would fall to 3.0 on white, the lighter wedge colours lower still.
COMMAND_COLOR = "#1C7ED6"

# Narrower than this, the text beside the logo would be squeezed into a sliver.
MIN_ART_WIDTH = 60
# The large logo needs this much room; smaller terminals get the compact one, which
# keeps the whole landing on a 24-line screen.
LARGE_ART_WIDTH = 100
LARGE_ART_HEIGHT = 30

# Block characters by the quarters of a cell they fill: top-left, top-right,
# bottom-left, bottom-right. A half-block pixel fills both quarters of its half.
_BLOCKS = {
    (0, 0, 0, 0): " ",
    (1, 0, 0, 0): "▘",
    (0, 1, 0, 0): "▝",
    (0, 0, 1, 0): "▖",
    (0, 0, 0, 1): "▗",
    (1, 1, 0, 0): "▀",
    (0, 0, 1, 1): "▄",
    (1, 0, 1, 0): "▌",
    (0, 1, 0, 1): "▐",
    (1, 0, 0, 1): "▚",
    (0, 1, 1, 0): "▞",
    (1, 1, 1, 0): "▛",
    (1, 1, 0, 1): "▜",
    (1, 0, 1, 1): "▙",
    (0, 1, 1, 1): "▟",
    (1, 1, 1, 1): "█",
}

# What the landing suggests trying first: (what it does, the command).
GET_STARTED = (
    ("Start a server on this machine, with example dashboards", "depictio local up"),
    (
        "Build dashboards from a pipeline's results",
        "depictio ingest --template nf-core/rnaseq/latest --data-root <dir>",
    ),
    ("Check the server and storage the CLI is set up for", "depictio config check"),
)


def _logo_cell(*quarters: str) -> tuple[str, Style | None]:
    """A cell's character and colours, from its quarters' palette letters ('.' where
    the logo is transparent): the first colour in front, the second behind it, and the
    terminal's own background wherever the logo is transparent."""
    colours = [c for c in dict.fromkeys(quarters) if c != "."]
    if not colours:
        return " ", None
    front, *behind = (logo_art.PALETTE[c] for c in colours)
    lit = tuple(int(q == colours[0]) for q in quarters)
    if all(lit):
        # A coloured space, not a full block: some fonts draw that short of the cell,
        # leaving seams between rows.
        return " ", Style(bgcolor=front)
    return _BLOCKS[lit], Style(color=front, bgcolor=behind[0] if behind else None)


def _logo(name: str) -> Text:
    """A logo_art rendition in block characters, two pixel rows per text row."""
    logo = logo_art.LOGOS[name]
    across = 2 if logo["glyphs"] == "quadrant" else 1
    pixels = logo["pixels"]
    art = Text(no_wrap=True)
    for row, (upper, lower) in enumerate(zip(pixels[::2], pixels[1::2])):
        if row:
            art.append("\n")
        cells = (
            _logo_cell(upper[x], upper[x + across - 1], lower[x], lower[x + across - 1])
            for x in range(0, len(upper), across)
        )
        # One span per run of like cells, so runs share one escape sequence.
        for (char, style), run in groupby(cells):
            art.append(char * len(list(run)), style)
    return art


def _in_colour(console: Console) -> bool:
    """Whether the console shows colours: a terminal, not a dumb one, NO_COLOR unset."""
    return (
        console.is_terminal
        and not console.is_dumb_terminal
        and not console.no_color
        and console.color_system is not None
    )


def art_supported(console: Console) -> bool:
    """Whether the logo renders as intended: a UTF-8 terminal, wide enough, with 256
    colours or more.

    Without colour (NO_COLOR, TERM=dumb, piped) it would be a grey blob, and on a
    narrow terminal it would leave the text beside it a few columns. With 16 colours
    the wedges would merge (violet and blue both become bright blue) into whatever the
    terminal's theme makes of them; with 256 they stay apart.
    """
    return (
        _in_colour(console)
        and console.color_system in ("256", "truecolor")
        and console.encoding.lower().startswith("utf")
        and console.width >= MIN_ART_WIDTH
    )


def _logo_size(console: Console) -> str:
    large = console.width >= LARGE_ART_WIDTH and console.height >= LARGE_ART_HEIGHT
    return "large" if large else "compact"


def print_banner(console: Console | None = None) -> None:
    """The name, version and tagline, beside the logo where the terminal allows."""
    from depictio.cli.cli.utils.telemetry import cli_version

    console = console or default_console
    title = Text.assemble(
        ("depictio", Style(color=ACCENT_COLOR, bold=True)), (f" {cli_version()}", "dim")
    )
    tagline = Text(TAGLINE)
    if not art_supported(console):
        console.print(title)
        console.print(tagline)
        return
    banner = Table.grid(padding=(0, 3))
    banner.add_column(no_wrap=True)
    # A cell of its own, so a tagline that wraps stays beside the logo.
    banner.add_column(vertical="middle")
    banner.add_row(_logo(_logo_size(console)), Group(title, tagline))
    console.print()
    console.print(banner)


def print_landing(console: Console | None = None) -> None:
    """What `depictio` alone prints: the banner, commands to start with, and where to
    read more."""
    console = console or default_console
    command_style = Style(color=COMMAND_COLOR)
    # A prompt sign marks what to type, in colour only: elsewhere the text stays as is.
    prompt = "$ " if _in_colour(console) else ""
    print_banner(console)
    console.print()
    console.print("Get started", style=Style(color=ACCENT_COLOR, bold=True))
    for purpose, command in GET_STARTED:
        console.print(f"  {purpose}", highlight=False)
        # soft_wrap: a long command stays on one line, so it copy-pastes intact.
        console.print(
            Text.assemble("    ", (prompt, "dim"), (command, command_style)), soft_wrap=True
        )
    console.print()
    console.print(Text.assemble(("All commands   ", "dim"), ("depictio --help", command_style)))
    console.print(
        Text.assemble(
            ("Documentation  ", "dim"),
            # A link where the terminal supports them (OSC 8), plain text elsewhere.
            (DOCS_URL, Style(color=COMMAND_COLOR, underline=True, link=DOCS_URL)),
        ),
        soft_wrap=True,
    )


def brand_help() -> None:
    """Give `--help` the landing's colours: what to type in blue, headings and short
    flags in purple, and no yellow, which light backgrounds make unreadable. Typer
    reads these styles each time it draws help."""
    from typer import rich_utils

    rich_utils.STYLE_USAGE = f"bold {ACCENT_COLOR}"
    rich_utils.STYLE_OPTION = f"bold {COMMAND_COLOR}"
    rich_utils.STYLE_COMMANDS_TABLE_FIRST_COLUMN = f"bold {COMMAND_COLOR}"
    rich_utils.STYLE_SWITCH = f"bold {ACCENT_COLOR}"
    rich_utils.STYLE_TYPES = ACCENT_COLOR
    rich_utils.STYLE_OPTION_ENVVAR = "dim"
    rich_utils.STYLE_OPTIONS_PANEL_BORDER = ACCENT_COLOR
    rich_utils.STYLE_COMMANDS_PANEL_BORDER = ACCENT_COLOR


def main():
    # Add rich display support for Polars DataFrames
    add_rich_display_to_polars()

    # No banner here: `depictio` alone shows one on its landing, and every other
    # command's output starts straight away.
    import sys

    # Only when help is asked for: Typer's help module takes some 25 ms to import,
    # which every other command would pay too.
    if "--help" in sys.argv[1:]:
        brand_help()

    from depictio.cli.cli.utils.telemetry import (
        CommandTimer,
        maybe_print_first_run_notice,
        maybe_send_install_event,
        resolve_command_path,
        send_command_event,
    )

    # Before the command runs, not after: an opt-out notice printed underneath a
    # command's output is one the user has already been counted by.
    maybe_print_first_run_notice()

    timer = CommandTimer()
    # Resolved from argv up front: Typer/Click raise SystemExit for --help and for
    # bad usage, so by the time we reach the finally block the parsed context is
    # gone. Only tokens matching registered command names survive this call.
    command = resolve_command_path(sys.argv[1:], depictiocli)
    succeeded = True
    interrupted = False

    try:
        app()
    except SystemExit as exc:
        # Typer signals both success (exit 0, e.g. --help) and failure this way.
        succeeded = exc.code in (0, None)
        raise
    except KeyboardInterrupt:
        # Someone pressing Ctrl-C wants out now. Skip the send entirely rather
        # than making them wait out a network timeout to leave.
        interrupted = True
        raise
    except BaseException:
        succeeded = False
        raise
    finally:
        if not interrupted:
            # Fire-and-forget on the way out, under a 2s cap. A collector that is
            # slow or gone delays the shell prompt slightly, nothing more.
            maybe_send_install_event()
            send_command_event(command, succeeded=succeeded, duration_seconds=timer.elapsed())
