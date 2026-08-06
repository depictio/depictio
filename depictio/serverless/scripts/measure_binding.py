"""Coverage report for the bind-and-refill matcher (RFC §4, phase 5a).

Runs :func:`depictio.serverless.binding.build_binding` over the penguins
example figure plus a battery of synthetic component dicts covering the
plotly-express shapes the matcher has to survive, and prints per case whether it
matched (and with what) or was refused. A refusal is a *correct* outcome for the
ambiguous / unsupported cases — the point of the report is that the split stays
where we expect it.

    DEPICTIO_CONTEXT=cli ./venv/bin/python -m depictio.serverless.scripts.measure_binding
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from depictio.serverless.binding import build_binding_with_reason

REPO_ROOT = Path(__file__).resolve().parents[3]
PENGUINS_DATA = REPO_ROOT / "depictio" / "projects" / "init" / "penguins" / "data"


def penguins_frame() -> pl.DataFrame:
    """The example table: the repo's penguins CSV runs joined on individual_id."""
    parts = []
    for run in sorted(p for p in PENGUINS_DATA.iterdir() if p.is_dir()):
        demographic = pl.read_csv(run / "demographic_data.csv")
        physical = pl.read_csv(run / "physical_features.csv")
        parts.append(demographic.join(physical, on="individual_id", how="inner"))
    return pl.concat(parts)


def ambiguous_frame() -> pl.DataFrame:
    """Two groups with byte-identical (x, y) data — no trace can be attributed
    to one group rather than the other, so the matcher must refuse."""
    return pl.DataFrame(
        {
            "grp": ["a", "a", "b", "b"],
            "x": [1.0, 2.0, 1.0, 2.0],
            "y": [3.0, 4.0, 3.0, 4.0],
        }
    )


def pruned(component: dict[str, Any], df: pl.DataFrame) -> pl.DataFrame:
    """The frame the exporter would actually bundle for this component — i.e.
    projected to ``component_columns`` (which is ``referenced_columns`` for a
    ui-mode figure). Binding against the *unpruned* frame hides pruning gaps."""
    from depictio.serverless.pruning import component_columns

    keep = component_columns(component)
    if keep is None:
        return df
    return df.select([c for c in df.columns if c in keep])


def cases(df: pl.DataFrame) -> list[tuple[str, dict[str, Any], pl.DataFrame, bool]]:
    """``(label, component dict, frame, expected-to-bind)``."""
    sexed = df.drop_nulls("sex")  # `sex` has 9 nulls; a null group never matches

    def figure(visu_type: str, **kwargs: Any) -> dict[str, Any]:
        return {"component_type": "figure", "visu_type": visu_type, "dict_kwargs": kwargs}

    text_figure = figure(
        "scatter",
        x="flipper_length_mm",
        y="body_mass_g",
        color="species",
        text="individual_id",
    )

    return [
        (
            "penguins example (color)",
            figure("scatter", x="flipper_length_mm", y="body_mass_g", color="species"),
            df,
            True,
        ),
        (
            "color + symbol",
            figure(
                "scatter",
                x="flipper_length_mm",
                y="body_mass_g",
                color="species",
                symbol="sex",
            ),
            sexed,
            True,
        ),
        (
            "facet_row",
            figure("scatter", x="flipper_length_mm", y="body_mass_g", facet_row="species"),
            df,
            True,
        ),
        (
            "facet_col + color",
            figure(
                "scatter",
                x="flipper_length_mm",
                y="body_mass_g",
                facet_col="island",
                color="species",
            ),
            df,
            True,
        ),
        (
            "line_group",
            figure("line", x="flipper_length_mm", y="body_mass_g", line_group="species"),
            df,
            True,
        ),
        (
            "trendline (ols) + color",
            figure(
                "scatter",
                x="flipper_length_mm",
                y="body_mass_g",
                color="species",
                trendline="ols",
            ),
            df,
            True,
        ),
        (
            "no grouping (single trace)",
            figure("scatter", x="flipper_length_mm", y="body_mass_g"),
            df,
            True,
        ),
        (
            "continuous color + size",
            figure(
                "scatter",
                x="flipper_length_mm",
                y="body_mass_g",
                color="bill_depth_mm",
                size="bill_length_mm",
            ),
            df,
            True,
        ),
        (
            "text labels (pruned frame)",
            text_figure,
            pruned(text_figure, df),
            True,
        ),
        (
            "AMBIGUOUS: two identical groups",
            figure("scatter", x="x", y="y", color="grp"),
            ambiguous_frame(),
            False,
        ),
        (
            # px drops null-keyed groups and the runtime never matches a null to
            # a group, so the two agree without the combination being bound.
            "null in grouping column (sex)",
            figure("scatter", x="flipper_length_mm", y="body_mass_g", color="sex"),
            df,
            True,
        ),
        (
            "null group + symbol + ols trendline",
            figure(
                "scatter",
                x="bill_length_mm",
                y="bill_depth_mm",
                color="species",
                symbol="sex",
                trendline="ols",
            ),
            df,
            True,
        ),
        (
            "box with points (null group)",
            figure("box", x="species", y="bill_length_mm", color="sex", points="all"),
            df,
            True,
        ),
        (
            # px stacks hover columns into a 2-D customdata array; the binder
            # resolves it column by column so the hovertemplate keeps working.
            "hover_data (2-D customdata)",
            figure("scatter", x="flipper_length_mm", y="body_mass_g", hover_data=["island"]),
            df,
            True,
        ),
    ]


def main() -> None:
    df = penguins_frame()
    matched = 0
    unexpected: list[str] = []
    print(f"binding coverage — penguins frame: {df.height} rows, {len(df.columns)} columns\n")
    for label, component, frame, expect_bound in cases(df):
        table, miss = build_binding_with_reason(component, frame)
        if table is not None:
            matched += 1
            customdata = sorted({c for t in table.traces for c in t.customdata})
            summary = (
                f"MATCHED  group_cols={table.group_cols} "
                f"traces={len(table.traces)} trendlines={len(table.trendlines)} "
                f"sampled={table.sampled} "
                f"fields={sorted({f for t in table.traces for f in t.fields})}"
                + (f" customdata={customdata}" if customdata else "")
            )
        else:
            summary = f"REFUSED  ({miss.value if miss else 'unknown'} -> frozen)"
        flag = " " if (table is not None) == expect_bound else "!"
        if flag == "!":
            unexpected.append(label)
        print(f"{flag} {label:34s} {summary}")

    total = len(cases(df))
    print(f"\nmatched {matched}/{total} cases ({total - matched} refused)")
    if unexpected:
        print("UNEXPECTED verdicts: " + ", ".join(unexpected))


if __name__ == "__main__":
    main()
