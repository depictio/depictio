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


class TestInstallEnablesTheTriggerGlobally:
    """`--install` writes the include Nextflow reads before every run.

    The point is to stop repeating `-c` on every command. What it must not do
    is disturb the rest of that file, or leave behind an include that outlives
    the CLI: Nextflow refuses to parse a config whose `includeConfig` target is
    missing, so a stale entry breaks *every* pipeline on the machine, whether
    or not it has anything to do with Depictio.
    """

    def _run(self, monkeypatch, home, *args):
        monkeypatch.delenv("NXF_HOME", raising=False)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(
            Path, "expanduser", lambda self: Path(str(self).replace("~", str(home), 1))
        )
        return runner.invoke(app, ["nextflow", *args])

    def test_include_target_is_outside_the_python_environment(self, monkeypatch, tmp_path):
        """The include must survive a pip uninstall or a change of virtualenv."""
        result = self._run(monkeypatch, tmp_path, "--install")

        assert result.exit_code == 0
        written = (tmp_path / ".nextflow" / "config").read_text()
        assert str(tmp_path / ".depictio" / "nextflow.config") in written
        assert "site-packages" not in written

    def test_handler_is_copied_to_the_stable_location(self, monkeypatch, tmp_path):
        self._run(monkeypatch, tmp_path, "--install")

        copied = tmp_path / ".depictio" / "nextflow.config"
        assert copied.is_file()
        assert "workflow.onComplete" in copied.read_text()

    def test_existing_settings_are_preserved(self, monkeypatch, tmp_path):
        config = tmp_path / ".nextflow" / "config"
        config.parent.mkdir(parents=True)
        config.write_text("process.executor = 'slurm'\n")

        self._run(monkeypatch, tmp_path, "--install")

        assert "process.executor = 'slurm'" in config.read_text()

    def test_installing_twice_does_not_duplicate_the_block(self, monkeypatch, tmp_path):
        self._run(monkeypatch, tmp_path, "--install")
        self._run(monkeypatch, tmp_path, "--install")

        written = (tmp_path / ".nextflow" / "config").read_text()
        assert written.count("includeConfig") == 1

    def test_uninstall_removes_only_our_block(self, monkeypatch, tmp_path):
        config = tmp_path / ".nextflow" / "config"
        config.parent.mkdir(parents=True)
        config.write_text("process.executor = 'slurm'\n")
        self._run(monkeypatch, tmp_path, "--install")

        self._run(monkeypatch, tmp_path, "--uninstall")

        written = config.read_text()
        assert "includeConfig" not in written
        assert "process.executor = 'slurm'" in written

    def test_uninstall_without_an_install_is_not_an_error(self, monkeypatch, tmp_path):
        result = self._run(monkeypatch, tmp_path, "--uninstall")

        assert result.exit_code == 0

    def test_install_and_uninstall_together_are_refused(self, monkeypatch, tmp_path):
        result = self._run(monkeypatch, tmp_path, "--install", "--uninstall")

        assert result.exit_code == 1


class TestTheHandlerForwardsDashboards:
    """`params.depictio_dashboard` reaches the CLI as `--dashboard`.

    Without it a pipeline Depictio ships no template for ingests fine and
    leaves nothing to look at, because only templates carry dashboards.
    """

    def _snippet(self) -> str:
        import depictio.cli

        return (
            Path(depictio.cli.__file__).parent / "configs" / "nextflow" / "depictio.config"
        ).read_text()

    def test_the_parameter_is_read_and_forwarded(self):
        snippet = self._snippet()
        assert "depictio_dashboard" in snippet
        assert "'--dashboard'" in snippet

    def test_a_list_of_dashboards_is_accepted(self):
        """Several dashboards per project is the normal case for a template."""
        assert "dashboards instanceof List" in self._snippet()

    def test_the_example_ships_a_dashboard(self):
        """The bundled example is the thing people copy; it must demonstrate one."""
        import depictio.cli

        example = Path(depictio.cli.__file__).parent / "configs" / "nextflow" / "example"
        assert (example / "depictio_dashboard.yaml").is_file()
        assert "depictio_dashboard" in (example / "nextflow.config").read_text()
