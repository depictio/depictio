"""Quarto cells, and the ``.qmd`` document that holds them.

A Quarto document is markdown with executable chunks: YAML front matter, then
prose, then fenced ```` ```{python} ```` blocks run top to bottom by a Jupyter
kernel. The generator lays its cells out in reading order, so the document is
simply those cells in sequence — no dependency graph, no second format to
derive.

``Cell`` carries a body as source text. A code body is parsed once when the
cell is made, so a generator bug that emits invalid Python fails the export
on the server rather than the reader's render.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from depictio.notebook.qmd_safe import defuse, defuse_code


@dataclass
class Cell:
    body: str
    kind: str = "code"  # "code" | "md"
    # A code-mode figure's own Python, written by the dashboard's author: it
    # is the reader's to run (the downloaded document), never the server's,
    # and it is emitted as written.
    authored: bool = False

    def __post_init__(self) -> None:
        if self.kind == "code":
            ast.parse(self.body)


def md_cell(text: str) -> Cell:
    """A markdown cell: the text, as the document's own prose."""
    return Cell(body=text.strip("\n"), kind="md")


_BACKTICK_RUN = re.compile(r"`{3,}")


def _fence(body: str) -> str:
    """A backtick fence longer than any run inside ``body``, so a code cell
    quoting a markdown block (an author's docstring, say) cannot close it."""
    longest = max((len(m.group(0)) for m in _BACKTICK_RUN.finditer(body)), default=2)
    return "`" * max(3, longest + 1)


def render_cell(cell: Cell) -> str:
    """The cell as document text, with no Quarto construct it did not mean.

    Every site that writes dynamic text escapes it (``depictio.notebook.qmd_safe``);
    this is the net under all of them. Markdown keeps only the raw blocks the
    generator writes (```` ```{=typst} ````); generated Python keeps its
    meaning, with no shortcode in its source and no stray line terminator.
    """
    if cell.kind == "md":
        return defuse(cell.body, allow_raw=True)
    body = cell.body if cell.authored else defuse_code(cell.body)
    if body != cell.body:
        ast.parse(body)
    fence = _fence(body)
    return f"{fence}{{python}}\n{body.rstrip()}\n{fence}"


def render_qmd(cells: list[Cell], *, front_matter: str) -> str:
    """The ``.qmd`` file: ``front_matter`` (YAML, without its ``---`` lines), then the cells."""
    parts = [f"---\n{front_matter.strip()}\n---"]
    parts.extend(render_cell(cell) for cell in cells)
    return "\n\n".join(parts) + "\n"
