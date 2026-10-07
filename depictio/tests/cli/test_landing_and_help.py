"""What `depictio` shows before any command runs: the landing, the banner, `--help`."""

import io
import re

import pytest
from rich.console import Console
from typer.testing import CliRunner

runner = CliRunner()

# The block characters the logo is drawn with (U+2580 to U+259F).
ART = re.compile("[▀-▟]")


@pytest.fixture
def cli(monkeypatch):
    """The depictio_cli module. Importing it sets DEPICTIO_CONTEXT=CLI for the whole
    process: monkeypatch puts the previous value back once the test is over."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    from depictio.cli import depictio_cli

    return depictio_cli


def _console(width: int = 100, **kwargs) -> Console:
    """A colour terminal of ``width`` columns writing to a string."""
    options = {"force_terminal": True, "color_system": "truecolor", **kwargs}
    return Console(file=io.StringIO(), width=width, **options)


class TestLanding:
    def test_depictio_alone_shows_where_to_start(self, cli):
        result = runner.invoke(cli.app, [])

        assert result.exit_code == 0, result.output
        assert "Missing command" not in result.output
        for _, command in cli.GET_STARTED:
            assert command in result.output
        assert "depictio --help" in result.output
        assert cli.DOCS_URL in result.output

    def test_piped_output_has_no_art_and_no_colour(self, cli):
        result = runner.invoke(cli.app, [])

        assert not ART.search(result.output)
        assert "\x1b[" not in result.output
        assert "$ " not in result.output
        assert result.output.startswith("depictio ")

    def test_a_command_prints_no_banner(self, cli):
        result = runner.invoke(cli.app, ["version"])

        assert result.output.startswith("Depictio CLI version:")


class TestBanner:
    @pytest.mark.parametrize("color_system", ["truecolor", "256"])
    def test_a_wide_colour_terminal_gets_the_art(self, cli, color_system):
        console = _console(color_system=color_system)
        cli.print_banner(console)

        out = console.file.getvalue()
        assert ART.search(out)
        assert "depictio" in out and cli.TAGLINE in out

    @pytest.mark.parametrize(
        ("width", "height", "size"),
        [(100, 40, "large"), (100, 24, "compact"), (80, 40, "compact"), (60, 24, "compact")],
    )
    def test_the_logo_size_follows_the_terminal(self, cli, width, height, size):
        console = _console(width=width, height=height)
        cli.print_banner(console)

        art_rows = len(cli.logo_art.LOGOS[size]["pixels"]) // 2
        # A blank line, then the art with the name and tagline beside it.
        assert len(console.file.getvalue().splitlines()) == 1 + art_rows

    @pytest.mark.parametrize(
        "console_args",
        [
            {"width": 59},
            {"no_color": True},
            {"force_terminal": False},
            {"_environ": {"TERM": "dumb"}},
            {"color_system": "standard"},
        ],
        ids=["narrow", "NO_COLOR", "not a terminal", "TERM=dumb", "16 colours"],
    )
    def test_the_art_is_skipped_where_it_would_not_render(self, cli, console_args):
        console = _console(**console_args)
        cli.print_banner(console)

        out = re.sub(r"\x1b\[[0-9;]*m", "", console.file.getvalue())
        assert not ART.search(out)
        # The name and tagline still show, as plain lines.
        name, tagline = out.splitlines()
        assert name.startswith("depictio ") and tagline == cli.TAGLINE

    def test_in_colour_the_commands_get_a_prompt_sign(self, cli):
        console = _console()
        cli.print_landing(console)

        out = re.sub(r"\x1b\[[0-9;]*m", "", console.file.getvalue())
        for _, command in cli.GET_STARTED:
            assert f"    $ {command}\n" in out


class TestLogoArt:
    """The generated logo_art module (scripts/generate_cli_logo.py writes it) and the
    art drawn from it."""

    @pytest.fixture(params=["large", "compact"])
    def logo(self, request, cli):
        return request.param, cli.logo_art.LOGOS[request.param]

    def test_the_palette_holds_hex_colours(self, cli):
        assert cli.logo_art.PALETTE
        for letter, colour in cli.logo_art.PALETTE.items():
            assert len(letter) == 1 and letter != "."
            assert re.fullmatch("#[0-9A-F]{6}", colour)

    def test_the_pixels_form_whole_cells_of_known_colours(self, cli, logo):
        _, rendition = logo
        across = {"half": 1, "quadrant": 2}[rendition["glyphs"]]
        pixels = rendition["pixels"]
        width = len(pixels[0])
        assert len(pixels) % 2 == 0 and width % across == 0
        assert all(len(row) == width for row in pixels)
        known = set(cli.logo_art.PALETTE) | {"."}
        assert set("".join(pixels)) <= known

    def test_no_cell_needs_more_colours_than_a_block_character_has(self, cli, logo):
        _, rendition = logo
        across = {"half": 1, "quadrant": 2}[rendition["glyphs"]]
        pixels = rendition["pixels"]
        for top in range(0, len(pixels), 2):
            for left in range(0, len(pixels[0]), across):
                cell = {row[left + dx] for row in pixels[top : top + 2] for dx in range(across)}
                # A foreground and a background, the terminal's own where transparent.
                colours = cell - {"."}
                assert len(colours) <= (1 if "." in cell else 2), (top, left, cell)

    def test_the_art_is_block_characters_in_the_logo_colours(self, cli, logo):
        name, rendition = logo
        art = cli._logo(name)

        across = {"half": 1, "quadrant": 2}[rendition["glyphs"]]
        lines = art.plain.split("\n")
        assert len(lines) == len(rendition["pixels"]) // 2
        assert {len(line) for line in lines} == {len(rendition["pixels"][0]) // across}
        assert set(art.plain) <= set(cli._BLOCKS.values()) | {"\n"}
        palette = {colour.lower() for colour in cli.logo_art.PALETTE.values()}
        for span in art.spans:
            for colour in (span.style.color, span.style.bgcolor):
                assert colour is None or colour.get_truecolor().hex in palette


class TestHelp:
    def test_commands_are_grouped_into_panels_in_order(self, cli):
        result = runner.invoke(cli.app, ["--help"], terminal_width=100)

        assert result.exit_code == 0, result.output
        out = result.output
        starts = [out.index(f"─ {panel} ─") for panel in cli.HELP_PANELS]
        assert starts == sorted(starts)
        # No leftover default panel for a command missing from HELP_PANELS.
        assert "─ Commands ─" not in out
        bounds = [*starts, len(out)]
        for i, names in enumerate(cli.HELP_PANELS.values()):
            panel = out[bounds[i] : bounds[i + 1]]
            for name in names:
                assert re.search(rf"│ {name} ", panel), f"{name} not in its panel"

    def test_every_visible_command_has_a_panel(self, cli):
        root = cli.depictiocli
        visible = {name for name, cmd in root.commands.items() if not cmd.hidden}
        listed = {name for names in cli.HELP_PANELS.values() for name in names}
        assert visible == listed

    def test_former_names_work_out_of_the_help(self, cli):
        """`run` became `ingest`, `images push` became `data push-images`: the old
        names stay callable for hooks and scripts, without a place in the help."""
        out = runner.invoke(cli.app, ["--help"], terminal_width=100).output

        assert re.search(r"│ ingest ", out)
        assert not re.search(r"│ (run|images) ", out)
        for command in (["run"], ["images", "push"], ["images", "list-bucket"]):
            result = runner.invoke(cli.app, [*command, "--help"])
            assert result.exit_code == 0, (command, result.output)
        assert "Ingest pipeline results" in runner.invoke(cli.app, ["run", "--help"]).output
        # The help says what each was called, for whoever looks for the old name.
        assert "Formerly `run`." in out

    def test_ingest_lists_its_steps_without_blank_lines(self, cli):
        result = runner.invoke(cli.app, ["ingest", "--help"], terminal_width=100)

        lines = [line.strip() for line in result.output.splitlines()]
        first = lines.index("1. Check that the server answers")
        last = next(i for i, line in enumerate(lines) if line.startswith("8. "))
        assert all(lines[first : last + 1]), "a blank line between the steps"

    def test_the_commands_table_lists_subcommands_by_panel(self, cli):
        result = runner.invoke(cli.app, ["commands"], terminal_width=120)

        assert result.exit_code == 0, result.output
        for panel in cli.HELP_PANELS:
            assert panel in result.output
        for subcommand in ("local up", "data scan", "backup restore", "catalog list"):
            assert subcommand in result.output

    def test_help_takes_the_landing_colours_and_drops_yellow(self, cli, monkeypatch):
        from typer import rich_utils

        styles = [name for name in vars(rich_utils) if name.startswith("STYLE_")]
        # Put Typer's own styles back afterwards, for the tests that follow.
        for name in styles:
            monkeypatch.setattr(rich_utils, name, getattr(rich_utils, name))

        cli.brand_help()

        assert rich_utils.STYLE_COMMANDS_TABLE_FIRST_COLUMN == f"bold {cli.COMMAND_COLOR}"
        assert not [name for name in styles if "yellow" in str(getattr(rich_utils, name))]


class TestStatusLines:
    @pytest.fixture
    def printed(self, monkeypatch):
        from depictio.cli.cli.utils import rich_utils

        console = Console(file=io.StringIO(), width=40)
        monkeypatch.setattr(rich_utils, "console", console)
        return lambda: console.file.getvalue()

    @pytest.mark.parametrize(
        ("mode", "symbol"),
        [("success", "✓"), ("error", "✗"), ("warning", "!"), ("info", "•"), ("loading", "…")],
    )
    def test_one_symbol_per_mode(self, printed, mode, symbol):
        from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement

        rich_print_checked_statement("Project synced", mode)

        assert printed() == f"{symbol} Project synced\n"

    def test_a_long_message_wraps_under_its_text(self, printed):
        from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement

        rich_print_checked_statement(
            "The viewer bundle is not built: the API runs but dashboards do not render",
            "warning",
        )

        first, *rest = printed().splitlines()
        assert first.startswith("! The viewer")
        assert rest and all(line.startswith("  ") and line[2] != " " for line in rest)
        assert all(line == line.rstrip() for line in [first, *rest])

    def test_markup_is_rendered(self, printed):
        from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement

        rich_print_checked_statement("Scanning [bold]asv_table[/bold]", "info")

        assert printed() == "• Scanning asv_table\n"
