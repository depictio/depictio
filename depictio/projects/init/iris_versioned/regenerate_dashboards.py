#!/usr/bin/env python3
"""Regenerate the four demo dashboards so every version is a real redesign.

The first cut of these YAMLs let two components (the sample-count card and the
variety filter) sit untouched across all four versions, and moved the rest only
slightly. That makes a poor fixture for the thing being demonstrated: opening
component history on a component that never changed shows four identical
renders, and a version diff that barely moves looks like the feature is broken
rather than like nothing happened.

So the rule enforced here is explicit and checked: **every component that
survives from one version to the next differs in something that shows on
screen** — a different aggregation, column, chart type, filter widget, or at
minimum a different size and position.

Generated rather than hand-written because the constraint is a property of the
*set* of files, and keeping four hand-edited YAMLs mutually consistent is how
the drift happened the first time. `verify()` below asserts the property, so a
future edit that flattens a version fails here rather than in someone's eyes.

    python regenerate_dashboards.py            # write the four YAMLs
    python regenerate_dashboards.py --check    # verify only, write nothing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE / "dashboards"

WF = "python/iris_versioned_workflow"
DC = "iris_versioned_table"

# Palette kept deliberately small and reused, so a colour change is never the
# *only* difference between two versions of a component.
BLUE, ORANGE, GREEN, PURPLE, RED = "#4C72B0", "#DD8452", "#55A868", "#8172B3", "#C44E52"


def card(tag, title, aggregation, column, ctype, layout, colour, icon, **extra):
    return {
        "tag": tag,
        "component_type": "card",
        "workflow_tag": WF,
        "data_collection_tag": DC,
        "aggregation": aggregation,
        "column_name": column,
        "column_type": ctype,
        "icon_name": icon,
        "icon_color": colour,
        "title_color": colour,
        "title_font_size": "xl",
        "value_font_size": "xl",
        "title": title,
        "layout": layout,
        **extra,
    }


def figure(tag, title, visu, kwargs, layout, description=""):
    return {
        "tag": tag,
        "component_type": "figure",
        "workflow_tag": WF,
        "data_collection_tag": DC,
        "visu_type": visu,
        "title": title,
        "description": description,
        "title_size": "h3",
        "dict_kwargs": kwargs,
        "layout": layout,
    }


def interactive(tag, title, widget, column, ctype, layout, colour, icon):
    return {
        "tag": tag,
        "component_type": "interactive",
        "workflow_tag": WF,
        "data_collection_tag": DC,
        "interactive_component_type": widget,
        "column_name": column,
        "column_type": ctype,
        "custom_color": colour,
        "icon_name": icon,
        "title": title,
        "layout": layout,
    }


def text(tag, title, body, layout):
    return {
        "tag": tag,
        "component_type": "text",
        "title": title,
        "order": 2,
        "alignment": "left",
        "body": body,
        "layout": layout,
    }


# ---------------------------------------------------------------------------
# The four versions.
#
# Read down a column to see one component's life: `headline` is a count, then a
# mean, then a range, then a max — four different questions in the same slot.
# `variety-filter` cycles through all three widgets its column supports.
# ---------------------------------------------------------------------------

V1 = {
    "title": "Iris Versioned — Survey",
    "subtitle": "Batch 1: Setosa only",
    "project_tag": "Iris Versioned Demo",
    "components": [
        text(
            "text-intro",
            "First collection",
            "First collection batch: **Setosa** only, 50 flowers. One variety, so "
            "every question here is about a single distribution — there is nothing "
            "yet to compare against.",
            {"x": 0, "y": 0, "w": 8, "h": 1},
        ),
        card(
            "headline",
            "Flowers Measured",
            "count",
            "variety",
            "object",
            {"x": 0, "y": 1, "w": 4, "h": 2},
            GREEN,
            "mdi:counter",
        ),
        card(
            "petal-stat",
            "Mean Petal Length",
            "average",
            "petal.length",
            "float64",
            {"x": 4, "y": 1, "w": 4, "h": 2},
            BLUE,
            "mdi:ruler",
        ),
        interactive(
            "variety-filter",
            "Variety",
            "Select",
            "variety",
            "object",
            {"x": 0, "y": 0, "w": 1, "h": 3},
            ORANGE,
            "mdi:filter-variant",
        ),
        figure(
            "main-chart",
            "Petal Length Distribution",
            "histogram",
            {"x": "petal.length", "nbins": 20, "color_discrete_sequence": [BLUE]},
            {"x": 0, "y": 3, "w": 8, "h": 5},
            "One variety, so a histogram is all this batch supports.",
        ),
    ],
}

V2 = {
    "title": "Iris Versioned — Survey",
    "subtitle": "Batch 2: Versicolor arrives",
    "project_tag": "Iris Versioned Demo",
    "components": [
        text(
            "text-intro",
            "Two varieties",
            "**Setosa** and **Versicolor**, 100 flowers. Comparison is finally "
            "possible, so the single distribution becomes a by-variety box plot and "
            "the headline number switches from *how many* to *how many kinds*.",
            {"x": 0, "y": 0, "w": 8, "h": 1},
        ),
        # count -> nunique, and half the width: the same slot now answers
        # "how many kinds?" rather than "how many flowers?".
        card(
            "headline",
            "Varieties Surveyed",
            "nunique",
            "variety",
            "object",
            {"x": 0, "y": 1, "w": 2, "h": 2},
            ORANGE,
            "mdi:flower-tulip",
        ),
        # average -> median: with two groups the mean sits between them and
        # describes neither.
        card(
            "petal-stat",
            "Median Petal Length",
            "median",
            "petal.length",
            "float64",
            {"x": 2, "y": 1, "w": 3, "h": 2},
            PURPLE,
            "mdi:ruler",
        ),
        card(
            "sepal-stat",
            "Mean Sepal Width",
            "average",
            "sepal.width",
            "float64",
            {"x": 5, "y": 1, "w": 3, "h": 2},
            GREEN,
            "mdi:arrow-expand-horizontal",
        ),
        # Select -> MultiSelect: with two varieties, seeing both at once is the
        # normal case and picking exactly one is the exception.
        interactive(
            "variety-filter",
            "Variety",
            "MultiSelect",
            "variety",
            "object",
            {"x": 0, "y": 0, "w": 1, "h": 3},
            ORANGE,
            "mdi:filter-variant",
        ),
        interactive(
            "petal-length-filter",
            "Petal length",
            "RangeSlider",
            "petal.length",
            "float64",
            {"x": 0, "y": 3, "w": 1, "h": 3},
            BLUE,
            "mdi:arrow-left-right",
        ),
        # histogram -> box, and half the width to make room for the scatter.
        figure(
            "main-chart",
            "Petal Length by Variety",
            "box",
            {"x": "variety", "y": "petal.length", "color": "variety"},
            {"x": 0, "y": 3, "w": 4, "h": 5},
            "Two groups: the interesting shape is between them, not within one.",
        ),
        figure(
            "second-chart",
            "Sepal vs Petal",
            "scatter",
            {"x": "sepal.length", "y": "petal.length", "color": "variety"},
            {"x": 4, "y": 3, "w": 4, "h": 5},
            "",
        ),
    ],
}

V3 = {
    "title": "Iris Versioned — Survey",
    "subtitle": "Batch 3: Setosa recalibrated",
    "project_tag": "Iris Versioned Demo",
    "components": [
        text(
            "text-intro",
            "Calibration correction",
            "Same 100 flowers, same two varieties — but Setosa's petals have been "
            "**re-measured** after a calibration fix. Nothing about the layout tells "
            "you that, which is exactly why the dataset version matters.",
            {"x": 0, "y": 0, "w": 8, "h": 1},
        ),
        # nunique -> range: the question becomes "how far apart are the
        # measurements?", which is what a recalibration is judged on.
        card(
            "headline",
            "Petal Length Range",
            "range",
            "petal.length",
            "float64",
            {"x": 0, "y": 1, "w": 4, "h": 2},
            RED,
            "mdi:arrow-expand-vertical",
        ),
        # median -> std_dev, and wider: spread is the recalibration's effect.
        card(
            "petal-stat",
            "Petal Length Spread",
            "std_dev",
            "petal.length",
            "float64",
            {"x": 4, "y": 1, "w": 4, "h": 2},
            PURPLE,
            "mdi:sigma",
        ),
        # `sepal-stat` is REMOVED here and returns in v4, so restoring v3 has to
        # delete a component and restoring v4 has to add one back.
        # SegmentedControl: the third and last widget this column supports.
        interactive(
            "variety-filter",
            "Variety",
            "SegmentedControl",
            "variety",
            "object",
            {"x": 0, "y": 0, "w": 1, "h": 4},
            RED,
            "mdi:filter-variant",
        ),
        interactive(
            "petal-length-filter",
            "Petal length",
            "Slider",
            "petal.length",
            "float64",
            {"x": 0, "y": 4, "w": 1, "h": 3},
            BLUE,
            "mdi:tune",
        ),
        # box -> bar, full width: after a recalibration the comparison people
        # want is the group means, not their distributions.
        figure(
            "main-chart",
            "Mean Petal Length by Variety",
            "bar",
            {"x": "variety", "y": "petal.length", "color": "variety"},
            {"x": 0, "y": 3, "w": 8, "h": 4},
            "Group means, which is what a calibration change moves.",
        ),
        # scatter -> line, and moved below.
        figure(
            "second-chart",
            "Petal Length by Width",
            "line",
            {"x": "petal.width", "y": "petal.length", "color": "variety"},
            {"x": 0, "y": 7, "w": 8, "h": 4},
            "",
        ),
    ],
}

V4 = {
    "title": "Iris Versioned — Survey",
    "subtitle": "Batch 4: the complete survey",
    "project_tag": "Iris Versioned Demo",
    "components": [
        text(
            "text-intro",
            "Complete survey",
            "All three varieties, 150 flowers. The survey is complete, so the "
            "dashboard returns to a broad overview: headline counts, the full "
            "by-variety comparison, and the raw measurements underneath.",
            {"x": 0, "y": 0, "w": 8, "h": 1},
        ),
        # range -> count: back to the simplest question, on a complete dataset.
        card(
            "headline",
            "Flowers Measured",
            "count",
            "variety",
            "object",
            {"x": 0, "y": 1, "w": 2, "h": 2},
            GREEN,
            "mdi:counter",
        ),
        # std_dev -> max.
        card(
            "petal-stat",
            "Longest Petal",
            "max",
            "petal.length",
            "float64",
            {"x": 2, "y": 1, "w": 2, "h": 2},
            BLUE,
            "mdi:ruler",
        ),
        # Returns after being absent in v3, with a different aggregation than
        # it had in v2 (average -> min).
        card(
            "sepal-stat",
            "Narrowest Sepal",
            "min",
            "sepal.width",
            "float64",
            {"x": 4, "y": 1, "w": 2, "h": 2},
            ORANGE,
            "mdi:arrow-collapse-horizontal",
        ),
        card(
            "variety-count",
            "Varieties",
            "nunique",
            "variety",
            "object",
            {"x": 6, "y": 1, "w": 2, "h": 2},
            PURPLE,
            "mdi:flower-tulip",
        ),
        # Back to MultiSelect, and `petal-length-filter` is removed.
        interactive(
            "variety-filter",
            "Variety",
            "MultiSelect",
            "variety",
            "object",
            {"x": 0, "y": 0, "w": 1, "h": 3},
            ORANGE,
            "mdi:filter-variant",
        ),
        # bar -> box again, but half width and beside the scatter.
        figure(
            "main-chart",
            "Petal Length by Variety",
            "box",
            {"x": "variety", "y": "petal.length", "color": "variety"},
            {"x": 0, "y": 3, "w": 4, "h": 5},
            "All three varieties, fully separated.",
        ),
        # line -> scatter.
        figure(
            "second-chart",
            "Sepal vs Petal",
            "scatter",
            {"x": "sepal.length", "y": "petal.length", "color": "variety"},
            {"x": 4, "y": 3, "w": 4, "h": 5},
            "",
        ),
        {
            "tag": "data-table",
            "component_type": "table",
            "workflow_tag": WF,
            "data_collection_tag": DC,
            "title": "All Measurements",
            "description": "Every row, including the batch each arrived in.",
            "title_size": "h3",
            "layout": {"x": 0, "y": 8, "w": 8, "h": 5},
        },
    ],
}

VERSIONS = [
    ("v1_survey.yaml", V1),
    ("v2_extended.yaml", V2),
    ("v3_recalibrated.yaml", V3),
    ("v4_complete.yaml", V4),
]

HEADER = """\
# Iris Versioned — dashboard {n} of 4.
#
# GENERATED by regenerate_dashboards.py. Edit that, not this file: the four
# versions are only useful if they differ from each other in specific ways, and
# that is a property of the set rather than of any one file.
#
# {subtitle}
"""

#: Fields whose change is visible on screen. Two consecutive versions of the
#: same component must differ in at least one of them, or the component-history
#: modal shows two identical renders and looks broken.
VISIBLE_FIELDS = (
    "component_type",
    "aggregation",
    "column_name",
    "visu_type",
    "dict_kwargs",
    "interactive_component_type",
    "title",
    "body",
    "layout",
)


def signature(component: dict) -> dict:
    return {k: component.get(k) for k in VISIBLE_FIELDS}


def verify() -> list[str]:
    """Every surviving component must visibly change between versions."""
    problems: list[str] = []
    previous: dict[str, dict] | None = None
    previous_name = ""

    for name, spec in VERSIONS:
        current = {c["tag"]: c for c in spec["components"]}
        if previous is not None:
            for tag in sorted(set(previous) & set(current)):
                if signature(previous[tag]) == signature(current[tag]):
                    problems.append(
                        f"{tag}: identical in {previous_name} and {name} — "
                        "its history would show two identical renders"
                    )
        previous, previous_name = current, name

    # And each version must differ structurally from its neighbour, not just in
    # the details of shared components.
    previous = None
    for name, spec in VERSIONS:
        current = {c["tag"] for c in spec["components"]}
        if previous is not None and previous == current:
            problems.append(f"{name}: same component set as the previous version")
        previous = current

    return problems


def render(spec: dict, index: int) -> str:
    header = HEADER.format(n=index, subtitle=spec["subtitle"])
    body = yaml.safe_dump(
        {"version": 1, **spec},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )
    return header + "\n" + body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify only, write nothing")
    args = ap.parse_args()

    problems = verify()
    if problems:
        print("The four versions are not distinct enough:\n")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    if args.check:
        print("OK — every surviving component changes between versions.")
        return 0

    for index, (name, spec) in enumerate(VERSIONS, start=1):
        (OUT / name).write_text(render(spec, index), encoding="utf-8")
        print(f"  wrote {name}  ({len(spec['components'])} components)")

    print("\nRe-import with rebuild_demo.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
