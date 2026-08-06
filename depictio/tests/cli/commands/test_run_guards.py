"""Guard-rail tests for `depictio run` option combinations (manifest mode).

The full run pipeline needs a live stack; these only prove the CLI rejects
inconsistent flag combinations before doing any work.
"""

from typer.testing import CliRunner

from depictio.cli.depictio_cli import app

runner = CliRunner()


def test_manifest_requires_template():
    result = runner.invoke(app, ["run", "--manifest", "https://example.org/m.json"])
    assert result.exit_code == 1
    assert "--manifest requires --template" in result.output


def test_manifest_and_data_root_are_exclusive(tmp_path):
    result = runner.invoke(
        app,
        [
            "run",
            "--template",
            "generic/manifest-tables/1",
            "--manifest",
            "https://example.org/m.json",
            "--data-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_template_requires_data_root_or_manifest():
    result = runner.invoke(app, ["run", "--template", "generic/manifest-tables/1"])
    assert result.exit_code == 1
    assert "--data-root (or --manifest)" in result.output


def test_local_manifest_must_exist():
    result = runner.invoke(
        app,
        [
            "run",
            "--template",
            "generic/manifest-tables/1",
            "--manifest",
            "/nonexistent/manifest.json",
            "--skip-server-check",
        ],
    )
    assert result.exit_code == 1
    assert "does not exist" in result.output
