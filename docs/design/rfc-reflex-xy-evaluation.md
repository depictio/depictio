# RFC — Evaluation: reflex-dev/xy for large point-plot rendering

**Status:** Evaluated — **GO (conditional)**: a Reflex-free React mount path exists and the
measured win over the shipped baseline is large; adoption should be additive
(point-plot family only) and gated on pinning the alpha's undocumented mount API.
**Audience:** maintainers
**Related:** [#945](https://github.com/depictio/depictio/issues/945),
`depictio/api/v1/services/figure/figure_builder.py`,
`packages/depictio-react-core/src/webglBudget.ts`,
`packages/depictio-react-core/src/selection.ts`,
`dev/xy_spike/` (benchmark scripts, PoC, raw findings), `benchmark/PERF_REPORT_v2.md`.

> This RFC records a spike (evidence + recommendation). The PoC under
> `dev/xy_spike/poc/` is demonstration code, not an integration; nothing under
> `depictio/` or `packages/` changed.

## 1. Context — the two limits

- **Server-side downsampling.** Scatter-family figures above the cap are
  sampled before trace JSON is built (`figure_builder.py`:
  `FIGURE_MAX_POINTS = 50_000` fallback; the runtime default actually passed is
  `settings.performance.figure_max_points = 10_000`). A 1M-row scatter would
  serialize to ~38 MB (measured, §5) and stall the browser, so users see a
  10k/50k sample and a "load all" affordance instead of their data.
- **The WebGL context budget.** Plotly allocates three GL canvases per
  `scattergl`; Chrome caps ~16 live contexts, so `webglBudget.ts` grants
  `MAX_GL_PLOTS = 4` slots and the rest fall back to SVG capped at
  `SVG_MAX_POINTS = 3000`.

[xy](https://github.com/reflex-dev/xy) (Apache-2.0, alpha) is a Python charting
library with a Rust compute core and a WebGL2 browser client, claiming flat
render time across four orders of magnitude. The central unknown from #945:
**can xy's browser runtime be driven from React without Reflex?**

## 2. What xy 0.0.6 actually is (verified from the wheel, not the README)

- The pip wheel bundles the Python package, a native Rust core, and the browser
  client as **separable static assets**: `xy/static/standalone.js` (IIFE,
  global `xy`) and `xy/static/index.js` (ESM) — each ~430 KB raw /
  **~123 KB gzip**. Pure JS + WebGL2, **no WASM in the browser**.
- `to_html()` is a thin wrapper: `spec, blob = fig.build_payload()` +
  the bundled client + one call — **`xy.renderStandalone(el, spec, buf)`**
  (`xy/export.py`). `Figure.build_payload()` returns the exact
  `(spec: dict ~1–2 KB, blob: bytes)` pair a server endpoint would ship.
- Interactivity (pan/zoom/hover/click/selection) is **browser-local** — no
  Python process needed after payload delivery.
- Releases: 0.0.1 (2026-07-17) → 0.0.6 (2026-08-07) — six releases in three
  weeks. The 0.0.6 wheel matrix covers macOS/Linux (glibc+musl,
  x86_64/aarch64/armv7)/Windows/Pyodide. Requires Python ≥ 3.11 (Depictio
  targets 3.12 ✓).

Several claims in #945 are already stale: mark coverage is far beyond
"line/scatter/density" (§8), and Windows wheels now exist.

## 3. Method & hardware

Everything is reproducible from `dev/xy_spike/README.md`. Data was generated
with the repo's canonical benchmark schema (`benchmark/datagen.py::_make_batch`,
`individual_id` as the selection column) at 100k / 1M / 10M rows, written as
local Delta tables, and loaded through the **real production read path** —
`load_deltatable_lite(..., init_data=...)` with `DEPICTIO_USE_LOCAL_FILES=true`
(the documented perf-testing escape hatch), projected to the referenced columns
exactly as `celery_tasks.py` does. The largest *committed* real dataset
(viralrecon `multiqc.parquet`) has only 5,351 rows, so synthetic data was
required; the Mongo aggregation-version lookup was stubbed to `None` (this
container has no Mongo; production pays ~ms there, this container would pay a
30 s server-selection timeout).

Hardware (`results/hardware_profile.md`): shared cloud container,
Intel Xeon @ 2.80 GHz × 4 cores, 15 GiB RAM, kernel 6.18.5.
**WebGL is SwiftShader (software rasterization)** — the renderer string is
recorded in `results/phase1_findings.json`. Absolute browser times are
therefore pessimistic for both engines; the plotly-vs-xy **ratios on identical
hardware** are the meaningful signal. Python versions: plotly 6.9.0 /
plotly.js-dist-min 2.35.3 (the viewer's locked version), xy 0.0.6,
Polars 1.42.1. Cold vs warm reported separately; every row states the points
actually serialized/drawn — the shipped baseline draws a **sample**, xy draws
**all N**.

## 4. Results — Python side (build + serialize, per figure)

`results/python_timings.csv`; warm = mean of 3, fresh subprocess per cell.

| engine | source rows | pts serialized | build warm | serialize warm | payload |
|---|---:|---:|---:|---:|---:|
| plotly@10k (shipped default) | 1M | 10,000 | 24 ms | 51 ms | 386 KB |
| plotly@50k (issue baseline) | 1M | 50,000 | 40 ms | 115 ms | 1.92 MB |
| plotly full (counterfactual) | 1M | 1,000,000 | 464 ms | 2,544 ms | 38.4 MB |
| **xy auto (density)** | 1M | **1,000,000** | **13 ms** | 11 ms | **266 KB** |
| xy direct (`density=False`) | 1M | 1,000,000 | 13 ms | 41 ms | 8.0 MB |
| plotly@10k | 10M | 10,000 | 25 ms | 50 ms | 386 KB |
| plotly@50k | 10M | 50,000 | 44 ms | 120 ms | 1.92 MB |
| **xy auto (density)** | 10M | **10,000,000** | **70 ms** | 45 ms | **264 KB** |

At 10M source rows xy builds and serializes a payload representing **all
10,000,000 points in ~115 ms at 264 KB** — 7× smaller and ~1.4× faster than the
50k-sample plotly baseline that ships 0.5% of the data. The payload is
screen-bounded: above ~200k points/trace xy switches to a density surface +
deterministic sample, which is why 1M and 10M cost the same. Peak RSS is
comparable between engines (dominated by the loaded frame).

## 5. Results — browser side (render + interaction)

`results/browser_timings.csv`; median of 3 fresh pages per cell; SwiftShader
caveat applies. Both pages measure the same protocol: payload fetch+parse,
data-in-hand → double-rAF after first paint, then 1.5 s of synthetic
wheel-zoom and drag-pan streams counting rAF frames. (The plotly page pins
`dragmode: 'pan'` + `scrollZoom: true` so both engines do real work on the
same gestures; the server figure's default `dragmode: 'lasso'` would have made
the probes no-ops.)

| cell | pts drawn | fetch+parse | render | zoom fps | pan fps | JS heap |
|---|---:|---:|---:|---:|---:|---:|
| plotly@10k (shipped default) | 10,000 | 11 ms | 471 ms | 23.3 | 29.4 | 31 MB |
| plotly@50k (issue baseline) | 50,000 | 42 ms | 900 ms | 10.6 | 16.0 | 51 MB |
| plotly full | 100,000 | 63 ms | 1,368 ms | 4.1 | 5.1 | 66 MB |
| plotly full | 1,000,000 | 457 ms | 10,394 ms | 0.4 | 0.4 | 274 MB |
| **xy (density)** | 100,000 | 14 ms | 233 ms | 45.9 | 60.0 | 5.6 MB |
| **xy (density)** | 1,000,000 | 17 ms | **144 ms** | 58.8 | 60.7 | 8.3 MB |
| **xy (density)** | **10,000,000** | 12 ms | **149 ms** | 57.8 | 60.0 | 8.3 MB |
| xy direct (`density=False`) | 1,000,000 | 68 ms | 1,007 ms | 3.4 | 60.7 | 12 MB |

Headline: xy renders **10M points in ~150 ms** where plotly needs ~470 ms for a
10k sample and ~10.4 s for 1M (with 274 MB of JS heap and an effectively frozen
0.4 fps pan). xy's zoom/pan stays at ~60 fps from 100k to 10M with ~8 MB heap. The one
xy cell that struggles is `density=False` at 1M on software GL (3 fps zoom) —
the knob exists precisely to trade render cost for browser-local selection, and
would be capped (e.g. ≤ 200k–500k) in any real integration.

## 6. The four integration paths — verdicts

1. **P1 — direct JS mount in React: VIABLE (demonstrated).**
   `renderStandalone(el, spec, buf)` mounted two charts in one page from the
   wheel's `standalone.js` + `build_payload()` output — no Reflex, no
   `to_html()` (`results/phase1_findings.json`), and the React 18 PoC
   (`dev/xy_spike/poc/`, StrictMode, mount/unmount-safe) drives it end to end.
   **Caveat:** neither `renderStandalone` nor `build_payload` is documented
   public API; this is alpha internals working exactly as the docs' own
   architecture describes, but with no stability contract. Adoption must pin
   the xy version and carry a smoke test.
2. **P2 — server-side `to_png()`/`to_svg()`: viable but not the win.** The
   native (browser-free) rasterizer produced a PNG in-process; useful for the
   screenshot/thumbnail path some day, but static images solve neither limit.
3. **P3 — iframe embed of `to_html()`: works, unnecessary.** The standalone
   HTML self-contains its CSP (inline scripts, `worker-src blob:`), and
   `xy:*` events would need a postMessage bridge. Strictly dominated by P1.
4. **P4 — upstream ask.** The right ask is small and concrete: publish
   `renderStandalone` + the payload format (or an npm package) as stable API,
   and expose selected row indices on the browser `xy:select` event (§7).
   Not filed as part of this spike per #945's scope.

## 7. Cross-filtering contract

Depictio's contract: lasso/box/click → `customdata[selection_column_index=0]`
values → `InteractiveFilter {index, value: string[], source:
'scatter_selection'}` (`selection.ts`, `figure_builder.py`).

Measured against xy 0.0.6 (browser-local, no Python):

- Events are DOM CustomEvents bubbling from the chart root (`xy:select`,
  `xy:click`, `xy:hover`, `xy:view_change`); Shift+drag = box/lasso select.
- `xy:click` carries full row identity locally: `{row: {trace, index, x, y},
  index, trace}`.
- `xy:select` carries **`{total, range|polygon, view}` — no indices**. But
  `renderStandalone` retains exact per-point coordinates
  (`view.gpuTraces[i]._cpu`), and replaying the region test over them
  recovered the selection **exactly** (13,847/13,847 at 50k points) and mapped
  positional indices → `individual_id` strings via an aligned ids array
  (canonical row order == the Polars frame's row order). The PoC emits a
  spec-shaped `InteractiveFilter` this way (`results/phase6_poc.json`).
  xy has no per-point customdata channel, so the ids array (or a
  server-side index→ID resolution) replaces `customdata[0]`.
- **The real boundary:** above ~200k points/trace (density tier), browser-local
  selection is a no-op — no event, no `_cpu` arrays
  (`results/phase1b_findings.json`). `density=False` restores it at 8 bytes/pt
  payload + real render cost. A live host resolves density-tier selections
  Python-side, but that transport is the Reflex/notebook path Depictio doesn't
  run. So: **selection-driven cross-filtering works Reflex-free up to a policy
  cap (≥ 4–20× today's 10k/50k sample); view-only rendering is unlimited.**

## 8. Mark coverage vs `ALLOWED_VISUALIZATIONS`

Checked against the installed 0.0.6 API (not the README): 11 of Depictio's 12
allowed types have an xy equivalent — scatter, line, bar, box, histogram
(`hist`), violin, ecdf, density_heatmap (`heatmap`/`hexbin`), density_contour
(`contour`), area, funnel. Only **`strip` is missing** (approximable with
jittered scatter). Also present: pie/polar/radar/sankey/segments/stem/facets.

That said, adoption should still be **additive on the point-plot path only**
(scatter/line/area/strip + ecdf): everything else
(box/histogram/violin/bar/density_*) is already reduced server-side by
`services/figure/aggregate.py` to a few hundred numbers — Plotly is not the
bottleneck there, and px's kwarg surface (trendlines, marginals, faceting
options) is what dashboard YAML already speaks.

## 9. Theming (Mantine light/dark)

Verified live (`results/phase5_theming.json`, `theme_*.png`): the client
consumes 22 documented `--chart-*` CSS custom properties (text, grid, axis,
bg, tooltip, selection, modebar, …) **at runtime** — setting `--chart-text` on
the host flipped the computed tick-label color to the Mantine dark value
(`rgb(233,236,239)`) on the *same* ChartView instance, no re-render, no
refetch. A `.dark` ancestor class additionally switches the built-in dark
palette for chart chrome (modebar/badges/selection tint), and the canvas paint
picks up the host's background color. The PoC drives both from a theme toggle
using `plotlyTheme.ts`'s exact color formula (Mantine `gray[2]`/`gray[8]`,
translucent grids). No hardcoded colors needed; and unlike
today's path — where a theme toggle **refetches every figure** from the server
(`theme` is a fetch dependency in `FigureRenderer.tsx`) — xy theming is pure
CSS.

## 10. WebGL budget & screenshots

- **GL topology (measured):** xy charts hold **one shared WebGL context per
  page** (two mounted charts report the identical `gl` object; marks are
  blitted into per-chart 2D canvases; internal host budget
  `window.XY_CONTEXT_BUDGET`, default 12, with context-loss recovery).
  The `MAX_GL_PLOTS = 4` / 17-lost-canvases problem **does not exist** on the
  xy path: 30 xy tiles cost one live GL context; `webglBudget.ts` (which
  tracks only Plotly's contexts) is simply bypassed, and mixed dashboards
  reduce Plotly's own pressure by taking scatters out of the slot pool.
- **Screenshot system:** capture would keep working (tiles live in
  `.react-grid-item`, capture target is `.mantine-AppShell-main`), **but** the
  draw-readiness gate is Plotly-specific: `wait_for_plotly_drawn()` polls
  `.plotly-graph-div` and returns true immediately when none exist, so an
  xy-only dashboard would be gated by nothing but the fixed stabilization
  sleep. An integration needs a readiness signal (e.g. the wrapper setting a
  `data-xy-drawn` attribute after first rAF — trivial given the mount handle).
  Separately, `to_png()`'s native rasterizer (browser-free, ~170 ms for a 5k-pt
  chart in-process) is a candidate to *replace* Playwright for figure-tile
  thumbnails eventually.

## 11. Alpha risk & mixed-renderer cost

- **API churn:** six releases in three weeks; docs say pre-1.0 may break
  callback payloads with migration notes. P1 additionally rests on
  **undocumented** internals (`build_payload`, `renderStandalone`,
  `_cpu` arrays for selection recovery). Mitigations: pin `xy==`, vendor
  `standalone.js` at build time, keep the Phase-1 Playwright checks as a
  canary, and make the upstream ask (§6 P4).
- **Bundle cost:** xy client ~123 KB gzip vs `vendor-plotly` ~1.27 MB gzip
  (plotly.js-dist-min 2.35.3). Shipping both engines costs +10% of today's
  chart-vendor bytes; a `vendor-xy` manualChunk loads lazily like the rest.
- **Duplicated surface:** a second renderer means a second theming shim
  (§9 — small), a second selection adapter (§7 — the PoC's ~80-line wrapper),
  and a readiness hook for screenshots (§10). No wasm plumbing needed in Vite.
- **Not covered by xy:** px-style kwargs (trendline, marginals, log axes are
  present but faceting/kwarg parity is unverified), server-side theme
  templates, and the aggregation path — all reasons the adoption is additive,
  not a replacement.
- **Data-fidelity nuance:** density tier means the browser holds a surface +
  sample, not rows; hover shows exact values only for retained points unless
  `density=False`. Today's UX shows 10k of 1M points — xy's density surface is
  strictly more faithful, but it is not "every row in the DOM".

## 12. Recommendation

**GO — scoped and conditional.** The spike meets both of #945's criteria:

1. **Reflex-free mount path:** demonstrated end to end (P1) — React 18 wrapper,
   real DC data through `load_deltatable_lite`, selection → `InteractiveFilter`
   emission, Mantine-token theming.
2. **Measured win on real data:** at 1M–10M rows, xy serves **all points** at
   ~150 ms render / ~264 KB payload / ~8 MB heap where the shipped baseline
   serves a 10k–50k sample at 0.47–0.9 s render / up to 1.9 MB payload — and
   the full-fidelity plotly counterfactual is 10.4 s / 38 MB / 274 MB heap at
   1M. Interaction: ~60 fps on xy at every N vs 23 fps (10k sample) down to
   0.4 fps (1M) on plotly.
   The GL-context budget problem disappears on the xy path.

Proposed next steps (separate issues, not this spike):
1. Integration RFC for an **opt-in `renderer: "xy"` on the scatter path**:
   server endpoint shipping `(spec, blob, ids)` from the existing load
   pipeline; `XyFigureRenderer` in depictio-react-core behind the existing
   `ComponentRenderer` dispatch; selection cap policy (direct tier ≤ ~200k,
   density above).
2. Upstream asks (P4): stable mount API + selected-indices on `xy:select`.
3. Screenshot readiness hook for non-Plotly tiles.
4. Re-evaluate `strip` + px-kwarg parity per release; revisit when xy
   publishes a JS package or hits 0.1.

**Re-evaluation trigger if deferred instead:** xy publishing a documented JS
entry point / npm package, or selection indices in browser events.

## Appendix — reproduce

```bash
uv venv --python 3.12.9 venv && uv pip install --python venv/bin/python -e ".[dev]"
uv pip install --python venv/bin/python xy deltalake playwright
venv/bin/python dev/xy_spike/gen_data.py            # Delta tables + read-path check
venv/bin/python dev/xy_spike/phase1_payloads.py     # payloads + size table
venv/bin/python dev/xy_spike/phase1_browser.py      # mount + selection findings
venv/bin/python dev/xy_spike/phase1b_browser.py     # density tier + GL topology
venv/bin/python dev/xy_spike/bench_python.py        # python_timings.csv
venv/bin/python dev/xy_spike/gen_browser_assets.py
venv/bin/python dev/xy_spike/bench_browser.py       # browser_timings.csv
venv/bin/python dev/xy_spike/phase5_theming.py
(cd dev/xy_spike/poc && npm i && npx esbuild main.tsx --bundle --outfile=app.js \
  --jsx=automatic --minify && venv/bin/python gen_poc_assets.py)
venv/bin/python dev/xy_spike/phase6_verify.py
```
