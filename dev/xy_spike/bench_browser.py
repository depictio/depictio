"""Phase 4 for the xy spike (issue #945): browser-side render + interaction bench.

Drives the pages produced by gen_browser_assets.py in the container's
preinstalled Chromium (SwiftShader software WebGL — absolute times carry that
caveat; plotly-vs-xy ratios on identical hardware are the meaningful signal).

Metrics per page:
  fetch_parse_ms   fetch + JSON/arrayBuffer parse of the payload
  render_ms        data-in-hand -> double-rAF after first paint
  zoom_fps         rAF frames/sec while dispatching wheel-zoom events (1.5 s)
  pan_fps          rAF frames/sec during a mouse drag-pan (1.5 s)
  heap_mb          performance.memory.usedJSHeapSize after render

Cells: 3 repeats each (fresh page per repeat; median reported).
Writes results/browser_timings.csv.

Run:  venv/bin/python dev/xy_spike/bench_browser.py
"""

from __future__ import annotations

import csv
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SPIKE = Path(__file__).parent
PAGES = SPIKE / "bench_pages"
RESULTS = SPIKE / "results"
PORT = 8234
REPEATS = 3

CELLS = [
    # (label, page, src, points_drawn)
    ("plotly_10k", "plotly_page.html", "fig_plotly_10k.json", 10_000),
    ("plotly_50k", "plotly_page.html", "fig_plotly_50k.json", 50_000),
    ("plotly_full_100k", "plotly_page.html", "fig_plotly_full_100k.json", 100_000),
    ("plotly_full_1m", "plotly_page.html", "fig_plotly_full_1m.json", 1_000_000),
    ("xy_100k", "xy_page.html", "xy_100k", 100_000),
    ("xy_1m", "xy_page.html", "xy_1m", 1_000_000),
    ("xy_10m", "xy_page.html", "xy_10m", 10_000_000),
    ("xy_1m_direct", "xy_page.html", "xy_1m_direct", 1_000_000),
]

FPS_JS = """
async (kind) => {
  const el = document.getElementById('chart');
  const box = el.getBoundingClientRect();
  const cx = box.left + box.width / 2, cy = box.top + box.height / 2;
  const durMs = 1500;
  let frames = 0, running = true;
  const count = () => { frames++; if (running) requestAnimationFrame(count); };
  requestAnimationFrame(count);
  const t0 = performance.now();
  const target = document.elementFromPoint(cx, cy) || el;
  if (kind === 'zoom') {
    while (performance.now() - t0 < durMs) {
      target.dispatchEvent(new WheelEvent('wheel', {
        clientX: cx, clientY: cy, deltaY: -60,
        bubbles: true, cancelable: true }));
      await new Promise(r => setTimeout(r, 40));
    }
  } else {
    target.dispatchEvent(new MouseEvent('mousedown', {
      clientX: cx, clientY: cy, buttons: 1, bubbles: true, cancelable: true }));
    let step = 0;
    while (performance.now() - t0 < durMs) {
      step += 1;
      const px = cx + 60 * Math.sin(step / 5), py = cy + 40 * Math.cos(step / 5);
      const opts = { clientX: px, clientY: py, buttons: 1,
                     bubbles: true, cancelable: true };
      target.dispatchEvent(new MouseEvent('mousemove', opts));
      window.dispatchEvent(new MouseEvent('mousemove', opts));
      await new Promise(r => setTimeout(r, 40));
    }
    target.dispatchEvent(new MouseEvent('mouseup', {
      clientX: cx, clientY: cy, bubbles: true, cancelable: true }));
  }
  running = false;
  const dt = (performance.now() - t0) / 1000;
  return frames / dt;
}
"""


def run_cell(browser, page_name: str, src: str) -> dict:
    page = browser.new_page(viewport={"width": 1100, "height": 600})
    try:
        page.goto(f"http://127.0.0.1:{PORT}/{page_name}?src={src}", timeout=120_000)
        page.wait_for_function("window.__ready === true || window.__error", timeout=180_000)
        err = page.evaluate("window.__error || null")
        if err:
            return {"error": err[:300]}
        m = page.evaluate("window.__metrics")
        time.sleep(0.3)
        zoom_fps = page.evaluate(FPS_JS, "zoom")
        time.sleep(0.3)
        pan_fps = page.evaluate(FPS_JS, "pan")
        heap = page.evaluate(
            "performance.memory ? performance.memory.usedJSHeapSize / 1048576 : null"
        )
        return {
            "fetch_parse_ms": m["fetch_parse_ms"],
            "render_ms": m["render_ms"],
            "zoom_fps": zoom_fps,
            "pan_fps": pan_fps,
            "heap_mb": heap,
        }
    finally:
        page.close()


def main() -> None:
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        cwd=PAGES,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cells = [c for c in CELLS if only is None or c[0].startswith(only)]
    rows = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            for label, page_name, src, points in cells:
                reps = []
                error = None
                for _ in range(REPEATS):
                    r = run_cell(browser, page_name, src)
                    if "error" in r:
                        error = r["error"]
                        break
                    reps.append(r)
                if error or not reps:
                    row = {"cell": label, "points_drawn": points, "error": error}
                else:
                    med = lambda k: statistics.median(  # noqa: E731
                        x[k] for x in reps if x[k] is not None
                    )
                    row = {
                        "cell": label,
                        "points_drawn": points,
                        "fetch_parse_ms": round(med("fetch_parse_ms"), 1),
                        "render_ms": round(med("render_ms"), 1),
                        "zoom_fps": round(med("zoom_fps"), 1),
                        "pan_fps": round(med("pan_fps"), 1),
                        "heap_mb": round(med("heap_mb"), 1) if reps[0]["heap_mb"] else None,
                    }
                rows.append(row)
                print(row)
            browser.close()
    finally:
        server.terminate()

    out = RESULTS / ("browser_timings.csv" if only is None else f"browser_timings_{only}.csv")
    fields = [
        "cell",
        "points_drawn",
        "fetch_parse_ms",
        "render_ms",
        "zoom_fps",
        "pan_fps",
        "heap_mb",
        "error",
    ]
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")
    print(json.dumps(rows, indent=1, default=str))


if __name__ == "__main__":
    main()
