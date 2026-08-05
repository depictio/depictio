"""Pin the build-side prologue executor against the cross-language arbiter.

``depictio/serverless/prologue_exec.py`` is the third implementation of the
same IR: the transpiler writes it, this executor runs it at build time (to
derive the frame a code-mode figure's binding is built against), and
``packages/depictio-static-core/src/prologue.ts`` runs it in the browser at
every filter state. If those three disagree, a "live" code-mode figure renders
data the server never would have.

So this module replays **every committed fixture case** through
:func:`execute_ops` and compares against ``fixtures/prologue-expected.json`` —
the very file the vitest suite checks the TypeScript interpreter against, and
the one ``test_prologue.py`` checks the transpiler + generator against. Same
input frame, same expectation, same serialisation helper (``columns_payload``
from the fixture generator: NaN/±Inf -> null, datetimes -> fixed-width ISO,
floats via repr's shortest round-trip), so "equal" means equal cell by cell.

Plus focused unit tests for :func:`terminal_px_call`, the other half of the
module — the ``fig = px.…`` reader whose ``None`` freezes a figure.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import polars as pl
import pytest
from pydantic import TypeAdapter

from depictio.models.models.serverless import PrologueOp
from depictio.serverless.prologue_exec import execute_ops, terminal_px_call

REPO_ROOT = Path(__file__).resolve().parents[4]
STATIC_CORE = REPO_ROOT / "packages" / "depictio-static-core"
FIXTURE_PATH = STATIC_CORE / "fixtures" / "prologue-fixture.json"
EXPECTED_PATH = STATIC_CORE / "fixtures" / "prologue-expected.json"
GENERATOR_PATH = STATIC_CORE / "scripts" / "generate_prologue_fixture.py"

_OPS = TypeAdapter(list[PrologueOp])


def _load_generator():
    """Import the fixture generator by path — it owns the reference semantics."""
    spec = importlib.util.spec_from_file_location("_prologue_fixture_gen", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()
FIXTURE = json.loads(FIXTURE_PATH.read_text())
EXPECTED = json.loads(EXPECTED_PATH.read_text())

FIXTURE_CASES = {case["name"]: case for case in FIXTURE["cases"]}
EXPECTED_CASES = {case["name"]: case for case in EXPECTED["cases"]}


@pytest.fixture(scope="module")
def input_frame() -> pl.DataFrame:
    """The fixture's input table — asserted below to BE the committed one."""
    return GEN.build_input()


def test_input_frame_is_the_committed_fixture_input(input_frame: pl.DataFrame) -> None:
    assert GEN.columns_payload(input_frame) == FIXTURE["input"]["columns"]


# ---------------------------------------------------------------------------
# differential: execute_ops == the committed expectation, case by case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(FIXTURE_CASES))
def test_execute_ops_matches_the_committed_expectation(
    name: str, input_frame: pl.DataFrame
) -> None:
    # The ops go through the model first: the executor's contract is typed IR,
    # and validating here also re-pins the fixture as legal IR.
    ops = _OPS.validate_python(FIXTURE_CASES[name]["ops"])
    out = execute_ops(ops, input_frame)

    expected = EXPECTED_CASES[name]["output"]
    assert out.height == expected["length"], name
    assert GEN.columns_payload(out) == expected["columns"], name


@pytest.mark.parametrize("name", sorted(FIXTURE_CASES))
def test_execute_ops_agrees_with_the_generator(name: str, input_frame: pl.DataFrame) -> None:
    """Frame-level equality (dtypes included) against the generator's
    ``apply_ops`` — the JSON payload above is lossy about dtypes."""
    ops_json = FIXTURE_CASES[name]["ops"]
    assert execute_ops(_OPS.validate_python(ops_json), input_frame).equals(
        GEN.apply_ops(input_frame, ops_json)
    ), name


def test_empty_program_is_the_identity(input_frame: pl.DataFrame) -> None:
    assert execute_ops([], input_frame).equals(input_frame)


def test_missing_column_raises(input_frame: pl.DataFrame) -> None:
    """A malformed program must fail loudly — the producers catch and freeze."""
    ops = _OPS.validate_python([{"op": "sort", "by": ["nope"], "desc": [False]}])
    with pytest.raises(Exception):
        execute_ops(ops, input_frame)


# ---------------------------------------------------------------------------
# terminal_px_call
# ---------------------------------------------------------------------------


def _code(prep: str, fig_line: str) -> str:
    return f"{prep}\n{fig_line}" if prep else fig_line


@pytest.mark.parametrize(
    "prep,fig_line,expected",
    [
        # No prologue: the terminal frame is `df` itself.
        ("", "fig = px.scatter(df, x='a', y='b')", ("scatter", {"x": "a", "y": "b"})),
        # `.to_pandas()` is an identity conversion (same rows, same names).
        (
            "",
            "fig = px.bar(df.to_pandas(), x='a', y='b')",
            ("bar", {"x": "a", "y": "b"}),
        ),
        # Explicit data_frame= keyword.
        (
            "",
            "fig = px.line(data_frame=df, x='a', y='b')",
            ("line", {"x": "a", "y": "b"}),
        ),
        # The frame the prologue ends on.
        (
            "df2 = df.group_by('g').agg(pl.col('v').mean())",
            "fig = px.bar(df2, x='g', y='v')",
            ("bar", {"x": "g", "y": "v"}),
        ),
        # Literal kwargs of every accepted shape.
        (
            "",
            "fig = px.bar(df, x='a', y='b', barmode='group', log_y=True, opacity=0.5,"
            " nbins=-3, title=None, hover_data=['a', 'b'],"
            " category_orders={'a': ['x', 'y']})",
            (
                "bar",
                {
                    "x": "a",
                    "y": "b",
                    "barmode": "group",
                    "log_y": True,
                    "opacity": 0.5,
                    "nbins": -3,
                    "title": None,
                    "hover_data": ["a", "b"],
                    "category_orders": {"a": ["x", "y"]},
                },
            ),
        ),
    ],
)
def test_terminal_px_call_accepts(prep, fig_line, expected) -> None:
    assert terminal_px_call(_code(prep, fig_line)) == expected


@pytest.mark.parametrize(
    "prep,fig_line",
    [
        # Not a px call at all.
        ("", "fig = go.Figure()"),
        ("", "fig = undefined_name"),
        ("", "fig = make_figure(df, x='a')"),
        ("", "fig = px"),
        # A frame that is not the terminal prologue frame: the ops we compiled
        # never produced it, so a binding built on them would be wrong.
        ("df2 = df.sort('a')", "fig = px.bar(df, x='a', y='b')"),
        ("", "fig = px.bar(other, x='a', y='b')"),
        # Conversions we do not model.
        ("", "fig = px.bar(df.to_dicts(), x='a', y='b')"),
        ("", "fig = px.bar(df.head(10), x='a', y='b')"),
        ("", "fig = px.bar(df['a'], x='a')"),
        # Non-literal kwarg values — never guess what they evaluate to.
        ("", "fig = px.bar(df, x='a', y=y_col)"),
        ("", "fig = px.bar(df, x='a', color=dict(a=1)['a'])"),
        ("", "fig = px.bar(df, x='a', y='b', labels={'a': label})"),
        ("", "fig = px.bar(df, x='a', y='b', category_orders={key: ['x']})"),
        ("", "fig = px.bar(df, x='a', title='n=' + str(1))"),
        # Unpacking.
        ("", "fig = px.bar(df, **kwargs)"),
        ("", "fig = px.bar(*args, x='a')"),
        # Extra positional arguments (px's positional API beyond data_frame).
        ("", "fig = px.bar(df, 'a', 'b')"),
        # Frame passed twice.
        ("", "fig = px.bar(df, data_frame=df)"),
        # No frame at all.
        ("", "fig = px.bar(x=[1, 2], y=[3, 4])"),
        # No fig assignment / unparseable.
        ("", "figure = px.bar(df, x='a')"),
        ("", "fig = px.bar(df, x='a'"),
    ],
)
def test_terminal_px_call_refuses(prep, fig_line) -> None:
    assert terminal_px_call(_code(prep, fig_line)) is None


@pytest.mark.parametrize("code", ["", "   \n\n"])
def test_terminal_px_call_refuses_empty(code: str) -> None:
    assert terminal_px_call(code) is None


def test_terminal_px_call_ignores_the_suffix() -> None:
    """Post-``fig`` customisation is baked into the scaffold by the real run."""
    code = (
        "df2 = df.sort('a')\n"
        "fig = px.bar(df2, x='a', y='b')\n"
        "fig.update_layout(title='Custom')\n"
        "fig.update_traces(marker_color='red')\n"
    )
    assert terminal_px_call(code) == ("bar", {"x": "a", "y": "b"})
