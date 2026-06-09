"""Tests for the `depictio-cli recipe` subcommand.

Regression coverage for the typer.Exit control-flow: a recipe with a
``dc_ref`` source must exit 0 (graceful skip) when run standalone, rather than
being swallowed by the broad ``except Exception`` handler and turned into a
failure. typer 0.26 vendors its own click, so ``typer.Exit`` is no longer a
``click.exceptions.Exit`` — the handler must catch ``typer.Exit`` itself.
"""

import polars as pl
import pytest
from typer.testing import CliRunner

import depictio.recipes as recipes_pkg
from depictio.cli.cli.commands.recipe import app


@pytest.fixture
def runner():
    return CliRunner()


class _Source:
    def __init__(self, ref, dc_ref=None):
        self.ref = ref
        self.dc_ref = dc_ref


def _patch_recipes(monkeypatch, sources, *, transform=None, schema=None):
    """Stub the depictio.recipes API used inside recipe_run."""

    class _Module:
        SOURCES = sources
        EXPECTED_SCHEMA = schema or {}

        @staticmethod
        def transform(resolved):
            if transform is None:
                raise AssertionError("transform must not run for this recipe")
            return transform(resolved)

    monkeypatch.setattr(recipes_pkg, "load_recipe", lambda name, ver=None: _Module())
    monkeypatch.setattr(
        recipes_pkg,
        "resolve_sources",
        lambda module, data_dir: {
            s.ref: pl.DataFrame({"a": [1]}) for s in sources if s.dc_ref is None
        },
    )
    monkeypatch.setattr(recipes_pkg, "validate_schema", lambda *a, **k: None)


def test_dc_ref_standalone_skip_exits_zero(runner, monkeypatch):
    """A recipe with a dc_ref source skips gracefully (exit 0) in standalone mode."""
    _patch_recipes(
        monkeypatch,
        [_Source("rel_table"), _Source("metadata", dc_ref="some_dc")],
    )

    result = runner.invoke(
        app,
        ["run", "nf-core/ampliseq/taxonomy_rel_abundance.py", "--data-dir", "/tmp"],
    )

    assert result.exit_code == 0, result.output
    assert "Skipped dc_ref sources" in result.output


def test_transform_runs_when_no_dc_ref(runner, monkeypatch):
    """A recipe with no dc_ref source runs transform and exits 0."""
    _patch_recipes(
        monkeypatch,
        [_Source("rel_table")],
        transform=lambda resolved: pl.DataFrame({"a": [1, 2]}),
    )

    result = runner.invoke(
        app,
        ["run", "nf-core/ampliseq/alpha_diversity.py", "--data-dir", "/tmp"],
    )

    assert result.exit_code == 0, result.output
    assert "Transform produced" in result.output
