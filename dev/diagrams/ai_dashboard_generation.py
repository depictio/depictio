#!/usr/bin/env python3
"""Render the whole-dashboard generation and its draft review as hand-drawn SVGs.

Two diagrams, each carrying one idea the prose in `docs/ai-assistant.md` needs
several paragraphs for:

* ``generation_pipeline`` — the one SSE run behind `POST /ai/generate-dashboard`:
  the project read as data, one planning call, the gate where the run can stop
  before anything is filled, the per-component loop with its single repair, and
  the dashboard the layout pass actually draws.
* ``model_contract``     — why a generated component is a Depictio component: the
  Pydantic definitions and the collection's own schema generate the prompt's
  legal space, and the same definitions reject an answer that leaves it.
* ``draft_review``       — the editor as the review surface: what the panel puts
  in front of the reviewer, what a decision writes, what comes back, and the
  two exits.

Both are drawn rather than labelled: a store looks like a store, a plan looks
like a sheet of paper, a question looks like a question, and the dashboard the
generator produces is the dashboard the reader sees.

Usage:
    python dev/diagrams/ai_dashboard_generation.py --out docs/images/v1.4/ai/schema
    # writes <out>_<name>.svg/.png for each diagram below

PNG rendering needs Playwright (already a dev dependency) and a local Virgil GS;
without the font the SVG still renders in whatever the fallback list finds.
See sketch.py for the drawing primitives.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    DIM,
    GREEN,
    GREY,
    INK,
    ORANGE,
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    arc_points,
    write,
)

# The component palette the app itself uses, so a tile in a diagram is the same
# colour as the tile on screen: filters teal, cards blue, figures violet.
FILTER_FILL = "#e6fcf5"
CARD_FILL = BLUE
FIGURE_FILL = VIOLET
TABLE_FILL = "#f1f3f5"
RAIL_FILL = "#f8f9fa"

# Pastel fills are for areas; a line has to carry across a wide diagram, so the
# two claims that are lines get their own ink.
WRITE_INK = "#2f9e44"
LOOP_INK = "#1971c2"
SELECT_INK = "#7048e8"

app = typer.Typer(add_completion=False)


def scribble(s: Sketch, x: float, y: float, widths: tuple[float, ...], gap: float = 15) -> None:
    """Ruled lines standing in for body text: it is a document, not its contents."""
    for i, w in enumerate(widths):
        s.line(x, y + i * gap, x + w, y + i * gap, colour=GREY, width=1.4, amount=0.7, passes=1)


def mini_dashboard(
    s: Sketch, x: float, y: float, w: float, h: float, *, highlight: int = -1
) -> list[Box]:
    """The dashboard the layout pass produces, drawn instead of described.

    Filters down the left panel, one full row of cards, a pair of figures, the
    reference table last: the funnel the planner is told to build, at the size
    it lands on an 8 column grid. Returns the tiles so a caller can point at one.
    """
    s.rect(Box(x, y, w, h, WHITE, ""), colour=GREY)
    pad = h * 0.045
    rail_w = w * 0.17
    s.rect(Box(x + pad, y + pad, rail_w, h - 2 * pad, RAIL_FILL, ""), colour=GREY)
    gap = h * 0.03
    fh = (h - 2 * pad - 5 * gap) / 4
    for i in range(4):
        s.rect(
            Box(
                x + pad + gap, y + pad + gap + i * (fh + gap), rail_w - 2 * gap, fh, FILTER_FILL, ""
            ),
            colour=GREY,
        )

    x0 = x + pad + rail_w + pad
    cw = w - rail_w - 3 * pad
    tiles: list[Box] = []
    row = y + pad
    tw = (cw - 3 * pad) / 4
    for i in range(4):
        tiles.append(Box(x0 + i * (tw + pad), row, tw, h * 0.20, CARD_FILL, ""))
    row += h * 0.20 + pad
    fw = (cw - pad) / 2
    for i in range(2):
        tiles.append(Box(x0 + i * (fw + pad), row, fw, h * 0.36, FIGURE_FILL, ""))
    row += h * 0.36 + pad
    tiles.append(Box(x0, row, cw, h * 0.26, TABLE_FILL, ""))
    for tile in tiles:
        s.rect(tile, colour=GREY)
    if highlight >= 0:
        hit = tiles[highlight]
        s.rect(Box(hit.x - 5, hit.y - 5, hit.w + 10, hit.h + 10, "none", ""), colour=SELECT_INK)
    return tiles


# --------------------------------------------------------------------------
# 1. The run: read, plan, gate, fill, lay out, save.
# --------------------------------------------------------------------------

PIPE_W, PIPE_H = 1560, 940


def build_pipeline() -> Sketch:
    """One run, left to right and back again.

    The top row is what a single LLM call buys: a plan. The gate is drawn as a
    question because it is one, and its "yes" exit is a dead end that costs one
    call. The bottom row is what happens per component, which is where the
    repair loop lives, and it ends in the dashboard itself rather than in a box
    saying "layout".
    """
    s = Sketch(PIPE_W, PIPE_H)
    s.heading(
        56,
        60,
        "Generating a whole dashboard",
        "POST /ai/generate-dashboard: one SSE run, from the project's own data to a saved draft",
    )

    # -- read -------------------------------------------------------------
    s.cylinder(72, 136, 170, 152, fill=BLUE)
    s.text(157, 194, "project", size=17, weight="bold")
    s.text(157, 222, "workflows and their", size=12, colour=DIM)
    s.text(157, 242, "table collections", size=12, colour=DIM)
    s.text(157, 324, "read, never guessed", size=13, colour=DIM)

    inventory = Box(
        300,
        152,
        172,
        130,
        WHITE,
        "inventory",
        ("columns + dtypes", "sample values", "ranked viz kinds", "catalog offers"),
    )
    s.stack(inventory)
    s.arrow(246, 212, 296, 214)
    s.text(386, 324, "one digest per collection", size=13, colour=DIM)

    # -- plan -------------------------------------------------------------
    s.arrow(478, 214, 518, 214)
    s.document(524, 130, 312, 216, fill=YELLOW)
    s.text(680, 166, "the plan", size=18, weight="bold")
    s.text(680, 112, "one LLM call, strict JSON, then clamped", size=13, colour=DIM)
    for i, (label, fill) in enumerate(
        (
            ("Cohort filters · 4 interactive", FILTER_FILL),
            ("Overview · 4 cards", CARD_FILL),
            ("Measurements · 5 figures", FIGURE_FILL),
            ("Reference · 1 table", TABLE_FILL),
        )
    ):
        s.chip(680, 200 + i * 32, label, fill=fill, w=258, h=27, size=11)

    # -- the gate ---------------------------------------------------------
    s.arrow(840, 214, 858, 214)
    s.diamond(940, 214, 172, 120, fill=VIOLET)
    s.text(940, 208, "plan only?", size=16, weight="bold")
    s.text(940, 230, "the gate", size=12, colour=DIM)

    s.arrow(1028, 214, 1086, 214)
    s.text(1057, 200, "yes", size=12, colour=DIM)
    s.box(
        Box(
            1090,
            150,
            252,
            132,
            WHITE,
            "status: planned",
            ("nothing filled,", "nothing saved,", "one call paid for"),
        )
    )
    s.line(1216, 282, 1216, 330, dashed=True, colour=DIM)
    s.arrow(1216, 330, 954, 330, dashed=True, colour=DIM)
    s.text(1085, 320, "Build this plan", size=12, colour=DIM)

    s.text(958, 300, "no", size=12, colour=DIM, anchor="start")
    s.line(940, 274, 940, 372)
    s.line(940, 372, 200, 372)
    s.arrow(200, 372, 200, 404)
    s.text(600, 362, "the approved plan, re-parsed and re-normalised", size=13, colour=DIM)

    # -- fill, one component at a time ------------------------------------
    s.rect(Box(56, 404, 836, 300, "none", ""), colour=GREY, dashed=True)
    s.text(76, 430, "for each planned component", size=14, colour=DIM, anchor="start")

    s.box(
        Box(
            90,
            470,
            168,
            108,
            WHITE,
            "intent",
            ("one line from the plan,", "its collection, its tag"),
        )
    )
    s.arrow(262, 528, 296, 528)
    s.document(300, 456, 190, 146, fill=YELLOW)
    s.text(395, 486, "component YAML", size=14, weight="bold")
    scribble(s, 325, 510, (130, 96, 118, 74), gap=17)
    s.text(395, 624, "one LLM call", size=12, colour=DIM)

    s.arrow(494, 528, 524, 528)
    s.diamond(600, 528, 152, 108, fill=GREEN)
    s.text(600, 524, "valid?", size=15, weight="bold")
    s.text(600, 544, "grammar + schema", size=11, colour=DIM)

    s.arrow(676, 508, 712, 492)
    s.chip(768, 486, "ok", fill=GREEN, w=112, h=42, size=14)
    s.tick(738, 482, colour=WRITE_INK)

    s.arrow(676, 552, 726, 592)
    s.chip(792, 604, "dropped", fill=PINK, w=132, h=42, size=14)
    s.cross(748, 604, size=8)

    s.line(600, 582, 600, 650, colour=RED)
    s.line(600, 650, 340, 650, colour=RED)
    s.arrow(340, 650, 340, 596, colour=RED)
    s.text(497, 674, "one repair round, then it is dropped", size=12, colour=RED)

    s.line(174, 468, 174, 444, colour=DIM)
    s.line(174, 444, 768, 444, colour=DIM)
    s.arrow(768, 444, 768, 463, colour=DIM)
    s.text(566, 436, "text and advanced viz: no call at all", size=12, colour=DIM)

    # -- lay out ----------------------------------------------------------
    s.text(1231, 380, "layout", size=17, weight="bold")
    s.text(1231, 398, "8 columns · filters left · full card rows · table last", size=12, colour=DIM)
    s.arrow(828, 486, 954, 470)
    mini_dashboard(s, 960, 410, 542, 262)

    # -- save -------------------------------------------------------------
    s.arrow(1231, 678, 1233, 756)
    s.cylinder(1146, 762, 178, 150, fill=PINK)
    s.text(1235, 820, "dashboards", size=17, weight="bold")
    s.text(1235, 848, "the import path itself", size=12, colour=DIM)
    s.arrow(1328, 812, 1368, 812)
    s.chip(1436, 812, "status: draft", fill=GREEN, w=126, h=28, size=12)

    # -- what stops it ----------------------------------------------------
    s.text(90, 782, "run limit", size=15, weight="bold", anchor="start")
    s.gauge(90, 794, 660, 24, 0.62, fill=ORANGE)
    s.text(766, 812, "tokens · wall clock · repairs", size=13, colour=DIM, anchor="start")
    s.text(
        90,
        858,
        'exhausted: what is left is dropped with reason "budget", and the run still saves what it has',
        size=13,
        colour=DIM,
        anchor="start",
    )
    return s


# --------------------------------------------------------------------------
# 2. The review: one panel, one writer, two exits.
# --------------------------------------------------------------------------

REVIEW_W, REVIEW_H = 1560, 970


def panel_section(s: Sketch, y: float, label: str, count: str, fill: str) -> None:
    """A fold header in the review panel: chevron, the section's own swatch, its tally."""
    s.line(671, y - 6, 676, y - 1, width=1.5, amount=0.4, passes=1)
    s.line(676, y - 1, 681, y - 6, width=1.5, amount=0.4, passes=1)
    s.rect(Box(689, y - 9, 13, 13, fill, ""), colour=GREY)
    s.text(710, y + 4, label, size=12, weight="bold", anchor="start")
    s.text(906, y + 4, count, size=11, colour=DIM, anchor="end")


def panel_row(
    s: Sketch, y: float, label: str, fill: str, *, done: bool, selected: bool = False
) -> None:
    """One generated tile, in the panel's own terms: its type's colour, and a tick once judged."""
    if selected:
        s.rect(Box(664, y - 13, 248, 26, FIGURE_FILL, ""), colour=SELECT_INK)
    s.rect(Box(703, y - 8, 12, 12, fill, ""), colour=GREY)
    s.text(724, y + 4, label, size=11, anchor="start")
    if done:
        s.tick(898, y - 2, size=6, colour=WRITE_INK)


def build_review() -> Sketch:
    """The editor, and the three things that happen inside it.

    Drawing the window is the point: the review is not a screen of its own, it
    is the panel next to the canvas, and the regenerate loop starts and ends on
    the same tile. Only the review route writes the run record, which is why the
    autosave arrow is crossed out and the write-back arrow is a single line
    carrying a counter.
    """
    s = Sketch(REVIEW_W, REVIEW_H)
    s.heading(
        56,
        60,
        "Reviewing the draft",
        "the editor is the review surface; one route writes the record, and nothing else does",
    )

    # -- the editor window ------------------------------------------------
    s.rect(Box(56, 130, 880, 630, WHITE, ""))
    s.line(56, 174, 936, 174, colour=GREY, width=1.4, passes=1)
    for cx in (78, 96, 114):
        s.stroke(arc_points(cx, 152, 5, 5, 0, 360, 14), colour=GREY, width=1.3, amount=0.5)
    s.text(134, 158, "dashboard-edit / a generated draft", size=12, colour=DIM, anchor="start")

    s.rect(Box(76, 192, 560, 44, VIOLET, ""))
    s.text(92, 220, "AI-generated draft", size=13, weight="bold", anchor="start")
    s.text(228, 220, "· 20 components · 1 warning", size=12, colour=DIM, anchor="start")
    s.chip(500, 214, "Promote", fill=GREEN, w=82, h=26, size=12)
    s.chip(590, 214, "Discard", fill=PINK, w=80, h=26, size=12)

    mini_dashboard(s, 76, 252, 560, 284, highlight=5)

    # -- the review panel -------------------------------------------------
    s.rect(Box(656, 192, 264, 486, "#fcfcfd", ""))
    s.text(672, 214, "AI DRAFT", size=10, colour=DIM, anchor="start")
    s.text(672, 236, "Review draft", size=15, weight="bold", anchor="start")
    s.text(672, 258, "3 of 20 reviewed", size=11, colour=DIM, anchor="start")
    s.gauge(672, 266, 232, 9, 0.15, fill="#a5d8ff")
    s.chip(724, 302, "Keep all", fill=GREEN, w=94, h=24, size=11)
    s.chip(846, 302, "Remove all", fill=PINK, w=110, h=24, size=11)
    s.line(666, 324, 910, 324, colour=GREY, width=1.2, passes=1)

    panel_section(s, 348, "Cohort filters", "2/5", FILTER_FILL)
    panel_row(s, 376, "Species", FILTER_FILL, done=True)
    panel_row(s, 400, "Island", FILTER_FILL, done=True)
    panel_row(s, 424, "Sex", FILTER_FILL, done=False)
    panel_section(s, 458, "Overview", "1/5", CARD_FILL)
    panel_row(s, 486, "Total penguins", CARD_FILL, done=True)
    panel_row(s, 510, "Average mass", CARD_FILL, done=False)
    panel_section(s, 544, "Measurements", "0/5", FIGURE_FILL)
    panel_row(s, 572, "Mass by species", FIGURE_FILL, done=False, selected=True)

    s.chip(722, 612, "Keep", fill=GREEN, w=92, h=26, size=12)
    s.chip(848, 612, "Regenerate", fill=BLUE, w=118, h=26, size=12)
    s.chip(788, 646, "Remove", fill=PINK, w=104, h=26, size=12)

    # -- regenerate: out of the panel, back into the same tile ------------
    s.line(848, 625, 848, 720, colour=LOOP_INK)
    s.line(848, 720, 200, 720, colour=LOOP_INK)
    s.arrow(200, 720, 200, 706, colour=LOOP_INK)
    s.document(125, 600, 150, 104, fill=YELLOW)
    s.text(200, 628, "component YAML", size=12, weight="bold")
    scribble(s, 152, 650, (92, 64, 80), gap=14)
    s.arrow(281, 652, 322, 652, colour=LOOP_INK)
    s.diamond(400, 652, 140, 92, fill=GREEN)
    s.text(400, 648, "valid?", size=14, weight="bold")
    s.text(400, 666, "the same check", size=11, colour=DIM)
    s.line(470, 652, 646, 652, colour=LOOP_INK)
    s.line(646, 652, 646, 386, colour=LOOP_INK)
    s.arrow(646, 386, 628, 386, colour=LOOP_INK)
    s.text(
        500,
        744,
        "regenerate: the same fill and check, replaced in place",
        size=12,
        colour=LOOP_INK,
    )

    # -- what a decision writes, and what comes back ----------------------
    s.box(
        Box(
            990,
            176,
            510,
            104,
            WHITE,
            "editor autosave",
            (
                "rewrites the dashboard like any other edit,",
                "never the reviewed tags, never the draft flag",
            ),
        ),
        dashed=True,
    )
    s.arrow(1290, 284, 1290, 348, dashed=True, colour=DIM)
    s.cross(1290, 314, size=11)
    s.text(1312, 320, "never", size=13, colour=RED, anchor="start")

    s.cylinder(1185, 352, 210, 170, fill=PINK)
    s.text(1290, 414, "the dashboard", size=16, weight="bold")
    s.text(1290, 440, "ai_generation.reviewed", size=12, colour=DIM)
    s.text(1290, 462, "and the draft flag", size=12, colour=DIM)

    s.arrow(924, 620, 986, 618)
    s.box(
        Box(
            990,
            560,
            510,
            130,
            BLUE,
            "POST /ai/generated-dashboards/<id>/review",
            (
                "keep · unkeep · keep-all · unkeep-all",
                "the only writer of the review state, and it",
                "keeps only the tags still on the page",
            ),
        )
    )
    s.arrow(1290, 556, 1290, 530)

    s.line(1181, 437, 960, 437, colour=WRITE_INK)
    s.line(960, 437, 960, 268, colour=WRITE_INK)
    s.arrow(960, 268, 926, 268, colour=WRITE_INK)
    s.text(1000, 427, "the counter comes back", size=12, colour=WRITE_INK, anchor="start")

    # -- the two exits ----------------------------------------------------
    s.arrow(266, 764, 266, 806)
    s.arrow(726, 764, 726, 806)
    s.text(496, 790, "promoting with tiles unjudged asks first", size=12, colour=DIM)
    s.box(
        Box(
            56,
            810,
            420,
            118,
            GREEN,
            "Promote",
            ("status = promoted, the provenance stays,", "the banner and the panel go away"),
        )
    )
    s.box(
        Box(
            516,
            810,
            420,
            118,
            PINK,
            "Discard",
            ("the dashboard and every component", "in it are deleted"),
        )
    )
    return s


# --------------------------------------------------------------------------
# 3. The contract: the same definitions on both sides of the call.
# --------------------------------------------------------------------------

CONTRACT_W, CONTRACT_H = 1560, 940

# Lifted verbatim from what the sheet builder emits, so the drawing can be
# checked against a real prompt rather than believed.
SHEET_LINES: tuple[tuple[str, bool], ...] = (
    ("CARD   aggregation by column_type", True),
    ("  int64    -> count, sum, average, median, min, max, range, ...", False),
    ("  bool     -> count, sum, min, max", False),
    ("  secondary_layout: vertical, compact, grid, box_plot, top_n, ...", False),
    ("INTERACTIVE   control by column_type", True),
    ("  int64    -> Slider, RangeSlider", False),
    ("  object   -> Select, MultiSelect, SegmentedControl", False),
    ("ADVANCED_VIZ   ranked against this collection's own dtypes", True),
    ("  viz_kind: volcano   (fit 0.92)", False),
    ("    config.x_col: required column (Float64). Candidates: log2FC", False),
    ("    config.y_col: required column (Float64). Candidates: pvalue", False),
    ("  config accepts ONLY the keys listed; unknown keys are rejected", False),
)


def build_contract() -> Sketch:
    """Why a generated component is a Depictio component and not a guess.

    The drawing exists for one claim, so the claim is the composition: a single
    group on the left with two arrows out of it, one into the prompt and one
    into the checks. The sheet in the middle is quoted rather than summarised,
    because "the prompt is generated from the models" is only believable when
    the reader can see the compatibility tables in it. The bottom row is the
    same definitions again, this time saying no.
    """
    s = Sketch(CONTRACT_W, CONTRACT_H)
    s.heading(
        56,
        60,
        "The model is the contract",
        "the same definitions generate the prompt's legal space and reject whatever falls outside it",
    )

    # -- one source of truth ----------------------------------------------
    s.rect(Box(56, 104, 330, 430, "none", ""), colour=GREY, dashed=True)
    s.text(221, 132, "one source of truth", size=15, weight="bold")
    for i, (label, fill) in enumerate(
        (
            ("models/components/constants.py", CARD_FILL),
            ("models/components/lite.py", GREEN),
            ("advanced_viz/schemas.py", FIGURE_FILL),
            ("ai_endpoints/component_style.py", ORANGE),
        )
    ):
        s.chip(221, 176 + i * 36, label, fill=fill, w=290, h=30, size=11)
    s.text(221, 322, "the definitions the builder and the CLI", size=11, colour=DIM)
    s.text(221, 340, "already use, read at request time", size=11, colour=DIM)
    s.cylinder(141, 366, 160, 148, fill=BLUE)
    s.text(221, 418, "this collection", size=14, weight="bold")
    s.text(221, 442, "columns, dtypes,", size=11, colour=DIM)
    s.text(221, 460, "distinct counts", size=11, colour=DIM)

    # -- what the prompt may say ------------------------------------------
    s.arrow(390, 260, 466, 260)
    s.text(428, 246, "generates", size=11, colour=DIM)
    s.document(470, 104, 570, 320, fill=YELLOW)
    s.text(755, 140, "the constraint sheet", size=18, weight="bold")
    s.text(755, 162, "what the prompt may say, generated per request", size=12, colour=DIM)
    for i, (line, heading) in enumerate(SHEET_LINES):
        s.text(
            496,
            192 + i * 18.5,
            line,
            size=12,
            colour=INK if heading else DIM,
            anchor="start",
            weight="bold" if heading else "normal",
        )

    s.arrow(1044, 260, 1086, 260)
    s.box(
        Box(
            1090,
            190,
            300,
            140,
            VIOLET,
            "one model call",
            ("the only step nothing", "constrains from inside"),
        )
    )

    s.line(1240, 330, 1240, 440)
    s.line(1240, 440, 1445, 440)
    s.arrow(1445, 440, 1445, 496)
    s.text(1288, 470, "the answer, in the CLI's own YAML grammar", size=12, colour=DIM)

    # -- what the answer has to pass --------------------------------------
    s.text(880, 470, "what the answer has to pass", size=15, weight="bold")
    s.document(1350, 500, 190, 130, fill=YELLOW)
    s.text(1445, 530, "the answer", size=14, weight="bold")
    scribble(s, 1376, 552, (132, 98, 114, 80), gap=17)

    s.arrow(1346, 564, 1314, 564)
    s.box(
        Box(
            1060,
            506,
            250,
            118,
            GREEN,
            "from_yaml",
            ("DashboardDataLite,", "the loader the CLI uses"),
        )
    )
    s.arrow(1056, 564, 1024, 564)
    s.box(
        Box(
            750,
            506,
            270,
            118,
            GREEN,
            "the typed component",
            ("CardLiteComponent, ...", "extra = forbid"),
        )
    )
    s.arrow(746, 564, 714, 564)
    s.box(
        Box(
            440,
            494,
            270,
            142,
            GREEN,
            "check_against_schema",
            (
                "every column real,",
                "aggregation by column type,",
                "MultiSelect <= 50, role dtypes",
            ),
        )
    )
    s.arrow(388, 505, 436, 545)
    s.text(414, 492, "rejects", size=11, colour=DIM)

    s.line(575, 636, 575, 672)
    s.arrow(575, 672, 575, 700)
    s.box(
        Box(
            455,
            700,
            240,
            118,
            GREEN,
            "the render probe",
            ("the real render path,", "in process, never HTTP"),
        )
    )
    s.arrow(699, 759, 745, 759)
    s.diamond(830, 759, 152, 104, fill=WHITE)
    s.text(830, 755, "clean?", size=15, weight="bold")
    s.text(830, 775, "no findings", size=11, colour=DIM)

    s.arrow(908, 759, 962, 759)
    s.chip(1044, 759, "kept", fill=GREEN, w=140, h=44, size=14)
    s.tick(1002, 755, colour=WRITE_INK)
    s.text(1044, 806, "still failing: dropped, never saved", size=11, colour=DIM)

    s.line(830, 811, 830, 858, colour=RED)
    s.line(830, 858, 1445, 858, colour=RED)
    s.arrow(1445, 858, 1445, 638, colour=RED)
    s.text(1130, 880, "one repair round: the finding, quoted verbatim", size=12, colour=RED)
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v1.4/ai/schema"),
        "--out",
        help="Output prefix; '_<name>.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the generation and review schemas under --out."""
    write(build_pipeline(), out, "generation_pipeline", png=png)
    write(build_contract(), out, "model_contract", png=png)
    write(build_review(), out, "draft_review", png=png)


if __name__ == "__main__":
    app()
