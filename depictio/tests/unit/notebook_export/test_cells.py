"""Cell analysis and file rendering follow marimo's rules."""

import importlib.util
import subprocess
import sys

import pytest

from depictio.api.v1.services.notebook_export.cells import (
    Cell,
    analyze,
    md_cell,
    render_notebook,
)


def test_analyze_defines_public_top_level_names_only():
    defs, refs = analyze(
        "import polars as pl\n"
        "_tmp = 1\n"
        "a, (b, *c) = 1, (2, 3)\n"
        "def _make(df):\n"
        "    fig = px.violin(df.to_pandas())\n"
        "    return fig\n"
        "fig_x = _make(final)\n"
        "for i in range(3):\n"
        "    pass\n"
        "with open('x') as fh:\n"
        "    pass\n"
    )
    assert defs == {"pl", "a", "b", "c", "fig_x", "i", "fh"}
    # Reads: px and final come from other cells; df/fig are locals of _make;
    # range/open are builtins that no cell defines (filtered at render time).
    assert {"px", "final", "range", "open"} <= refs
    assert "df" not in refs and "fig" not in refs and "_tmp" not in refs


def test_render_computes_params_and_returns():
    cells = [
        Cell("import polars as pl\nimport plotly.express as px"),
        Cell("df_x = pl.DataFrame({'a': [1, 2, 3]})"),
        Cell("stage_1 = df_x.filter(pl.col('a') > 1)"),
        Cell("fig_a = px.bar(stage_1, x='a')\nfig_a"),
        md_cell('# Title\n\nSome *text* with """quotes""".'),
    ]
    src = render_notebook(cells, generated_with="0.24.0")
    assert src.startswith(
        'import marimo\n\n__generated_with = "0.24.0"\napp = marimo.App(width="medium")'
    )
    assert "def _(df_x, pl):" in src
    assert "def _(px, stage_1):" in src
    assert "    return (fig_a,)" in src
    assert "    return (pl, px)" in src
    assert '\\"\\"\\"quotes\\"\\"\\"' in src
    assert src.endswith('if __name__ == "__main__":\n    app.run()\n')


def test_duplicate_global_is_rejected():
    with pytest.raises(ValueError, match="defined by cells 0 and 1"):
        render_notebook([Cell("x = 1"), Cell("x = 2")], generated_with="0.24.0")


def test_rendered_file_imports_and_runs(tmp_path):
    cells = [
        Cell("import marimo as mo\nimport polars as pl"),
        Cell("df_x = pl.DataFrame({'a': [1, 2, 3]})"),
        Cell("stage_1 = df_x.filter(pl.col('a') > 1)"),
        Cell("_local = 5\ntotal = stage_1.height + _local"),
        md_cell("## Done"),
    ]
    path = tmp_path / "nb.py"
    path.write_text(render_notebook(cells, generated_with="0.24.0"))
    spec = importlib.util.spec_from_file_location("nb_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outputs, defs = module.app.run()
    assert defs["stage_1"].height == 2
    assert defs["total"] == 7
    assert "_local" not in defs


def test_marimo_check_accepts_rendered_file(tmp_path):
    pytest.importorskip("marimo")
    path = tmp_path / "nb.py"
    path.write_text(
        render_notebook(
            [
                Cell("import marimo as mo\nimport polars as pl"),
                Cell("x = pl.Series([1])"),
                md_cell("hello"),
            ],
            generated_with="0.24.0",
        )
    )
    proc = subprocess.run(
        [sys.executable, "-m", "marimo", "check", "--strict", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
