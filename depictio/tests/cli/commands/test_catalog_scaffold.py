"""Tests for the catalog contributor commands: `dev catalog new` + `dev catalog lint`.

Covers the no-code scaffolding path (a folder that immediately passes the CI
gate), fixture-driven column inference, overwrite safety, and the headless
preview-payload snapshot.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import depictio.models.components.advanced_viz.catalog as catalog_mod
from depictio.cli.cli.commands.catalog import dev_app


@pytest.fixture
def runner():
    return CliRunner()


def test_new_then_lint_round_trip(runner, tmp_path, monkeypatch):
    # `new` scaffolds a folder that validates with zero manual edits.
    monkeypatch.setattr(catalog_mod, "CATALOG_DIR", tmp_path)
    result = runner.invoke(dev_app, ["new", "demo"])
    assert result.exit_code == 0, result.output

    tool_dir = tmp_path / "demo"
    assert (tool_dir / "module.yaml").exists()
    assert (tool_dir / "output.yaml").exists()
    assert (tool_dir / "output.tsv").exists()

    lint = runner.invoke(dev_app, ["lint", "--path", str(tool_dir)])
    assert lint.exit_code == 0, lint.output
    assert "OK" in lint.output


def test_new_with_fixture_infers_columns(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_mod, "CATALOG_DIR", tmp_path)
    sample = tmp_path / "sample.tsv"
    sample.write_text("gene\tcount\nBRCA1\t5\nTP53\t9\n")

    result = runner.invoke(dev_app, ["new", "mytool", "--fixture", str(sample)])
    assert result.exit_code == 0, result.output

    out_yaml = (tmp_path / "mytool" / "output.yaml").read_text()
    assert "gene:" in out_yaml and "count:" in out_yaml  # inferred-columns reference comment
    assert (tmp_path / "mytool" / "output.tsv").exists()  # fixture copied in

    lint = runner.invoke(dev_app, ["lint", "--path", str(tmp_path / "mytool")])
    assert lint.exit_code == 0, lint.output


def test_new_refuses_overwrite_without_force(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_mod, "CATALOG_DIR", tmp_path)
    assert runner.invoke(dev_app, ["new", "demo"]).exit_code == 0

    second = runner.invoke(dev_app, ["new", "demo"])
    assert second.exit_code == 1
    assert "force" in second.output.lower()

    assert runner.invoke(dev_app, ["new", "demo", "--force"]).exit_code == 0


def test_lint_snapshot_writes_payloads(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_mod, "CATALOG_DIR", tmp_path)
    sample = tmp_path / "s.tsv"
    sample.write_text("sample\tvalue\na\t1.0\nb\t2.0\n")
    runner.invoke(dev_app, ["new", "snaptool", "--fixture", str(sample)])

    snap_dir = tmp_path / "snap"
    result = runner.invoke(
        dev_app,
        ["lint", "--path", str(tmp_path / "snaptool"), "--snapshot", str(snap_dir)],
    )
    assert result.exit_code == 0, result.output
    assert (snap_dir / "snaptool_output.json").exists()
