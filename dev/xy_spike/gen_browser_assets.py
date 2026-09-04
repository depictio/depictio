"""Phase 4 asset generator: figure payloads + static pages for the browser bench.

Produces bench_pages/ (gitignored contents are regenerable):
  plotly.min.js                copied from harness/node_modules (2.35.3 — the
                               exact version depictio-react-core resolves)
  standalone.js                xy 0.0.6 client from the wheel
  fig_plotly_10k.json / _50k.json / _full_100k.json / _full_1m.json
                               figure JSON from the real figure_builder
                               (plotly 6.x typed-array wire format)
  xy_{100k,1m,10m}_{spec.json,blob.bin}      density-auto payloads
  xy_1m_direct_{spec.json,blob.bin}          density=False (selection-capable)
  plotly_page.html / xy_page.html            instrumented pages

Run:  venv/bin/python dev/xy_spike/gen_browser_assets.py
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

SPIKE = Path(__file__).parent
REPO = SPIKE.parent.parent
PAGES = SPIKE / "bench_pages"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SPIKE))

import _env  # noqa: E402, F401

X, Y, SEL = "bill_length_mm", "bill_depth_mm", "individual_id"

PLOTLY_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}#chart{width:1000px;height:500px}</style>
<script src="./plotly.min.js"></script></head><body>
<div id="chart"></div>
<script>
window.__metrics = {};
(async () => {
  const src = new URLSearchParams(location.search).get('src');
  let t0 = performance.now();
  const fig = await fetch(src).then(r => r.json());
  window.__metrics.fetch_parse_ms = performance.now() - t0;
  // Interaction parity with the xy page: wheel = zoom, drag = pan.
  // The server figure ships dragmode 'lasso' (selection_enabled) and plotly
  // ignores wheel without scrollZoom — both would make the FPS probes no-ops.
  const layout = Object.assign({}, fig.layout, {dragmode: 'pan'});
  t0 = performance.now();
  await Plotly.newPlot('chart', fig.data, layout,
                       {responsive: true, displaylogo: false, scrollZoom: true});
  // double rAF: a frame actually presented after newPlot resolved
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  window.__metrics.render_ms = performance.now() - t0;
  window.__ready = true;
})().catch(e => { window.__error = String(e && e.stack || e); });
</script></body></html>
"""

XY_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}#chart{width:1000px;height:500px}</style>
<script src="./standalone.js"></script></head><body>
<div id="chart"></div>
<script>
window.__metrics = {};
(async () => {
  const base = new URLSearchParams(location.search).get('src');
  let t0 = performance.now();
  const [spec, blob] = await Promise.all([
    fetch(`${base}_spec.json`).then(r => r.json()),
    fetch(`${base}_blob.bin`).then(r => r.arrayBuffer()),
  ]);
  window.__metrics.fetch_parse_ms = performance.now() - t0;
  t0 = performance.now();
  window.__view = xy.renderStandalone(
    document.getElementById('chart'), spec, new Uint8Array(blob));
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  window.__metrics.render_ms = performance.now() - t0;
  window.__ready = true;
})().catch(e => { window.__error = String(e && e.stack || e); });
</script></body></html>
"""


def load_frame(n: int):
    from bson import ObjectId

    from depictio.api.v1 import deltatables_utils

    deltatables_utils._get_aggregation_version = lambda _dc: None  # no Mongo here
    dc_ids = {
        100_000: "64b000000000000000000100",
        1_000_000: "64b000000000000000001000",
        10_000_000: "64b000000000000000010000",
    }
    path = SPIKE / "data" / f"points_{n}"
    init_data = {
        dc_ids[n]: {
            "delta_location": str(path),
            "dc_type": "Table",
            "size_bytes": 1,
        }
    }
    return deltatables_utils.load_deltatable_lite(
        ObjectId("64b0000000000000000000aa"),
        dc_ids[n],
        init_data=init_data,
        select_columns=[X, Y, SEL],
    )


def dump_plotly(df, max_points: int, name: str) -> None:
    from depictio.api.v1.services.figure.figure_builder import create_figure_from_data

    t0 = time.perf_counter()
    fig = create_figure_from_data(
        df,
        "scatter",
        {"x": X, "y": Y},
        theme="light",
        selection_enabled=True,
        selection_column=SEL,
        max_points=max_points,
        render_stats={},
    )
    out = PAGES / f"fig_{name}.json"
    out.write_text(fig.to_json())
    print(f"{out.name}: {out.stat().st_size} bytes ({time.perf_counter() - t0:.1f}s)")


def dump_xy(df, name: str, density: bool | None) -> None:
    import xy

    xs, ys = df[X].to_numpy(), df[Y].to_numpy()
    scatter = xy.scatter(xs, ys) if density is None else xy.scatter(xs, ys, density=density)
    ch = xy.chart(
        scatter,
        xy.interaction_config(hover=True, click=True, select=True, brush=True),
    )
    spec, blob = ch.figure().build_payload()
    (PAGES / f"xy_{name}_spec.json").write_text(json.dumps(spec))
    (PAGES / f"xy_{name}_blob.bin").write_bytes(blob)
    print(f"xy_{name}: spec+blob {len(blob)} bytes")


def main() -> None:
    PAGES.mkdir(exist_ok=True)
    shutil.copy(
        SPIKE / "harness/node_modules/plotly.js-dist-min/plotly.min.js",
        PAGES / "plotly.min.js",
    )
    import xy as _xy

    shutil.copy(Path(_xy.__file__).parent / "static/standalone.js", PAGES / "standalone.js")
    (PAGES / "plotly_page.html").write_text(PLOTLY_PAGE)
    (PAGES / "xy_page.html").write_text(XY_PAGE)

    df_100k = load_frame(100_000)
    df_1m = load_frame(1_000_000)
    df_10m = load_frame(10_000_000)

    dump_plotly(df_1m, 10_000, "plotly_10k")
    dump_plotly(df_1m, 50_000, "plotly_50k")
    dump_plotly(df_100k, -1, "plotly_full_100k")
    dump_plotly(df_1m, -1, "plotly_full_1m")

    dump_xy(df_100k, "100k", None)
    dump_xy(df_1m, "1m", None)
    dump_xy(df_10m, "10m", None)
    dump_xy(df_1m, "1m_direct", False)


if __name__ == "__main__":
    main()
