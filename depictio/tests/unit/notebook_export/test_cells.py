"""Cells and the ``.qmd`` file that holds them."""

import pytest
import yaml

from depictio.api.v1.services.notebook_export.cells import Cell, md_cell, render_qmd


def test_render_is_front_matter_then_cells_in_order():
    cells = [
        Cell("import polars as pl"),
        md_cell("# Title\n\nSome *text*."),
        Cell("df_x = pl.DataFrame({'a': [1, 2, 3]})\ndf_x"),
    ]
    src = render_qmd(cells, front_matter="title: T\njupyter: python3")
    assert src.startswith("---\ntitle: T\njupyter: python3\n---\n\n")
    head, _, body = src.partition("\n---\n")
    assert yaml.safe_load(head.strip("-\n")) == {"title": "T", "jupyter": "python3"}
    assert body == (
        "\n```{python}\nimport polars as pl\n```\n\n"
        "# Title\n\nSome *text*.\n\n"
        "```{python}\ndf_x = pl.DataFrame({'a': [1, 2, 3]})\ndf_x\n```\n"
    )


def test_a_code_cell_quoting_a_fence_gets_a_longer_one():
    cell = Cell('doc = """\n```python\nx = 1\n```\n"""')
    src = render_qmd([cell], front_matter="title: T")
    assert "\n````{python}\n" in src and src.rstrip().endswith("````")


def test_markdown_is_kept_verbatim():
    # No escaping: the prose is the document's own, quotes and backslashes too.
    text = 'A "quoted" \\ path and """triple""" quotes.'
    assert render_qmd([md_cell(text)], front_matter="title: T").endswith(text + "\n")


def test_invalid_python_is_refused_when_the_cell_is_made():
    with pytest.raises(SyntaxError):
        Cell("def broken(:\n    pass")
