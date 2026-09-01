"""marimo cells, and the file that holds them.

marimo's file format is plain Python: one ``@app.cell`` function per cell,
whose parameters are the globals the cell reads and whose ``return`` tuple is
the globals it defines. Names prefixed with ``_`` are local to the cell. Every
other global may be defined by exactly one cell.

``Cell`` carries a body as source text; ``analyze`` derives, with ``ast``,
which public names the body binds (its defs) and which names it reads (its
refs). ``render_notebook`` turns the list into a file, computing each cell's
parameter list as "refs that some other cell defines".
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Iterable

INDENT = "    "


@dataclass
class Cell:
    body: str
    kind: str = "code"  # "code" | "md"
    defines: set[str] = field(default_factory=set)
    refs: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        defs, refs = analyze(self.body)
        self.defines = defs
        self.refs = refs


def _targets(node: ast.AST) -> Iterable[str]:
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _targets(elt)
    elif isinstance(node, ast.Starred):
        yield from _targets(node.value)


def _bound_at_top_level(tree: ast.Module) -> set[str]:
    bound: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign,)):
            for t in stmt.targets:
                bound.update(_targets(t))
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            bound.update(_targets(stmt.target))
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            bound.update(_targets(stmt.target))
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if item.optional_vars is not None:
                    bound.update(_targets(item.optional_vars))
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(stmt.name)
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
                bound.add(sub.target.id)
    return bound


def _bound_anywhere(tree: ast.Module) -> set[str]:
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return bound


def analyze(body: str) -> tuple[set[str], set[str]]:
    """``(defines, refs)`` of a cell body.

    ``defines`` are the public names bound at the top level of the body;
    ``refs`` are the names the body reads without binding them anywhere
    (locals, function parameters and ``_``-prefixed names excluded).
    """
    tree = ast.parse(body)
    defines = {n for n in _bound_at_top_level(tree) if not n.startswith("_")}
    bound = _bound_anywhere(tree)
    loads = {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    refs = {n for n in loads - bound if not n.startswith("_")}
    return defines, refs


def md_cell(text: str) -> Cell:
    """A markdown cell: ``mo.md(...)`` as the cell's only expression."""
    escaped = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    lines = escaped.strip("\n").split("\n")
    body = 'mo.md(\n    """\n' + "\n".join(lines) + '\n"""\n)'
    return Cell(body=body, kind="md")


def indent(text: str, level: int = 1) -> str:
    pad = INDENT * level
    return "\n".join((pad + line) if line.strip() else "" for line in text.split("\n"))


def render_cell(cell: Cell, params: list[str]) -> str:
    defs = sorted(cell.defines)
    if len(defs) == 0:
        ret = "return"
    elif len(defs) == 1:
        ret = f"return ({defs[0]},)"
    else:
        ret = "return (" + ", ".join(defs) + ")"
    header = f"@app.cell\ndef _({', '.join(params)}):"
    return f"{header}\n{indent(cell.body)}\n{INDENT}{ret}"


def render_notebook(cells: list[Cell], *, generated_with: str, width: str = "medium") -> str:
    """The marimo file. Raises when two cells define the same global."""
    owners: dict[str, int] = {}
    for i, cell in enumerate(cells):
        for name in cell.defines:
            if name in owners:
                raise ValueError(
                    f"global {name!r} is defined by cells {owners[name]} and {i}; "
                    "marimo allows exactly one definition per global"
                )
            owners[name] = i
    parts = [
        "import marimo",
        "",
        f'__generated_with = "{generated_with}"',
        f'app = marimo.App(width="{width}")',
        "",
        "",
    ]
    for i, cell in enumerate(cells):
        params = sorted(n for n in cell.refs if n in owners and owners[n] != i)
        parts.append(render_cell(cell, params))
        parts.append("")
        parts.append("")
    parts.append('if __name__ == "__main__":')
    parts.append(f"{INDENT}app.run()")
    parts.append("")
    return "\n".join(parts)
