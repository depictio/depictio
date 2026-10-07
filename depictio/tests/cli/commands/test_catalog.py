"""`depictio catalog preview` and `gallery`: the bundle they need, and MultiQC's logs."""

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
