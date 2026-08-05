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

from depictio.serverless.binding import build_binding

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


def cases(df: pl.DataFrame) -> list[tuple[str, dict[str, Any], pl.DataFrame, bool]]:
    """``(label, component dict, frame, expected-to-bind)``."""
    sexed = df.drop_nulls("sex")  # `sex` has 9 nulls; a null group never matches

    def figure(visu_type: str, **kwargs: Any) -> dict[str, Any]:
        return {"component_type": "figure", "visu_type": visu_type, "dict_kwargs": kwargs}

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
            "AMBIGUOUS: two identical groups",
            figure("scatter", x="x", y="y", color="grp"),
            ambiguous_frame(),
            False,
        ),
        (
            "null in grouping column (sex)",
            figure("scatter", x="flipper_length_mm", y="body_mass_g", color="sex"),
            df,
            False,
        ),
        (
            "hover_data (2-D customdata)",
            figure("scatter", x="flipper_length_mm", y="body_mass_g", hover_data=["island"]),
            df,
            False,
        ),
    ]


def main() -> None:
    df = penguins_frame()
    matched = 0
    unexpected: list[str] = []
    print(f"binding coverage — penguins frame: {df.height} rows, {len(df.columns)} columns\n")
    for label, component, frame, expect_bound in cases(df):
        table = build_binding(component, frame)
        if table is not None:
            matched += 1
            summary = (
                f"MATCHED  group_cols={table.group_cols} "
                f"traces={len(table.traces)} trendlines={len(table.trendlines)} "
                f"sampled={table.sampled} "
                f"fields={sorted({f for t in table.traces for f in t.fields})}"
            )
        else:
            summary = "REFUSED  (component freezes with binding_miss)"
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
