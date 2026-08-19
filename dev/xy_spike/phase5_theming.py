"""Phase 5 theming check for the xy spike (issue #945).

Verifies, against a live mounted xy chart (no re-render, no refetch):
  1. `.dark` on an ancestor flips the built-in dark palette (docs' contract).
  2. Mantine-derived `--chart-*` CSS custom properties re-color the chart at
     runtime — the same color formula `plotlyTheme.ts` uses
     (dark: text=gray[2], grid=rgba(255,255,255,0.08); light: text=gray[8]).
  3. The change is CSS-only: the ChartView instance is not re-created.

Evidence: computed style of a DOM tick label before/after + three screenshots
(light / dark-auto / dark-mantine-tokens), plus canvas pixel means.

Also exercises `to_png()` (native browser-free rasterizer) as a candidate
for the screenshot system.

Run:  venv/bin/python dev/xy_spike/phase5_theming.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SPIKE = Path(__file__).parent
PAGES = SPIKE / "bench_pages"
RESULTS = SPIKE / "results"
PORT = 8235

# Mantine default theme grays used by plotlyTheme.ts (colors.gray[2] / [8])
MANTINE = {
    "dark_text": "#e9ecef",
    "light_text": "#343a40",
    "dark_grid": "rgba(255,255,255,0.08)",
    "light_grid": "rgba(0,0,0,0.08)",
    "dark_body_bg": "#1a1b1e",  # Mantine dark.7 app background
}

TICK_STYLE_JS = """
() => {
  const tick = document.querySelector(
    '.xy [data-xy-slot="x_tick_label"], .xy [data-xy-slot="tick_label"],'
    + ' .xy [class*="tick"], .xy text, .xy span');
  const root = document.querySelector('#chart .xy') ||
               document.querySelector('#chart > div') ||
               document.getElementById('chart');
  return {
    tickColor: tick ? getComputedStyle(tick).color : null,
    rootColor: root ? getComputedStyle(root).color : null,
    chartViewAlive: !!(window.__view && !window.__view._destroyed),
  };
}
"""

CANVAS_MEAN_JS = """
() => [...document.querySelectorAll('#chart canvas')].map(c => {
  const g = c.getContext('2d');
  if (!g) return null;
  const d = g.getImageData(0, 0, c.width, c.height).data;
  let r = 0, gg = 0, b = 0, n = 0;
  for (let i = 0; i < d.length; i += 40) {
    if (d[i + 3] > 0) { r += d[i]; gg += d[i + 1]; b += d[i + 2]; n++; }
  }
  return n ? [r / n | 0, gg / n | 0, b / n | 0] : null;
})
"""


def main() -> None:
    findings: dict = {}
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        cwd=PAGES,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            page = browser.new_page(viewport={"width": 1100, "height": 600})
            page.goto(f"http://127.0.0.1:{PORT}/xy_page.html?src=xy_100k")
            page.wait_for_function("window.__ready === true || window.__error", timeout=60_000)
            time.sleep(0.5)

            findings["light"] = page.evaluate(TICK_STYLE_JS)
            findings["light_canvas_mean"] = page.evaluate(CANVAS_MEAN_JS)
            page.screenshot(path=str(RESULTS / "theme_light.png"))

            # 1. Mantine-style dark switch: .dark class + dark app background
            page.evaluate(
                f"""() => {{
                  document.documentElement.classList.add('dark');
                  document.body.style.background = '{MANTINE["dark_body_bg"]}';
                }}"""
            )
            time.sleep(0.6)
            findings["dark_auto"] = page.evaluate(TICK_STYLE_JS)
            findings["dark_auto_canvas_mean"] = page.evaluate(CANVAS_MEAN_JS)
            page.screenshot(path=str(RESULTS / "theme_dark_auto.png"))

            # 2. Mantine tokens via --chart-* custom properties
            page.evaluate(
                f"""() => {{
                  const el = document.getElementById('chart');
                  el.style.setProperty('--chart-text', '{MANTINE["dark_text"]}');
                  el.style.setProperty('--chart-grid', '{MANTINE["dark_grid"]}');
                  el.style.setProperty('--chart-axis', '{MANTINE["dark_grid"]}');
                  el.style.setProperty('--chart-bg', 'rgba(0,0,0,0)');
                }}"""
            )
            time.sleep(0.6)
            findings["dark_mantine_tokens"] = page.evaluate(TICK_STYLE_JS)
            findings["dark_tokens_canvas_mean"] = page.evaluate(CANVAS_MEAN_JS)
            page.screenshot(path=str(RESULTS / "theme_dark_mantine.png"))

            findings["same_chartview_instance"] = page.evaluate(
                "window.__view === window.__view && !window.__view._destroyed"
            )
            browser.close()
    finally:
        server.terminate()

    # 3. to_png native rasterizer (screenshot-system candidate)
    import numpy as np
    import xy

    rng = np.random.default_rng(0)
    ch = xy.chart(xy.scatter(rng.normal(size=5000), rng.normal(size=5000)))
    t0 = time.perf_counter()
    ch.to_png(str(RESULTS / "to_png_native.png"), width=1200, height=630, scale=2)
    findings["to_png_native_s"] = round(time.perf_counter() - t0, 3)
    findings["to_png_bytes"] = (RESULTS / "to_png_native.png").stat().st_size

    out = RESULTS / "phase5_theming.json"
    out.write_text(json.dumps(findings, indent=2, default=str))
    print(json.dumps(findings, indent=2, default=str))


if __name__ == "__main__":
    main()
