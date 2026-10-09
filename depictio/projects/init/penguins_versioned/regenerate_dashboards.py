#!/usr/bin/env python3
"""Regenerate the five dashboard versions of the penguins_versioned demo.

One dashboard family, five states, each saved right after its batch:

  v1 First season          1 tab   a small 2007 survey
  v2 Second season         2 tabs  seasons split out, an Islands & Seasons tab,
                                   a row on the persisted join
  v3 Scale recalibrated    2 tabs  only the physical_features components change
  v4 Three seasons         2 tabs  renamed, rebranded, regrouped into sections
  v5 Sex records completed 3 tabs  only the demographic_data components change,
                                   plus a Census records tab

The layout mirrors the data. At the two steps where only one dataset moves (3
and 5), only the components reading that dataset change, and every component
reading the other one is left exactly as it was. Opening the history of one of
those shows the same definition on the same data across the step, which is the
right answer and the control for the components that did change.

The join (`penguins_complete`, both datasets on one row per bird) moves at every
step, since every step moves one of its inputs. Its two components keep the
same definition across steps 3 and 5, so their history there shows the join's
data following the one input that moved, and nothing else.

Generated rather than hand-written because the useful properties belong to the
set of files, not to any one of them. `check()` asserts them:

  * component tags are unique across the tabs of a version (the component id is
    derived from the tag, so two equal tags would be one component twice);
  * every version differs from the one before, or no version is captured;
  * a component reading a dataset that did not move at the step is unchanged;
  * the storyline components change at every step that ingests their dataset,
    so their history always has something to show;
  * each version reads exactly the collections the story says it stamps;
  * the join's components are unchanged across the single-input steps;
  * tab titles never change: a tab is matched across imports by its title.

    python regenerate_dashboards.py            # write the five YAMLs
    python regenerate_dashboards.py --check    # verify only, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import yaml
from penguins_story import DASHBOARDS_DIR, DD, JOIN, PF, PROJECT_NAME, STEPS, WORKFLOW_NAME

ORANGE, PURPLE, TEAL = "#FF8C00", "#A034F0", "#159090"
GREEN, RED, INDIGO, BROWN = "#55A868", "#C44E52", "#5C6BC0", "#937860"

SPECIES_COLOURS = json.dumps({"Adelie": ORANGE, "Chinstrap": PURPLE, "Gentoo": TEAL})
ISLAND_COLOURS = json.dumps({"Biscoe": "#5B8FA8", "Dream": "#B07AA1", "Torgersen": "#8C7B6B"})
SEX_COLOURS = json.dumps({"female": RED, "male": "#546E7A"})
LABELS = json.dumps(
    {
        "species": "Species",
        "island": "Island",
        "year": "Field season",
        "sex": "Sex",
        "body_mass_g": "Body mass (g)",
        "flipper_length_mm": "Flipper length (mm)",
        "bill_length_mm": "Bill length (mm)",
        "bill_depth_mm": "Bill depth (mm)",
    }
)

# The palmerpenguins palette, from v4 on. A child tab does not inherit a brand
# theme, so each tab that should carry it states it.
BRAND = {"primary": TEAL, "secondary": PURPLE, "tertiary": ORANGE, "tint_mode": "full"}

TAB_ISLANDS = "Islands & Seasons"
TAB_RECORDS = "Census records"

#: Followed across every version by the README's "what to try" section.
STORYLINE = ("card-birds", "card-mass", "fig-mass", "fig-morph", "card-sexed", "isl-sex-by-species")

#: Read the join. Same definition across steps 3 and 5 (see `check`).
JOINED = ("card-joined", "fig-mass-by-sex")


def at(x: int, y: int, w: int, h: int) -> dict[str, int]:
    return {"x": x, "y": y, "w": w, "h": h}


def text(tag: str, title: str, body: str, layout: dict, **extra: Any) -> dict:
    return {
        "tag": tag,
        "component_type": "text",
        "title": title,
        "order": 2,
        "alignment": "left",
        "body": body,
        "layout": layout,
        **extra,
    }


def card(
    tag: str,
    dc: str,
    title: str,
    aggregation: str,
    column: str,
    column_type: str,
    layout: dict,
    colour: str,
    icon: str,
    **extra: Any,
) -> dict:
    return {
        "tag": tag,
        "component_type": "card",
        "workflow_tag": WORKFLOW_NAME,
        "data_collection_tag": dc,
        "aggregation": aggregation,
        "column_name": column,
        "column_type": column_type,
        "icon_name": icon,
        "icon_color": colour,
        "title_color": colour,
        "title_font_size": "md",
        "value_font_size": "xl",
        "title": title,
        "layout": layout,
        **extra,
    }


def figure(
    tag: str,
    dc: str,
    title: str,
    visu: str,
    kwargs: dict,
    layout: dict,
    description: str = "",
    **extra: Any,
) -> dict:
    return {
        "tag": tag,
        "component_type": "figure",
        "workflow_tag": WORKFLOW_NAME,
        "data_collection_tag": dc,
        "visu_type": visu,
        "title": title,
        "description": description,
        "title_size": "h3",
        "dict_kwargs": kwargs,
        "layout": layout,
        **extra,
    }


def interactive(
    tag: str,
    dc: str,
    title: str,
    widget: str,
    column: str,
    column_type: str,
    layout: dict,
    colour: str,
    icon: str,
    **extra: Any,
) -> dict:
    return {
        "tag": tag,
        "component_type": "interactive",
        "workflow_tag": WORKFLOW_NAME,
        "data_collection_tag": dc,
        "interactive_component_type": widget,
        "column_name": column,
        "column_type": column_type,
        "custom_color": colour,
        "icon_name": icon,
        "title": title,
        "layout": layout,
        **extra,
    }


def table(tag: str, dc: str, title: str, layout: dict, description: str, **extra: Any) -> dict:
    return {
        "tag": tag,
        "component_type": "table",
        "workflow_tag": WORKFLOW_NAME,
        "data_collection_tag": dc,
        "title": title,
        "description": description,
        "title_size": "h3",
        "page_size": 50,
        "layout": layout,
        **extra,
    }


# ---------------------------------------------------------------------------
# Components shared verbatim between versions. A component that a step leaves
# alone is the *same object* in both, so "unchanged" is a fact of the code, not
# something two hand-copied blocks happen to agree on.
# ---------------------------------------------------------------------------

# demographic_data side, v2 and v3 (batch 3 does not touch this dataset).
CARD_SEXED_V2 = card(
    "card-sexed",
    DD,
    "Sex recorded",
    "count",
    "sex",
    "object",
    at(4, 1, 2, 2),
    RED,
    "mdi:account-multiple-outline",
    secondary_layout="completeness",
)
CARD_SPECIES_V2 = card(
    "card-species",
    DD,
    "Species mix",
    "nunique",
    "species",
    "object",
    at(6, 1, 2, 2),
    PURPLE,
    "mdi:chart-donut",
    secondary_layout="donut",
    breakdown_col="species",
    top_n_count=3,
)
FILTER_SPECIES_V2 = interactive(
    "filter-species",
    DD,
    "Species",
    "MultiSelect",
    "species",
    "object",
    at(0, 0, 1, 3),
    ORANGE,
    "mdi:dna",
)
FILTER_YEAR_V2 = interactive(
    "filter-year",
    DD,
    "Season",
    "RangeSlider",
    "year",
    "int64",
    at(0, 3, 1, 3),
    TEAL,
    "mdi:calendar-outline",
    show_marks=True,
)
ISLANDS_TAB_V2 = [
    text(
        "isl-intro",
        "Where the birds were sampled",
        "Read from *demographic_data* only. *Adelie* is found on all three islands, "
        "*Chinstrap* only on Dream and *Gentoo* only on Biscoe, so island and species "
        "are confounded for two of the three.",
        at(0, 0, 8, 1),
    ),
    interactive(
        "isl-filter-island",
        DD,
        "Island",
        "MultiSelect",
        "island",
        "object",
        at(0, 0, 1, 3),
        "#8172B2",
        "mdi:map-marker-outline",
    ),
    figure(
        "isl-birds-per-island",
        DD,
        "Birds per island",
        "histogram",
        {
            "x": "island",
            "color": "species",
            "barmode": "stack",
            "color_discrete_map": SPECIES_COLOURS,
            "labels": LABELS,
        },
        at(0, 1, 4, 5),
        "Stacked counts per island.",
    ),
    figure(
        "isl-sex-by-species",
        DD,
        "Sex by species",
        "histogram",
        {"x": "species", "color": "sex", "barmode": "group", "labels": LABELS},
        at(4, 1, 4, 5),
        "Birds with no recorded sex form their own bar.",
    ),
]

# The join, v2 and v3. One row per bird with both records: body mass from
# physical_features, sex from demographic_data. Step 3 moves the masses and step
# 5 the sexes, so the same two definitions show both inputs moving.
CARD_JOINED_V2 = card(
    "card-joined",
    JOIN,
    "Mean body mass, by sex mix",
    "average",
    "body_mass_g",
    "float64",
    at(6, 8, 2, 2),
    INDIGO,
    "mdi:chart-donut",
    secondary_layout="donut",
    breakdown_col="sex",
    top_n_count=3,
)
FIG_MASS_BY_SEX_V2 = figure(
    "fig-mass-by-sex",
    JOIN,
    "Body mass by sex",
    "box",
    {
        "x": "sex",
        "y": "body_mass_g",
        "color": "species",
        "boxmode": "group",
        "color_discrete_map": SPECIES_COLOURS,
        "labels": LABELS,
    },
    at(0, 8, 6, 5),
    "Mass from physical_features, sex from demographic_data: the persisted join.",
)

# physical_features side, v4 and v5 (batch 5 does not touch this dataset).
CARD_BIRDS_V4 = card(
    "card-birds",
    PF,
    "Birds measured",
    "count",
    "individual_id",
    "object",
    at(0, 0, 2, 2),
    GREEN,
    "mdi:counter",
    secondary_layout="coverage",
    coverage_max=342,
    section="Cohort",
)
CARD_MASS_V4 = card(
    "card-mass",
    PF,
    "Body mass (g)",
    "median",
    "body_mass_g",
    "float64",
    at(6, 0, 2, 2),
    ORANGE,
    "mdi:chart-box-outline",
    aggregations=["box_plot_stats"],
    secondary_layout="box_plot",
    section="Cohort",
)
FILTER_MASS_V4 = interactive(
    "filter-mass",
    PF,
    "Body mass (g)",
    "RangeSlider",
    "body_mass_g",
    "float64",
    at(0, 6, 1, 3),
    PURPLE,
    "bx:slider-alt",
    section="Measurements",
)
FIG_MASS_V4 = figure(
    "fig-mass",
    PF,
    "Body mass by season and species",
    "box",
    {
        "x": "year",
        "y": "body_mass_g",
        "color": "species",
        "boxmode": "group",
        "notched": True,
        "color_discrete_map": SPECIES_COLOURS,
        "labels": LABELS,
    },
    at(0, 0, 4, 5),
    "Three seasons side by side, per species.",
    section="Morphometrics",
)
FIG_MORPH_V4 = figure(
    "fig-morph",
    PF,
    "Bill shape: length vs depth",
    "scatter",
    {
        "x": "bill_length_mm",
        "y": "bill_depth_mm",
        "color": "species",
        "color_discrete_map": SPECIES_COLOURS,
        "labels": LABELS,
    },
    at(4, 0, 4, 5),
    "The one view where Adelie and Chinstrap separate.",
    section="Morphometrics",
)
FIG_MASS_HIST_V4 = figure(
    "fig-mass-hist",
    PF,
    "Body mass distribution by island",
    "histogram",
    {
        "x": "body_mass_g",
        "color": "island",
        "barmode": "overlay",
        "opacity": 0.6,
        "nbins": 30,
        "color_discrete_map": ISLAND_COLOURS,
        "labels": LABELS,
    },
    at(0, 5, 8, 4),
    "Biscoe looks heavy because Gentoo lives there.",
    section="Morphometrics",
)
TABLE_MEASUREMENTS_V4 = table(
    "table-measurements",
    PF,
    "Measurements",
    at(0, 0, 8, 5),
    "Every row of physical_features, with the season it arrived in.",
    section="Records",
)
CARD_SPECIES_V4 = card(
    "card-species",
    DD,
    "Island balance",
    "nunique",
    "island",
    "object",
    at(4, 0, 2, 2),
    PURPLE,
    "mdi:map-marker-outline",
    secondary_layout="composition",
    breakdown_col="island",
    top_n_count=3,
    section="Cohort",
)
FILTER_SPECIES_V4 = interactive(
    "filter-species",
    DD,
    "Species",
    "SegmentedControl",
    "species",
    "object",
    at(0, 0, 1, 3),
    ORANGE,
    "mdi:dna",
    section="Cohort",
)
FILTER_YEAR_V4 = interactive(
    "filter-year",
    DD,
    "Field season",
    "RangeSlider",
    "year",
    "int64",
    at(0, 3, 1, 3),
    TEAL,
    "mdi:calendar-outline",
    show_marks=True,
    section="Cohort",
)
ISL_INTRO_V4 = text(
    "isl-intro",
    "Three seasons, three islands",
    "The species and season filters on the left come from the Overview tab: its "
    "Cohort section is persistent, so it reaches this tab without being declared "
    "here. *Body mass by island* reads *physical_features*; the rest reads "
    "*demographic_data*.",
    at(0, 0, 8, 1),
)
ISL_FILTER_ISLAND = ISLANDS_TAB_V2[1]
ISL_BIRDS_V4 = figure(
    "isl-birds-per-island",
    DD,
    "Birds per island and species",
    "histogram",
    {
        "x": "island",
        "color": "species",
        "barmode": "group",
        "color_discrete_map": SPECIES_COLOURS,
        "labels": LABELS,
    },
    at(0, 1, 4, 5),
    "Grouped, so each species reads against its own axis.",
)
ISL_MASS_BY_ISLAND_V4 = figure(
    "isl-mass-by-island",
    PF,
    "Body mass by island",
    "box",
    {
        "x": "island",
        "y": "body_mass_g",
        "color": "species",
        "boxmode": "group",
        "color_discrete_map": SPECIES_COLOURS,
        "labels": LABELS,
    },
    at(0, 6, 8, 5),
    "Biscoe splits into its Adelie and Gentoo halves.",
)

# The join, v4 and v5, in a section of its own.
CARD_JOINED_V4 = {**CARD_JOINED_V2, "layout": at(6, 0, 2, 2), "section": "Joined"}
FIG_MASS_BY_SEX_V4 = {
    **FIG_MASS_BY_SEX_V2,
    "title": "Body mass by sex, three seasons",
    "layout": at(0, 0, 6, 5),
    "section": "Joined",
}

V4_FILTER_SECTIONS = [
    {
        "name": "Cohort",
        "icon": "mdi:account-group-outline",
        "color": "teal",
        "description": "Which birds to look at, on every tab",
        "persistent": True,
        "pin": "top",
    },
    {
        "name": "Measurements",
        "icon": "mdi:ruler",
        "color": "indigo",
        "description": "A body-mass range, read from physical_features",
        "collapsed": True,
    },
]
V4_GRID_SECTIONS = [
    {
        "name": "Cohort",
        "icon": "mdi:account-group-outline",
        "color": "teal",
        "description": "How many birds, of which species, and what the census is missing",
    },
    {
        "name": "Morphometrics",
        "icon": "mdi:ruler",
        "color": "indigo",
        "description": "Body mass, flipper and bill, from physical_features",
    },
    {
        "name": "Joined",
        "icon": "mdi:set-merge",
        "color": "violet",
        "description": "physical_features joined to demographic_data: mass and sex on one row",
    },
    {
        "name": "Records",
        "icon": "mdi:table",
        "color": "gray",
        "description": "The measurement rows behind every chart",
        "collapsed": True,
    },
]


def main_tab(title: str, subtitle: str, components: list[dict], **extra: Any) -> dict:
    return {
        "title": title,
        "subtitle": subtitle,
        "project_tag": PROJECT_NAME,
        "main_tab_name": "Overview",
        "tab_icon": "mdi:penguin",
        "tab_icon_color": "orange",
        **extra,
        "components": components,
    }


def child_tab(
    title: str, subtitle: str, icon: str, colour: str, components: list[dict], **extra: Any
) -> dict:
    return {
        "title": title,
        "subtitle": subtitle,
        "tab_icon": icon,
        "tab_icon_color": colour,
        **extra,
        "components": components,
    }


def islands_tab(components: list[dict], **extra: Any) -> dict:
    return child_tab(
        TAB_ISLANDS,
        "Where each species was sampled, season by season",
        "mdi:map-marker-outline",
        "teal",
        components,
        **extra,
    )


# ---------------------------------------------------------------------------
# The five versions.
# ---------------------------------------------------------------------------

V1 = {
    "main_dashboard": main_tab(
        "Penguin Field Survey",
        "Season 2007: the first field season",
        [
            text(
                "intro",
                "First season on record",
                "109 birds from the 2007 season, held as two datasets: *physical_features* "
                "(the measurements) and *demographic_data* (who each bird is). From here "
                "on they are ingested on different schedules.",
                at(0, 0, 8, 1),
            ),
            card(
                "card-birds",
                PF,
                "Birds measured",
                "count",
                "individual_id",
                "object",
                at(0, 1, 4, 2),
                GREEN,
                "mdi:counter",
            ),
            card(
                "card-mass",
                PF,
                "Mean body mass (g)",
                "average",
                "body_mass_g",
                "float64",
                at(4, 1, 4, 2),
                ORANGE,
                "mdi:ruler",
            ),
            interactive(
                "filter-species",
                DD,
                "Species",
                "Select",
                "species",
                "object",
                at(0, 0, 1, 3),
                ORANGE,
                "mdi:dna",
            ),
            # Deliberately bare: two columns and nothing else, so the later
            # versions have a default chart to grow from.
            figure(
                "fig-mass",
                PF,
                "Body mass by species",
                "box",
                {"x": "species", "y": "body_mass_g"},
                at(0, 3, 4, 5),
                "One season, so there is nothing to compare it against yet.",
            ),
            figure(
                "fig-morph",
                PF,
                "Flipper length vs body mass",
                "scatter",
                {"x": "flipper_length_mm", "y": "body_mass_g", "color": "species"},
                at(4, 3, 4, 5),
            ),
        ],
    ),
    "tabs": [],
}

V2 = {
    "main_dashboard": main_tab(
        "Penguin Field Survey",
        "Seasons 2007 and 2008",
        [
            text(
                "intro",
                "Two seasons",
                "2008 arrives: 223 birds over two seasons. The body-mass chart now splits "
                "by season, which is where the next correction will show. Sex and species "
                "cards read *demographic_data*, the *Body mass by sex* row reads their "
                "persisted join, and the rest reads *physical_features*.",
                at(0, 0, 8, 1),
            ),
            card(
                "card-birds",
                PF,
                "Birds measured so far",
                "count",
                "individual_id",
                "object",
                at(0, 1, 2, 2),
                GREEN,
                "mdi:counter",
                secondary_layout="coverage",
                coverage_max=342,
            ),
            card(
                "card-mass",
                PF,
                "Median body mass (g)",
                "median",
                "body_mass_g",
                "float64",
                at(2, 1, 2, 2),
                ORANGE,
                "mdi:ruler",
            ),
            CARD_SEXED_V2,
            CARD_SPECIES_V2,
            FILTER_SPECIES_V2,
            FILTER_YEAR_V2,
            figure(
                "fig-mass",
                PF,
                "Body mass by season",
                "box",
                {
                    "x": "year",
                    "y": "body_mass_g",
                    "color": "species",
                    "boxmode": "group",
                    "color_discrete_map": SPECIES_COLOURS,
                    "labels": LABELS,
                },
                at(0, 3, 4, 5),
                "Each species, season against season.",
            ),
            figure(
                "fig-morph",
                PF,
                "Flipper vs mass, by species and island",
                "scatter",
                {
                    "x": "flipper_length_mm",
                    "y": "body_mass_g",
                    "color": "species",
                    "symbol": "island",
                    "color_discrete_map": SPECIES_COLOURS,
                    "labels": LABELS,
                },
                at(4, 3, 4, 5),
            ),
            FIG_MASS_BY_SEX_V2,
            CARD_JOINED_V2,
        ],
    ),
    "tabs": [islands_tab(ISLANDS_TAB_V2)],
}

V3 = {
    "main_dashboard": main_tab(
        "Penguin Field Survey",
        "2007 body masses recalibrated (a synthetic correction)",
        [
            text(
                "intro",
                "Scale recalibration",
                "Same 223 birds, same two seasons, but every 2007 body mass was re-weighed "
                "after a scale fix (+5%, synthetic). Only *physical_features* "
                "moved: the sex and species cards and the Islands tab read "
                "*demographic_data*, still the 2008 copy. The joined row is unchanged; its "
                "data followed the masses.",
                at(0, 0, 8, 1),
            ),
            card(
                "card-birds",
                PF,
                "Birds re-weighed",
                "count",
                "individual_id",
                "object",
                at(0, 1, 2, 2),
                GREEN,
                "mdi:counter",
                secondary_layout="coverage",
                coverage_max=342,
            ),
            card(
                "card-mass",
                PF,
                "Mean body mass by season (g)",
                "average",
                "body_mass_g",
                "float64",
                at(2, 1, 2, 2),
                ORANGE,
                "mdi:chart-line",
                secondary_layout="trend",
                trend_col="year",
            ),
            CARD_SEXED_V2,
            CARD_SPECIES_V2,
            FILTER_SPECIES_V2,
            FILTER_YEAR_V2,
            figure(
                "fig-mass",
                PF,
                "Body mass by season, recalibrated",
                "violin",
                {
                    "x": "year",
                    "y": "body_mass_g",
                    "color": "species",
                    "box": True,
                    "points": "all",
                    "violinmode": "group",
                    "color_discrete_map": SPECIES_COLOURS,
                    "labels": LABELS,
                },
                at(0, 3, 4, 5),
                "The 2007 distributions moved up; 2008 did not.",
            ),
            figure(
                "fig-morph",
                PF,
                "Flipper vs mass, with trend",
                "scatter",
                {
                    "x": "flipper_length_mm",
                    "y": "body_mass_g",
                    "color": "species",
                    "trendline": "ols",
                    "color_discrete_map": SPECIES_COLOURS,
                    "labels": LABELS,
                },
                at(4, 3, 4, 5),
            ),
            figure(
                "fig-mass-hist",
                PF,
                "Body mass distribution",
                "histogram",
                {
                    "x": "body_mass_g",
                    "color": "species",
                    "barmode": "overlay",
                    "opacity": 0.6,
                    "nbins": 30,
                    "color_discrete_map": SPECIES_COLOURS,
                    "labels": LABELS,
                },
                at(0, 13, 8, 4),
            ),
            FIG_MASS_BY_SEX_V2,
            CARD_JOINED_V2,
        ],
    ),
    "tabs": [islands_tab(ISLANDS_TAB_V2)],
}

V4 = {
    "main_dashboard": main_tab(
        "Palmer Penguins: Three Field Seasons",
        "2007 to 2009: the complete survey",
        [
            text(
                "intro",
                "The complete survey",
                "2009 arrives: 342 birds over three seasons. Renamed, rebranded with the "
                "species palette and regrouped into sections. Both datasets moved at this "
                "step, and so did their join.",
                at(0, 0, 8, 1),
            ),
            CARD_BIRDS_V4,
            card(
                "card-sexed",
                DD,
                "Sex recorded, three seasons",
                "count",
                "sex",
                "object",
                at(2, 0, 2, 2),
                RED,
                "mdi:account-multiple-outline",
                secondary_layout="completeness",
                section="Cohort",
            ),
            CARD_SPECIES_V4,
            CARD_MASS_V4,
            FILTER_SPECIES_V4,
            FILTER_YEAR_V4,
            FILTER_MASS_V4,
            FIG_MASS_V4,
            FIG_MORPH_V4,
            FIG_MASS_HIST_V4,
            FIG_MASS_BY_SEX_V4,
            CARD_JOINED_V4,
            TABLE_MEASUREMENTS_V4,
        ],
        brand_theme=BRAND,
        filter_sections=V4_FILTER_SECTIONS,
        grid_sections=V4_GRID_SECTIONS,
    ),
    "tabs": [
        islands_tab(
            [
                ISL_INTRO_V4,
                ISL_FILTER_ISLAND,
                ISL_BIRDS_V4,
                figure(
                    "isl-sex-by-species",
                    DD,
                    "Sex by species, three seasons",
                    "histogram",
                    {
                        "x": "species",
                        "color": "sex",
                        "barmode": "group",
                        "color_discrete_map": SEX_COLOURS,
                        "labels": LABELS,
                    },
                    at(4, 1, 4, 5),
                    "Nine birds still have no recorded sex.",
                ),
                ISL_MASS_BY_ISLAND_V4,
            ],
            brand_theme=BRAND,
        )
    ],
}

V5 = {
    "main_dashboard": main_tab(
        "Palmer Penguins: Three Field Seasons",
        "Sex records completed (a synthetic imputation)",
        [
            text(
                "intro",
                "Census completed",
                "The 9 birds with no recorded sex now have one, imputed from body mass "
                "(synthetic). Only *demographic_data* moved: every *physical_features* chart "
                "is as it was in v4, on the same data. The Joined section is unchanged, but "
                "its data moved with the census: the birds with no sex now sit in one.",
                at(0, 0, 8, 1),
            ),
            CARD_BIRDS_V4,
            card(
                "card-sexed",
                DD,
                "Sex recorded: complete",
                "count",
                "sex",
                "object",
                at(2, 0, 2, 2),
                RED,
                "mdi:account-multiple-outline",
                secondary_layout="completeness",
                section="Cohort",
            ),
            CARD_SPECIES_V4,
            CARD_MASS_V4,
            FILTER_SPECIES_V4,
            FILTER_YEAR_V4,
            FILTER_MASS_V4,
            FIG_MASS_V4,
            FIG_MORPH_V4,
            FIG_MASS_HIST_V4,
            FIG_MASS_BY_SEX_V4,
            CARD_JOINED_V4,
            TABLE_MEASUREMENTS_V4,
        ],
        brand_theme=BRAND,
        filter_sections=V4_FILTER_SECTIONS,
        grid_sections=V4_GRID_SECTIONS,
    ),
    "tabs": [
        islands_tab(
            [
                ISL_INTRO_V4,
                ISL_FILTER_ISLAND,
                ISL_BIRDS_V4,
                figure(
                    "isl-sex-by-species",
                    DD,
                    "Sex by species, completed",
                    "histogram",
                    {
                        "x": "species",
                        "color": "sex",
                        "barmode": "stack",
                        "color_discrete_map": SEX_COLOURS,
                        "labels": LABELS,
                    },
                    at(4, 1, 4, 5),
                    "Every bird now has a sex, so the bars are two colours, not three.",
                ),
                ISL_MASS_BY_ISLAND_V4,
            ],
            brand_theme=BRAND,
        ),
        child_tab(
            TAB_RECORDS,
            "The census rows behind the Cohort cards",
            "mdi:table",
            "gray",
            [
                text(
                    "rec-intro",
                    "Census records",
                    "*demographic_data* as it stands. Filter by sex to find the birds whose "
                    "sex was imputed: they are the ones v4 still showed without one.",
                    at(0, 0, 8, 1),
                ),
                interactive(
                    "rec-filter-sex",
                    DD,
                    "Sex",
                    "MultiSelect",
                    "sex",
                    "object",
                    at(0, 0, 1, 3),
                    RED,
                    "mdi:account-multiple-outline",
                ),
                table(
                    "rec-table",
                    DD,
                    "Census records",
                    at(0, 1, 8, 6),
                    "One row per bird: species, island, season and sex.",
                ),
            ],
            brand_theme=BRAND,
        ),
    ],
}

VERSIONS = [V1, V2, V3, V4, V5]

HEADER = """\
# Penguins Versioned: dashboard version {n} of {total}, "{label}".
#
# GENERATED by regenerate_dashboards.py. Edit that, not this file: the versions
# are only useful if they differ from each other in specific ways, which is a
# property of the set rather than of any one file.
#
# Imported by rebuild_demo.py right after batch {n} ({batch}) is ingested.
"""


def components_of(version: dict) -> dict[str, dict]:
    """Tag -> component, across every tab of a version."""
    tabs = [version["main_dashboard"], *version["tabs"]]
    return {c["tag"]: c for tab in tabs for c in tab["components"]}


def tag_count(version: dict) -> int:
    tabs = [version["main_dashboard"], *version["tabs"]]
    return sum(len(tab["components"]) for tab in tabs)


def fingerprint(component: dict) -> str:
    return json.dumps(component, sort_keys=True)


def check() -> list[str]:
    problems: list[str] = []
    previous: dict | None = None
    previous_tabs: list[str] = []

    for step, version in zip(STEPS, VERSIONS, strict=True):
        name = step.dashboard
        current = components_of(version)
        tabs = [t["title"] for t in version["tabs"]]

        if tag_count(version) != len(current):
            problems.append(f"{name}: a tag is used twice across the tabs")
        if len(current) != step.components:
            problems.append(f"{name}: {len(current)} components, story says {step.components}")
        if 1 + len(tabs) != step.tabs:
            problems.append(f"{name}: {1 + len(tabs)} tabs, story says {step.tabs}")
        if previous_tabs and tabs[: len(previous_tabs)] != previous_tabs:
            problems.append(
                f"{name}: tab titles {tabs} do not extend {previous_tabs}; a renamed tab "
                "is imported as a new one and the old one is left behind"
            )

        if previous is not None:
            same = {
                t
                for t in set(previous) & set(current)
                if fingerprint(previous[t]) == fingerprint(current[t])
            }
            if same == set(previous) == set(current):
                problems.append(f"{name}: no component changed, so no version would be captured")
            for tag in sorted(set(previous) & set(current)):
                dc = current[tag].get("data_collection_tag")
                if dc and dc not in step.moves and tag not in same:
                    problems.append(
                        f"{name}: {tag} reads {dc}, which does not move at batch {step.n}, and "
                        "yet it changed; the layout no longer mirrors the data"
                    )
                if tag in STORYLINE and dc in step.ingest and tag in same:
                    problems.append(
                        f"{name}: storyline component {tag} is unchanged although {dc} moved"
                    )
                if tag in JOINED and len(step.ingest) == 1 and tag not in same:
                    problems.append(
                        f"{name}: {tag} changed at a single-input step; its history there "
                        "should show the join's data moving and nothing else"
                    )

        read = {c["data_collection_tag"] for c in current.values() if c.get("data_collection_tag")}
        if read != set(step.reads):
            problems.append(f"{name}: reads {sorted(read)}, story says {sorted(step.reads)}")
        previous, previous_tabs = current, tabs

    return problems


def render(step_index: int) -> str:
    step = STEPS[step_index]
    header = HEADER.format(n=step.n, total=len(STEPS), label=step.label, batch=step.batch)
    body = yaml.safe_dump(
        {"version": 1, **VERSIONS[step_index]},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )
    return header + "\n" + body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify only, write nothing")
    args = ap.parse_args()

    problems = check()
    if problems:
        print("The dashboard versions do not tell the story:\n")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    if args.check:
        print("OK: the five versions match the story.")
        return 0

    DASHBOARDS_DIR.mkdir(exist_ok=True)
    for index, step in enumerate(STEPS):
        (DASHBOARDS_DIR / step.dashboard).write_text(render(index), encoding="utf-8")
        print(f"  wrote {step.dashboard:28} {step.tabs} tab(s), {step.components} components")
    print("\nRebuild with rebuild_demo.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
