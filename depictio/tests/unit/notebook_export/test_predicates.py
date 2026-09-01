"""The predicate emitter must agree with ``add_filter`` on every branch.

Each case builds the server's ``pl.Expr`` through ``add_filter`` and the
notebook's expression by ``eval``-ing the emitted source in the namespace the
generated imports cell provides; the two must select the same rows.
"""

from __future__ import annotations

import datetime

import polars as pl
import pytest

from depictio.api.v1.deltatables_utils import LINK_NO_MATCH, add_filter
from depictio.api.v1.services.notebook_export.predicates import (
    PredicateSource,
    emit_filter_expr,
    emit_predicate,
)
from depictio.models.components.filter_expr import build_filter_expr

FRAME = pl.DataFrame(
    {
        "s": ["a", "b", "c", None],
        "i": [1, 2, 3, None],
        "f": [1.5, 2.5, 3.5, None],
        "b": [True, False, True, None],
        "d": [
            datetime.date(2024, 1, 1),
            datetime.date(2024, 6, 1),
            datetime.date(2025, 1, 1),
            None,
        ],
        "dt": [
            datetime.datetime(2024, 1, 1, 12, 30, 45),
            datetime.datetime(2024, 6, 1, 0, 0, 0),
            datetime.datetime(2025, 1, 1, 8, 0, 0),
            None,
        ],
        "t": [datetime.time(1, 0), datetime.time(2, 0), datetime.time(3, 0), None],
        "txt": ["2024-01-01", "2024-06-01T00:00:00Z", "2025-01-01 08:00:00", None],
    }
)

NAMESPACE = {"pl": pl, "datetime": datetime, "col": pl.col, "lit": pl.lit}


def _eval(src: PredicateSource) -> pl.Expr:
    scope = dict(NAMESPACE)
    if src.prelude:
        exec("\n".join(src.prelude), scope)  # noqa: S102 - test evaluates generated source
    expr = eval(src.expr, scope)  # noqa: S307
    assert isinstance(expr, pl.Expr)
    return expr


def _server(itype: str, column: str, value, dtype) -> pl.Expr | None:
    out: list = []
    add_filter(out, itype, column, value, dtype=dtype)
    assert len(out) <= 1
    return out[0] if out else None


CASES = [
    # categorical, every dtype branch
    ("MultiSelect", "s", ["a", "c"], None),
    ("MultiSelect", "s", ["a", "c"], pl.String),
    ("Select", "s", "b", pl.String),
    ("SegmentedControl", "i", ["1", "3"], pl.Int64),
    ("MultiSelect", "i", [2], pl.Int64),
    ("MultiSelect", "f", ["1.5"], pl.Float64),
    ("MultiSelect", "d", ["2024-06-01"], pl.Date),
    ("MultiSelect", "dt", ["2024-01-01 12:30:45", "2025-01-01T08:00:00"], pl.Datetime("us")),
    ("MultiSelect", "t", ["01:00:00"], pl.Time),
    ("MultiSelect", "b", ["true"], pl.Boolean),  # unconvertible dtype → string-cast fallback
    ("MultiSelect", "i", ["abc"], pl.Int64),  # nothing converts → fallback
    ("MultiSelect", "i", ["1", "abc"], pl.Int64),  # partial conversion keeps the convertible
    # the other controls
    ("TextInput", "s", "a|c", None),
    ("Slider", "i", 2, None),
    ("RangeSlider", "f", [2.0, 3.5], None),
    ("RangeSlider", "i", [0, 2], pl.Int64),
    ("DateRangePicker", "d", ["2024-01-01", "2024-06-01"], pl.Date),
    ("DateRangePicker", "txt", ["2024-01-01", "2024-12-31"], pl.String),
    ("Timeline", "dt", ["2024-06-01T00:00:00Z", "2025-06-01T00:00:00.000"], pl.Datetime("us")),
    ("Timeline", "txt", ["2024-05-05T16:10:27Z", "2025-05-05T16:10:27Z"], pl.String),
    (LINK_NO_MATCH, "s", [], None),
]


@pytest.mark.parametrize("itype,column,value,dtype", CASES)
def test_emitted_source_matches_add_filter(itype, column, value, dtype):
    expected = _server(itype, column, value, dtype)
    emitted = emit_predicate(itype, column, value, dtype)
    assert expected is not None and emitted is not None
    got = FRAME.filter(_eval(emitted))
    want = FRAME.filter(expected)
    assert got.equals(want), f"{emitted.expr}\n got {got}\n want {want}"


@pytest.mark.parametrize(
    "itype,value",
    [
        ("MultiSelect", []),
        ("MultiSelect", None),
        ("TextInput", ""),
        ("Slider", None),
        ("RangeSlider", []),
        ("DateRangePicker", ["2024-01-01"]),  # not a pair → server skips it too
        ("Switch", True),  # no server branch at all
        ("Unknown", "x"),
    ],
)
def test_nothing_emitted_when_the_server_appends_nothing(itype, value):
    assert _server(itype, "s", value, None) is None
    assert emit_predicate(itype, "s", value, None) is None


def test_link_no_match_selects_no_rows():
    src = emit_predicate(LINK_NO_MATCH, "s", [], None)
    assert src is not None and src.expr == "pl.lit(False)"
    assert FRAME.filter(_eval(src)).height == 0


@pytest.mark.parametrize(
    "expr",
    [
        "col('i') > 1",
        "(col('i') >= 2) & (col('s') != 'c')",
        "col('s').is_in(['a', 'b'])",
        "col('f').is_between(2.0, 3.0)",
        "~col('s').is_null()",
    ],
)
def test_filter_expr_is_emitted_verbatim_and_evaluates_like_the_server(expr):
    src = emit_filter_expr(expr)
    got = FRAME.filter(eval(src, dict(NAMESPACE)))  # noqa: S307
    want = FRAME.filter(build_filter_expr(expr))
    assert got.equals(want)


def test_filter_expr_rejects_unsafe_source():
    with pytest.raises(ValueError):
        emit_filter_expr("__import__('os').system('x')")


def test_as_lines_produces_an_assignment():
    src = emit_predicate("MultiSelect", "s", ["a"], pl.String)
    assert src is not None
    assert src.as_lines("stage_1") == ["stage_1 = stage_1.filter(pl.col('s').is_in(['a']))"]
