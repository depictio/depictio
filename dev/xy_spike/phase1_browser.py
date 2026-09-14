"""Phase 1 browser verification for the xy spike (issue #945).

Serves harness/ over http, opens mount_test.html in the preinstalled
Chromium, and answers the decisive questions:
  1. Do two xy charts mount from external standalone.js + build_payload()
     output (no Reflex, no to_html)?
  2. What does the browser-local xy:select payload actually carry
     (row identity or just counts/bounds)?  Small + large selections.
  3. Does xy:click carry per-point row identity locally?
  4. Can selected row indices be recovered client-side from the ChartView
     (the _cpu arrays + polygon/range replay a wrapper would use)?
  5. What WebGL renderer string does this container get (honesty caveat)?

Writes results/phase1_findings.json.
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
PORT = 8231

RECOVER_INDICES_JS = """
() => {
  // What a React wrapper would do on xy:select: replay the range test over
  // the retained CPU coordinate arrays to recover selected row indices,
  // then map them to selection-column values via the aligned ids array.
  const view = window.__views.a;
  const ev = [...window.__xyEvents].reverse().find(
    (e) => e.name === 'xy:select' && (e.hasRange || e.hasPolygon));
  if (!ev) return { error: 'no select event with range/polygon' };
  const detail = window.__lastSelectDetail;
  if (!detail || !detail.range) return { error: 'no stashed detail.range' };
  const { x0, x1, y0, y1 } = detail.range;
  const out = [];
  for (const t of view.gpuTraces) {
    if (!t._cpu) continue;
    const xs = t._cpu.x, ys = t._cpu.y;
    const xm = t._cpu.xMeta || t.xMeta, ym = t._cpu.yMeta || t.yMeta;
    const fx = xm.offset, sx = xm.scale || 1, fy = ym.offset, sy = ym.scale || 1;
    for (let i = 0; i < t.n; i++) {
      const px = xs[i] / sx + fx, py = ys[i] / sy + fy;
      if (px >= x0 && px <= x1 && py >= y0 && py <= y1) out.push(i);
    }
  }
  return {
    count: out.length,
    first_ids: out.slice(0, 5).map((i) => window.__ids[i]),
    eventTotal: detail.total,
  };
}
"""


def drag(page, sel: str, fx0: float, fy0: float, fx1: float, fy1: float, shift=True):
    box = page.locator(sel).bounding_box()
    x0, y0 = box["x"] + box["width"] * fx0, box["y"] + box["height"] * fy0
    x1, y1 = box["x"] + box["width"] * fx1, box["y"] + box["height"] * fy1
    if shift:
        page.keyboard.down("Shift")
    page.mouse.move(x0, y0)
    page.mouse.down()
    for i in range(1, 11):
        page.mouse.move(x0 + (x1 - x0) * i / 10, y0 + (y1 - y0) * i / 10)
    page.mouse.up()
    if shift:
        page.keyboard.up("Shift")


def main() -> None:
    findings: dict = {}
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        cwd=HARNESS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with sync_playwright() as p:
            # container ships chromium-1194; installed playwright expects a
            # newer build, so point at the preinstalled executable directly
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            page = browser.new_page(viewport={"width": 1400, "height": 600})
            console_errors: list[str] = []
            page.on(
                "console",
                lambda m: console_errors.append(m.text) if m.type == "error" else None,
            )

            # stash raw select detail before the summarizer flattens it
            page.add_init_script(
                "document.addEventListener('xy:select',"
                " e => { window.__lastSelectDetail = e.detail; });"
            )

            page.goto(f"http://127.0.0.1:{PORT}/mount_test.html")
            page.wait_for_function("window.__ready === true || window.__mountError", timeout=30_000)
            findings["mount_error"] = page.evaluate("window.__mountError || null")

            # WebGL renderer string (honesty caveat for all timings)
            findings["webgl_renderer"] = page.evaluate(
                """() => {
                  const c = document.createElement('canvas');
                  const gl = c.getContext('webgl2');
                  if (!gl) return 'NO WEBGL2';
                  const ext = gl.getExtension('WEBGL_debug_renderer_info');
                  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)
                             : gl.getParameter(gl.RENDERER);
                }"""
            )

            # non-blank canvases?
            findings["canvases"] = page.evaluate(
                """() => [...document.querySelectorAll('canvas')].map(c => {
                  const g = c.getContext('2d');
                  if (g) {
                    const d = g.getImageData(0, 0, c.width, c.height).data;
                    return {w: c.width, h: c.height,
                            blank: !d.some((v, i) => i % 4 === 3 && v > 0)};
                  }
                  return {w: c.width, h: c.height, gl: true};
                })"""
            )
            page.screenshot(path=str(RESULTS / "raw" / "mount_test.png"))

            # small box select on chart A (shift+drag)
            drag(page, "#chartA", 0.45, 0.45, 0.6, 0.6)
            time.sleep(0.5)
            findings["small_select_events"] = page.evaluate(
                "window.__xyEvents.filter(e => e.name === 'xy:select')"
            )
            findings["small_select_detail_keys"] = page.evaluate(
                "window.__lastSelectDetail ? Object.keys(window.__lastSelectDetail) : null"
            )
            findings["recovered_indices_small"] = page.evaluate(RECOVER_INDICES_JS)

            # click a point → does it carry row identity?
            page.evaluate("window.__xyEvents.length = 0")
            page.locator("#chartA").click(position={"x": 300, "y": 200})
            time.sleep(0.4)
            findings["click_events"] = page.evaluate(
                "window.__xyEvents.filter(e => e.name === 'xy:click')"
            )

            # large select: whole chart A (~50k points)
            page.evaluate("window.__xyEvents.length = 0")
            drag(page, "#chartA", 0.02, 0.02, 0.98, 0.98)
            time.sleep(0.8)
            findings["large_select_events"] = page.evaluate(
                "window.__xyEvents.filter(e => e.name === 'xy:select')"
            )
            findings["recovered_indices_large"] = page.evaluate(RECOVER_INDICES_JS)

            # does chart B stay independent (its own events/contexts)?
            findings["view_b_alive"] = page.evaluate(
                "!!(window.__views.b && !window.__views.b._destroyed)"
            )
            findings["console_errors"] = console_errors[:10]
            browser.close()
    finally:
        server.terminate()

    out = RESULTS / "phase1_findings.json"
    out.write_text(json.dumps(findings, indent=2, default=str))
    print(json.dumps(findings, indent=2, default=str))


if __name__ == "__main__":
    main()
