"""The Python a bundle's Pyodide runtime runs: the server's own code, shipped.

Nothing here is a second implementation. The modules a Python-live tile needs
are copied from the server tree at export time:

* whole files, verbatim — the code-figure sandbox
  (``services/figure/code_executor.py`` + ``code_mode.py``, RestrictedPython
  guards and audit hook included), the group comparison
  (``services/group_compare.py``), the dimension reductions
  (``recipes/lib/dimreduction.py``);
* single functions, with every module-level name they reach, extracted from
  modules too heavy to ship whole (:func:`extract`): the code-figure post-pass
  of ``build_figure_preview`` (``recolor_code_figure``, ``tidy_facet_layout``,
  ``code_group_globals``, ``code_sets_template``) and the embedding's
  ``_embedding_result_from_frame``, one module each under
  ``depictio_bundle_ext/``.

One edit: the depictio logger is a stub (``logging.getLogger``). The code
executor is shipped unmodified — it builds its write guard from pandas types at
import, so a bundle with a code figure always embeds pandas.
``depictio_bundle.py`` (next to this file) is the entry point the runtime
calls.
"""

from __future__ import annotations

import ast
import inspect
import types
from importlib import import_module
from pathlib import Path

BOOTSTRAP = Path(__file__).with_name("depictio_bundle.py")

_LOGGER_STUB = 'import logging\n\nlogger = logging.getLogger("depictio.bundle")\n'

#: Whole server files shipped as is: (module, path in the Pyodide FS).
_VERBATIM: tuple[tuple[str, str], ...] = (
    (
        "depictio.api.v1.services.figure.code_executor",
        "depictio/api/v1/services/figure/code_executor.py",
    ),
    ("depictio.api.v1.services.figure.code_mode", "depictio/api/v1/services/figure/code_mode.py"),
    ("depictio.api.v1.services.group_compare", "depictio/api/v1/services/group_compare.py"),
    ("depictio.recipes.lib.dimreduction", "depictio/recipes/lib/dimreduction.py"),
)

#: Functions extracted from heavy modules, by module.
_EXTRACTED: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "depictio.api.v1.services.figure.figure_builder",
        ("recolor_code_figure", "code_sets_template"),
    ),
    ("depictio.api.v1.services.figure.groups", ("code_group_globals", "tidy_facet_layout")),
    ("depictio.api.v1.celery_tasks", ("_embedding_result_from_frame",)),
)

#: depictio imports an extracted function may keep, because the module they
#: name is shipped too (or stubbed).
_SHIPPED_IMPORTS = {
    "depictio.api.v1.configs.logging_init",
    "depictio.recipes.lib.dimreduction",
}


class ExtractError(RuntimeError):
    """A function reaches a module-level name that cannot be shipped."""


def _bound_names(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    return set()


def _used_names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def extract(module: types.ModuleType, roots: tuple[str, ...]) -> str:
    """Source of ``roots`` plus every top-level name of ``module`` they reach.

    Statements come out in the module's own order; imports are kept when a
    shipped statement uses what they bind. A ``from depictio...`` import is kept
    only for a shipped (or stubbed) module, and anything else raises, so a
    server change that drags a new dependency into one of these functions fails
    the export test instead of the bundle.
    """
    source = inspect.getsource(module)
    tree = ast.parse(source)
    defs: dict[str, ast.stmt] = {}
    imports: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
        for name in _bound_names(node):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                defs.setdefault(name, node)
    wanted: set[int] = set()
    used: set[str] = set()
    stack = list(roots)
    while stack:
        name = stack.pop()
        node = defs.get(name)
        if node is None:
            if name not in roots:
                continue
            raise ExtractError(f"{module.__name__} defines no {name!r}")
        if id(node) in wanted:
            continue
        wanted.add(id(node))
        names = _used_names(node)
        used |= names
        stack.extend(n for n in names if n in defs)
    lines = ["from __future__ import annotations", ""]
    for node in imports:
        bound = _bound_names(node)
        if not bound & used:
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        mod = node.module if isinstance(node, ast.ImportFrom) else None
        if mod and mod.startswith("depictio"):
            if mod not in _SHIPPED_IMPORTS:
                raise ExtractError(
                    f"{module.__name__}: {', '.join(sorted(bound & used))} come(s) from {mod}, "
                    "which a bundle does not ship"
                )
        lines.append(ast.get_source_segment(source, node) or "")
    lines.append("")
    for node in tree.body:
        if id(node) in wanted:
            lines.append(ast.get_source_segment(source, node) or "")
            lines.append("")
    return "\n".join(lines)


def _verbatim(module_name: str) -> str:
    return inspect.getsource(import_module(module_name))


def bundle_python_sources() -> dict[str, str]:
    """``{path: source}`` written into the Pyodide filesystem before the import."""
    files: dict[str, str] = {}
    for module_name, path in _VERBATIM:
        files[path] = _verbatim(module_name)
    files["depictio/api/v1/configs/logging_init.py"] = _LOGGER_STUB
    for module_name, roots in _EXTRACTED:
        short = module_name.rsplit(".", 1)[-1]
        header = f'"""Extracted from {module_name}: {", ".join(roots)} (modules.py)."""\n'
        files[f"depictio_bundle_ext/{short}.py"] = header + extract(
            import_module(module_name), roots
        )
    files["depictio_bundle.py"] = BOOTSTRAP.read_text()
    # Packages for every directory on the way (namespace packages would do in
    # CPython, but explicit ones make the tree importable the same everywhere).
    for path in list(files):
        parts = Path(path).parts[:-1]
        for i in range(1, len(parts) + 1):
            init = "/".join(parts[:i]) + "/__init__.py"
            files.setdefault(init, "")
    return files
