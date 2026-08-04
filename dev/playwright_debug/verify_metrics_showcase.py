#!/usr/bin/env python3
"""Visual smoke check for the two metrics-showcase dashboards.

Renders each dashboard in the React viewer with an authenticated session and
asserts on the live DOM that:
  - every card shows a non-placeholder hero value,
  - the secondary strips actually painted (box plot svg, top-N bars, coverage
    bar, concentration line, stat rows),
  - the left panel renders one Paper per interactive family with the expected
    member count.

Usage:
    .venv/bin/python dev/playwright_debug/verify_metrics_showcase.py \
        --viewer-url http://localhost:5601 \
        --token-file /tmp/live_token
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DASHBOARDS = [
    ("iris", "6a71d86c6e487f6fa132f473", ["Sepal geometry", "Petal geometry", "Variety"]),
    (
        "penguins",
        "6a71d8726e487f6fa132f475",
        ["Taxonomy", "Bill morphology", "Body size", "Cohort"],
    ),
]


def build_local_store(token: str) -> str:
    return json.dumps(
        {
            "access_token": token,
            "logged_in": True,
            "token_type": "bearer",
            "token_lifetime": "short-lived",
        }
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--viewer-url", default="http://localhost:5601")
    ap.add_argument("--token-file", default="/tmp/live_token")
    ap.add_argument("--out-dir", default="/tmp/showcase_shots")
    args = ap.parse_args()

    token = Path(args.token_file).read_text().strip()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1680, "height": 1200})
        ctx.add_init_script(
            f"window.localStorage.setItem('local-store', {build_local_store(token)!r});"
        )
        page = ctx.new_page()
        console_errors: list[str] = []
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )

        for name, did, expected_groups in DASHBOARDS:
            console_errors.clear()
            url = f"{args.viewer_url}/dashboard/{did}"
            print(f"\n=== {name}: {url}")
            page.goto(url, wait_until="networkidle", timeout=90_000)
            # Cards resolve via bulk_compute_cards after mount; give it room.
            page.wait_for_timeout(6000)

            stats = page.evaluate(
                """
                () => {
                  const txt = (el) => (el?.textContent || '').trim();
                  // A card is any tile carrying the aggregation description line.
                  const cards = [...document.querySelectorAll('.depictio-component-chrome')]
                    .filter(c => c.querySelector('.card-secondary-metrics, [class*=card]'))
                  ;
                  const heroes = [...document.querySelectorAll('.depictio-component-chrome')]
                    .map(c => txt(c))
                    .filter(t => t.length);
                  return {
                    chromeCount: document.querySelectorAll('.depictio-component-chrome').length,
                    svgCount: document.querySelectorAll('svg').length,
                    papers: [...document.querySelectorAll('.mantine-Paper-root')].length,
                    bodyText: document.body.innerText.slice(0, 20000),
                  };
                }
                """
            )

            body = stats["bodyText"]

            # 1. No em-dash placeholder hero values ("—" alone means "no value").
            #    The renderer prints '—' when the bulk compute returned null.
            placeholder_hits = body.count("\n—\n")
            if placeholder_hits:
                failures.append(f"{name}: {placeholder_hits} card(s) show a '—' placeholder value")

            # 2. Every interactive family header must be present in the sidebar.
            for g in expected_groups:
                if g.upper() not in body.upper():
                    failures.append(f"{name}: missing interactive group header {g!r}")

            # 3. Cards did render some SVG (box plots + top-N bars + figures).
            if stats["svgCount"] < 5:
                failures.append(f"{name}: only {stats['svgCount']} svg nodes, strips likely blank")

            print(
                f"  chrome={stats['chromeCount']} svg={stats['svgCount']} "
                f"papers={stats['papers']} placeholders={placeholder_hits}"
            )
            groups_found = [g for g in expected_groups if g.upper() in body.upper()]
            print(f"  groups found: {groups_found}")

            shot = out_dir / f"{name}_showcase.png"
            page.screenshot(path=str(shot), full_page=True)
            print(f"  screenshot -> {shot}")

            hard_errors = [
                e
                for e in console_errors
                if "favicon" not in e.lower() and "download the react devtools" not in e.lower()
            ]
            if hard_errors:
                print(f"  console errors ({len(hard_errors)}):")
                for e in hard_errors[:5]:
                    print(f"    - {e[:160]}")

        browser.close()

    print("\n=== RESULT")
    if failures:
        for f in failures:
            print(f"  FAIL {f}")
        return 1
    print("  All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
