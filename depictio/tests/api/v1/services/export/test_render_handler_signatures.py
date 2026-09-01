"""The export services call viewer route handlers directly; the calls must bind.

``services/export/`` builds its payloads by calling the very same handlers the live
viewer calls over HTTP (``render_figure_endpoint``, ``render_table_endpoint`` and
friends), so that an export and the dashboard cannot render different things. That
is the right design and it has one sharp edge: a direct Python call gets none of
FastAPI's dependency injection, so adding a parameter to a handler silently breaks
the export path.

It breaks at *request* time, not import time, and only for the component type
that handler serves. ``render_table_endpoint`` gained a ``response: Response``
parameter for its diagnostic ``X-Link-*`` headers; every table embed then failed
with ``missing 1 required positional argument: 'response'`` while every other
component type kept working, so nothing short of exporting a table noticed.

Every module in the package is scanned, not just ``embed.py``: ``table_export.py``
calls the same handler for ``format=data``, and the next one will too.

Nor is it only the route handlers. ``plotly_export.py`` calls ``render_map``
straight out of the map service the same way, and when that function dropped its
``active_selection_values`` parameter every map export began answering 500 while
the rest of the API was fine. So the scan covers every function the package
imports from anywhere in ``depictio`` and calls: the sharp edge is the direct
call across a package boundary, not the callee's address.

The check is derived from the source rather than from a hand-written list of
arguments: a list would be one more thing to update in the same commit that
breaks this, which is exactly the commit that will forget.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

ROUTES_MODULE = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
MAP_RENDER_MODULE = "depictio.api.v1.services.map.render"
EXPORT_PACKAGE = (
    Path(__file__).resolve().parents[6] / "depictio" / "api" / "v1" / "services" / "export"
)


def _handler_calls() -> list[tuple[str, str, str, list[str], int, int]]:
    """Every call in the export package to a function imported from depictio.

    Returns ``(module, callee_module, callee, keywords, positional_count,
    lineno)`` per call site. The imports are mostly function-local (they break
    import cycles), so the walk collects names from every ``ImportFrom`` it
    finds rather than only the ones at the top of the file. ``callee`` is the
    name in its own module, not the local alias: the package imports the
    deltatables ``specs`` handler as ``fetch_specs``.
    """
    calls = []
    for source in sorted(EXPORT_PACKAGE.glob("*.py")):
        tree = ast.parse(source.read_text())

        imported: dict[str, tuple[str, str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not (node.module or "").startswith("depictio"):
                continue
            for alias in node.names:
                imported[alias.asname or alias.name] = (node.module or "", alias.name)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # `await handler(...)` parses as a Call inside an Await, so the Call
            # node is reached either way and needs no special case.
            if not isinstance(func, ast.Name) or func.id not in imported:
                continue
            # `f(*args)` / `f(**kwargs)` hide their arity from a static read, so
            # binding them would test the unpacking rather than the signature.
            if any(isinstance(arg, ast.Starred) for arg in node.args):
                continue
            if any(kw.arg is None for kw in node.keywords):
                continue
            keywords = [kw.arg for kw in node.keywords if kw.arg is not None]
            callee_module, callee = imported[func.id]
            calls.append(
                (source.name, callee_module, callee, keywords, len(node.args), node.lineno)
            )
    return calls


CALLS = _handler_calls()


def test_the_scan_found_the_known_call_sites():
    """Guard the guard: an empty parse would make every assertion below vacuous."""
    called = {(module, callee) for module, _, callee, _, _, _ in CALLS}
    assert ("embed.py", "render_figure_endpoint") in called, called
    assert ("table_export.py", "render_table_endpoint") in called, called
    assert ("plotly_export.py", "render_map") in called, called


@pytest.mark.parametrize(
    "module,callee_module,callee,keywords,positional,lineno",
    CALLS,
    ids=[f"{module}:{callee}:L{lineno}" for module, _, callee, _, _, lineno in CALLS],
)
def test_handler_call_binds(
    module: str,
    callee_module: str,
    callee: str,
    keywords: list[str],
    positional: int,
    lineno: int,
):
    """Each call site supplies every parameter the callee has no default for."""
    function = getattr(importlib.import_module(callee_module), callee)
    signature = inspect.signature(function)
    try:
        signature.bind(*[None] * positional, **dict.fromkeys(keywords))
    except TypeError as error:
        pytest.fail(
            f"{module}:{lineno} cannot call {callee}{signature}: {error}. "
            f"The signature changed in {callee_module} under the export path; a "
            "direct call gets no dependency injection, so every parameter "
            "without a default has to be passed explicitly."
        )
