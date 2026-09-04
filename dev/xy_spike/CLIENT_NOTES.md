# xy 0.0.6 browser-client internals — spike notes (issue #945)

> **Version-pinned**: everything below was read from the `xy==0.0.6` wheel and
> verified in Chromium 1194 (Playwright). xy is alpha; pre-1.0 releases may
> break any of it. Treat these as observations, not contracts.

## The Reflex-free mount path exists (path 1 = viable)

`to_html()` is a thin wrapper (`xy/export.py:285`):

```python
spec, blob = fig.build_payload()          # xy/_payload.py:197 — public-ish
# … inline standalone.js + base64(blob) …
# bootstrap:
xy.renderStandalone(document.getElementById("chart"), spec, buf)
```

- The wheel ships the browser client as **separable static assets**:
  `xy/static/standalone.js` (IIFE, global `xy`) and `xy/static/index.js`
  (ESM, used by the anywidget notebook path). Each ≈ 430 KB raw /
  **≈ 123 KB gzip**. Pure JS + WebGL2 — no WASM.
- Exports on the bundle: `renderStandalone(el, spec, bytes) -> ChartView`,
  `render` (live-host variant), `ChartView`, `decodeFrame`, `markOf`,
  `MARK_KINDS`.
- `Figure.build_payload(px_width=None) -> (spec: dict, blob: bytes)` gives the
  exact pair the bootstrap consumes: `spec` is small JSON (~1–2 KB), `blob` is
  typed binary column buffers. `build_payload_split` also exists.
- **Verified live**: two charts mounted in one page from external
  `standalone.js` + fetched spec/blob, no Reflex, no to_html, no errors
  (`phase1_browser.py` → `results/phase1_findings.json`).

None of this is in the documented public API — the docs only document
`to_html()`. Upstream ask (path 4 note): publish `renderStandalone` +
`build_payload` as a stable, versioned contract (or an npm package).

## GL topology: one shared WebGL context per page

- Per chart, the DOM holds **2D canvases only** (marks blitted from GL).
  The WebGL2 context lives on a **detached off-DOM canvas** managed by an
  internal "GL host" registry (`window.XY_CONTEXT_BUDGET`, default 12;
  `window.XY_SHARED_WEBGL` override).
- **Verified live**: two ChartViews report `a.gl === b.gl` and the same GL
  canvas — all charts on a page share one context.
- Consequence for Depictio: the entire `webglBudget.ts` problem
  (Plotly = 3 GL canvases × chart, Chrome cap 16, `MAX_GL_PLOTS = 4`,
  SVG fallback at 3k pts) does not exist on the xy path. Any number of xy
  tiles cost one live GL context total.
- Context-loss handling is built in (`webglcontextlost` replay + recovery
  timer on the host).

## Selection / row identity (browser-local, no Python)

- Event contract: `ChartView._dispatchChartEvent(name, detail)` →
  `CustomEvent('xy:'+name, {detail, bubbles: true, composed: true})` on the
  chart root. Events: `xy:hover`, `xy:click`, `xy:select`, `xy:view_change`.
- Gesture: **Shift+drag** box select (or `dragMode` starting with `select`);
  modebar buttons wire the same paths.
- `xy:select` detail = **`{total, range|polygon, view}` — no indices** in
  standalone mode. Indices are computed internally (CPU loop over retained
  `trace._cpu.x/y`, mask uploaded to GPU) but not exposed.
- **Row identity is recoverable client-side**: `renderStandalone` retains
  exact coordinates as `view.gpuTraces[i]._cpu.{x,y}` (+ `xMeta/yMeta`
  offset/scale) for non-density scatter. Replaying the range/polygon test
  over those arrays reproduced the selection exactly (13 847/13 847 at 50k
  pts) and mapped positional indices → id strings
  (`results/phase1_findings.json: recovered_indices_small`). Row order ==
  canonical row order == the Polars frame's row order, so Depictio's
  `selection_column` values can ride as a plain aligned JS array (xy has no
  per-point customdata channel).
- `xy:click` detail carries `{row: {trace, index, x, y}, index, trace, view}`
  — full per-point identity locally.

## The density-tier boundary (the one real limitation found)

- Above ~200k points/trace the scatter switches to `tier: 'density'`:
  the payload becomes a fixed-size density surface + deterministic sample
  (1M pts → **264 KB** blob vs 800 KB for 100k direct) — screen-bounded and
  flat-scaling, this is where the "0.08 s at 100M" claim comes from.
- **Verified live**: at density tier, browser-local selection selects
  nothing and fires no event; `_cpu` arrays are absent
  (`results/phase1b_findings.json: density_1m`). With a live Python host the
  client sends `select_polygon` over comm instead — that transport is the
  Reflex/notebook path Depictio would not have.
- Knob: `xy.scatter(..., density=False)` forces direct tier at any N —
  1M pts → 8 MB blob (2 × f32 columns), CPU arrays retained, selection
  works. So browser-only cross-filtering is a policy choice:
  direct tier (full selection) up to a chosen N, density tier (view-only,
  no selection) beyond.

## Sizing (measured, `results/payload_sizes.csv`)

| N | spec | blob | to_html file | build_payload | to_html |
|---|---|---|---|---|---|
| 20k | 1.3 KB | 160 KB | 656 KB | 0.9 ms | 4.2 ms |
| 50k | 1.3 KB | 400 KB | 976 KB | 0.7 ms | 4.8 ms |
| 100k | 1.3 KB | 800 KB | 1.5 MB | 0.9 ms | 6.3 ms |
| 1M (density) | 2.1 KB | 264 KB | 796 KB | 17.7 ms | 12.2 ms |
| 1M (density=False) | 2.1 KB | 8.0 MB | — | 21 ms | — |

Blob = 8 bytes/pt at direct tier (two f32 + overhead), fixed ≈ 264 KB at
density tier. The client JS (~123 KB gzip) is ~10× smaller than
`plotly.js-dist-min` 2.35.3 (~1.27 MB gzip).

## Misc

- `ChartView` public-ish surface seen: `setView(ranges, opts)`, `resetView`,
  `resize`, `destroy` (+ internal `_clearSelection`, `applySelection` via
  state patches). A wrapper's imperative "clear selection" hook exists
  (`clearSelection` paths) — mirror of `FigureRenderer.tsx`'s
  `Plotly.restyle` escape hatch.
- Standalone HTML emits a defensive CSP (`script-src 'unsafe-inline'`,
  `worker-src blob:`) — only relevant to iframe embedding (path 3), not to
  the direct mount, which needs no inline scripts.
- WebGL renderer in this container: SwiftShader (software) — all browser
  timings in this spike carry that caveat.
