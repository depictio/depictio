"""The builtins a code-mode figure may call.

RestrictedPython's `safe_builtins` is not the whole allowlist: the executor
adds to it. A builtin missing from both surfaces only when the figure runs,
as a bare `NameError` inside the tile, so the set is worth pinning.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1.services.figure.code_executor import SimpleCodeExecutor

PURE_BUILTINS = [
    "max",
    "min",
    "sum",
    "any",
    "all",
    "set",
    "sorted",
    "reversed",
    "abs",
    "round",
    "len",
    "range",
    "list",
    "dict",
    "tuple",
    "enumerate",
    "zip",
    "int",
    "float",
    "str",
]


def _frame() -> pl.DataFrame:
    return pl.DataFrame({"x": [1.0, 4.0, 2.0], "y": [3.0, 1.0, 5.0]})


@pytest.mark.parametrize("name", PURE_BUILTINS)
def test_pure_builtin_is_bound_in_a_code_figure(name: str) -> None:
    # Binding the name is the whole assertion: an unbound builtin raises
    # NameError here exactly as it would mid-figure. The preprocessing step
    # requires the snippet to create a variable, hence the assignment.
    code = f"probe = {name}\nfig = px.scatter(df.to_pandas(), x='x', y='y')\n"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert ok, f"{name}: {message}"


def test_max_sizes_a_reference_line():
    """The shape that failed in production: a diagonal drawn to the data's own extent."""
    code = (
        "limit = max(1, int(max(df['x'].max() or 0, df['y'].max() or 0)))\n"
        "fig = px.scatter(df.to_pandas(), x='x', y='y')\n"
        "fig.add_shape(type='line', x0=0, y0=0, x1=limit, y1=limit)\n"
    )
    ok, fig, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert ok, message
    assert fig.layout.shapes[0].x1 == 5


def test_import_is_still_refused():
    """The allowlist grew; the sandbox did not open."""
    ok, _, message = SimpleCodeExecutor().execute_code(
        "import os\nfig = px.scatter(df.to_pandas(), x='x', y='y')\n", _frame()
    )
    assert not ok
    assert "import" in message.lower()
