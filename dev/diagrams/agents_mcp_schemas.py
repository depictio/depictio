#!/usr/bin/env python3
"""Render the agents + MCP schemas as hand-drawn SVGs (+ PNGs).

Four diagrams, two per PR:

* ``mcp_architecture``    (PR 1): external agents reach Depictio through a
  stdio proxy and a streamable HTTP endpoint, and every call lands in the one
  shared tool registry that the in-app orchestrator (PR 2) consumes too.
* ``token_scopes``        (PR 1): what each scope unlocks, and the fail-closed
  rules that apply to scoped tokens only.
* ``agent_team_pipeline`` (PR 2): router, parallel analysts, skeptic, then the
  actors that write proposals and the report for a human to review.
* ``evidence_flow``       (PR 2): a finding survives only if it cites
  successful evidence-capable calls; the server builds the Evidence itself.

Usage:
    python dev/diagrams/agents_mcp_schemas.py --out docs/images/v1.4/agents/schema
    # writes <out>_<name>.svg/.png for the four names above

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
    ORANGE,
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)

W, H = 1400, 820


# --------------------------------------------------------------------------
# 1. MCP architecture: two doors, one registry.
# --------------------------------------------------------------------------


def build_architecture() -> Sketch:
    """External agents and the in-app orchestrator share one tool registry.

    The registry is drawn as the chain every call goes through, so the reader
    sees that the checks live in one place and not per consumer.
    """
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "Agents on Depictio: one tool registry, every consumer",
        "MCP clients and the in-app orchestrator call the same tools through the same checks",
    )

    # -- row 1: the external path --------------------------------------------
    agents = Box(
        40, 128, 230, 112, WHITE, "External agents", ("Claude Code, Claude Desktop,", "Agent SDK")
    )
    proxy = Box(
        330,
        118,
        270,
        122,
        BLUE,
        "`depictio mcp serve`",
        ("stdio proxy", "mints a local token", "with scopes"),
    )
    http = Box(
        660,
        118,
        320,
        122,
        BLUE,
        "`/depictio/api/v1/mcp`",
        ("streamable HTTP", "`Authorization: Bearer`"),
    )
    auth = Box(
        1040, 118, 320, 122, YELLOW, "auth", ("token -> user + scopes", "no anonymous fallback")
    )
    s.stack(agents, n=3)
    s.box(proxy)
    s.box(http)
    s.box(auth)
    s.arrow(agents.right + 4, 190, proxy.x, 190)
    s.text((agents.right + proxy.x) / 2 + 4, 212, "stdio", size=13, colour=DIM)
    s.arrow(proxy.right, 179, http.x, 179)
    s.text((proxy.right + http.x) / 2, 169, "HTTP", size=13, colour=DIM)
    s.arrow(http.right, 179, auth.x, 179)

    # -- row 2: the registry and its second consumer -------------------------
    reg = Box(330, 318, 1030, 150, VIOLET, "", ())
    s.rect(reg)
    s.text(reg.cx, reg.y + 30, "one shared tool registry", size=20, weight="bold")
    chain = [
        ("scope check", PINK),
        ("rate limit", WHITE),
        ("input validation", WHITE),
        ("output budget", WHITE),
        ("untrusted wrapping", ORANGE),
        ("audit row", GREEN),
    ]
    widths = [max(52.0, 8.2 * len(label) + 24) for label, _ in chain]
    gap = 34
    x = reg.cx - (sum(widths) + gap * (len(chain) - 1)) / 2
    cy = reg.y + 78
    for (label, fill), w in zip(chain, widths):
        s.chip(x + w / 2, cy, label, fill=fill, w=w)
        if x + w + gap < reg.right - 40:
            s.arrow(x + w + 5, cy, x + w + gap - 5, cy, colour=DIM)
        x += w + gap
    s.text(
        reg.cx,
        reg.y + 128,
        "`invoke()` runs the same chain for every tool and every consumer",
        size=14,
        colour=DIM,
    )

    s.arrow(auth.cx, auth.bottom, auth.cx, reg.y)
    s.text(auth.cx + 12, 290, "`ToolContext`", size=14, colour=DIM, anchor="start")

    orch = Box(
        40,
        318,
        230,
        150,
        WHITE,
        "in-app orchestrator",
        ("agent teams, litellm", "tool-calling", "next PR"),
    )
    s.box(orch, colour=DIM, dashed=True)
    s.arrow(orch.right + 4, reg.cy, reg.x, reg.cy, dashed=True, colour=DIM)

    # -- row 3: the services behind the tools --------------------------------
    services = [
        ("component data", BLUE, ("Polars + filters",)),
        ("sandboxed query", BLUE, ("Polars, timeout",)),
        ("ingestion", BLUE, ("project from a run",)),
        ("dashboards", GREEN, ("components, YAML",)),
        ("dashboard drafts", GREEN, ("never published",)),
        ("comments", GREEN, ("annotations,", "questions")),
        ("reports", GREEN, ("findings + evidence",)),
    ]
    sw, sgap, sy = 175, 16, 548
    bus_y = 510
    boxes = []
    for i, (title, fill, lines) in enumerate(services):
        b = Box(40 + i * (sw + sgap), sy, sw, 100, fill, title, lines)
        s.box(b)
        boxes.append(b)
    s.line(reg.cx, reg.bottom, reg.cx, bus_y, colour=DIM)
    s.line(boxes[0].cx, bus_y, boxes[-1].cx, bus_y, colour=DIM)
    for b in boxes:
        s.arrow(b.cx, bus_y, b.cx, b.y - 2, colour=DIM)

    # -- row 4: the stores ---------------------------------------------------
    delta = (70, 700, 420, 92)
    mongo = (640, 700, 720, 92)
    s.cylinder(*delta, fill=BLUE)
    s.cylinder(*mongo, fill=GREEN)
    s.text(delta[0] + delta[2] / 2, 748, "Delta / S3", size=18, weight="bold")
    s.text(delta[0] + delta[2] / 2, 770, "data collections", size=14, colour=DIM)
    s.text(mongo[0] + mongo[2] / 2, 748, "MongoDB", size=18, weight="bold")
    s.text(
        mongo[0] + mongo[2] / 2,
        770,
        "dashboards, drafts, threads, reports, `agent_tool_calls` audit",
        size=14,
        colour=DIM,
    )
    for b in boxes[:2]:
        s.arrow(b.cx, b.bottom, b.cx, 712, colour=GREY)
    s.arrow(boxes[2].cx - 20, boxes[2].bottom, 440, 712, colour=GREY)
    s.arrow(boxes[2].cx + 20, boxes[2].bottom, 680, 712, colour=GREY)
    for b in boxes[3:]:
        s.arrow(b.cx, b.bottom, b.cx, 712, colour=GREY)

    s.text(40, 492, "dashed = next PR", size=13, colour=DIM, anchor="start")
    return s


# --------------------------------------------------------------------------
# 2. Token scopes.
# --------------------------------------------------------------------------


def build_scopes() -> Sketch:
    """What a scope unlocks, and what a scoped token can never do."""
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "Scoped tokens: least privilege for agents",
        "legacy tokens keep full access; a scoped token gets only what its scopes map to",
    )

    token = Box(40, 310, 260, 80, WHITE, "API token", ("`scopes: list | None`",))
    legacy = Box(
        40,
        128,
        260,
        122,
        GREEN,
        "`scopes = None`",
        ("legacy tokens, sessions,", "CLI: full access,", "nothing to migrate"),
    )
    s.box(token)
    s.box(legacy)
    s.arrow(token.cx, token.y, legacy.cx, legacy.bottom)
    s.text(token.cx + 10, 285, "`None`", size=14, colour=DIM, anchor="start")

    # -- the scope table ------------------------------------------------------
    tx, tw = 370, 990
    col_tools, col_rest = 560, 1010
    top, row_h = 150, 82
    s.text(tx + 90, top - 14, "scope", size=16, weight="bold")
    s.text(col_tools + 10, top - 14, "MCP tools", size=16, weight="bold", anchor="start")
    s.text(col_rest + 10, top - 14, "REST writes", size=16, weight="bold", anchor="start")
    rows = [
        (
            "read",
            BLUE,
            ("`get_dashboard`, `get_component`,", "`get_component_data`, `query_data`, ..."),
            ("every GET, plus read-only POSTs", "like `render_*`, `bulk_compute_cards`"),
        ),
        (
            "annotate",
            YELLOW,
            ("`create_annotation`, `reply`,", "`ask_question`"),
            ("comments and threads,", "forced to agent authorship"),
        ),
        ("report", GREEN, ("`create_report`, `update_report`",), ("analysis reports",)),
        (
            "edit_dashboard",
            VIOLET,
            ("`propose_component`, `suggest_components`,", "`generate_dashboard` (drafts)"),
            ("dashboard drafts",),
        ),
        (
            "ingest",
            ORANGE,
            ("`list_templates`, `preview_run`,", "`create_project_from_run`"),
            ("project from a run,", "also needs `enable_ingest`"),
        ),
    ]
    for i, (scope, fill, tools, rest) in enumerate(rows):
        y = top + i * row_h
        s.rect(Box(tx, y, tw, row_h - 8, WHITE, ""), colour=GREY)
        mid = y + (row_h - 8) / 2
        s.chip(tx + 90, mid, f"`{scope}`", fill=fill, w=150, h=32, size=15)
        for j, line in enumerate(tools):
            s.text(
                col_tools + 10,
                mid + 5 + (j - (len(tools) - 1) / 2) * 22,
                line,
                size=14,
                anchor="start",
            )
        for j, line in enumerate(rest):
            s.text(
                col_rest + 10,
                mid + 5 + (j - (len(rest) - 1) / 2) * 22,
                line,
                size=14,
                colour=DIM,
                anchor="start",
            )
    s.arrow(token.right, token.cy, tx - 4, token.cy)
    s.text((token.right + tx) / 2, token.cy - 12, "explicit", size=13, colour=DIM)
    s.text(
        tx, top + 5 * row_h + 14, "any scope implies `read`", size=14, colour=DIM, anchor="start"
    )

    # -- the rules for scoped tokens -------------------------------------------
    ry, rh = 640, 120
    get = Box(40, ry, 300, rh, BLUE, "GET", ("needs `read`, as do", "read-only POSTs"))
    refused = Box(
        380,
        ry,
        330,
        rh,
        PINK,
        "unmapped write",
        ("refused: fail-closed,", "incl. token minting", "and thread review"),
    )
    proposed = Box(
        750,
        ry,
        290,
        rh,
        YELLOW,
        "agent writes",
        ("land as `proposed`,", "comments authored", "as the agent"),
    )
    human = Box(
        1080, ry, 280, rh, GREEN, "human", ("reviews and publishes;", "an agent never does")
    )
    s.text(40, ry - 18, "rules for a scoped token", size=17, weight="bold", anchor="start")
    s.box(get)
    s.box(refused)
    s.box(proposed)
    s.box(human)
    s.cross(refused.right - 30, refused.y + 26, size=9, colour=RED)
    s.arrow(proposed.right, proposed.cy, human.x, human.cy)
    s.tick(human.right - 30, human.y + 24)
    return s


# --------------------------------------------------------------------------
# 3. The agent team pipeline.
# --------------------------------------------------------------------------


def build_team() -> Sketch:
    """One question, a routed team, and only confirmed findings reach the UI."""
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "Agent team run: route, analyse, challenge, then propose",
        "every write is a proposal; a human reviews it in the comments drawer",
    )

    # -- row 1: input, router, analysts, skeptic -----------------------------
    s.document(40, 250, 190, 112, fill=WHITE)
    s.text(135, 290, "question", size=18, weight="bold")
    s.text(135, 314, "+ dashboard", size=15, colour=DIM)

    router = Box(
        270,
        222,
        260,
        160,
        VIOLET,
        "router",
        (
            "rules: template id,",
            "catalog modules, columns,",
            "component types, keywords",
            "LLM fallback if no match",
        ),
    )
    s.box(router)
    s.arrow(230, 306, router.x, 306)

    topics = ("QC / MultiQC", "differential expression", "microbiome", "variants")
    analysts = []
    for i, topic in enumerate(topics):
        b = Box(590, 128 + i * 88, 250, 74, BLUE, "analyst", (topic,))
        s.box(b)
        analysts.append(b)
        s.arrow(router.right, router.cy, b.x - 2, b.cy, colour=DIM)
    s.text(715, 120 - 6, "in parallel, one per topic", size=14, colour=DIM)
    s.text(715, 484, "tools: `get_component_data`, `query_data`", size=14, colour=DIM)

    skeptic = Box(900, 170, 200, 250, PINK, "skeptic", ())
    s.box(skeptic)
    for i, (label, fill) in enumerate(
        (("confirmed", GREEN), ("weakened", YELLOW), ("refuted", WHITE), ("unverified", GREY))
    ):
        s.chip(skeptic.cx, 232 + i * 46, label, fill=fill, w=130)
    s.cross(skeptic.cx + 76, 324, size=8)
    for b in analysts:
        s.arrow(
            b.right + 2, b.cy, skeptic.x - 2, skeptic.cy + (b.cy - skeptic.cy) * 0.5, colour=DIM
        )

    team = Box(1150, 150, 220, 250, YELLOW, "team = role x topic", ())
    s.box(team)
    for i, line in enumerate(
        (
            "roles: analyst, skeptic,",
            "annotator, questioner,",
            "reporter",
            "",
            "topics from YAML",
            "profiles, named",
            "`role/topic@version`",
        )
    ):
        s.text(team.cx, team.y + 60 + i * 24, line, size=14, colour=DIM)

    # -- row 2: the actors ---------------------------------------------------
    ay = 550
    annot = Box(690, ay, 210, 88, GREEN, "annotator", ("`create_annotation`",))
    quest = Box(920, ay, 210, 88, GREEN, "questioner", ("`ask_question`",))
    rep = Box(1150, ay, 210, 88, GREEN, "reporter", ("`create_report`",))
    for b in (annot, quest, rep):
        s.box(b)
    s.arrow(skeptic.cx - 30, skeptic.bottom, annot.cx, annot.y - 2)
    s.arrow(skeptic.cx, skeptic.bottom, quest.cx, quest.y - 2)
    s.arrow(skeptic.cx + 30, skeptic.bottom, rep.cx - 20, rep.y - 2, colour=DIM)
    s.text(800, 510, "confirmed", size=14, weight="bold")
    s.text(800, 530, "findings only", size=14, weight="bold")
    s.text(1030, 492, "weakened", size=14, weight="bold", anchor="start")
    s.text(1030, 512, "only", size=14, weight="bold", anchor="start")
    s.text(1150, 470, "all verdicts", size=14, colour=DIM, anchor="start")

    # -- row 3: outputs and the human ----------------------------------------
    band = Box(690, 676, 670, 120, WHITE, "", ())
    s.rect(band, colour=GREY)
    s.chip(annot.cx, 708, "proposed annotations", fill=YELLOW, w=200)
    s.chip(quest.cx, 708, "proposed questions", fill=YELLOW, w=200)
    s.chip(rep.cx, 708, "report + evidence", fill=GREEN, w=200)
    s.chip(rep.cx, 758, "optional draft", fill=WHITE, w=200, colour=DIM)
    s.text((annot.cx + quest.cx) / 2, 763, "on components, status `proposed`", size=14, colour=DIM)
    for b in (annot, quest, rep):
        s.arrow(b.cx, b.bottom, b.cx, 693, colour=DIM)

    review = Box(
        270,
        686,
        350,
        100,
        GREEN,
        "human review",
        ("comments drawer: accept, reject,", "publish; never an agent"),
    )
    s.box(review)
    s.arrow(band.x - 2, review.cy, review.right + 2, review.cy)

    # -- the budget ledger --------------------------------------------------
    s.text(40, 546, "`BudgetLedger`: one pool, one share per phase", size=15, anchor="start")
    s.gauge(40, 588, 580, 18, 0.62, fill=ORANGE)
    start = 0.0
    for share, label in (
        (0.45, "analysts"),
        (0.25, "skeptic"),
        (0.15, "writers"),
        (0.15, "reporter"),
    ):
        mid = 40 + 580 * (start + share / 2)
        s.text(mid, 632, label, size=13, colour=DIM)
        s.text(mid, 650, f"{share:.0%}", size=13, colour=DIM)
        start += share
        if start < 1:
            s.line(40 + 580 * start, 580, 40 + 580 * start, 614, colour=RED, amount=0.6)
    s.text(
        40,
        570,
        "a phase may not eat the next one's share; unused share rolls forward",
        size=12,
        colour=DIM,
        anchor="start",
    )
    return s


# --------------------------------------------------------------------------
# 4. The evidence flow.
# --------------------------------------------------------------------------


def build_evidence() -> Sketch:
    """A finding reaches a component only through calls that actually ran."""
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "Evidence: findings cite calls, the server copies the values",
        "the model never writes evidence itself; it can only point at tool calls that succeeded",
    )

    calls = Box(40, 120, 420, 250, WHITE, "tool calls in this run", ())
    s.box(calls)
    rows = [
        ("`c1  query_data`", "ok", True),
        ("`c2  get_component_data`", "ok", True),
        ("`c3  query_data`", "error", False),
        ("`c4  get_dashboard`", "not evidence", False),
    ]
    for i, (label, status, good) in enumerate(rows):
        y = 185 + i * 50
        s.text(64, y, label, size=16, anchor="start")
        s.text(400, y, status, size=14, colour=DIM, anchor="end")
        if good:
            s.tick(426, y - 6)
        else:
            s.cross(426, y - 6, size=7)

    f1 = Box(40, 450, 420, 100, VIOLET, "finding f1", ("claim + `cites: c1, c2`",))
    f2 = Box(40, 580, 420, 100, PINK, "finding f2", ("claim + `cites: c3, c4`",))
    s.box(f1)
    s.box(f2)

    s.diamond(620, 560, 200, 150, fill=YELLOW)
    s.text(620, 556, "validate", size=18, weight="bold")
    s.text(620, 578, "cited ids", size=14, colour=DIM)
    s.arrow(f1.right, f1.cy, 540, 540)
    s.arrow(f2.right, f2.cy, 540, 580)
    s.curve([(calls.right, 255), (620, 255)], colour=DIM)
    s.arrow(620, 255, 620, 487, colour=DIM)
    s.text(630, 460, "look up", size=13, colour=DIM, anchor="start")

    s.arrow(620, 635, 620, 720, colour=RED)
    s.cross(620, 750, size=10)
    s.text(650, 756, "f2 dropped: no successful evidence call", size=14, colour=DIM, anchor="start")

    ev = Box(
        780,
        470,
        270,
        140,
        GREEN,
        "Evidence",
        ("built by the server:", "query + values copied", "from c1 and c2"),
    )
    s.box(ev)
    s.arrow(720, 560, ev.x - 2, ev.cy)
    s.text(742, 530, "f1 ok", size=13, colour=DIM)

    ann = Box(
        1100,
        470,
        270,
        140,
        YELLOW,
        "annotation",
        ("`finding_id: f1`", "`dedupe_key`", "status `proposed`"),
    )
    s.box(ann)
    s.arrow(ev.right, ev.cy, ann.x - 2, ann.cy)

    rerun = Box(
        1100,
        170,
        270,
        130,
        BLUE,
        "re-run",
        ("same `dedupe_key`:", "updates its own proposal,", "no duplicate thread"),
    )
    s.box(rerun, dashed=True, colour=DIM)
    s.arrow(rerun.cx, rerun.bottom, rerun.cx, ann.y - 2, dashed=True, colour=DIM)

    caps = Box(690, 120, 380, 200, WHITE, "caps per run", ())
    s.box(caps)
    s.text(712, 195, "threads", size=15, anchor="start")
    s.gauge(800, 182, 190, 18, 0.7, fill=YELLOW)
    s.text(1045, 197, "50", size=15, weight="bold", anchor="end")
    s.text(712, 255, "reports", size=15, anchor="start")
    s.gauge(800, 242, 190, 18, 0.4, fill=GREEN)
    s.text(1045, 257, "20", size=15, weight="bold", anchor="end")
    s.text(caps.cx, 300, "`run_id` derived when absent, so caps always apply", size=13, colour=DIM)

    review = Box(
        1100, 670, 270, 110, GREEN, "human review", ("comments drawer:", "accept or reject")
    )
    s.box(review)
    s.arrow(ann.cx, ann.bottom, ann.cx, review.y - 2)
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v1.4/agents/schema"),
        "--out",
        help="Output prefix; '_<name>.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the four agents + MCP schemas under --out."""
    write(build_architecture(), out, "mcp_architecture", png=png)
    write(build_scopes(), out, "token_scopes", png=png)
    write(build_team(), out, "agent_team_pipeline", png=png)
    write(build_evidence(), out, "evidence_flow", png=png)


if __name__ == "__main__":
    app()
