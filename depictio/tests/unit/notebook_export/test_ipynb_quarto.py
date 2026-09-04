"""The derived artefacts: marimo's ipynb converter and the Quarto front matter."""

import json

import pytest

from depictio.api.v1.services.notebook_export.cells import Cell, md_cell, render_notebook
from depictio.api.v1.services.notebook_export.ipynb import ipynb_available, to_ipynb
from depictio.api.v1.services.notebook_export.quarto import (
    FRONT_MATTER_TAG,
    QuartoFrontMatter,
    to_quarto_ipynb,
)

SOURCE = render_notebook(
    [
        Cell("import marimo as mo\nimport polars as pl"),
        md_cell("# Title\n\nIntro"),
        Cell("df_x = pl.DataFrame({'a': [1]})"),
        Cell("df_x"),
    ],
    generated_with="0.24.0",
)


@pytest.mark.skipif(not ipynb_available(), reason="marimo/nbformat not installed")
def test_ipynb_is_derived_top_down_without_outputs():
    nb = json.loads(to_ipynb(SOURCE).decode())
    assert nb["nbformat"] == 4
    kinds = [c["cell_type"] for c in nb["cells"]]
    # marimo turns the markdown-only cell into a real markdown cell.
    assert "markdown" in kinds
    sources = ["".join(c["source"]) for c in nb["cells"]]
    assert any("import polars as pl" in s for s in sources)
    assert sources.index(next(s for s in sources if "df_x = pl" in s)) < sources.index("df_x")
    assert all(c.get("outputs", []) == [] for c in nb["cells"] if c["cell_type"] == "code")


@pytest.mark.skipif(not ipynb_available(), reason="marimo/nbformat not installed")
def test_quarto_variant_prepends_front_matter_only():
    import nbformat
    import yaml

    ipynb = to_ipynb(SOURCE)
    quarto = to_quarto_ipynb(
        ipynb, QuartoFrontMatter(title="Penguins", author="t.weber", date="2026-09-01")
    )
    plain = nbformat.reads(ipynb.decode(), as_version=4)
    q = nbformat.reads(quarto.decode(), as_version=4)
    assert q.cells[0].cell_type == "raw"
    assert FRONT_MATTER_TAG in q.cells[0].metadata["tags"]
    front = yaml.safe_load(q.cells[0].source.strip("-\n"))
    assert front["title"] == "Penguins"
    assert front["jupyter"] == "python3"
    assert front["format"]["html"]["toc"] is True
    assert [c.source for c in q.cells[1:]] == [c.source for c in plain.cells]
    nbformat.validate(q)


def test_front_matter_yaml_shape():
    text = QuartoFrontMatter(title="T", subtitle="S").to_yaml()
    assert text.startswith("title: T\nsubtitle: S\n")
    # Code is hidden by default (no box per cell, just the results — figures,
    # cards, tables); one global code-tools "View Source" replaces the click
    # a reader would otherwise need on every single cell to see it at all.
    assert "echo: false" in text
    assert "code-tools: true" in text
