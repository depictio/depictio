"""Folding the injected code-mode context at the export's default state."""

from __future__ import annotations

import polars as pl

from depictio.serverless.context_fold import fold_context
from depictio.serverless.prologue import transpile_with_reason
from depictio.serverless.prologue_exec import execute_ops, terminal_px_call

AMPLISEQ = """grp_col = depictio_group_by[0] if depictio_group_by else 'habitat'
colors = depictio_group_kwargs.get('color_discrete_map') or depictio_category_colors.get('habitat') or {}
fig = px.box(df.to_pandas(), x=grp_col, y='shannon', color=grp_col, color_discrete_map=colors, points='all')
"""


def test_the_injected_names_fold_into_literals():
    folded = fold_context(AMPLISEQ, {"habitat": {"lake": "#123456"}})
    assert "depictio_" not in folded and "grp_col" not in folded
    ops, refusal = transpile_with_reason(folded)
    assert ops == [] and refusal is None
    visu, kwargs = terminal_px_call(folded)
    assert visu == "box"
    assert kwargs["x"] == "habitat" and kwargs["color_discrete_map"] == {"lake": "#123456"}
    # Unfolded, the transpiler took the helper names for frames.
    assert transpile_with_reason(AMPLISEQ)[0] is None


def test_a_columns_guard_folds_only_against_the_schema():
    code = (
        "grp = depictio_group_by[0] if depictio_group_by else 'habitat'\n"
        "d = df if grp in df.columns else df.with_columns(pl.lit('All').alias(grp))\n"
        "d = d.filter(pl.col('shannon').is_not_null()).sort(grp)\n"
        "fig = px.box(d.to_pandas(), x=grp, y='shannon')\n"
    )
    assert transpile_with_reason(fold_context(code))[0] is None
    folded = fold_context(code, columns=["habitat", "shannon"])
    ops, _ = transpile_with_reason(folded)
    assert [op.op for op in ops] == ["filter", "sort"]


def test_spreads_and_pure_builtins_fold():
    code = (
        "df_modified = df.group_by(list(dict.fromkeys([*depictio_group_by, 'city', 'habitat'])))"
        ".len().rename({'len': 'samples'}).sort('city')\n"
        "fig = px.bar(df_modified.to_pandas(), x='city', y='samples', color='habitat', **depictio_group_kwargs)\n"
    )
    folded = fold_context(code)
    ops, refusal = transpile_with_reason(folded)
    assert refusal is None and [op.op for op in ops] == ["group_by", "rename", "sort"]
    df = pl.DataFrame({"city": ["b", "a", "a"], "habitat": ["x", "y", "y"]})
    out = execute_ops(ops, df)
    assert out.to_dicts() == [
        {"city": "a", "habitat": "y", "samples": 2},
        {"city": "b", "habitat": "x", "samples": 1},
    ]


def test_code_without_the_names_is_untouched():
    code = "fig = px.scatter(df.to_pandas(), x='a', y='b')\n"
    assert fold_context(code) == code
