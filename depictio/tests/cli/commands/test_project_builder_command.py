"""``depictio project-builder``: refuses cleanly without its server extra or a folder."""

from __future__ import annotations

from typer.testing import CliRunner

from depictio.cli.cli.commands import project_builder as command
from depictio.cli.depictio_cli import app

runner = CliRunner()


def test_help_answers_without_importing_fastapi():
    result = runner.invoke(app, ["project-builder", "--help"])
    assert result.exit_code == 0
    assert "--out" in result.output


def test_a_missing_server_extra_names_the_install(monkeypatch, tmp_path):
    monkeypatch.setattr(command, "_missing_server_modules", lambda: ["fastapi", "uvicorn"])
    result = runner.invoke(app, ["project-builder", str(tmp_path), "--no-open"])
    assert result.exit_code == 1
    assert "depictio[builder]" in result.output


def test_a_missing_folder_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(command, "_missing_server_modules", lambda: [])
    result = runner.invoke(app, ["project-builder", str(tmp_path / "nope"), "--no-open"])
    assert result.exit_code == 1
    assert "Not a folder" in result.output


def test_it_serves_the_folder_with_the_viewer_bundle(monkeypatch, tmp_path):
    served = {}
    monkeypatch.setattr(command, "_missing_server_modules", lambda: [])
    monkeypatch.setattr(command, "_viewer_dist", lambda: tmp_path / "dist")

    import depictio.project_builder.standalone as standalone

    monkeypatch.setattr(
        standalone, "serve", lambda root, **kwargs: served.update(root=root, **kwargs)
    )
    result = runner.invoke(
        app, ["project-builder", str(tmp_path), "--no-open", "--port", "9000", "--out", "b"]
    )
    assert result.exit_code == 0, result.output
    assert served["root"] == tmp_path.resolve()
    assert served["port"] == 9000
    assert served["open_browser"] is False
    assert served["out_dir"].name == "b"
    assert "/projects/build" in result.output
