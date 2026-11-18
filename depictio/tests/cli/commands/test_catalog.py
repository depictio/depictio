"""`depictio catalog preview`, `gallery` and `export-site`: the bundle they need, and MultiQC's logs."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands import catalog
from depictio.cli.cli.commands.catalog import app

runner = CliRunner()


@pytest.mark.parametrize(
    ("args", "build"),
    [
        (["gallery", "--no-open"], "render_gallery_html"),
        (["gallery", "--out", "g.html", "--no-open"], "render_gallery_html"),
        (["preview", "qiime2_alpha_diversity", "--no-open"], "render_html"),
    ],
    ids=["gallery", "gallery --out", "preview"],
)
def test_without_the_bundle_it_stops_before_building(tmp_path, args, build):
    """Building the gallery takes some 20 seconds, for a page with nowhere to go."""
    with (
        patch("depictio.catalog.payload.TEMPLATE_PATH", tmp_path / "missing.html"),
        patch(f"depictio.catalog.payload.{build}") as render,
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 1
    render.assert_not_called()
    message = " ".join(result.output.split())
    assert "catalog-preview bundle is not built" in message
    assert "pnpm run build:catalog-preview" in message


def test_export_site_without_the_bundle_stops_before_building(tmp_path):
    with (
        patch("depictio.catalog.payload.SITE_BUNDLE_DIR", tmp_path / "missing"),
        patch("depictio.catalog.payload.export_site_data") as export,
    ):
        result = runner.invoke(app, ["export-site", "--out-dir", str(tmp_path / "site")])

    assert result.exit_code == 1
    export.assert_not_called()
    message = " ".join(result.output.split())
    assert "catalog site bundle is not built" in message
    assert "pnpm run build:catalog-site" in message


def test_export_site_copies_the_bundle_and_replaces_stale_data(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>")
    (bundle / "assets" / "app.js").write_text("//")
    site = tmp_path / "site"
    (site / "data" / "outputs").mkdir(parents=True)
    (site / "data" / "outputs" / "gone.json").write_text("{}")

    def fake_export(entries, out_dir, version):
        out_dir.mkdir(parents=True)
        (out_dir / "index.json").write_text(version)
        return {"tools": 1, "outputs": 2, "failed": 0, "index_bytes": 1, "outputs_bytes": 2}

    with (
        patch("depictio.catalog.payload.SITE_BUNDLE_DIR", bundle),
        patch("depictio.catalog.payload.export_site_data", side_effect=fake_export),
    ):
        result = runner.invoke(app, ["export-site", "--out-dir", str(site), "--version", "1.2.3"])

    assert result.exit_code == 0, result.output
    assert (site / "index.html").exists()
    assert (site / "assets" / "app.js").exists()
    assert (site / "data" / "index.json").read_text() == "1.2.3"
    assert not (site / "data" / "outputs" / "gone.json").exists()
    assert "1 tools, 2 outputs" in result.output


def test_export_site_strict_fails_on_an_output_without_preview(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "index.html").write_text("<html></html>")

    def fake_export(entries, out_dir, version):
        out_dir.mkdir(parents=True)
        return {"tools": 1, "outputs": 2, "failed": 1, "index_bytes": 1, "outputs_bytes": 2}

    with (
        patch("depictio.catalog.payload.SITE_BUNDLE_DIR", bundle),
        patch("depictio.catalog.payload.export_site_data", side_effect=fake_export),
    ):
        lenient = runner.invoke(app, ["export-site", "--out-dir", str(tmp_path / "a")])
        strict = runner.invoke(app, ["export-site", "--out-dir", str(tmp_path / "b"), "--strict"])

    assert lenient.exit_code == 0
    assert strict.exit_code == 1
    assert "could not be previewed" in strict.output


@pytest.fixture
def levels():
    """The CLI and MultiQC loggers' levels, put back after the test."""
    loggers = [logging.getLogger(name) for name in ("depictio-cli", "multiqc")]
    saved = [lg.level for lg in loggers]
    yield
    for lg, level in zip(loggers, saved):
        lg.setLevel(level)


@pytest.mark.parametrize(
    ("cli_level", "quiet"), [(logging.ERROR, True), (logging.INFO, False)], ids=["", "-v"]
)
def test_multiqc_warnings_show_only_with_v(levels, cli_level, quiet):
    logging.getLogger("depictio-cli").setLevel(cli_level)
    multiqc = logging.getLogger("multiqc.utils.mqc_colour")

    with catalog._quiet_multiqc():
        assert multiqc.isEnabledFor(logging.WARNING) is not quiet

    assert multiqc.isEnabledFor(logging.WARNING)


def test_the_gallery_help_says_both_modes_need_the_bundle():
    result = runner.invoke(app, ["gallery", "--help"], terminal_width=200)

    help_text = " ".join(result.output.split())
    assert "Served or exported, the page needs the prebuilt bundle" in help_text
