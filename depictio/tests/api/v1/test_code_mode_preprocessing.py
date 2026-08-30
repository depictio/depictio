"""What a code-mode figure's preprocessing section is allowed to be called.

The analyzer splits user code into "preprocessing" and "the figure statement".
It used to recognise preprocessing only by variable name (`df_modified`, or a
`df_` prefix) and silently dropped every other line, so code that named an
intermediate anything else failed at render time on a NameError pointing at the
figure line — nowhere near the line that had been thrown away.
"""

from __future__ import annotations

from depictio.api.v1.services.figure.code_mode import analyze_constrained_code


def test_keeps_preprocessing_under_any_variable_name() -> None:
    code = "\n".join(
        [
            "depths = sorted(df['depth'].unique().to_list())[-2:]",
            "top2 = df.filter(pl.col('depth').is_in(depths))",
            "gain = top2.group_by('sample').agg(pl.col('faith_pd').max())",
            "fig = px.strip(gain.to_pandas(), x='faith_pd')",
        ]
    )
    analysis = analyze_constrained_code(code)

    assert analysis["is_valid"]
    assert analysis["has_preprocessing"]
    for name in ("depths", "top2", "gain"):
        assert name in analysis["preprocessing_code"], f"{name} was dropped"


def test_multi_line_statement_under_any_name_stays_whole() -> None:
    code = "\n".join(
        [
            "summary = df.group_by('sample').agg([",
            "    pl.col('value').median().alias('median'),",
            "])",
            "fig = px.bar(summary.to_pandas(), x='sample', y='median')",
        ]
    )
    analysis = analyze_constrained_code(code)

    assert analysis["is_valid"]
    assert "pl.col('value').median()" in analysis["preprocessing_code"]
    assert analysis["preprocessing_code"].count("summary =") == 1


def test_df_modified_convention_still_recognised() -> None:
    code = "\n".join(
        [
            "df_modified = df.filter(pl.col('x') > 0)",
            "fig = px.scatter(df_modified.to_pandas(), x='x', y='y')",
        ]
    )
    analysis = analyze_constrained_code(code)

    assert analysis["is_valid"]
    assert analysis["uses_modified_df"]
    assert "df_modified =" in analysis["preprocessing_code"]


def test_figure_only_code_has_no_preprocessing() -> None:
    analysis = analyze_constrained_code("fig = px.scatter(df.to_pandas(), x='x', y='y')")

    assert analysis["is_valid"]
    assert not analysis["has_preprocessing"]


def test_post_figure_customisation_is_not_preprocessing() -> None:
    code = "\n".join(
        [
            "counts = df.group_by('g').len()",
            "fig = px.bar(counts.to_pandas(), x='g', y='len')",
            "fig.update_layout(showlegend=False)",
        ]
    )
    analysis = analyze_constrained_code(code)

    assert analysis["is_valid"]
    assert "counts =" in analysis["preprocessing_code"]
    assert "update_layout" in analysis["figure_code"]
    assert "update_layout" not in analysis["preprocessing_code"]


def test_post_figure_loop_survives_whole() -> None:
    """A block after the figure statement must reach the interpreter intact.

    Post-figure lines used to be filtered down to the ones starting with `fig.`
    and re-emitted at column 0. A `fig.add_scatter(...)` written in a loop body
    therefore came back stranded, referring to a loop variable whose assignment
    had been dropped, and rendering died on a NameError for a name the user had
    in fact defined.
    """
    code = "\n".join(
        [
            "palette = {'a': '#111111', 'b': '#222222'}",
            "fig = px.scatter(df.to_pandas(), x='x', y='y')",
            "for name, colour in palette.items():",
            "    sub = df.to_pandas()",
            "    fig.add_scatter(x=sub['x'], y=sub['y'], name=name, marker=dict(color=colour))",
        ]
    )
    analysis = analyze_constrained_code(code)

    assert analysis["is_valid"]
    figure_code = analysis["figure_code"]
    assert "for name, colour in palette.items():" in figure_code
    assert "    sub = df.to_pandas()" in figure_code
    # Indentation is what makes the two lines above a loop body rather than two
    # statements, so assert on the indented form, not merely on the substring.
    assert "    fig.add_scatter(" in figure_code
    compile(figure_code, "<figure_code>", "exec")


def test_preprocessing_block_keeps_its_indentation() -> None:
    """The same guarantee before the figure statement."""
    code = "\n".join(
        [
            "totals = {}",
            "for key in ['a', 'b']:",
            "    totals[key] = 1",
            "fig = px.bar(df.to_pandas(), x='x', y='y')",
        ]
    )
    analysis = analyze_constrained_code(code)

    assert analysis["is_valid"]
    assert "    totals[key] = 1" in analysis["preprocessing_code"]
    compile(analysis["preprocessing_code"], "<preprocessing>", "exec")
