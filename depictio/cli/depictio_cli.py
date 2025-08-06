import os

os.environ["DEPICTIO_CONTEXT"] = "CLI"

import typer
from typer.main import get_command

from depictio.cli.cli.commands.backup import app as backup
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


app.add_typer(backup, name="backup", help="Backup commands")
app.add_typer(config, name="config", help="Configuration commands")
app.add_typer(data, name="data", help="Data management commands")
depictiocli = get_command(app)


def display_depictio_cli_logo():
    """Display the Depictio CLI logo at startup."""
    from rich.columns import Columns
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    # Depictio brand colors
    DEPICTIO_COLORS = {
        "purple": "#9966CC",
        "violet": "#7A5DC7",
        "blue": "#6495ED",
        "teal": "#45B8AC",
        "green": "#8BC34A",
        "yellow": "#F9CB40",
        "orange": "#F68B33",
        "pink": "#E6779F",
    }

    # Character to color mapping for the favicon
    ASCII_TO_COLOR = {
        "*": DEPICTIO_COLORS["violet"],
        "+": DEPICTIO_COLORS["blue"],
        "_": DEPICTIO_COLORS["orange"],
        ".": DEPICTIO_COLORS["yellow"],
        ":": DEPICTIO_COLORS["green"],
        "-": DEPICTIO_COLORS["teal"],
        "~": DEPICTIO_COLORS["pink"],
        "=": DEPICTIO_COLORS["purple"],
    }

    # Original favicon ASCII art
    FAVICON_ASCII_FINAL = """
                                                        *******
                                                        ***********
                                                       ****************
                                                       ********************
                                                       ***********************
                                                       **************************
                                                       ****************************
                                                       ******************************
                                                       *********************************
                                        ==========     *******************************
                                   ===============     *****************************
                                ==================     ****************************
                             =====================     **************************
                            ======================     ************************
                             =====================     **********************
                              ====================     ********************
                                ==================     ******************        ++
                                  ================     *****************       +++++
                                    ==============     ***************       +++++++++
                                      ============     ************         +++++++++++
                                        ==========     ***********       +++++++++++++++
                                          ========     *********       ++++++++++++++++++
                                 ~~~       =======     *******       +++++++++++++++++++++
                                ~~~~~~       =====     *****        ++++++++++++++++++++++
                               ~~~~~~~~~       ===     ***        +++++++++++++++++++++++++
                              ~~~~~~~~~~~~      ==              +++++++++++++++++++++++++++
                             ~~~~~~~~~~~~~~~     =            +++++++++++++++++++++++++++++
                             ~~~~~~~~~~~~~~~~               +++++++++++++++++++++++++++++++



---------------------------------------------               ________________________________
-------------------------------------------                   ______________________________
------------------------------------------                      ___________________________
----------------------------------------       :::     ...        _________________________
 -------------------------------------       :::::     .....        _______________________
 -----------------------------------       :::::::     .......       _____________________
 ---------------------------------        ::::::::     .........       ___________________
  -------------------------------       ::::::::::     ...........       ________________
  -----------------------------       ::::::::::::     ............        _____________
   --------------------------       ::::::::::::::     .............         __________
    -----------------------       ::::::::::::::::     ..............          ______
     --------------------        :::::::::::::::::                              ____
      -----------------        :::::::::::::::::::
       --------------        :::::::::::::::::::::
        -----------         ::::::::::::::::::::::
          -------             ::::::::::::::::::::
           -----                 :::::::::::::::::
                                    ::::::::::::::
                                         :::::::::
"""

    # Original CLI ASCII art
    NAME_CLI_ASCII = """
      ██████████████████           ██████████████████████    ███████████████████        ██████           ████████████        ████████████████████████   ██████            █████████████                                       ██████████      █████               ████████████████
      █████████████████████        ███████████████████████   █████████████████████     ███████        ██████████████████     ████████████████████████  ███████         ███████████████████                                 ██████████████    ███████              █████████████████
      ███████████████████████      ███████████████████████   ██████████████████████    ███████      ██████████████████████   ████████████████████████  ███████       ██████████████████████                              ████████████████    ███████              █████████████████
                    ██████████     ███████                   ███████        ████████   ███████     ███████████   ██████████           ███████          ███████      ███████████   ██████████                            █████████     ███    ███████                   ███████
                       ████████    ███████                   ██████           ███████  ███████    ████████           ███████          ██████           ███████     ████████          ████████                          ████████              ███████                   ███████
                        ████████   ███████                   ██████           ███████  ███████    ██████              ██████          ██████           ███████    ███████              ███████                         ███████               ███████                   ███████
                         ███████   █████████████████████     ██████          ███████   ███████   ███████                              ██████           ███████    ███████               ███████                        ██████                ███████                   ███████
                         ███████   █████████████████████     ███████████████████████   ███████   ███████                              ██████           ███████    ██████                ███████      █████████████     ██████                ███████                   ███████
                         ███████   █████████████████████     ██████████████████████    ███████   ███████                              ██████           ███████    ██████                ███████      █████████████     ██████                ███████                   ███████
                        ████████   ███████                   ████████████████████      ███████   ███████               ███            ██████           ███████    ███████               ██████       █████████████     ███████               ███████                   ███████
                       ████████    ███████                   ██████████████            ███████    ███████             ██████          ██████           ███████    ████████             ███████                         ███████               ███████                   ███████
                      ████████     ███████                   ██████                    ███████     ████████         ████████          ██████           ███████     █████████        █████████                           ████████      ███    ███████                   ███████
      ███████████████████████      ██████████████████████    ██████                    ███████      ███████████████████████           ██████           ███████      ████████████████████████                             ████████████████    ██████████████████   █████████████████
      ██████████████████████       ███████████████████████   ██████                    ███████       ████████████████████             ██████           ███████        █████████████████████                               ███████████████    ██████████████████   █████████████████
      ███████████████████          ███████████████████████   ██████                    ███████         ████████████████               ██████           ███████          ████████████████                                     ██████████       ████████████████    ████████████████
"""

    def scale_ascii_art(ascii_art: str, scale: float = 1.0) -> str:
        """Scale ASCII art by removing lines and characters based on scale factor."""
        if scale >= 1.0:
            return ascii_art

        lines = ascii_art.split("\n")

        # Skip lines based on scale factor
        line_step = max(1, int(1 / scale))
        scaled_lines = lines[::line_step]

        # Skip characters within each line based on scale factor
        char_step = max(1, int(1 / scale))
        scaled_art_lines = []

        for line in scaled_lines:
            if scale <= 0.5:
                # For very small scales, take every nth character
                scaled_line = line[::char_step]
            else:
                # For moderate scaling, just use line scaling
                scaled_line = line
            scaled_art_lines.append(scaled_line)

        return "\n".join(scaled_art_lines)

    def create_colored_favicon() -> Text:
        """Create the colored favicon with proper scaling."""
        # Scale to small size (0.33)
        scaled_art = scale_ascii_art(FAVICON_ASCII_FINAL, 0.33)

        logo_text = Text()
        for line in scaled_art.split("\n"):
            line_text = Text()
            for char in line:
                if char in ASCII_TO_COLOR:
                    line_text.append(char, style=ASCII_TO_COLOR[char])
                else:
                    line_text.append(char)
            line_text.append("\n")
            logo_text.append_text(line_text)
        return logo_text

    def create_colored_name() -> Text:
        """Create the colored CLI name with proper scaling."""
        # Scale to small size (0.33)
        scaled_art = scale_ascii_art(NAME_CLI_ASCII, 0.33)

        name_text = Text()
        colors = [
            DEPICTIO_COLORS["violet"],
            DEPICTIO_COLORS["blue"],
            DEPICTIO_COLORS["teal"],
            DEPICTIO_COLORS["green"],
            DEPICTIO_COLORS["yellow"],
            DEPICTIO_COLORS["orange"],
            DEPICTIO_COLORS["pink"],
            DEPICTIO_COLORS["purple"],
        ]

        lines = scaled_art.split("\n")
        for line in lines:
            line_text = Text()
            if line.strip():
                char_count = len(line.replace(" ", ""))
                if char_count > 0:
                    chars_per_color = max(1, char_count // len(colors))
                    color_index = 0
                    char_index = 0

                    for char in line:
                        if char != " ":
                            if (
                                char_index > 0
                                and char_index % chars_per_color == 0
                                and color_index < len(colors) - 1
                            ):
                                color_index += 1
                            line_text.append(char, style=colors[color_index])
                            char_index += 1
                        else:
                            line_text.append(char)
                else:
                    line_text.append(line)
            else:
                line_text.append(line)
            line_text.append("\n")
            name_text.append_text(line_text)
        return name_text

    def _get_text_height(text: Text) -> int:
        """Get the height (number of lines) of a Rich Text object."""
        return len(text.plain.split("\n"))

    def _pad_text_vertically(text: Text, target_height: int) -> Text:
        """Add vertical padding to center text within target height."""
        current_height = _get_text_height(text)
        if current_height >= target_height:
            return text

        padding_needed = target_height - current_height
        top_padding = padding_needed // 2

        padded_text = Text()
        for _ in range(top_padding):
            padded_text.append("\n")
        padded_text.append_text(text)
        return padded_text

    console = Console()
    favicon = create_colored_favicon()
    name = create_colored_name()

    # Center both vertically
    favicon_height = _get_text_height(favicon)
    name_height = _get_text_height(name)
    max_height = max(favicon_height, name_height)

    centered_favicon = _pad_text_vertically(favicon, max_height)
    centered_name = _pad_text_vertically(name, max_height)

    content = Columns([centered_favicon, centered_name], align="left", expand=False)

    panel = Panel(
        content,
        title="🎨 DEPICTIO-CLI",
        title_align="center",
        border_style="bright_blue",
        padding=(1, 2),
    )
    console.print(panel)
    console.print()


def main():
    # Add rich display support for Polars DataFrames
    add_rich_display_to_polars()

    # Display Depictio CLI logo
    display_depictio_cli_logo()

    app()
