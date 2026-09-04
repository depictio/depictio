"""Phase 1b: density-tier selection, large select retry, GL-context topology.

Questions:
  1. Large box select retry (drag inside the plot area, not the axis margin).
  2. At 1M points (density tier): does browser-local selection work at all?
     (_selectLocalPolygon skips traces with tier === 'density'.)
  3. GL topology: does xy use one shared WebGL context blitted into per-chart
     2D canvases (=> no 16-context cap), or one GL context per chart?

Writes results/phase1b_findings.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SPIKE = Path(__file__).parent
HARNESS = SPIKE / "harness"
RESULTS = SPIKE / "results"
PORT = 8232

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}#chart{width:1000px;height:500px;border:1px solid #ccc}</style>
</head><body>
<div id="chart"></div>
<script src="./standalone.js"></script>
<script>
window.__xySelects = [];
document.addEventListener('xy:select', e => window.__xySelects.push(e.detail));
window.__ready = false;
(async () => {
  const n = new URLSearchParams(location.search).get('n') || '50000';
  const [spec, blob] = await Promise.all([
    fetch(`./spec_${n}.json`).then(r => r.json()),
    fetch(`./blob_${n}.bin`).then(r => r.arrayBuffer()),
  ]);
  window.__view = xy.renderStandalone(
    document.getElementById('chart'), spec, new Uint8Array(blob));
  window.__ready = true;
})().catch(e => { window.__mountError = String(e && e.stack || e); });
</script></body></html>
"""

GL_TOPOLOGY_JS = """
() => {
  const v = window.__view;
  const canvases = [...document.querySelectorAll('canvas')].map(c => {
    // getContext returns the existing context type only
    let kind = 'unknown';
    try { if (c.getContext('2d')) kind = '2d'; } catch (e) {}
    if (kind === 'unknown') {
      try { if (c.getContext('webgl2')) kind = 'webgl2'; } catch (e) {}
    }
    return { w: c.width, h: c.height, kind };
  });
  const gl = v.gl || null;
  return {
    canvases,
    viewHasGl: !!gl,
    glCanvasInDom: gl ? document.contains(gl.canvas) : null,
    glCanvasSize: gl ? { w: gl.canvas.width, h: gl.canvas.height } : null,
    glIsOffscreen: gl
      ? (typeof OffscreenCanvas !== 'undefined' && gl.canvas instanceof OffscreenCanvas)
      : null,
    sharedFlag: window.XY_SHARED_WEBGL,
    tiers: v.gpuTraces.map(t => ({
      kind: t.trace.kind, tier: t.tier, n: t.n,
      hasCpu: !!t._cpu, hasDrill: !!t.drill,
    })),
  };
}
"""


def drag_select(page, fx0, fy0, fx1, fy1):
    box = page.locator("#chart").bounding_box()
    x0, y0 = box["x"] + box["width"] * fx0, box["y"] + box["height"] * fy0
    x1, y1 = box["x"] + box["width"] * fx1, box["y"] + box["height"] * fy1
    page.keyboard.down("Shift")
    page.mouse.move(x0, y0)
    page.mouse.down()
    for i in range(1, 13):
        page.mouse.move(x0 + (x1 - x0) * i / 12, y0 + (y1 - y0) * i / 12)
        time.sleep(0.02)
    page.mouse.up()
    page.keyboard.up("Shift")


def main() -> None:
    (HARNESS / "single.html").write_text(PAGE)
    findings: dict = {}
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        cwd=HARNESS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            for n, label in ((50_000, "direct_50k"), (1_000_000, "density_1m")):
                page = browser.new_page(viewport={"width": 1100, "height": 600})
                page.goto(f"http://127.0.0.1:{PORT}/single.html?n={n}")
                page.wait_for_function(
                    "window.__ready === true || window.__mountError", timeout=30_000
                )
                time.sleep(0.6)
                res: dict = {
                    "mount_error": page.evaluate("window.__mountError || null"),
                    "topology": page.evaluate(GL_TOPOLOGY_JS),
                }
                # selection well inside the plot area
                drag_select(page, 0.2, 0.2, 0.8, 0.8)
                time.sleep(0.6)
                res["selects"] = page.evaluate(
                    "window.__xySelects.map(d => ({total: d.total, keys: Object.keys(d)}))"
                )
                page.screenshot(path=str(RESULTS / "raw" / f"phase1b_{label}.png"))
                findings[label] = res
                page.close()
            browser.close()
    finally:
        server.terminate()

    out = RESULTS / "phase1b_findings.json"
    out.write_text(json.dumps(findings, indent=2, default=str))
    print(json.dumps(findings, indent=2, default=str))


if __name__ == "__main__":
    main()
