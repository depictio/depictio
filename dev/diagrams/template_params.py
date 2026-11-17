#!/usr/bin/env python3
"""Render the ``from_params`` schema as a hand-drawn SVG (+ PNG).

One diagram for ``docs/template-params.md`` and PR #1408. Everything in it is
the real thing, nothing is illustrative: nf-core/rnaseq 3.26.0 run with
``--skip_alignment``, its params dump, the template's three rules evaluated on
it, the four conditionals (one fires), the exact paths each collection reads
before and after, the output of ``depictio template check`` on it, and the
coverage of the 57 bundled templates.

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
    tick,
    write,
)

app = typer.Typer(add_completion=False)

LOGOS = Path(__file__).parent / "logos"
SECTION = "#7048e8"
ORANGE_INK = "#e8590c"
TICK = "#2f9e44"
CODE_BG = "#1e1e1e"
CODE_INK = "#e9ecef"
CODE_KEY = "#b197fc"
CODE_STR = "#8ce99a"
CODE_NUM = "#ffc078"
CODE_DIM = "#868e96"
CODE_RED = "#ff8787"

W, H = 1760, 1330
NBSP = " "


def logo(s: Sketch, name: str, x: float, y: float, w: float, h: float | None = None) -> None:
    s.image(LOGOS / name, x, y, w, h if h is not None else w)


def section(s: Sketch, x: float, y: float, label: str) -> None:
    s.text(x, y, label, size=17, colour=SECTION, anchor="start", weight="bold")


def mono(s: Sketch, x: float, y: float, text: str, *, size: float = 13, colour: str = INK) -> None:
    s.text(x, y, f"`{text.replace(' ', NBSP)}`", size=size, colour=colour, anchor="start")


def code(
    s: Sketch,
    x: float,
    y: float,
    w: float,
    lines: list[tuple[str, str]],
    *,
    size: float = 13,
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
        if text:
            mono(s, x + 16, y + 44 + i * (size + 7), text, size=size, colour=colour)
    return box


def build() -> Sketch:
    s = Sketch(W, H)
    s.heading(
        60,
        64,
        "nf-core/rnaseq 3.26.0 run with `--skip_alignment`: what the template does, step by step",
        "the real rules, values, conditionals and paths of `nf-core/rnaseq/3.26.0/template.yaml`; nobody passes `--var`",
    )
    s.line(60, 104, 1190, 104, colour=SECTION, width=2.4, amount=1.0, passes=1)

    # -- 1 · the run ------------------------------------------------------------
    section(s, 60, 160, "1 · THE RUN")
    run = Box(60, 180, 440, 600, WHITE, "")
    s.rect(run)
    logo(s, "nf-core.png", 78, 194, 44)
    logo(s, "nf-core-rnaseq.webp", 130, 192, 140, 52)
    s.text(282, 226, "`3.26.0`", size=15, anchor="start")
    code(
        s,
        78,
        254,
        404,
        [
            ("nextflow run nf-core/rnaseq -r 3.26.0 \\", CODE_INK),
            ("  --skip_alignment \\", CODE_NUM),
            ("  --pseudo_aligner salmon  …", CODE_INK),
        ],
        size=12.5,
    )
    folder(s, 78, 372, 92, 62, YELLOW, "")
    s.text(124, 412, "`results/`", size=12.5)
    tree = (
        ("pipeline_info/params_2026-11-02_10-12-00.json", INK, "tick", "read: the newest full dump"),
        ("pipeline_info/nf-params.json", GREY, "cross", "never: overrides only"),
        ("salmon/salmon.merged.gene_tpm.tsv", INK, "tick", "written"),
        ("star_salmon/", GREY, "cross", "not written: no alignment"),
        ("multiqc/salmon/multiqc_report_data/", INK, "tick", "written"),
    )
    for i, (path, colour, mark, why) in enumerate(tree):
        ty = 382 + i * 34
        mono(s, 184, ty, path, size=11, colour=colour)
        s.text(184, ty + 15, why, size=11, colour=DIM, anchor="start")
        if mark == "tick":
            tick(s, 482, ty - 4, size=5)
        else:
            s.cross(482, ty - 4, size=5)
    code(
        s,
        78,
        562,
        404,
        [
            ("{", CODE_INK),
            ('  "skip_alignment": true,', CODE_NUM),
            ('  "pseudo_aligner": "salmon",', CODE_STR),
            ('  "skip_multiqc": false,', CODE_NUM),
            ('  "skip_quantification_merge": false,', CODE_NUM),
            ("  …  (133 params in the 3.26.0 schema)", CODE_DIM),
            ("}", CODE_INK),
        ],
        size=12.5,
        title="params_2026-11-02_10-12-00.json",
    )

    # -- 2 · the rules on this run -----------------------------------------------
    section(s, 540, 160, "2 · EACH VARIABLE, ON THIS RUN")
    tbl = Box(540, 180, 680, 300, WHITE, "")
    s.rect(tbl)
    cols = (556, 790, 1060, 1140)
    for x, head in zip(cols, ("variable", "set by (template.yaml)", "value", "→")):
        s.text(x, 210, head, size=13, colour=DIM, anchor="start")
    s.line(552, 220, 1208, 220, colour=GREY, width=1.0, amount=0.4, passes=1)
    rows = (
        ("PSEUDOALIGNER_ONLY", "from_params: {param: skip_alignment}", "true", "true", True),
        ("SKIP_MULTIQC", "from_params: {param: skip_multiqc}", "false", "unset", False),
        ("SKIP_QUANTIFICATION_", "from_params: {param:", "false", "unset", False),
        ("TRACKS_URI", "--var only (where BAMs live)", "", "unset", False),
        ("SAMPLESHEET_FILE", "auto: input/samplesheet.csv", "", "found", True),
        ("DATA_ROOT", "auto: the results directory", "", "results/", True),
    )
    y = 246
    for name, how, value, result, on in rows:
        mono(s, cols[0], y, name, size=12, colour=INK if on else DIM)
        mono(s, cols[1], y, how, size=11.5, colour=SECTION if how.startswith("from") else DIM)
        if value:
            mono(s, cols[2], y, value, size=12, colour=ORANGE_INK)
        if on:
            tick(s, cols[3] + 4, y - 4, size=6)
        else:
            dot(s, cols[3] + 4, y - 4, GREY)
        mono(s, cols[3] + 18, y, result, size=12, colour=TICK if on else GREY)
        if name.endswith("_"):
            y += 18
            mono(s, cols[0], y, "  MERGE", size=12, colour=DIM)
            mono(s, cols[1], y, "  skip_quantification_merge}", size=11.5, colour=SECTION)
        y += 34
    s.arrow(run.right, 470, tbl.x, 300)

    over = Box(540, 500, 680, 120, YELLOW, "")
    s.rect(over)
    s.text(556, 528, "an explicit `--var` always wins", size=14, anchor="start", weight="bold")
    mono(s, 556, 556, "--var SKIP_MULTIQC=true", size=12)
    s.text(780, 556, "sets it, whatever the rule says", size=12.5, colour=DIM, anchor="start")
    mono(s, 556, 582, "--var PSEUDOALIGNER_ONLY=false", size=12)
    s.text(840, 582, "unsets it (also `0`, `null`, empty)", size=12.5, colour=DIM, anchor="start")
    s.text(556, 606, "no params file: no rule fires; the template is used as is", size=12.5, colour=DIM, anchor="start")

    rulebox = Box(540, 640, 680, 140, VIOLET, "")
    s.rect(rulebox)
    s.text(556, 668, "the five tests a rule can use", size=14, anchor="start", weight="bold")
    tests = (
        ("{param: p}", "on: true, \"true\", non-empty"),
        ("{param: p, is: false}", "off, \"null\", empty, absent"),
        ("equals / not_equals: v", "the value, any case"),
        ("contains / not_contains: v", "in a list or \"a,b\""),
        ("any: [...] / all: [...]", "one / every nested rule"),
    )
    for i, (rule, what) in enumerate(tests):
        tx, dx = (556, 740) if i < 3 else (900, 1080)
        ty = 694 + (i % 3) * 24
        mono(s, tx, ty, rule, size=11.5, colour=SECTION)
        s.text(dx, ty, what, size=11.5, colour=DIM, anchor="start")

    # -- 3 · the conditionals --------------------------------------------------------
    section(s, 1260, 160, "3 · CONDITIONALS")
    cond = code(
        s,
        1260,
        180,
        440,
        [
            ("conditional:", CODE_KEY),
            ("- if_var_present: PSEUDOALIGNER_ONLY", CODE_STR),
            ("    remove_dc_tags: [tracks]", CODE_NUM),
            ("    override_dcs:          # 7 collections", CODE_INK),
            ("      sample_overview, expression_heatmap,", CODE_INK),
            ("      gene_expression, gene_summary,", CODE_INK),
            ("      gene_counts, deseq2_qc_pca,", CODE_INK),
            ("      deseq2_qc_dists   → salmon/", CODE_INK),
            ("", CODE_INK),
            ("- if_var_present: SKIP_MULTIQC", CODE_DIM),
            ("    remove_dc_tags: [multiqc_data,", CODE_DIM),
            ("                     general_stats]", CODE_DIM),
            ("- if_var_present: SKIP_QUANTIFICATION_MERGE", CODE_DIM),
            ("    remove_dc_tags: [5 expression DCs]", CODE_DIM),
            ("- if_var_present: TRACKS_URI", CODE_DIM),
            ("    override_dcs: tracks → read in place", CODE_DIM),
        ],
        size=12,
        title="template.yaml",
    )
    # line i of the card sits at y + 44 + i * 19
    tick(s, 1680, 180 + 44 + 19 - 5, size=7)
    for i in (9, 12, 14):
        dot(s, 1684, 180 + 44 + i * 19 - 5, GREY)
    s.text(1260, cond.bottom + 26, "green: fires on this run · grey: does not", size=12.5, colour=DIM, anchor="start")
    s.arrow(tbl.right, 260, cond.x, 230)

    # -- 4 · what each collection reads ---------------------------------------------
    section(s, 60, 830, "4 · WHAT EACH COLLECTION READS")
    dcs = Box(60, 850, 1080, 250, WHITE, "")
    s.rect(dcs)
    dc_cols = (76, 330, 740)
    for x, head in zip(dc_cols, ("data collection", "a default run (STAR + Salmon)", "this run")):
        s.text(x, 878, head, size=13, colour=DIM, anchor="start")
    s.line(72, 888, 1128, 888, colour=GREY, width=1.0, amount=0.4, passes=1)
    dc_rows = (
        ("sample_overview, expression_heatmap,", "star_salmon/salmon.merged.gene_tpm.tsv", "salmon/salmon.merged.gene_tpm.tsv", "moved"),
        ("  gene_expression, gene_summary", "", "", None),
        ("gene_counts", "star_salmon/salmon.merged.gene_counts.tsv", "salmon/salmon.merged.gene_counts.tsv", "moved"),
        ("deseq2_qc_pca, deseq2_qc_dists", "star_salmon/deseq2_qc/*pca.vals.txt …", "salmon/deseq2_qc/*pca.vals.txt …", "moved"),
        ("multiqc_data, general_stats", "multiqc/star_salmon/multiqc_report_data/", "multiqc/salmon/… (same pattern)", "kept"),
        ("tracks", "star_salmon/bigwig/*.bigWig, *.markdup.sorted.bam", "dropped: no alignment, no BAM", "dropped"),
    )
    y = 914
    for tag, before, after, state in dc_rows:
        mono(s, dc_cols[0], y, tag, size=11.5)
        if before:
            mono(s, dc_cols[1], y, before, size=11.5, colour=DIM)
        if state == "moved":
            mono(s, dc_cols[2], y, after, size=11.5, colour=TICK)
        elif state == "kept":
            mono(s, dc_cols[2], y, after, size=11.5, colour=INK)
        elif state == "dropped":
            s.cross(dc_cols[2] + 6, y - 4, size=6)
            s.text(dc_cols[2] + 20, y, after, size=12, colour=RED, anchor="start")
        y += 30
    s.curve([(cond.cx, cond.bottom + 40), (cond.cx, 820), (1100, 820), (1100, dcs.y)], colour=INK)
    s.arrow(1100, 830, 1100, dcs.y)

    dash = browser(s, 1180, 850, 520, 250)
    s.text(1240, 869, "`dashboard · nf-core/rnaseq`", size=12, colour=DIM, anchor="start")
    logo(s, "depictio.png", 1672, 854, 22)
    for i, tab in enumerate(("Overview", "Expression", "QC")):
        s.rect(Box(1196 + i * 100, 888, 92, 24, VIOLET if i == 0 else WHITE, ""), colour=GREY)
        s.text(1242 + i * 100, 905, tab, size=12)
    expr = Box(1196, 924, 160, 160, WHITE, "")
    s.rect(expr, colour=GREY)
    for i, frac in enumerate((0.4, 0.75, 0.55, 0.95, 0.3)):
        s.rect(Box(1210 + i * 28, 950 + 80 * (1 - frac), 18, 80 * frac, "#a5d8ff", ""))
    s.text(expr.cx, 1052, "expression", size=12)
    mono(s, 1218, 1072, "salmon/", size=11, colour=TICK)
    mqc = Box(1366, 924, 160, 160, VIOLET, "")
    s.rect(mqc, colour=GREY)
    logo(s, "multiqc_icon_color.svg", mqc.cx - 20, 940, 40)
    s.text(mqc.cx, 1006, "MultiQC", size=12.5)
    tick(s, mqc.cx - 18, 1036, size=6)
    s.text(mqc.cx - 6, 1041, "kept", size=12, colour=DIM, anchor="start")
    trk = Box(1536, 924, 150, 160, PINK, "")
    s.rect(trk, colour=RED, dashed=True)
    for i in range(3):
        ly = 950 + i * 20
        s.line(1550, ly, 1672, ly, colour=GREY, width=3, amount=0.5, passes=1)
    s.cross(trk.cx, 970, size=20)
    s.text(trk.cx, 1040, "genome tracks", size=12.5)
    s.text(trk.cx, 1060, "tab dropped", size=12, colour=RED)

    # -- 5 · check it yourself ----------------------------------------------------
    section(s, 60, 1150, "5 · CHECK IT YOURSELF")
    code(
        s,
        60,
        1166,
        760,
        [
            ("$ depictio template check nf-core/rnaseq/3.26.0 --fetch-schema --run results/", CODE_INK),
            ("This run fires: if_var_present: PSEUDOALIGNER_ONLY → drops tracks; repoints …", CODE_STR),
            ("✓ every param a rule reads exists in this release", CODE_STR),
            ("! skip_* params no rule reads, whose tool the template names: skip_bigwig, …", CODE_NUM),
        ],
        size=12,
    )
    ci = Box(850, 1166, 400, 124, WHITE, "")
    s.rect(ci)
    logo(s, "githubactions.svg", 866, 1180, 30)
    logo(s, "github.svg", 1214, 1180, 22)
    s.text(906, 1200, "`template-params.yaml`", size=13, anchor="start")
    s.text(866, 1230, "the same command, `--all`, on every template", size=12.5, colour=DIM, anchor="start")
    s.text(866, 1250, "change, against each release's schema on GitHub", size=12.5, colour=DIM, anchor="start")
    tick(s, 872, 1272, size=6)
    s.text(886, 1277, "57 templates · 51 rules · 0 unknown params", size=12.5, anchor="start")

    cov = Box(1280, 1166, 420, 124, WHITE, "")
    s.rect(cov)
    s.text(1296, 1190, "coverage of the 57 templates", size=13.5, anchor="start", weight="bold")
    x0, total, bw = 1296, 57, 388
    for n, fill, label in ((18, GREEN, "18 rules"), (24, YELLOW, "24 inputs only"), (15, "#f1f3f5", "15 no route")):
        w = bw * n / total
        s.rect(Box(x0, 1204, w, 26, fill, ""), colour=GREY)
        s.text(x0 + w / 2, 1222, label, size=11.5)
        x0 += w
    s.text(1296, 1254, "29 with `skip_*` flags to verify (`--all` lists them)", size=12, colour=ORANGE_INK, anchor="start")
    s.text(1296, 1274, "see docs/template-params.md, Coverage", size=11.5, colour=DIM, anchor="start")
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
