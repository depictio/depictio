"""Annotated PR screenshots for the agents + MCP feature.

Captures the comments drawer with agent-authored annotations, a close-up of
one agent thread card, and the ``/cli-agents`` scoped-token UI, then draws
numbered callouts over each page (injected DOM overlay, not app UI).

The demo content (agent annotations, a question, one accepted and published
annotation) must already exist on the target instance; seed it through
``depictio mcp serve`` first.

Usage::

    python dev/screenshots/agents_mcp_pr_shots.py \\
        --base-url http://127.0.0.1:8158 \\
        --dashboard-id 6824cb3b89d2b72169309737 \\
        --chart-title "Sepal vs Petal Length" \\
        --accepted-thread 6abae497b26ea06b806b5ec4 \\
        --proposed-thread 6abae497b26ea06b806b5ec6 \\
        --out-dir docs/images/v1.4/agents

Needs Python Playwright with Chromium, and ImageMagick (``magick``) unless
``--no-compress`` is given.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

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
    const r = it.rect;
    if (r) add({left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px',
      border: '2.5px solid ' + ink, borderRadius: '8px'});
    if (it.label) { const l = labelBox({left: it.label.x + 'px', top: it.label.y + 'px',
      [it.label.fixed ? 'width' : 'maxWidth']: (it.label.w || 260) + 'px'});
      l.textContent = it.label.text; }
    if (it.line) { const {x1, y1, x2, y2} = it.line; const len = Math.hypot(x2 - x1, y2 - y1);
      add({left: x1 + 'px', top: y1 + 'px', width: len + 'px', height: '0',
        borderTop: '2px solid ' + ink, transformOrigin: '0 0',
        transform: `rotate(${Math.atan2(y2 - y1, x2 - x1)}rad)`}); }
    if (it.panel) add({left: it.panel.x + 'px', top: it.panel.y + 'px', width: it.panel.w + 'px',
      height: it.panel.h + 'px', background: '#f8fafc'});
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


def box(loc: Locator, pad: float = 4) -> dict[str, float]:
    b = loc.bounding_box()
    if b is None:
        raise RuntimeError(f"not visible: {loc}")
    return {
        "x": b["x"] - pad,
        "y": b["y"] - pad,
        "w": b["width"] + 2 * pad,
        "h": b["height"] + 2 * pad,
    }


def union(*rects: dict[str, float]) -> dict[str, float]:
    x0 = min(r["x"] for r in rects)
    y0 = min(r["y"] for r in rects)
    x1 = max(r["x"] + r["w"] for r in rects)
    y1 = max(r["y"] + r["h"] for r in rects)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def corner(r: dict[str, float], dx: float = -13, dy: float = -13) -> dict[str, float]:
    return {"x": r["x"] + dx, "y": r["y"] + dy}


def overlay(page: Page, items: list[dict], legend: dict | None = None) -> None:
    page.evaluate(OVERLAY_JS, {"items": items, "legend": legend})
    page.wait_for_timeout(200)


def skip_tour(page: Page) -> None:
    try:
        page.get_by_role("button", name="Skip tour").click(timeout=2500)
        page.wait_for_timeout(400)
    except Exception:
        pass


def plot_shapes(page: Page, chart: Locator) -> tuple[dict[str, float], dict[str, float]]:
    """Bounding boxes of the reference line and the range band drawn on a Plotly chart."""
    rects = chart.evaluate(
        """el => [...el.querySelectorAll('.shapelayer path')].map(p => {
             const r = p.getBoundingClientRect();
             return {x: r.x, y: r.y, w: r.width, h: r.height};
           })"""
    )
    rects = [r for r in rects if r["w"] > 0]
    line = min((r for r in rects if r["w"] > 200), key=lambda r: r["h"])
    band = max((r for r in rects if r["w"] < 300), key=lambda r: r["h"])
    return line, band


def open_dashboard(page: Page, base: str, dashboard_id: str) -> None:
    page.goto(f"{base}/dashboard/{dashboard_id}")
    page.wait_for_timeout(6000)
    skip_tour(page)
    # Collapse the filter panel so the chart gets the room left of the drawer.
    page.get_by_text("Filters", exact=True).locator("xpath=..").locator("button").first.click()
    page.wait_for_timeout(600)
    page.get_by_role("button", name="Comments").first.click()
    page.wait_for_timeout(2000)


def shot_drawer_annotations(page: Page, args: argparse.Namespace, out: Path) -> None:
    open_dashboard(page, args.base_url, args.dashboard_id)
    drawer = page.get_by_test_id("comments-drawer")
    drawer.get_by_role("tab", name="Annotations").click()
    page.wait_for_timeout(800)
    accepted = drawer.locator(f'[data-thread-id="{args.accepted_thread}"]')
    proposed = drawer.locator(f'[data-thread-id="{args.proposed_thread}"]')
    accepted.get_by_text("Show on dashboard").click()
    page.wait_for_timeout(2500)
    page.mouse.move(5, 995)

    chart = page.locator(".react-grid-item", has_text=args.chart_title).first
    line, band = plot_shapes(page, chart)
    # The line runs on under the drawer: stop the outline at the drawer edge.
    edge = drawer.locator(".mantine-Drawer-content").bounding_box()["x"] - 6
    line = {
        "x": line["x"],
        "y": line["y"] - 7,
        "w": min(line["w"], edge - line["x"]),
        "h": line["h"] + 14,
    }
    band = {"x": band["x"] - 4, "y": band["y"] - 4, "w": band["w"] + 8, "h": band["h"] + 8}
    acc = box(accepted, 3)
    author = box(proposed.get_by_text("Agent on behalf of").locator("xpath=../.."), 3)
    evidence = box(proposed.get_by_text("Evidence", exact=True).locator("xpath=.."), 3)
    review = box(proposed.get_by_role("button", name="Accept").locator("xpath=../.."), 3)
    items = [
        {"n": 1, "rect": line, "badge": {"x": line["x"] - 30, "y": line["y"] - 4}},
        {"n": 2, "rect": band, "badge": corner(band, band["w"] - 13, band["h"] - 13)},
        {"n": 3, "rect": acc, "badge": {"x": acc["x"] - 30, "y": acc["y"] + 8}},
        {"n": 4, "rect": author, "badge": {"x": author["x"] - 30, "y": author["y"] + 4}},
        {"n": 5, "rect": evidence, "badge": {"x": evidence["x"] - 30, "y": evidence["y"] + 2}},
        {"n": 6, "rect": review, "badge": {"x": review["x"] - 30, "y": review["y"] + 2}},
    ]
    legend = {
        "x": args.legend_x,
        "y": args.legend_y,
        "w": 470,
        "entries": [
            (1, "Accepted agent annotation, published on the chart"),
            (2, "Proposed range from the same agent run"),
            (3, "Accepted by a human, then made visible to viewers"),
            (4, "Agent name, acting on behalf of the user"),
            (5, "Evidence backed by a query_data call"),
            (6, "Human review: Accept or Reject"),
        ],
    }
    overlay(page, items, legend)
    page.screenshot(path=str(out))


def shot_drawer_comments(page: Page, args: argparse.Namespace, out: Path) -> None:
    open_dashboard(page, args.base_url, args.dashboard_id)
    drawer = page.get_by_test_id("comments-drawer")
    drawer.get_by_role("tab", name="Comments").click()
    page.wait_for_timeout(800)
    cards = drawer.locator("[data-thread-id]")
    cards.first.get_by_text("Show on dashboard").click()
    page.wait_for_timeout(2500)
    page.mouse.move(5, 995)
    question = drawer.locator("[data-thread-id]", has_text=args.question_text).first
    comment = drawer.locator("[data-thread-id]", has_text="Evidence").first
    chips = box(drawer.get_by_text("Show", exact=True).locator("xpath=.."), 3)
    header = box(page.get_by_role("button", name="Comments").first, 3)
    q = box(question, 3)
    ev = box(comment.get_by_text("Evidence", exact=True).locator("xpath=.."), 3)
    items = [
        {"n": 1, "rect": header, "badge": {"x": header["x"] - 30, "y": header["y"] + 3}},
        {"n": 2, "rect": chips, "badge": {"x": chips["x"] - 30, "y": chips["y"] + 2}},
        {"n": 3, "rect": ev, "badge": {"x": ev["x"] - 30, "y": ev["y"] + 2}},
        {"n": 4, "rect": q, "badge": {"x": q["x"] - 30, "y": q["y"] + 8}},
    ]
    legend = {
        "x": args.legend_x,
        "y": args.comments_legend_y,
        "w": 470,
        "entries": [
            (1, "Open threads on the tab; hover for proposals awaiting review"),
            (2, "Filter threads by status, Proposed included"),
            (3, "Agent comment with its evidence"),
            (4, "Agent question for the team, reviewed like a proposal"),
        ],
    }
    overlay(page, items, legend)
    page.screenshot(path=str(out))


def shot_thread_card(page: Page, args: argparse.Namespace, out: Path) -> None:
    open_dashboard(page, args.base_url, args.dashboard_id)
    drawer = page.get_by_test_id("comments-drawer")
    drawer.get_by_role("tab", name="Annotations").click()
    page.wait_for_timeout(800)
    card = drawer.locator(f'[data-thread-id="{args.proposed_thread}"]')
    card.scroll_into_view_if_needed()
    page.wait_for_timeout(600)
    page.mouse.move(5, 995)
    c = box(card, 0)
    left = c["x"] - 360
    # A blank panel left of the card holds the labels.
    items: list[dict] = [
        {"n": 0, "panel": {"x": left - 20, "y": 0, "w": c["x"] - left + 4, "h": 2000}}
    ]
    targets = [
        (
            1,
            card.locator("xpath=.//*[contains(text(),'x from')]/ancestor::div[1]/.."),
            "Shape proposed by the agent",
        ),
        (
            2,
            card.get_by_text("Agent on behalf of").locator("xpath=../.."),
            "Agent name, on behalf of the user",
        ),
        (
            3,
            card.get_by_text("Evidence", exact=True).locator("xpath=.."),
            "Evidence from a query_data call",
        ),
        (
            4,
            card.get_by_role("button", name="Accept").locator("xpath=../.."),
            "Accept or Reject before it counts",
        ),
    ]
    for n, loc, text in targets:
        r = box(loc, 3)
        if n == 1:
            # Take in the numbered pill left of the annotation title.
            r = {**r, "x": c["x"] + 8, "w": r["x"] + r["w"] - c["x"] - 8}
        cy = r["y"] + r["h"] / 2
        items.append(
            {
                "n": n,
                "rect": r,
                "badge": {"x": left + 290, "y": cy - 13},
                "label": {"text": text, "x": left, "y": cy - 16, "w": 280, "fixed": True},
                "line": {"x1": left + 280, "y1": cy, "x2": r["x"], "y2": cy},
            }
        )
    overlay(page, items)
    clip = {
        "x": left - 20,
        "y": c["y"] - 14,
        "width": c["x"] + c["w"] - left + 40,
        "height": c["h"] + 24,
    }
    page.screenshot(path=str(out), clip=clip)


def shot_token_modal(page: Page, args: argparse.Namespace, out: Path) -> None:
    page.goto(f"{args.base_url}/cli-agents")
    page.wait_for_timeout(4000)
    skip_tour(page)
    page.get_by_role("button", name="Add New Configuration").click()
    page.wait_for_timeout(800)
    page.get_by_test_id("cli-config-name-input").fill("claude-code-agent")
    page.get_by_test_id("cli-config-access-mode").get_by_text("Agent (MCP)").click()
    page.wait_for_timeout(600)
    seg = box(page.get_by_test_id("cli-config-access-mode"), 4)
    scopes = box(page.get_by_test_id("cli-config-scopes"), 6)
    modal = page.locator(".mantine-Modal-content").first
    m = box(modal, 0)
    lx = m["x"] + m["w"] + 24
    items = [
        {
            "n": 1,
            "rect": seg,
            "badge": {"x": seg["x"] - 32, "y": seg["y"] + 3},
            "label": {"text": "Agent (MCP) preset", "x": lx, "y": seg["y"] + 2, "w": 260},
        },
        {
            "n": 2,
            "rect": scopes,
            "badge": {"x": scopes["x"] - 32, "y": scopes["y"] + 3},
            "label": {
                "text": "Read, annotate and report: no edits, no ingestion, no token or user admin",
                "x": lx,
                "y": scopes["y"] + 2,
                "w": 260,
            },
        },
    ]
    overlay(page, items)
    page.screenshot(path=str(out))
    page.keyboard.press("Escape")


def shot_token_list(page: Page, args: argparse.Namespace, out: Path) -> None:
    page.goto(f"{args.base_url}/cli-agents")
    page.wait_for_timeout(4000)
    skip_tour(page)
    page.mouse.move(5, 895)
    # The badge group of each token: an unscoped one and a scoped one.
    full = page.get_by_text("Full access", exact=True).first.locator("xpath=../..")
    scoped = page.get_by_text("annotate", exact=True).first.locator("xpath=../..")
    items = []
    for n, loc, text in [
        (1, full, "Unscoped token: full account access"),
        (2, scoped, "Scoped agent token: its scopes as badges"),
    ]:
        r = box(loc, 4)
        items.append(
            {
                "n": n,
                "rect": r,
                "badge": {"x": r["x"] + r["w"] + 10, "y": r["y"] + r["h"] / 2 - 13},
                "label": {
                    "text": text,
                    "x": r["x"] + r["w"] + 44,
                    "y": r["y"] + r["h"] / 2 - 16,
                    "w": 320,
                },
            }
        )
    overlay(page, items)
    page.screenshot(path=str(out))


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
    "drawer_annotations": (shot_drawer_annotations, 1000),
    "drawer_comments": (shot_drawer_comments, 1000),
    "thread_card": (shot_thread_card, 1000),
    "token_modal": (shot_token_modal, 900),
    "token_list": (shot_token_list, 900),
}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base-url", default="http://127.0.0.1:8158")
    ap.add_argument("--dashboard-id", default="6824cb3b89d2b72169309737")
    ap.add_argument("--chart-title", default="Sepal vs Petal Length")
    ap.add_argument(
        "--accepted-thread", required=True, help="Accepted, published annotation thread id."
    )
    ap.add_argument("--proposed-thread", required=True, help="Proposed agent annotation thread id.")
    ap.add_argument(
        "--question-text", default="log scale", help="Text of the agent question thread."
    )
    ap.add_argument(
        "--legend-x", type=int, default=330, help="Left of the callout legend on drawer shots."
    )
    ap.add_argument(
        "--comments-legend-y", type=int, default=830, help="Legend top on the comments shot."
    )
    ap.add_argument(
        "--legend-y", type=int, default=790, help="Top of the callout legend on drawer shots."
    )
    ap.add_argument("--out-dir", type=Path, default=Path("docs/images/v1.4/agents"))
    ap.add_argument("--prefix", default="pr1_")
    ap.add_argument("--only", nargs="*", choices=sorted(SHOTS), help="Capture only these shots.")
    ap.add_argument("--scale", type=float, default=2.0, help="device_scale_factor")
    ap.add_argument("--no-compress", action="store_true")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_compress and shutil.which("magick") is None:
        raise SystemExit("ImageMagick `magick` not found; pass --no-compress")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name in args.only or SHOTS:
            fn, height = SHOTS[name]
            ctx = browser.new_context(
                viewport={"width": 1440, "height": height}, device_scale_factor=args.scale
            )
            page = ctx.new_page()
            out = args.out_dir / f"{args.prefix}{name}.png"
            fn(page, args, out)
            ctx.close()
            if not args.no_compress:
                compress(out)
            print(f"{out}  {out.stat().st_size // 1024} KB")
        browser.close()


if __name__ == "__main__":
    main()
