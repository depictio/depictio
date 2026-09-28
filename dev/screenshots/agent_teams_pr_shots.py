"""Annotated PR screenshots for agent teams.

Captures the Team mode of the AI panel, a run's trace, the comments drawer
filtered by that run, a proposed annotation drawn on its chart, the run's
report, and a ``?thread=`` deep link, then draws numbered callouts over each
page (injected DOM overlay, not app UI).

No agent run is started. The script replays a recorded run instead:

* ``POST /ai/agent-runs/route`` is answered with the team and routing of the
  recording's ``run_started`` event;
* ``POST /ai/agent-runs`` is answered with the recorded SSE transcript, so the
  trace renders the real run;
* everything else (threads, the stored run, its report) is the live instance.

The recorded run (``--run-id``) must exist on the target instance with its
threads and report. Nothing that mutates data is clicked.

Usage::

    python dev/screenshots/agent_teams_pr_shots.py \\
        --base-url http://127.0.0.1:8258 \\
        --dashboard-id 6824cb3b89d2b72169309738 \\
        --run-id a42b4f3754ae4b6c89c1f9f0bb4fc83a \\
        --sse path/to/team_run.sse \\
        --token-file path/to/token \\
        --out-dir docs/images/v1.4/agents

Needs Python Playwright with Chromium, and ImageMagick (``magick``) unless
``--no-compress`` is given.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from playwright.sync_api import BrowserContext, Locator, Page, Route, sync_playwright

# Overlay chrome: a neutral dark outline and white label boxes.
OVERLAY_JS = """
({items, legend}) => {
  document.getElementById('pr-overlay')?.remove();
  const root = document.createElement('div');
  root.id = 'pr-overlay';
  Object.assign(root.style, {position: 'fixed', inset: '0', zIndex: 2147483647,
    pointerEvents: 'none', fontFamily: 'Inter, -apple-system, Segoe UI, sans-serif'});
  const ink = '#1f2937';
  const add = (css) => { const d = document.createElement('div');
    Object.assign(d.style, {position: 'absolute', boxSizing: 'border-box'}, css);
    root.appendChild(d); return d; };
  const badge = (n, x, y) => { const b = add({left: x + 'px', top: y + 'px', width: '26px',
    height: '26px', borderRadius: '50%', background: ink, color: '#fff', fontSize: '14px',
    fontWeight: '700', display: 'flex', alignItems: 'center', justifyContent: 'center',
    border: '2px solid #fff', boxShadow: '0 1px 4px rgba(0,0,0,.35)'}); b.textContent = n; };
  const labelBox = (css) => add(Object.assign({background: '#fff', color: ink,
    border: '1.5px solid ' + ink, borderRadius: '8px', padding: '6px 10px', fontSize: '13px',
    fontWeight: '600', lineHeight: '1.35', boxShadow: '0 2px 8px rgba(0,0,0,.18)'}, css));
  for (const it of items) {
    if (it.panel) add({left: it.panel.x + 'px', top: it.panel.y + 'px', width: it.panel.w + 'px',
      height: it.panel.h + 'px', background: '#f8fafc'});
  }
  for (const it of items) {
    const r = it.rect;
    if (r) add({left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px',
      border: '2.5px solid ' + ink, borderRadius: '8px'});
    if (it.line) { const {x1, y1, x2, y2} = it.line; const len = Math.hypot(x2 - x1, y2 - y1);
      add({left: x1 + 'px', top: y1 + 'px', width: len + 'px', height: '0',
        borderTop: '2px solid ' + ink, transformOrigin: '0 0',
        transform: `rotate(${Math.atan2(y2 - y1, x2 - x1)}rad)`}); }
    if (it.label) { const l = labelBox({left: it.label.x + 'px', top: it.label.y + 'px',
      [it.label.fixed ? 'width' : 'maxWidth']: (it.label.w || 260) + 'px'});
      l.textContent = it.label.text; }
  }
  for (const it of items) if (it.badge) badge(it.n, it.badge.x, it.badge.y);
  if (legend) {
    const box = labelBox({left: legend.x + 'px', top: legend.y + 'px', width: legend.w + 'px',
      padding: '10px 14px', fontWeight: '500'});
    for (const [n, text] of legend.entries) {
      const row = document.createElement('div');
      Object.assign(row.style, {display: 'flex', alignItems: 'center', gap: '10px', margin: '5px 0'});
      const b = document.createElement('div');
      Object.assign(b.style, {width: '22px', height: '22px', flex: '0 0 22px', borderRadius: '50%',
        background: ink, color: '#fff', fontSize: '12px', fontWeight: '700', display: 'flex',
        alignItems: 'center', justifyContent: 'center'});
      b.textContent = n;
      const t = document.createElement('span'); t.textContent = text;
      row.append(b, t); box.appendChild(row);
    }
  }
  document.body.appendChild(root);
}
"""

Rect = dict[str, float]


def box(loc: Locator, pad: float = 4) -> Rect:
    b = loc.bounding_box()
    if b is None:
        raise RuntimeError(f"not visible: {loc}")
    return {
        "x": b["x"] - pad,
        "y": b["y"] - pad,
        "w": b["width"] + 2 * pad,
        "h": b["height"] + 2 * pad,
    }


def union(*rects: Rect) -> Rect:
    x0 = min(r["x"] for r in rects)
    y0 = min(r["y"] for r in rects)
    x1 = max(r["x"] + r["w"] for r in rects)
    y1 = max(r["y"] + r["h"] for r in rects)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def clip_of(r: Rect) -> dict[str, float]:
    return {"x": max(r["x"], 0), "y": max(r["y"], 0), "width": r["w"], "height": r["h"]}


def overlay(page: Page, items: list[dict], legend: dict | None = None) -> None:
    page.evaluate(OVERLAY_JS, {"items": items, "legend": legend})
    page.wait_for_timeout(200)


def side_labels(
    targets: list[tuple[int, Rect, str]],
    left: float,
    width: float = 250,
    no_line: tuple[int, ...] = (),
) -> list[dict]:
    """Numbered labels stacked in a column left of their targets, each with a
    leader line to the target's left edge. Labels never overlap: one pushed
    down by its predecessor gets a slanted leader."""
    items = []
    floor = -1e9
    for n, r, text in targets:
        cy = r["y"] + min(r["h"] / 2, 16)
        ly = max(cy - 16, floor)
        lines = 1 + len(text) // 30
        floor = ly + 14 + 19 * lines + 10
        label = {"text": text, "x": left, "y": ly, "w": width, "fixed": True}
        if n in no_line:
            # Targets side by side: a badge on the target and one on its label.
            items.append({"n": n, "rect": r, "badge": {"x": r["x"] - 10, "y": r["y"] - 14}})
            items.append({"n": n, "badge": {"x": left + width + 10, "y": ly + 3}, "label": label})
            continue
        items.append(
            {
                "n": n,
                "rect": r,
                "badge": {"x": left + width + 10, "y": ly + 3},
                "label": label,
                "line": {"x1": left + width + 36, "y1": ly + 16, "x2": r["x"], "y2": cy},
            }
        )
    return items


# --- session, recorded run, routes -----------------------------------------


def session_payload(base: str, token: str) -> dict:
    """The localStorage['local-store'] payload the viewer reads its token from."""
    req = urllib.request.Request(
        f"{base}/depictio/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req) as res:
        me = json.load(res)
    return {
        "logged_in": True,
        "email": me["email"],
        "user_id": me["id"],
        "access_token": token,
        "refresh_token": token,
        "expire_datetime": "2099-01-01 00:00:00",
        "refresh_expire_datetime": "2099-01-01 00:00:00",
        "token_type": "bearer",
    }


def recorded_route(sse: str) -> str:
    """The /ai/agent-runs/route answer rebuilt from the recording's run_started."""
    for block in sse.split("\n\n"):
        if block.startswith("event: run_started"):
            data = json.loads(block.split("data:", 1)[1])
            return json.dumps({"team": data["team"], "routing": data["routing"]})
    raise SystemExit("no run_started event in the SSE recording")


def install(ctx: BrowserContext, args: argparse.Namespace) -> None:
    ctx.add_init_script(
        f"localStorage.setItem('local-store', {json.dumps(json.dumps(args.session))});"
    )

    def handle(route: Route) -> None:
        req = route.request
        path = req.url.split("?")[0]
        if req.method == "POST" and path.endswith("/ai/agent-runs/route"):
            route.fulfill(status=200, content_type="application/json", body=args.route_body)
        elif req.method == "POST" and path.endswith("/ai/agent-runs"):
            # Replay, never start: a real run spends the LLM budget.
            route.fulfill(status=200, content_type="text/event-stream", body=args.sse)
        elif req.method == "POST" and "/ai/agent-runs/" in path:
            route.abort()  # cancel etc.: nothing to act on
        else:
            route.continue_()

    ctx.route("**/ai/agent-runs**", handle)


def skip_tour(page: Page) -> None:
    try:
        page.get_by_role("button", name="Skip tour").click(timeout=4000)
        page.wait_for_timeout(400)
    except Exception:
        pass


def open_dashboard(page: Page, args: argparse.Namespace, query: str = "") -> None:
    page.goto(f"{args.base_url}/dashboard/{args.dashboard_id}{query}")
    page.wait_for_timeout(6000)
    skip_tour(page)
    # Collapse the filter panel: the dashboard gets the room.
    page.get_by_text("Filters", exact=True).locator("xpath=..").locator("button").first.click()
    page.wait_for_timeout(600)


def team_mode(page: Page, args: argparse.Namespace) -> None:
    page.get_by_test_id("ai-prompt-mode").get_by_text("Team", exact=True).click()
    page.wait_for_timeout(400)
    page.get_by_label("Question for the agent team").fill(args.question)
    page.get_by_test_id("agent-team-panel").get_by_text("reporter · general").first.wait_for()
    page.wait_for_timeout(500)


def run_team(page: Page) -> None:
    page.get_by_role("button", name="Run team").click()
    page.get_by_test_id("agent-run-trace").get_by_text("Open report").wait_for()
    page.wait_for_timeout(800)


def ai_card(page: Page) -> Locator:
    return page.get_by_test_id("agent-team-panel").locator(
        "xpath=ancestor::div[contains(@class,'mantine-Paper-root')][1]"
    )


def open_drawer_on_run(page: Page, args: argparse.Namespace) -> Locator:
    page.get_by_role("button", name="Comments").first.click()
    page.wait_for_timeout(1500)
    drawer = page.get_by_test_id("comments-drawer")
    drawer.get_by_test_id("comments-run-filter").click()
    page.wait_for_timeout(400)
    # Runs of the same question on the same day share a label: pick by value.
    opt = page.locator(f'[role="option"][value="{args.run_id}"]')
    if not opt.count():
        raise SystemExit(f"run {args.run_id} is not among the drawer's run options")
    opt.first.click()
    page.wait_for_timeout(1500)
    names = drawer.locator("[data-thread-id]").all_inner_texts()
    if any("differential" in n for n in names):
        raise SystemExit("run filter picked another run")
    return drawer


def hover_away(page: Page) -> None:
    page.mouse.move(2, page.viewport_size["height"] - 2)
    page.wait_for_timeout(400)


# --- shots -------------------------------------------------------------------


def shot_team_mode(page: Page, args: argparse.Namespace, out: Path) -> None:
    open_dashboard(page, args)
    team_mode(page, args)
    hover_away(page)
    card = box(ai_card(page), 0)
    panel = page.get_by_test_id("agent-team-panel")
    seg = box(page.get_by_test_id("ai-prompt-mode"), 3)
    question = box(panel.get_by_label("Question for the agent team"), 3)
    routed = box(panel.get_by_text("routed by rules"), 3)
    team = box(panel.locator(".mantine-MultiSelect-input").first, 3)
    reasons = box(panel.get_by_text("no specialist topic matched").locator("xpath=../.."), 3)
    items = [
        {"n": 1, "rect": seg, "badge": {"x": seg["x"] - 13, "y": seg["y"] - 13}},
        {"n": 2, "rect": question, "badge": {"x": question["x"] - 13, "y": question["y"] - 13}},
        {
            "n": 3,
            "rect": routed,
            "badge": {"x": routed["x"] + routed["w"] + 6, "y": routed["y"] - 5},
        },
        {"n": 4, "rect": team, "badge": {"x": team["x"] - 13, "y": team["y"] + team["h"] - 13}},
        {
            "n": 5,
            "rect": reasons,
            "badge": {"x": reasons["x"] - 13, "y": reasons["y"] + reasons["h"] - 13},
        },
    ]
    top = card["y"] + card["h"] + 12
    legend = {
        "x": card["x"],
        "y": top,
        "w": 620,
        "entries": [
            (1, "Team mode of the AI panel (behind the agent-teams feature flag)"),
            (2, "One question for the whole team"),
            (3, "Routed by rules: no specialist topic matched, so the general pack"),
            (4, "The routed team, 5 roles; editable before the run"),
            (5, "Why each member is on the team"),
        ],
    }
    items.append(
        {"n": 0, "panel": {"x": card["x"] - 20, "y": top - 6, "w": card["w"] + 40, "h": 200}}
    )
    overlay(page, items, legend)
    lg = box(page.locator("#pr-overlay > div").last, 0)
    page.screenshot(
        path=str(out),
        clip=clip_of(
            {
                "x": card["x"] - 20,
                "y": card["y"] - 16,
                "w": card["w"] + 40,
                "h": lg["y"] + lg["h"] - card["y"] + 32,
            }
        ),
    )


def shot_trace(page: Page, args: argparse.Namespace, out: Path) -> None:
    open_dashboard(page, args)
    team_mode(page, args)
    run_team(page)
    trace = page.get_by_test_id("agent-run-trace")
    # Keep only the skeptic lane open: its verdict list names every finding.
    ctrls = trace.locator(".mantine-Accordion-control")
    for i in range(ctrls.count()):
        if "skeptic" not in ctrls.nth(i).inner_text():
            ctrls.nth(i).click()
            page.wait_for_timeout(250)
    page.wait_for_timeout(600)
    trace.scroll_into_view_if_needed()
    content = page.get_by_test_id("dashboard-content")
    top = box(trace, 0)["y"] - 50
    content.evaluate("(el, dy) => el.scrollBy(0, dy)", top - 80)
    page.wait_for_timeout(500)
    hover_away(page)

    t = box(trace, 0)
    status = trace.get_by_text(re.compile(r"^(complete|budget)$")).first
    tally = trace.get_by_text(re.compile(r"^\d+ (confirmed|weakened)$")).first
    heads = union(box(status, 3), box(tally, 3))
    budget = box(trace.get_by_label("Budget spent").locator("xpath=.."), 3)
    lanes = trace.locator(".mantine-Accordion-item")
    lane_rects = [
        box(lanes.nth(i).locator(".mantine-Accordion-control"), 0) for i in range(lanes.count())
    ]
    analyst_head = lane_rects[0]
    skeptic = lanes.filter(has_text="skeptic").first
    confirmed = box(skeptic.get_by_text("confirmed", exact=True).first, 3)
    verdicts = box(skeptic.locator(".mantine-Accordion-panel"), 2)
    rest = union(*lane_rects[2:])
    left = t["x"] - 300
    targets = [
        (1, heads, "Run status, routing, and the skeptic's verdicts"),
        (2, budget, "Budget meter: $ spent of the run cap, tool calls of the max"),
        (3, analyst_head, "One lane per agent: calls, findings, outcome (folded)"),
        (4, confirmed, "A finding the skeptic confirmed"),
        (5, verdicts, "The skeptic re-checks each finding and rules on it"),
        (6, rest, "Annotator, questioner, reporter lanes"),
    ]
    items = [{"n": 0, "panel": {"x": left - 20, "y": 0, "w": t["x"] - left + 8, "h": 4000}}]
    items += side_labels(targets, left, 250)
    overlay(page, items)
    y0 = t["y"] - 36  # takes in the run's question
    page.screenshot(
        path=str(out),
        clip=clip_of(
            {
                "x": left - 20,
                "y": y0,
                "w": t["x"] + t["w"] - left + 36,
                "h": min(t["y"] + t["h"] + 14, page.viewport_size["height"]) - y0,
            }
        ),
    )


def shot_drawer_run(page: Page, args: argparse.Namespace, out: Path) -> None:
    open_dashboard(page, args)
    drawer = open_drawer_on_run(page, args)
    hover_away(page)
    content = drawer.locator(".mantine-Drawer-content")
    d = box(content, 0)
    run = box(drawer.get_by_test_id("comments-run-filter"), 3)
    questions = box(drawer.get_by_test_id("comments-questions-filter").locator("xpath=.."), 2)
    accept = box(drawer.get_by_test_id("comments-accept-confirmed"), 3)
    card = drawer.locator("[data-thread-id]").first
    author = box(card.get_by_text("Agent on behalf of").locator("xpath=../.."), 3)
    evidence = box(card.get_by_text("Evidence", exact=True).locator("xpath=.."), 3)
    review = box(card.get_by_role("button", name="Accept").locator("xpath=../.."), 3)
    left = d["x"] - 300
    targets = [
        (1, run, "Threads of one agent-team run"),
        (2, questions, "Only the questions the agents asked"),
        (3, accept, "Accept every proposal the skeptic confirmed, in one go"),
        (4, author, "Which agent of the team wrote it, on whose behalf"),
        (5, evidence, "Evidence: the query_data calls behind the claim"),
        (6, review, "Still a proposal: a person accepts or rejects it"),
    ]
    items = [{"n": 0, "panel": {"x": left - 20, "y": 0, "w": d["x"] - left + 20, "h": 4000}}]
    items += side_labels(targets, left, 250, no_line=(1, 2, 3))
    overlay(page, items)
    page.screenshot(
        path=str(out),
        clip=clip_of(
            {
                "x": left - 20,
                "y": 0,
                "w": d["x"] + d["w"] - left + 20,
                "h": page.viewport_size["height"],
            }
        ),
    )


def shot_annotation_on_chart(page: Page, args: argparse.Namespace, out: Path) -> None:
    open_dashboard(page, args)
    drawer = open_drawer_on_run(page, args)
    drawer.get_by_role("tab", name="Annotations").click()
    page.wait_for_timeout(800)
    card = drawer.locator(f'[data-thread-id="{args.annotation_thread}"]')
    card.get_by_text("Show on dashboard").click()
    page.wait_for_timeout(3000)
    hover_away(page)
    chart = page.locator(".react-grid-item", has_text=args.chart_title).first
    c = box(chart, 0)
    items: list[dict] = []
    legend_entries = []
    missing = chart.get_by_text("points found")
    if missing.count():
        # Marked points the chart cannot place (ids on a column the figure
        # does not carry): the layer says so instead of drawing them.
        m = box(missing.first, 3)
        items.append(
            {"n": 1, "rect": m, "badge": {"x": m["x"] + m["w"] + 6, "y": m["y"] + m["h"] / 2 - 13}}
        )
        legend_entries.append(
            (1, "Marked points the chart could not place (ids not in the figure)")
        )
    else:
        marks = chart.evaluate(
            """el => [...el.querySelectorAll('.shapelayer path, .annotation')]
                 .map(p => { const r = p.getBoundingClientRect();
                             return {x: r.x, y: r.y, w: r.width, h: r.height}; })
                 .filter(r => r.w > 0 && r.h > 0)"""
        )
        if marks:
            m = union(*marks)
            m = {"x": m["x"] - 6, "y": m["y"] - 6, "w": m["w"] + 12, "h": m["h"] + 12}
            items.append({"n": 1, "rect": m, "badge": {"x": m["x"] - 13, "y": m["y"] - 13}})
            legend_entries.append((1, "Proposed annotation drawn on the chart"))
    k = box(card, 3)
    items.append({"n": 2, "rect": k, "badge": {"x": k["x"] - 30, "y": k["y"] + 8}})
    legend_entries.append((2, "Its thread: shape, agent, evidence, review buttons"))
    legend = {"x": c["x"] + 12, "y": c["y"] + c["h"] + 12, "w": 520, "entries": legend_entries}
    items.append(
        {"n": 0, "panel": {"x": c["x"] - 10, "y": c["y"] + c["h"] + 4, "w": 560, "h": 120}}
    )
    overlay(page, items, legend)
    d = box(drawer.locator(".mantine-Drawer-content"), 0)
    y0 = min(c["y"] - 10, k["y"] - 46)
    y1 = max(c["y"] + c["h"] + 100, k["y"] + k["h"] + 16)
    page.screenshot(
        path=str(out),
        clip=clip_of({"x": c["x"] - 20, "y": y0, "w": d["x"] + d["w"] - c["x"] + 20, "h": y1 - y0}),
    )


def shot_report(page: Page, args: argparse.Namespace, out: Path) -> None:
    open_dashboard(page, args)
    team_mode(page, args)
    run_team(page)
    page.get_by_test_id("agent-run-trace").get_by_role("button", name="Open report").click()
    modal = page.locator(".mantine-Modal-content").first
    modal.wait_for()
    page.wait_for_timeout(3000)
    hover_away(page)
    m = box(modal, 0)

    def verdict(text: str) -> Rect:
        return box(modal.get_by_text(text, exact=True).first.locator("xpath=.."), 2)

    author = box(modal.get_by_text("reporter/general", exact=False).first.locator("xpath=.."), 2)
    summary = box(modal.get_by_text("Confirmed findings", exact=True).first.locator("xpath=.."), 2)
    history = box(modal.get_by_text("Previous analyses").locator("xpath=../.."), 2)
    confirmed = verdict("confirmed")
    evidence = box(modal.get_by_text("confirmed", exact=True).nth(1).locator("xpath=../.."), 2)
    items: list[dict] = []
    for n, r in [(1, author), (2, summary), (3, confirmed), (4, evidence)]:
        items.append({"n": n, "rect": r, "badge": {"x": r["x"] - 13, "y": r["y"] - 15}})
    items.append(
        {"n": 5, "rect": history, "badge": {"x": history["x"] - 13, "y": history["y"] - 13}}
    )
    legend = {
        "x": history["x"] + 8,
        "y": history["y"] + history["h"] + 30,
        "w": history["w"] - 16,
        "entries": [
            (1, "Written by the team's reporter agent"),
            (2, "Narrative grouped by the skeptic's verdicts"),
            (3, "Finding the skeptic confirmed"),
            (4, "Each finding keeps its evidence and the component it concerns"),
            (5, "Team reports join the analysis history, tagged Agent"),
        ],
    }
    overlay(page, items, legend)
    page.screenshot(
        path=str(out),
        clip=clip_of({"x": m["x"] - 8, "y": m["y"] - 8, "w": m["w"] + 16, "h": m["h"] + 16}),
    )


def shot_thread_link(page: Page, args: argparse.Namespace, out: Path) -> None:
    page.goto(f"{args.base_url}/dashboard/{args.dashboard_id}?thread={args.question_thread}")
    page.wait_for_timeout(7000)
    skip_tour(page)
    page.wait_for_timeout(1500)
    hover_away(page)
    drawer = page.get_by_test_id("comments-drawer")
    d = box(drawer.locator(".mantine-Drawer-content"), 0)
    card = drawer.locator(f'[data-thread-id="{args.question_thread}"]')
    k = box(card, 3)
    left = d["x"] - 300
    comp = box(
        drawer.get_by_text("Where the species separate", exact=True).first.locator("xpath=../.."), 2
    )
    targets = [
        (1, comp, "The component the question is about"),
        (2, k, "?thread=<id> opens the drawer on the agent's question, focused"),
    ]
    items = [{"n": 0, "panel": {"x": left - 20, "y": 0, "w": d["x"] - left + 20, "h": 4000}}]
    items += side_labels(targets, left, 250)
    overlay(page, items)
    page.screenshot(
        path=str(out),
        clip=clip_of(
            {
                "x": left - 20,
                "y": 0,
                "w": d["x"] + d["w"] - left + 20,
                "h": page.viewport_size["height"],
            }
        ),
    )


def compress(path: Path) -> None:
    tmp = path.with_suffix(".tmp.png")
    subprocess.run(
        [
            "magick",
            str(path),
            "-strip",
            "-colors",
            "128",
            "-define",
            "png:compression-level=9",
            str(tmp),
        ],
        check=True,
    )
    tmp.replace(path)


SHOTS = {
    "team_mode": (shot_team_mode, 1000),
    "trace": (shot_trace, 1600),
    "drawer_run": (shot_drawer_run, 1000),
    "annotation_on_chart": (shot_annotation_on_chart, 1100),
    "report": (shot_report, 1000),
    "thread_link": (shot_thread_link, 1000),
}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base-url", default="http://127.0.0.1:8258")
    ap.add_argument("--dashboard-id", default="6824cb3b89d2b72169309738")
    ap.add_argument("--run-id", required=True, help="Finished agent-team run to show.")
    ap.add_argument("--sse", type=Path, required=True, help="SSE transcript of that run.")
    ap.add_argument("--token-file", type=Path, required=True, help="File holding a JWT.")
    ap.add_argument("--chart-title", default="Body Mass vs Flipper Length")
    ap.add_argument(
        "--annotation-thread", help="Run thread carrying an annotation (default: the first)."
    )
    ap.add_argument("--question-thread", help="Run question thread (default: the first).")
    ap.add_argument("--out-dir", type=Path, default=Path("docs/images/v1.4/agents"))
    ap.add_argument("--prefix", default="pr2_")
    ap.add_argument("--only", nargs="*", choices=sorted(SHOTS), help="Capture only these shots.")
    ap.add_argument("--scale", type=float, default=2.0, help="device_scale_factor")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--no-compress", action="store_true")
    args = ap.parse_args()

    token = args.token_file.read_text().strip()
    args.session = session_payload(args.base_url, token)
    args.sse = args.sse.read_text()
    args.route_body = recorded_route(args.sse)
    req = urllib.request.Request(
        f"{args.base_url}/depictio/api/v1/ai/agent-runs/{args.run_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as res:
        run = json.load(res)
    args.question = run["question"]
    threads = run.get("threads", [])
    if not args.question_thread:
        args.question_thread = next(t["thread_id"] for t in threads if t["kind"] == "question")
    if not args.annotation_thread:
        args.annotation_thread = _annotation_thread(args, token, threads)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_compress and shutil.which("magick") is None:
        raise SystemExit("ImageMagick `magick` not found; pass --no-compress")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name in args.only or SHOTS:
            fn, height = SHOTS[name]
            ctx = browser.new_context(
                viewport={"width": args.width, "height": height}, device_scale_factor=args.scale
            )
            install(ctx, args)
            page = ctx.new_page()
            out = args.out_dir / f"{args.prefix}{name}.png"
            fn(page, args, out)
            ctx.close()
            if not args.no_compress:
                compress(out)
            print(f"{out}  {out.stat().st_size // 1024} KB")
        browser.close()


def _annotation_thread(args: argparse.Namespace, token: str, threads: list[dict]) -> str:
    for t in threads:
        req = urllib.request.Request(
            f"{args.base_url}/depictio/api/v1/comments/threads/{t['thread_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as res:
            if json.load(res).get("annotation"):
                return t["thread_id"]
    raise SystemExit("the run wrote no annotation thread")


if __name__ == "__main__":
    main()
