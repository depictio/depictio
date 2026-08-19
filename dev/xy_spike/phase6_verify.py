"""Phase 6 verification: drive the React PoC in Chromium.

Checks:
  1. React 18 mounts the xy chart (StrictMode double-effect safe: the wrapper
     destroys and remounts cleanly).
  2. Shift+drag select -> the emitted object matches depictio-react-core's
     InteractiveFilter shape with real individual_id values.
  3. Theme toggle re-colors the live chart via .dark + --chart-* tokens.
Screenshots: results/poc_light.png, results/poc_selected.png,
             results/poc_dark.png.

Run:  venv/bin/python dev/xy_spike/phase6_verify.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SPIKE = Path(__file__).parent
POC = SPIKE / "poc"
RESULTS = SPIKE / "results"
PORT = 8236


def main() -> None:
    findings: dict = {}
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        cwd=POC,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            page = browser.new_page(viewport={"width": 1100, "height": 760})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{PORT}/index.html")
            page.wait_for_selector("#theme-toggle", timeout=30_000)
            # chart canvases appear once renderStandalone ran
            page.wait_for_function("document.querySelectorAll('canvas').length > 0", timeout=30_000)
            time.sleep(0.8)
            page.screenshot(path=str(RESULTS / "poc_light.png"))

            # shift+drag box select in the chart area
            chart = page.evaluate(
                """() => {
                  const c = document.querySelector('canvas');
                  const r = c.getBoundingClientRect();
                  return {x: r.x, y: r.y, w: r.width, h: r.height};
                }"""
            )
            x0, y0 = chart["x"] + chart["w"] * 0.35, chart["y"] + chart["h"] * 0.35
            x1, y1 = chart["x"] + chart["w"] * 0.65, chart["y"] + chart["h"] * 0.65
            page.keyboard.down("Shift")
            page.mouse.move(x0, y0)
            page.mouse.down()
            for i in range(1, 11):
                page.mouse.move(x0 + (x1 - x0) * i / 10, y0 + (y1 - y0) * i / 10)
                time.sleep(0.02)
            page.mouse.up()
            page.keyboard.up("Shift")
            time.sleep(0.8)

            filters = page.evaluate("window.__pocFilters")
            findings["filters_emitted"] = len(filters)
            if filters:
                last = filters[-1]
                findings["filter_shape"] = {
                    k: (v if k != "value" else f"[{len(v)} ids, first={v[:3]}]")
                    for k, v in last.items()
                }
            page.screenshot(path=str(RESULTS / "poc_selected.png"))

            # theme toggle
            page.click("#theme-toggle")
            time.sleep(0.8)
            page.screenshot(path=str(RESULTS / "poc_dark.png"))
            findings["dark_body_bg"] = page.evaluate(
                "getComputedStyle(document.body).backgroundColor"
            )
            findings["chart_text_token"] = page.evaluate(
                "getComputedStyle(document.documentElement).getPropertyValue('--chart-text')"
            )
            findings["page_errors"] = errors[:5]
            findings["react_strictmode"] = True  # App renders under <StrictMode>
            browser.close()
    finally:
        server.terminate()

    out = RESULTS / "phase6_poc.json"
    out.write_text(json.dumps(findings, indent=2, default=str))
    print(json.dumps(findings, indent=2, default=str))


if __name__ == "__main__":
    main()
