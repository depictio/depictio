"""`depictio-cli config nextflow`: the path a Nextflow command substitutes.

The command exists so a user never has to type a site-packages path:

    nextflow run <pipeline> -c $(depictio-cli config nextflow)

Which means its output contract is unusually strict. Anything printed on stdout
besides the path itself lands on the Nextflow command line, so these tests guard
the bareness of the output as much as its content.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from depictio.cli.cli.commands.config import app

runner = CliRunner()


def _stdout(*args) -> str:
    result = runner.invoke(app, ["nextflow", *args])
    assert result.exit_code == 0, result.output
    return result.stdout


class TestPathOutput:
    def test_it_prints_a_path_that_exists(self):
        path = Path(_stdout().strip())
        assert path.is_file()
        assert path.name == "depictio.config"

    def test_the_snippet_is_the_one_the_package_ships(self):
        """A stale copy elsewhere on disk would be worse than no command."""
        path = Path(_stdout().strip())
        assert path.parts[-3:] == ("configs", "nextflow", "depictio.config")
        assert "workflow.onComplete" in path.read_text()

    def test_stdout_is_the_bare_path_and_nothing_else(self):
        """It is substituted into a shell command: decoration would break it."""
        out = _stdout()
        assert out.endswith("\n")
        assert len(out.strip().splitlines()) == 1
        # Rich's checkmarks, banners and box drawing all fail this.
        assert not any(ch in out for ch in "•✅❌╭╮╰╯│")


class TestPrintOutput:
    def test_print_emits_the_snippet_itself(self):
        out = _stdout("--print")
        assert "workflow.onComplete" in out
        assert "depictio_cli_executable" in out

    def test_print_round_trips_to_a_usable_file(self, tmp_path):
        """`config nextflow --print > depictio.config` has to yield the original."""
        source = Path(_stdout().strip())
        copy = tmp_path / "depictio.config"
        copy.write_text(_stdout("--print"))
        assert copy.read_text() == source.read_text()
