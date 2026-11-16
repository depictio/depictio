#!/usr/bin/env python3
"""Render the ``from_params`` schema as a hand-drawn SVG (+ PNG).

One diagram for ``docs/template-params.md`` and PR #1408: how a run's own
``params_<ts>.json`` becomes the variables a template's conditionals read,
without anyone passing ``--var``, and what CI holds true about the rules.

The worked example is nf-core/rnaseq 3.26.0 run with ``--skip_alignment``: its
real rules and conditionals, and their real outcome (the genome tracks are
dropped, MultiQC is kept).

Logos are embedded from ``dev/diagrams/logos/``; see its README.

Usage:
    python dev/diagrams/template_params.py --out docs/images/template-params/schema
    # writes <out>_from_params.svg/.png
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
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    browser,
    circle,
    dot,
    folder,
    page,
    terminal,
    tick,
    write,
)

app = typer.Typer(add_completion=False)

LOGOS = Path(__file__).parent / "logos"
SECTION = "#7048e8"
ORANGE_INK = "#e8590c"
CODE_BG = "#1e1e1e"
CODE_INK = "#e9ecef"
CODE_KEY = "#b197fc"
CODE_STR = "#8ce99a"
CODE_NUM = "#ffc078"
CODE_DIM = "#868e96"

W, H = 1760, 1140


def logo(s: Sketch, name: str, x: float, y: float, w: float, h: float | None = None) -> None:
    s.image(LOGOS / name, x, y, w, h if h is not None else w)


def section(s: Sketch, x: float, y: float, label: str) -> None:
    s.text(x, y, label, size=17, colour=SECTION, anchor="start", weight="bold")


def code(
    s: Sketch,
    x: float,
    y: float,
    w: float,
    lines: list[tuple[str, str]],
    *,
    size: float = 14,
    title: str = "",
) -> Box:
    """A dark code card: (text, colour) per line, monospace."""
    h = 40 + len(lines) * (size + 7)
    box = Box(x, y, w, h, CODE_BG, "")
    s.rect(box)
    for i, colour in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        circle(s, x + 16 + i * 15, y + 14, 4.5, colour)
    if title:
        s.text(x + w - 14, y + 19, f"`{title}`", size=12, colour=CODE_DIM, anchor="end")
    for i, (text, colour) in enumerate(lines):
        if not text:
            continue
        shown = text.replace(" ", " ")
        s.text(
            x + 16, y + 44 + i * (size + 7), f"`{shown}`", size=size, colour=colour, anchor="start"
        )
    return box


def pill(s: Sketch, x: float, y: float, label: str, fill: str = VIOLET) -> float:
    """A rule-test chip; returns the x after it."""
    w = 18 + len(label) * 8.2
    s.rect(Box(x, y, w, 28, fill, ""), colour=DIM)
    s.text(x + w / 2, y + 19, f"`{label}`", size=13)
    return x + w + 10


def bars(s: Sketch, x: float, y: float, w: float, h: float, heights: tuple[float, ...]) -> None:
    n = len(heights)
    bw = w / n * 0.62
    for i, frac in enumerate(heights):
        bx = x + i * w / n + (w / n - bw) / 2
        s.rect(Box(bx, y + h * (1 - frac), bw, h * frac, "#a5d8ff", ""))


def build() -> Sketch:
    s = Sketch(W, H)
    s.heading(
        60,
        64,
        "The run says which route it took; the template listens",
        "`from_params` rules read the run's `pipeline_info/params_<ts>.json` · no `--var` to pass · an explicit `--var` always wins",
    )
    s.line(60, 104, 1190, 104, colour=SECTION, width=2.4, amount=1.0, passes=1)

    # -- 1 · the run ------------------------------------------------------------
    section(s, 60, 160, "1 · THE RUN WRITES WHAT IT DID")
    run = Box(60, 180, 420, 500, WHITE, "")
    s.rect(run)
    logo(s, "nf-core.png", 80, 196, 50)
    logo(s, "nf-core-rnaseq.webp", 140, 194, 150, 56)
    s.text(300, 228, "`3.26.0`", size=15, anchor="start")
    s.text(140, 270, "run with `--skip_alignment`", size=14, colour=DIM, anchor="start")

    out = folder(s, 80, 296, 110, 72, YELLOW, "")
    s.text(out.cx, out.y + 46, "`--outdir`", size=14)
    tree = (
        ("`pipeline_info/`", INK, None),
        ("`  params_2026-11-02_1012.json`", INK, "newest"),
        ("`  params_2026-11-01_0915.json`", GREY, None),
        ("`  nf-params.json`", GREY, "overrides"),
    )
    for i, (text, colour, mark) in enumerate(tree):
        ty = 304 + i * 22
        s.text(206, ty, text.replace(" ", " "), size=12.5, colour=colour, anchor="start")
        if mark == "newest":
            tick(s, 458, ty - 5, size=6)
        elif mark == "overrides":
            s.cross(458, ty - 5, size=6)
    s.text(206, 400, "newest dump decides (a resumed run", size=12, colour=DIM, anchor="start")
    s.text(206, 416, "leaves one per attempt); overrides only", size=12, colour=DIM, anchor="start")
    s.text(206, 432, "would read an absent default as off", size=12, colour=DIM, anchor="start")

    js = code(
        s,
        80,
        452,
        380,
        [
            ("{", CODE_INK),
            ('  "skip_alignment": true,', CODE_NUM),
            ('  "pseudo_aligner": "salmon",', CODE_STR),
            ('  "skip_multiqc": false,', CODE_NUM),
            ('  "skip_quantification_merge": false,', CODE_NUM),
            ("  …", CODE_DIM),
            ("}", CODE_INK),
        ],
        size=13,
        title="params_<ts>.json",
    )
    s.text(run.cx, js.bottom + 24, '`true`, `"true"`, `"a,b"`, `["a"]`: all read', size=13, colour=DIM)

    # -- 2 · the template -------------------------------------------------------
    section(s, 540, 160, "2 · THE TEMPLATE DECLARES A RULE PER ROUTE")
    yml = code(
        s,
        540,
        180,
        500,
        [
            ("variables:", CODE_KEY),
            ("  - name: PSEUDOALIGNER_ONLY", CODE_INK),
            ("    from_params: {param: skip_alignment}", CODE_STR),
            ("  - name: SKIP_MULTIQC", CODE_INK),
            ("    from_params: {param: skip_multiqc}", CODE_STR),
            ("  - name: SKIP_QUANTIFICATION_MERGE", CODE_INK),
            ("    from_params: {param: skip_quantification_merge}", CODE_STR),
            ("", CODE_INK),
            ("conditionals:", CODE_KEY),
            ("  - if_var_present: PSEUDOALIGNER_ONLY", CODE_INK),
            ("    remove_dc_tags: [tracks]", CODE_NUM),
            ("  - if_var_present: SKIP_MULTIQC", CODE_INK),
            ("    remove_dc_tags: [multiqc_data, general_stats]", CODE_NUM),
        ],
        size=13.5,
        title="rnaseq/3.26.0/template.yaml",
    )
    s.arrow(run.right, 360, yml.x, 300)

    s.text(540, yml.bottom + 34, "what a rule can test", size=15, anchor="start")
    x = 540.0
    for label in ("param", "is: false", "equals", "not_equals"):
        x = pill(s, x, yml.bottom + 48, label)
    x = 540.0
    for label in ("contains", "not_contains", "any: [...]", "all: [...]"):
        x = pill(s, x, yml.bottom + 86, label, fill=BLUE)
    for i, line in enumerate(
        (
            "rnafusion: `{all: [{param: tools, not_contains: arriba},`",
            "`                   {param: tools, not_contains: all}]}`",
        )
    ):
        s.text(
            540, yml.bottom + 144 + i * 18, line.replace("  ", "  "),
            size=12.5, colour=DIM, anchor="start",
        )

    # -- 3 · the variables and the dashboard -----------------------------------
    section(s, 1100, 160, "3 · WHAT THE TEMPLATE GETS")
    var = Box(1100, 180, 330, 176, GREEN, "")
    s.rect(var)
    s.text(1118, 208, "variables", size=16, anchor="start", weight="bold")
    rows = (
        ("PSEUDOALIGNER_ONLY", "= true", True),
        ("SKIP_MULTIQC", "not set", False),
        ("SKIP_QUANTIFICATION_MERGE", "not set", False),
    )
    for i, (name, value, on) in enumerate(rows):
        ry = 244 + i * 34
        if on:
            tick(s, 1126, ry - 5, size=7)
        else:
            dot(s, 1126, ry - 5, GREY)
        s.text(1144, ry, f"`{name}`", size=13, colour=INK if on else DIM, anchor="start")
        if on or len(name) < 20:
            s.text(1416, ry, value, size=13, colour=INK if on else GREY, anchor="end")
    s.text(1118, 346, "a rule that does not hold sets nothing", size=12.5, colour=DIM, anchor="start")
    s.arrow(yml.right, 268, var.x, 268)

    # The user, who can always overrule a rule.
    circle(s, 1480, 196, 11, "#ffc9c9")
    s.poly([(1462, 236), (1466, 216), (1494, 216), (1498, 236)], fill="#ffc9c9", amount=0.8)
    s.text(1512, 222, "an explicit `--var` wins", size=14, anchor="start")
    term = terminal(s, 1460, 250, 250, 58)
    s.text(1472, 294, "`--var SKIP_X=false`", size=13, anchor="start")
    s.text(1460, 330, "`false`, `0`, `null`, empty: unsets", size=12.5, colour=DIM, anchor="start")
    s.text(1460, 348, "a rule that misfires", size=12.5, colour=DIM, anchor="start")
    s.arrow(term.x, term.cy, var.right, term.cy, colour=ORANGE_INK)

    dash = browser(s, 1100, 400, 610, 260)
    s.text(1160, 419, "`dashboard · nf-core/rnaseq`", size=12, colour=DIM, anchor="start")
    logo(s, "depictio.png", 1680, 404, 22)
    for i, (tab, active) in enumerate((("Overview", True), ("Expression", False), ("QC", False))):
        tx = 1116 + i * 110
        s.rect(Box(tx, 438, 100, 26, VIOLET if active else WHITE, ""), colour=GREY)
        s.text(tx + 50, 456, tab, size=12.5)

    expr = Box(1116, 478, 190, 160, WHITE, "")
    s.rect(expr, colour=GREY)
    bars(s, 1128, 500, 166, 80, (0.4, 0.75, 0.55, 0.95, 0.3))
    s.text(expr.cx, 604, "expression", size=12.5)
    s.text(expr.cx, 624, "reads `salmon/`", size=12, colour=DIM)

    mqc = Box(1318, 478, 180, 160, VIOLET, "")
    s.rect(mqc, colour=GREY)
    logo(s, "multiqc_icon_color.svg", mqc.cx - 22, 494, 44)
    s.text(mqc.cx, 562, "MultiQC", size=13)
    tick(s, mqc.cx - 30, 590, size=6)
    s.text(mqc.cx - 18, 595, "kept", size=12.5, colour=DIM, anchor="start")
    s.text(mqc.cx, 622, "`skip_multiqc: false`", size=11.5, colour=DIM)

    trk = Box(1510, 478, 186, 160, PINK, "")
    s.rect(trk, colour=RED, dashed=True)
    for i in range(3):
        ly = 506 + i * 22
        s.line(1526, ly, 1680, ly, colour=GREY, width=3, amount=0.6, passes=1)
        s.rect(Box(1540 + i * 34, ly - 6, 40 + i * 6, 12, "#ffa8a8", ""), colour=GREY)
    s.cross(trk.cx, 528, size=22)
    s.text(trk.cx, 600, "genome tracks", size=13)
    s.text(trk.cx, 622, "dropped: no BAM", size=12, colour=RED)
    s.arrow(var.cx, var.bottom, var.cx, dash.y)

    s.text(
        1100,
        690,
        "one template fits a default run, a pseudo-aligner run, a run without MultiQC…",
        size=13.5,
        colour=DIM,
        anchor="start",
    )

    # -- 4 · CI -----------------------------------------------------------------
    section(s, 60, 760, "4 · HELD TRUE IN CI")
    ci = Box(60, 780, 700, 290, WHITE, "")
    s.rect(ci)
    logo(s, "githubactions.svg", 80, 798, 36)
    s.text(128, 824, "`template-params.yaml`, on every template change", size=15, anchor="start")

    page(s, 90, 860, 64, 82, BLUE)
    s.text(122, 962, "`template.yaml`", size=12, colour=DIM)
    s.text(122, 978, "51 rules", size=12, colour=DIM)
    s.arrow(170, 900, 250, 900)
    terminal(s, 256, 862, 220, 76)
    s.text(268, 904, "`check_template_`", size=13, anchor="start")
    s.text(268, 922, "`params.py`", size=13, anchor="start")
    s.arrow(574, 900, 486, 900)
    logo(s, "github.svg", 652, 846, 26)
    page(s, 584, 874, 58, 66, YELLOW)
    s.text(650, 962, "`nextflow_schema.json`", size=12, colour=DIM)
    s.text(650, 978, "at each template's release tag", size=12, colour=DIM)

    tick(s, 96, 1010, size=8)
    s.text(116, 1015, "every rule's param exists in its release: 51 rules, 0 unknown", size=14, anchor="start")
    s.cross(96, 1046, size=8)
    s.text(
        116,
        1051,
        "a param renamed upstream fails CI, not a rule that silently never holds",
        size=14,
        colour=RED,
        anchor="start",
    )

    tests = Box(800, 780, 420, 290, GREEN, "")
    s.rect(tests)
    s.text(820, 816, "pytest, every shipped template", size=15, anchor="start", weight="bold")
    for i, line in enumerate(
        (
            "loads: `extra=forbid`, so `from_param:` fails",
            "`required: true` with a rule is refused",
            '`"true"`, `"False"`, `"null"` read as booleans',
            "only `params_<ts>.json` feeds rules",
            "a `[]` or scalar params file sets nothing",
            "`--var X=false` unsets; no file: as before",
        )
    ):
        ly = 856 + i * 34
        tick(s, 826, ly - 5, size=6)
        s.text(842, ly, line, size=13, anchor="start")

    reach = Box(1260, 780, 450, 290, WHITE, "")
    s.rect(reach)
    s.text(1280, 816, "51 rules · 18 templates · 15 pipelines", size=15, anchor="start", weight="bold")
    for i, name in enumerate(("rnaseq", "airrflow", "smrnaseq", "funcscan", "ampliseq", "viralrecon")):
        lx = 1280 + (i % 3) * 140
        ly = 838 + (i // 3) * 64
        logo(s, f"nf-core-{name}.webp", lx, ly, 128, 50)
    for i, line in enumerate(
        (
            "+ rnafusion, mhcquant, crisprseq, pairgenomealign,",
            "proteinannotator, stableexpression, epitopeprediction,",
            "differentialabundance, demultiplex",
            "each read against the release's schema and code",
        )
    ):
        s.text(1280, 988 + i * 19, line, size=12.5, colour=DIM if i < 3 else INK, anchor="start")

    s.text(
        60,
        H - 30,
        "Stays `--var` (params alone cannot tell): mcmicro `SINGLE_SEGMENTER`, epitopeprediction "
        "`SINGLE_PREDICTOR` / `NO_VARIANT_INPUT`, chipseq `PRESEQ_RAN`. Output introspection "
        "(phylogeny, pplacer, metadata file) still runs after the rules.",
        size=13,
        colour=DIM,
        anchor="start",
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/template-params/schema"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render PNGs through Playwright."),
) -> None:
    """Write the from_params schema under --out."""
    write(build(), out, "from_params", png=png)


if __name__ == "__main__":
    app()
