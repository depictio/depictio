# RFC — Serverless Depictio (backend-less deployment)

**Status:** Draft / design only (no code).
**Audience:** maintainers.
**Related:** `depictio/viewer/vite.catalog-preview.config.ts` + `depictio/viewer/src/catalog-preview/`
(the working precedent this generalises), `depictio/catalog/payload.py`,
`depictio/api/v1/deltatables_utils.py`, `depictio/api/v1/services/figure/figure_builder.py`,
`docs/design/rfc-reshape-on-render.md` (see §11).

> This RFC is design-only. It is **not** a deliverable of the change that
> introduced it; it captures a direction to validate before any code is written.

> **On the word "serverless".** Used here in its literal sense — *no backend at all*, the page runs
> entirely in the browser. Not the cloud-industry sense (FaaS / Lambda), where a server still exists
> and is merely unmanaged. "Backend-less" is the precise term; "serverless deployment" is the one
> we use in conversation.

## 1. Context

Viewing a dashboard today requires the whole stack: FastAPI + MongoDB + Redis + MinIO + a Celery
worker. Every filter interaction is a network round-trip that ends in Polars reading a Delta Lake
table from S3. So a dashboard cannot be handed to someone — as a paper supplement, a GitHub Pages
demo, a reviewer artifact, a zero-install trial — without also deploying a backend.

The target capability: **preformatted data in → Depictio renders with no server → host it anywhere**
(GH Pages, an S3 website, a file on disk), with interactive filtering still working.

Two facts make this tractable rather than a rewrite:

1. **Rendering is already 100% client-side React.** `packages/depictio-react-core/` holds the real
   renderers; the remaining Python is a *data + figure-JSON service*.
2. **A working backend-less build already ships.** `depictio catalog preview --out x.html` emits one
   self-contained HTML that runs the **real** `ComponentRenderer` with no network, via a Vite
   `resolveId` plugin that swaps `api.ts` for a payload-reading shim.

The gap is narrow and specific: that shim **ignores the `filters` argument everywhere**
(`mockApi.ts` returns `filter_applied: false`), so the existing backend-less mode is a frozen
snapshot.

> Note: `CLAUDE.md` still documents a "Dash Multi-App Architecture" and `depictio/dash/app.py`.
> That directory no longer exists — the Dash → React migration is complete. The stale doc misleads
> anyone (or any tool) orienting in the repo and should be corrected independently of this RFC.
> `depictio/react-frontend/` is likewise a dead prototype: not in `pnpm-workspace.yaml`, not in
> compose, and its README still claims Dash is production.

## 2. Problem

### 2.1 Framing: a deployment mode, not an export

An earlier draft of this RFC was scoped as "static dashboard export" and centred on a CLI that
snapshots a *running* instance. That framing was wrong in a way that mattered:

- It named a **workflow** rather than the **capability**. Export is one route to backend-less
  rendering, not the thing itself.
- It made a live backend a **prerequisite**. But "preformatted data → render" needs no server at
  all: a dashboard spec plus local Parquet is sufficient input.
- It hid the real contract. The durable artifact is the **manifest schema** (§3.1), not any one
  command. Once the manifest is the interface, producers are plural and cheap.

So this RFC is structured as three layers: a **contract**, a **runtime** that consumes it, and
**producers** that emit it. Export-from-instance is one producer among others.

### 2.2 The technical problem

Making the existing backend-less bundle *interactive* means moving four server responsibilities into
the browser: filtering, aggregation, figure construction, and cross-DC link resolution. A naive
reading says that's a rewrite of the ~4.9k-line `dashboards_endpoints/routes.py` render layer plus
the ~1.6k-line `deltatables_utils.py` load layer.

It is much smaller than that, but only if three specific traps are avoided. Sections 4–6 are those
traps and their resolutions.

### 2.3 What the reference dashboards actually contain

Measured across all 50 `.db_seeds/*.json` (251 components), because the tiering rests on it:

| type | count | | type | count |
|---|---|---|---|---|
| `interactive` | 60 | | `figure` | 27 |
| `advanced_viz` | 54 | | `text` | 15 |
| `card` | 47 | | `table` | 15 |
| `multiqc` | 32 | | `map` | 1 |

- **Interactive types in practice: only 3** — `MultiSelect` 43, `RangeSlider` 13,
  `DateRangePicker` 4. No `Timeline`, `Slider`, `TextInput` or `SegmentedControl` in any seed.
- **Figures: 18 `mode:"code"` vs 9 `mode:"ui"`.** The split is structural, not incidental:
  `penguins`/`iris` are mostly ui-mode; **`viralrecon` 7/7, `ampliseq` 2.14 6/7, 2.16 1/1 are
  code-mode.** Code mode is where the scientific content lives.
- **`filter_expr`: 7 occurrences, 4 distinct, all row-level, zero `.over()`** — e.g.
  `col('q_val') < 0.05`, `col('Phylum').is_not_null() & (col('Phylum') != '')`. The grammar
  supports `.over()` window predicates (`depictio/models/components/filter_expr.py:19-36`) but
  nothing uses it.
- **advanced_viz kinds:** `embedding` 9, `complex_heatmap` 5, `da_barplot` 4, `volcano` 4,
  `stacked_taxonomy` 4, others ≤3. The 6 Celery-dispatch kinds account for ~22 of 54; the other
  ~32 already render client-side from `POST /advanced_viz/data`.
- Dashboard documents are 3–35 KB of JSON. Largest single table is a 25 MB Parquet; most are 1–3 MB.

### 2.4 What cannot cross over

- **6 Celery computes are filter-dependent** (`filter_metadata` is in their payload): embedding
  (pca/umap/tsne/pcoa), complex_heatmap (scipy clustering), upset, sankey, coverage_track.
  `packages/plotly-complexheatmap` and `packages/plotly-upset` are **Python** packages.
- **Code-mode figures** execute arbitrary user Python via RestrictedPython.
- **MultiQC** rendering imports the whole `multiqc` package.
- **Maps need network tiles.** `services/map/render.py` emits MapLibre `scattermap` traces, so
  "zero network" and a basemap are mutually exclusive. A frozen map keeps the dashboard's own
  `map_style`, so its basemap loads for an online reader; offline, the static runtime probes the
  basemap host once and draws the same markers on a blank background (`mapBasemap.ts`). The
  basemap hosts (`BASEMAP_HOSTS`, `depictio/serverless/maps.py`) are the only network a bundle
  may reach for a map.

**A bounded prerender cross-product cannot rescue these.** Every real dashboard mixes
high-cardinality MultiSelects (`sample`, `Phylum`) with **continuous** RangeSliders (`AF`, `lfc`,
`rel_abundance`), so the filter state space is unbounded. Frozen means frozen at the default state.

## 3. Proposal — contract, runtime, producers

### 3.1 The contract: a bundle manifest

One schema, describing a dashboard's layout, its data references, its per-component liveness, and
its frozen payloads. This is the interface; everything else plugs into it.

Three delivery modes share the schema; only `data_refs[].uri` changes:

| | `single-file` | `static-dir` | `remote` |
|---|---|---|---|
| output | one `.html` | `index.html` + `data/` + `frozen/` | `index.html` |
| `uri` | `inline:dc_<id>` | `data/<id>.parquet` | absolute URL |
| read | `Uint8Array` from base64 | `fetch` | `fetch` + `Range:` per row-group |
| CORS | none | none | required on bucket |
| ceiling | ~40 MB | ~GB | ~GB |

All runtime URI resolution goes through one `resolveUri(manifest, uri)` helper, so base-path bugs
have exactly one place to live.

### 3.2 The runtime: three component tiers

- **Live:** `figure` (ui-mode, and recognised code-mode — §7), `card`, `table`, `interactive`,
  `text`, advanced_viz data-path kinds. Filters re-query in the browser.
- **Partial:** components whose fidelity degrades (e.g. a DC above `FIGURE_MAX_POINTS`, where the
  build samples before filtering rather than after).
- **Frozen:** everything in §2.4. Ships a precomputed default-filter result with a **visible badge**
  — never dropped, never silently wrong.

The runtime is the existing viewer with three modules shimmed out (§8). It does not know or care
which producer built its manifest.

### 3.3 The producers

| producer | needs a backend? | tiers it can emit | use case |
|---|---|---|---|
| **A — export from instance**<br>`depictio dashboard export-static <id>` | yes (Mongo + S3 + API) | live · partial · frozen | snapshot an existing dashboard; full fidelity |
| **B — build from spec**<br>`depictio dashboard build-static --spec d.yaml --data ./parquet/` | **no** | live · partial only | author against local files; never run a server |
| **C — API endpoint**<br>`POST /dashboards/{id}/export-static` | yes | same as A | an "Export static" button in the UI |

**Producer B is the one the earlier framing missed**, and it is close to free once the manifest
exists: joins are already materialised at ingest (`depictio/cli/cli/utils/joins.py:316`), so one
component reads one flat table and there is no query planner to stand up.

**Its honest limit:** the frozen tier is computed by real Python (MultiQC, the Celery computes,
code-mode scaffolds). Producer B therefore *omits* those components rather than freezing them.
Full-fidelity bundles need producer A. This must be reported by `--check`, not discovered later.

A `--check` / preflight mode prints the per-component live/frozen/omitted table with reasons and
writes nothing. This is what makes the feature usable: authors can see *why* a component degraded.

### 3.4 Why not Pyodide

Ruled out on evidence. The data layer cannot go there: `polars` and `deltalake` are Rust,
`pymongo`/`motor`/`redis` need raw sockets, `umap-learn` pulls `numba`/`llvmlite` (no Pyodide
support at all), `multiqc` is a large tree. Only `plotly` + `narwhals` would port — and plotly.js is
already in the bundle. Pyodide buys a ~30 MB runtime and leaves the data problem unsolved.

> **Update (§13.6).** Still not the data layer — the in-browser engine stays hyparquet + typed-array
> kernels. But as an *optional add-on* for the computes TypeScript cannot reproduce (arbitrary
> code-mode figures, group comparisons, PCA / PCoA / t-SNE), Pyodide 314.0.7 now packages polars,
> boots from `file://` with zero network, and runs the server's own Python. Measured: +37 MB
> (core + numpy + polars) to +69 MB per bundle, ~8 s boot; embedded only when a tile needs it.

### 3.5 Why not DuckDB-WASM as the primary engine

It was the obvious choice and it is the wrong one **for the inlined single-file mode**: its `eh`
bundle is tens of MB of wasm, which base64-inlined dwarfs the payload. For reference, the existing
catalog-preview bundle is **7.27 MB (2.20 MB gzip)** — that is the floor for `single-file`, and the
budget DuckDB-WASM would blow.

It is also unnecessary. The query surface is **single-table, no joins** — `load_deltatable_lite`
raises `NotImplementedError` on joined DC ids (`deltatables_utils.py:~1140`) and
`join_deltatables_dev` (`:1567`) is dead. The operations are 7 predicates, ~12 scalar reductions,
one `group_by+sort+head`, `unique`, `min/max`, `sort+slice`.

Proposal: **`hyparquet` (pure-JS Parquet reader, ~30 KB, async byte-range reader) plus hand-written
kernels over typed arrays in a Web Worker**, behind a `QueryEngine` interface. hyparquet's async
reader gives `remote` range requests for free, `static-dir` via plain `fetch`, `single-file` via a
`Uint8Array` over an inlined blob. No `SharedArrayBuffer` → **no COOP/COEP → GH Pages works
unmodified**. DuckDB-WASM stays a pluggable second engine behind the same interface if datasets
outgrow the browser heap.

> **Open question / first task.** The bundle-size figure above is reasoned, not measured. Measure it
> before committing. If DuckDB-WASM proves acceptable for `static-dir`/`remote`, the interface makes
> that a config choice rather than a rewrite.

## 4. Trap 1 — do not port plotly-express. Bind and refill.

A faithful TS port of px's partitioning, colorway cycling, facet-domain math, hovertemplate
synthesis and legend dedupe is ~1000+ LOC with a long fidelity tail. Avoid it by exploiting one
invariant:

> **Filtering only removes rows. It can never create a new trace, a new colour, or a new facet.**

So the trace set built on unfiltered data is always a superset of any filtered view.

**At build time:** build the figure with the **real** `create_figure_from_data(...)` on the
unfiltered frame — layout, colorway, faceting, hovertemplates, coloraxis and the mantine template
are all authentic. Then compute px's grouping columns in order
(`[color, symbol, line_dash, line_group, pattern_shape, facet_row, facet_col]`), match each trace to
exactly one group tuple via `legendgroup`/`name` (facet cells disambiguated by `xaxis`/`yaxis`), and
emit a **binding table**: per trace, its group predicates and which column feeds which field.

**At runtime:** per binding, AND the group's equality predicates onto the current filter mask,
project the bound columns, write the arrays into the trace in place. Empty group → `visible:false`.
Layout never changes.

This is exact where it matters: histogram binning, box quartiles, violin KDE and `histogram2d` are
computed **by plotly.js** from the raw arrays it receives — precisely what the server used to send.
It also makes two things *in scope* that looked like blockers: `trendline` and
`marginal_x`/`marginal_y` (raw-data traces in scaffold-fixed subplot domains, so they bind as
ordinary raw traces). Every px trendline kind is refit in TypeScript, without the Python runtime:
`ols` (closed-form, with `add_constant`/`log_x`/`log_y`), `lowess` (the statsmodels kernel, px's
`frac=0.6666666`, `it=3`, `delta=0`), and `rolling`/`expanding`/`ewm` (pandas' window kernels for
mean/sum/min/max/median/std/var/count) — `packages/depictio-static-core/src/trendline.ts`, pinned
against px by `fixtures/trendline-expected.json`. A time-offset or weighted window, a `step`,
another aggregation or an overall-scope fit stays frozen, and says which.

**Degradation is structural:** any trace that fails to match exactly one tuple freezes the whole
component rather than rendering something wrong.

Accepted deviations, to be asserted as *named exemptions* in the differential tests rather than
silently tolerated:

| deviation | server | bind-and-refill | verdict |
|---|---|---|---|
| `marker.sizeref` | recomputed on filtered data | fixed at unfiltered max | ours is better (stable bubble scale) |
| `coloraxis.cmin/cmax` | recomputed on filtered | global range | ours is better |
| categorical axis ticks | vanished category disappears | tick retained, trace hidden | arguably better; visible diff |
| `FIGURE_MAX_POINTS` (50k) | `sample(seed=0)` *after* filtering | build samples, runtime masks | real loss → `partial` + badge |
| `area`/`stackgroup` | stacks the filtered frame | stacks refilled arrays | low risk; note it |

## 5. Trap 2 — do not port Polars' string and date semantics. Materialise them.

The filter translator is one function — `add_filter` (`deltatables_utils.py:125`), 7 predicates —
but two of them hide most of the project's fidelity risk. Push that work to build time instead:

```python
# categorical filters (Select/MultiSelect/SegmentedControl) and DC-link columns
pl.col(c).cast(pl.Utf8, strict=False).alias(f"__u8__{c}")

# DateRangePicker / Timeline columns
pl.coalesce([
    pl.col(c).cast(pl.Utf8, strict=False).str.to_datetime(strict=False).dt.replace_time_zone(None),
    pl.col(c).cast(pl.Utf8, strict=False).str.strptime(pl.Datetime, "%Y-%m-%d", strict=False),
]).dt.epoch("us").alias(f"__ts__{c}")

# component-static row-level filter_expr (no .over())
build_filter_expr(expr).alias(f"__fe__{sha1(expr)[:8]}")   # boolean
```

This removes three problems outright:

- **`cast(Utf8)` is not `String(x)`.** Polars renders `3.0`→`"3.0"`, `true`→`"true"`, and
  `Datetime(us)` with microseconds; JS gives `"3"`. Reimplementing that in TS is a permanent bug
  farm. The `__u8__` column reduces predicate #1 to set membership.
- **The ~80-line datetime-normalisation branch** (`add_filter:163-243`) becomes an integer compare.
- **`filter_expr` entirely.** It is *component-static* — it does not depend on user filter state —
  so it materialises as a boolean column the client just ANDs in. No TS Polars-expression parser.
  Only `.over()` needs freezing (a window predicate's correctness depends on whether the window
  spans filtered or unfiltered rows), and nothing currently uses it.

Import these from **one shared helper** so they cannot drift from `add_filter`; ideally refactor
`add_filter`'s date branch to *call* that helper so build and server share one expression.

Two remaining subtleties that must be ported verbatim or cause quiet systematic drift:

- **Filters bind by column *name*, not `dc_id`.** `_build_filter_metadata` (`routes.py:1418`) drops
  `dc_id`; `apply_runtime_filters` (`deltatables_utils.py:1411`) keeps only filters whose
  `column_name` is in `df.columns` and skips the rest *individually*. This is the de-facto cross-DC
  filtering mechanism, independent of DC Links.
- **`str.contains` is regex by default**, not substring — `LIKE '%v%'` is not equivalent. (Rust's
  `regex` has no lookahead, so JS is a superset and any pattern Polars accepts works.)

Aggregation traps for the differential suite: Polars `std`/`var` default **ddof=1**; `n_unique()`
counts null as a distinct value; `count` is `drop_nulls().len()`, not row count; `median` uses
`interpolation="linear"`; `box_plot_stats` uses Tukey fences with a min/max fallback when IQR=0.

## 6. Trap 3 — re-export Parquet, do not copy Delta part-files

Globbing `data/**/*.parquet` from a Delta table is unsafe: `_delta_log` is the source of truth for
which files are live, and files removed by an overwrite stay on disk until `VACUUM`, so a naive glob
**double-counts rows**. Depictio rewrites DCs on re-ingest (hence `_get_aggregation_version`), so
tombstones exist in the wild. Being correct would mean reimplementing delta-rs in JS.

Re-export is wanted anyway: column pruning, codec control, row-group sizing for range requests, and
the §5 companion columns. Pruning unions `referenced_columns()` (`figure_builder.py:54`) per figure,
`_filter_columns()` (`deltatables_utils.py:640`) per interactive component, card columns, link
columns, and all columns for tables — then intersects with the real schema. Expect 2–5 of 80+
columns for figures.

Producer B skips the Delta step entirely: its input is already plain Parquet. It still applies
pruning and companion columns.

## 7. The code-mode transpiler is small, because §4 already did the hard part

Code-mode figures are two-thirds of the reference figures, so freezing them all would gut the
feature on exactly the dashboards that matter. They are also not lowerable to ui-mode kwargs — they
do real reshaping before plotting:

```python
df_modified = df.unpivot(on=['shannon','observed_features','faith_pd','evenness'],
                         index=['sample_id','habitat'], ...).filter(pl.col('value').is_not_null())
fig = px.box(df_modified.to_pandas(), x='habitat', y='value', color='habitat',
             facet_col='metric', facet_col_wrap=2, points='all', ...)
fig.update_yaxes(matches=None, showticklabels=True)
fig.for_each_annotation(lambda a: a.update(text=a.text.split('=')[-1], ...))
```

But under bind-and-refill you **do not translate the `px` call or the `fig.update_*` chain at all** —
the real Python runs once at build time to produce the scaffold. Only the **data prologue** needs
translating so it can re-run on filtered data, and prologue ops are all SQL-native. Measured across
the 18 real code-mode figures:

| prologue shape | count | treatment |
|---|---|---|
| no reshape (`df.to_pandas()` then px) | 6 | **live for free** — binds to the base table, zero transpilation |
| `group_by(...).agg(...)` (+ `sort`/`rename`/`reset_index`) | ~9 | transpiler stage 1 — the dominant shape |
| `unpivot` / `pivot` (+ `filter`) | 2 | transpiler stage 2 |
| whole-frame viz (`scatter_matrix`, `sunburst`) | 3 | **frozen regardless** — not in `ALLOWED_VISUALIZATIONS` |

Realistic ceiling ≈ **15 of 18 code-mode figures live**, i.e. ~24 of 27 figures overall. The
`lambda` / `for_each_annotation` calls that look alarming are layout-only and captured in the
scaffold. Grammar is a closed allowlist; anything unrecognised freezes. Reuse the existing analysis
machinery (`services/figure/code_mode.py::analyze_constrained_code`) rather than writing a new parser.

Note this is a producer-A capability: it needs the real Python to build the scaffold. See §11 for
why `rfc-reshape-on-render.md` could lift that restriction.

## 8. Supporting decisions

**DC Links are mostly live, not merely precomputable.** The resolvers are pure functions of
`(source_values, link_config)` (~60 LOC to port). Only `_translate_filter_values` reads data, and it
is `SELECT DISTINCT link_col WHERE filter_col IN (...)` — runnable client-side when the source DC is
in the bundle (tier A), precomputed as a value-mapping table when it is not (tier B), or a freeze
signal when that table would be too large (tier C). Port `regex`/`wildcard` as the pass-through the
server currently does; "fixing" it client-side would make the bundle *diverge* from the server.

**Reuse `App.tsx`, do not reimplement it.** It owns filter orchestration (736 LOC). A sibling
reimplementation guarantees drift — exactly the trap `payload.py` fell into by reimplementing
aggregation and figure logic instead of calling `figure_builder`. For the same reason the new build
package must call the *real* server code paths, not re-derive them.

**Three module shims are needed, not one.** Beyond `api.ts`, `App.tsx` pulls `useCurrentUser`
(`viewer/src/hooks/useCurrentUser.ts:87`, raw `fetch`, not via `api.ts`) and `useDataCollectionUpdates`
(`packages/depictio-react-core/src/realtime.ts:169`, raw `WebSocket`). `bootstrapSession()` is not
bypassed — a separate entry HTML simply never imports it, exactly as `src/catalog-preview/main.tsx`
already does. Extract the existing `catalog-api-shim` plugin into a shared `moduleShim(map)` helper
so both bundles use one implementation.

**Badge placement.** Thread a `staticBadge` prop through `wrapWithChrome`
(`components/chrome/index.ts:27`) from a React context, so all 10 call sites in `ComponentRenderer`
are untouched and the normal server build renders nothing. Pin it **top-left and always visible** —
not in the hover-revealed action row, since a viewer must see it without hovering.

**Permissions (producers A and C).** `viewer` for preflight, **`owner`** for the build itself: a
bundle is bulk data exfiltration and should not be available to every viewer.

### 8.1 Size envelope for `single-file`

Measured on the five reference families (v1.5.0, 2026-08-06):

| family | file | Parquet (base64) | rows × cols | frozen payloads |
|---|---|---|---|---|
| iris | 8.1 MB | 0.01 MB | 150 × 7 | 0.01 MB |
| penguins | 8.1 MB | 0.01 MB | 342 × 12 | 0.04 MB |
| advanced-viz-showcase | 8.7 MB | 0.19 MB | 11 793 × 55 | 0.33 MB |
| ampliseq | 11.0 MB | 1.37 MB | 58 495 × 68 | 1.33 MB |
| viralrecon | 11.1 MB | 0.20 MB | 21 096 × 75 | 1.39 MB |

Three facts fall out, and they set the budget:

* **The runtime is the floor** — ~7.7 MB raw in every bundle whatever the data. The CI byte budget
  (3.20 MB gzip) guards *that* number; this section is about everything on top of it.
* **Data is cheap**: ~2 bytes per cell in snappy Parquet after column pruning and codebooks.
* **Frozen payloads are not** — viralrecon ships 1.39 MB of frozen figures against 0.20 MB of live
  data. Every component moved from frozen to live makes the bundle *smaller*, not larger.

**Recommended ceiling: 25 MB**, roughly 300k rows × 20 columns at the measured density. Beyond that
`single-file` degrades for reasons that are not the file size itself: nothing renders until the whole
document is parsed, and the payload is resident three to four times over (HTML text, base64 string,
ArrayBuffer, materialised columns). The hard wall is V8's maximum string length (~512 M chars), but
distribution bites long before — GitHub rejects a file over 100 MB, mail attachments cap near 25 MB.

Above the ceiling the answer is a different `BundleMode`, not a bigger file: hyparquet reads Parquet
by byte range, so a directory-mode bundle fetches only the column chunks it touches and the ceiling
essentially disappears. The trade is distribution, not capability — a page opened from `file://`
cannot `fetch` its sibling files (Chrome blocks `file://` sub-resources from a `file://` origin), so
directory mode needs a host, even a local one. The two modes serve two channels; neither replaces
the other.

## 9. Phasing

Roughly 9–12 engineer-weeks for someone fluent in the codebase; ~3 months part-time.

| phase | scope | est. |
|---|---|---|
| 0 | **Manifest schema + runtime against a hand-written fixture.** Shim-plugin extraction, static entry, badge, all tiers frozen. No Mongo, no S3, no producer. | 1 wk |
| 1 | **Producer B** (build from spec + local Parquet) + the data layer: Parquet ingest, pruning, companions, query kernels. Live cards / interactive / text. | 2 wk |
| 2 | **Producer A** (export from instance) + the frozen tier. | 1 wk |
| 3 | Live tables (sort + slice over the mask). | 0.5 wk |
| 4 | Live advanced_viz data-path kinds (~14 of 20 renderers, ~30 LOC of shim). | 0.75 wk |
| 5 | Live ui-mode figures via bind-and-refill. **Highest risk.** | 2.5 wk |
| 6 | Code-mode transpiler (stage 1 no-reshape + group_by; stage 2 unpivot/pivot). | 1.5 wk |
| 7 | DC Links + maps. | 1 wk |
| 8 | Producer C (API endpoint + Celery job + artifact lifecycle). | 1 wk |
| 9 | Remote mode, base paths, size budgets, GH Pages recipe. | 1 wk |

Phase 0 changed under the §2.1 reframing and is better for it: rendering a **fixture** manifest
decouples all the TypeScript from Mongo/S3, so it is testable with zero infrastructure and pins the
contract before any producer exists. Producer B now precedes producer A, because it is simpler, has
no infrastructure dependency, and exercises the same manifest.

Phase 4 is the best value-per-effort and should precede figures. Phase 5 is where the schedule will
slip; the mitigation is structural (binding failure → frozen + badge), so it can ship at partial
coverage and improve incrementally.

**Out of scope:** dashboard editing; unrecognised code-mode prologues; `heatmap` /
`plotly_complexheatmap`; whole-frame vizzes; live MultiQC; the 6 Celery advanced_viz computes;
JBrowse; live images; realtime/WebSocket; notes persistence; auth and sharing; multi-dashboard site
export; any write path; `.over()` `filter_expr`; Pyodide.

## 10. Verification

**Differential testing is the core of the strategy** — it is the only thing that makes client-side
filtering trustworthy. Per seed dashboard, generate N filter states (empty; each control alone at
1/2/all values; random k-subsets; boundary ranges; date ranges covering and excluding everything).
Produce the golden side by calling the real endpoint *bodies* in-process
(`bulk_compute_cards`, `render_table_endpoint`, `build_figure_preview`, `fetch_advanced_viz_data`)
and commit the fixtures so CI needs no Mongo/S3. Replay the same states against the TS kernels over
the bundled Parquet and compare.

Comparison rules stated up front: ints exact; floats `|a-b| <= 1e-9*max(1,|a|)`; row *sets* exact;
row *order* exact only where a sort is specified; figure traces compared as
`{trace_index → sorted(x,y) pairs}` (px does not guarantee cross-group array order); the §4
deviations asserted as named exemptions. Failure output must print the filter state, component,
column and both values — half the value of the harness is telling you *which* trap you hit.

Supporting layers: unit tests shaped like `depictio/tests/catalog/test_payload.py` (including its
`test_*_is_json_serialisable` guard — NaN/Inf tokens blank the whole embedded blob), a
`test_companion_columns_match_add_filter` equivalence test, Playwright specs under
`depictio/tests/e2e-playwright/` (`no-network`, `filter-parity`, `badges`, `base-path`,
`range-requests`), and a CI byte-budget guard on the single-file bundle — bundle bloat is the
failure mode that silently ruins `single-file`.

## 11. Open questions

- **Engine choice** (§3.5) — measure DuckDB-WASM's real inlined cost before committing to hyparquet.
- **Trace-binding match rate** (§4) — the logic is sound, but matching against
  `legendgroup`/`name`/`xaxis`/`yaxis` is empirical. The honest measure of phase 5 is the match rate
  across the 27 seed figures, which nobody has measured yet.
- **Does producer B need its own spec format?** Reusing `DashboardDataLite`
  (`depictio/models/models/dashboards.py`) is attractive — a dashboard authored for a server and one
  authored for a static build would be the same document — but it carries `wf_id`/`dc_id` ObjectIds
  that are meaningless without a backend. Either the spec gains symbolic DC references resolved
  against `--data`, or producer B is restricted to specs previously exported from an instance, which
  would undercut the "never run a server" claim. **This is the main unresolved design question.**
- **Staleness semantics.** A bundle is a point-in-time snapshot: link translation tables, frozen
  prerenders and Parquet all go stale together when a DC is re-ingested. Should the manifest carry
  source DC versions and warn on mismatch when rebuilt?
- **Relationship to `rfc-reshape-on-render.md`.** A lazy `recipe@render` reshape is the same shape of
  problem as §7's prologue transpiler — both need "re-run a declared reshape against filtered data".
  If that RFC lands first, code-mode figures expressed as declarative renders become live for free,
  the transpiler shrinks to a migration aid, **and producer B gains reshaping without needing
  Python** — which would materially widen what a backend-less build can express. Worth sequencing
  deliberately.

## 12. Errata vs. main@4ee7924 (v1.3.1)

This RFC was written against v1.2.1. Main has since had major perf refactors to the exact files it
cites. Verified corrections — implementation must encode these, not the original text:

1. **§5 categorical predicates changed direction (critical).** `add_filter` is now at
   `deltatables_utils.py:225` and gained a `dtype` parameter. Categorical filtering is no longer
   `pl.col(c).cast(pl.Utf8).is_in(...)` — it is `_categorical_predicate` (`:138`), which casts the
   **values** to the column dtype (String → bare `is_in`; numeric/Date → `cast`; Datetime →
   `str.to_datetime` then cast; Time → `str.to_time`; else the old Utf8 fallback), so parquet
   row-group statistics and dictionary pushdown survive. Its docstring notes the old column-cast
   form *never matched temporal values* — copying §5 as written would reintroduce a fixed bug.
   Resolution: replace the `__u8__` companion columns with **codebooks** — at build time, map each
   categorical-filtered non-String column's unique values to dense integer codes (companion Int32
   `__code__<col>` + a `{json_serialized_value: code}` codebook serialized through the same
   `_json_safe` path that produces MultiSelect options, so option values and codebook keys are
   byte-identical by construction); at runtime, filtering is integer set membership — no casting
   semantics in JS at all. Extract `_categorical_predicate` + the datetime normalisation into
   `depictio/models/components/predicates.py` so build and server share one expression.
2. **New predicate branch:** `add_filter` gained a `LINK_NO_MATCH` sentinel
   (`"__link_no_match__"`, const `:135`) → `pl.lit(False)`. A browser port missing this branch
   renders **all** rows where the server renders none. The §5 predicate count is 6 branches / 9
   component-type strings, not 7 predicates.
3. **Line/size drift:** `App.tsx` 799 LOC (was 736); `useDataCollectionUpdates` at
   `realtime.ts:129` (`:169` is the `new WebSocket` inside it); `routes.py` 5528 LOC
   (`_build_filter_metadata` `:1606`, `bulk_compute_cards` `:1636`, `render_table_endpoint`
   `:2430`); `deltatables_utils.py` 2194 LOC (`load_deltatable_lite` `:1393`, joined-id
   `NotImplementedError` guards `:1442-1448` **and a second one in `count_deltatable_lite`
   `:1767`**, `apply_runtime_filters` `:1963`, `_filter_columns` `:834`, datetime branch
   `:274-356`, `join_deltatables_dev` `:2122` — still dead); `referenced_columns`
   `figure_builder.py:76`; `_get_aggregation_version` `:580`.
4. **`build_figure_preview` is a Celery task, not a route** (`celery_tasks.py:95`), called
   in-process by `render_figure_endpoint` (`routes.py:2288` → `:2410`). Preview and render share
   one worker code path — a single golden-fixture entry point.
5. **`fetchComponentData` (`api.ts:402`) is dead** — no callers; exclude it from the shim
   surface. The realtime shim is optional-for-correctness: `useDataCollectionUpdates` is inert
   when the dashboard document omits `project_realtime.enabled` (early return, no socket). Keep
   the shim for tree-shaking only.
6. **Badge placement (§8) revised:** `wrapWithChrome` has 9 call sites in `ComponentRenderer.tsx`
   plus a 10th in `advanced_viz/AdvancedVizDispatch.tsx:104`, which lives in a separately
   lazy-loaded chunk — an `opts`-threaded prop would miss it. Instead, read a
   `StaticBadgeContext` **inside `ComponentChrome`** (a real component, so it can `useContext`)
   with the provider above the `LazyMount`/`Suspense` boundary: zero call-site changes, no public
   signature change (`wrapWithChrome` is re-exported at `index.ts:76`).
7. **`load_deltatable_lite` gained `select_columns` and `init_data`**
   (`{dc_id: {delta_location, size_bytes}}`). The manifest's `data_refs` should mirror
   `init_data`'s shape — it is the already-proven "resolve a DC without an API round-trip"
   contract.
8. **Staleness token:** prefer `_get_aggregation_hash` (`deltatables_utils.py:607`, documented as
   the preferred cache-key salt) over `_get_aggregation_version`.
9. **`AdvancedVizLiteComponent` does not exist** in `depictio/models/components/lite.py`, yet
   advanced_viz is 54 of the 251 seed components — they pass the `LiteComponent | dict` union as
   raw dicts, unvalidated. Adding it is a prerequisite for producer B reusing
   `DashboardDataLite` as its spec.
10. **Amendment to §3.3:** producer B **may freeze ui-mode figures** by calling
    `create_figure_from_data` locally — `figure_builder.py` is Dash- and FastAPI-free, and
    `create_figure_from_data` (`:241`) consumes Polars natively and installs the mantine
    templates itself. Producer B's *omitted* set therefore narrows to: MultiQC, the 6 Celery
    computes, code-mode figures (RestrictedPython execution is a producer-A policy decision), and
    JBrowse. Also note `create_figure_from_data`'s newer `max_points` / `render_stats` out-params:
    frozen/binding builds must pin them (sampling ⇒ `partial` tier).
11. **§7 caveat:** `analyze_constrained_code` (`code_mode.py:18`) is a line/paren-counting
    splitter that returns raw Python source — reuse it for *classification*, but the prologue
    transpiler needs its own `ast`-based parser to emit a browser-executable IR; it cannot get
    referenced columns or ops from the existing analyzer.

## 13. Component compatibility (status on PR #963)

Tiers: **live** (filters recompute in the browser from the bundled Parquet), **live (Python)**
(recomputed in the browser by the server's own Python, in the optional Pyodide add-on, §13.6),
**frozen** (a snapshot at the export's default filter state, badged), **omitted** (left out, with
the reason in the tier table and the export modal). The per-kind source of truth is
`SERVERLESS_KINDS` in `depictio/api/v1/services/export/capabilities.py` — every `AdvancedVizKind`
must have an entry (import-time self-check +
`depictio/tests/unit/serverless/test_serverless_capabilities.py`); nothing is live by elimination.
Which tiles the Python runtime takes is `depictio/serverless/pyodide/plan.py`. Bundles draw the
**Paper** chrome (the app default), gated read-only; `?chrome=base` opts into Classic.

Rule of this pass: **every component the live server can render renders in a bundle.** Where the
browser cannot recompute it, the producer renders it at export with the server's own code and
ships the result, badged; where even the view needs a remote service (a genome browser, an image
store), the bundle shows an export-time snapshot or summary of it.

### 13.1 Component types and sub-features

| component / feature | tier | interactive? | notes / reason |
|---|---|---|---|
| card (hero value, multi-metric, all variants) | live | yes | q1/q3/percentile/skewness/kurtosis ported (`_agg_value` parity fixture) |
| card `filter_expr` (row-level) | live | yes | `__fe__<sha8>` companion evaluated with `build_filter_expr`; `.over()` windows → frozen (A) / omitted (B) |
| card breakdown / numeric layouts | live | yes | `cardLayouts` = `card_breakdown` / `card_metrics` (fixture parity) |
| card group-compare strip (`__group_compare__`) | — | no | not ported: the strip is absent under selection groups |
| card region / residue scoping | live | yes | `scopeRegionFilters` = `region_scope.scope_region_filters` |
| text, markdown, tab links, logos, live values, `{{param:KEY}}` | live | yes | `{{param}}` baked by producer A; B prints a dash |
| table | live | yes | `renderTableLive` |
| all interactive filters, funnel, `always_selected`, selection groups | live | yes | unchanged |
| persistent sections, floating maps, highlight | live / source's tier | as source | unchanged |
| figure ui-mode (bindable) | live | yes | bind-and-refill |
| figure ui-mode trendlines (ols + options, lowess, rolling / expanding / ewm) | live | yes | refit in TypeScript (`trendline.ts`), pinned to px by a parity fixture; a time-offset or weighted window, a `step`, another aggregation or an overall-scope fit stays frozen |
| figure ui-mode whole-frame visus | frozen | no | trace set is not a per-group partition |
| figure code-mode (transpilable, context folded) | live | yes | prologue IR + bind-and-refill |
| figure code-mode (arbitrary Python) | **live (Python)** / frozen | yes (Python) | re-run in the server's RestrictedPython sandbox (`code_executor.py`, verbatim) on every filter change, ≤ 200k filtered rows; frozen without the add-on |
| MultiQC plots / General Statistics | live (A) / omitted (B) | yes | GS data bars keep the export scale |
| map (scatter/density) | frozen (A and B) | no | the dashboard's own basemap when online; markers on a blank background offline. A choropleth: frozen (A), omitted (B: no region geometry) |
| image gallery | **frozen (snapshot)** — was omitted | no | default rows' images read from the bucket at export, ≤ 384 px thumbnails, ≤ 48, under the object budget; `blob:` URLs |
| JBrowse | **frozen (summary)** — was omitted | no | export-time session: assembly, locus, track table (`render_jbrowse` at the default state) |
| server-state (comments, annotations, versions, saved filters, avatar, editing) | hidden | — | shimmed to "not available in a read-only bundle" |

### 13.2 Advanced-viz kinds (54 on this branch)

| tier | before → after | kinds |
|---|---|---|
| live (data path) | 44 → 44 | unchanged (volcano, ma, qq, table-driven embedding, manhattan, stacked_bar, …, msa, sequence_track, hmm_logo, secondary_structure, domain_architecture, ranked_distribution, spatial_cells, allele_grid, pedigree, ranked_table) |
| live (replayed compute, TS port) | 1 → 2 | coverage_track, **contact_map** (`contactMapWindow` = `contact_map_window`, fixture parity; any window, any filter state) |
| live (objects shipped) | 0 → 3 | **molecule_3d** (+ 3Dmol.js add-on), **pae_matrix**, **ramachandran** — structure / PAE files read at export from the indexed_file DC (or the structure resolver, ≤ 12 entities), ≤ 24 MB / bundle, ≤ 8 MB / file |
| live (Python, optional) | 0 → 2 | **group_compare** (any pair, `group_compare_from_frame`, ≤ 50k rows), **embedding** with `compute_method` pca / pcoa / tsne (`_embedding_result_from_frame`, ≤ 5k / ≤ 1k rows) |
| frozen (export-time compute) | 3 → 4 | complex_heatmap, upset_plot, sankey, **group_compare** without the add-on (the tile's opening pair; another pair is refused with the reason, never relabelled); `embedding` + umap keeps its coordinates and drops filtered-out points |
| frozen (tree) | 1 → 1 | phylogenetic |
| omitted | 5 → **0** | — |

Counts, producer A, kinds: live 45 → 49 without the Python runtime (51 counting the Python-live
kinds), frozen 4 → 5 (→ 4 with Python, group_compare going live), omitted 5 → 0. Component
types: image and JBrowse omitted → frozen, arbitrary code-mode figures frozen → live (Python).

Producer B (no server, by design): Celery kinds without the Python runtime (complex_heatmap,
upset_plot, sankey, umap embeddings), MultiQC and phylogenetic stay omitted; group_compare is
now frozen there too (the service function runs on the local Parquet), and with the Python
runtime computed embeddings and code figures go live.

### 13.3 Cannot render at all vs renders but is not interactive

**Cannot render at all** (producer A), after this pass:

| what | why |
|---|---|
| a kind with no `SERVERLESS_KINDS` entry (a future kind) | refused by design until classified — never live by elimination |
| a tile whose export-time compute fails or exceeds the export's compute budget | omitted with the error in its detail; the build never aborts for one tile |
| a gallery / structure whose files exceed the object budget | the files that fit ship; the rest are named in the tier detail |
| (not on this branch) `bioimage_viewer` | see §13.5 |

**Renders, not interactive** (a snapshot or a frozen compute, badged): map (with its basemap online),
whole-frame visus, trendlines with an unported option (time-offset or weighted windows), complex_heatmap, upset_plot, sankey, phylogenetic, UMAP layout
(points follow filters), group_compare and arbitrary code-mode figures *without* the Python
runtime, image gallery, JBrowse session, MultiQC GS data-bar scale, resolver models beyond the
12 frozen entities.

**Hard limits, unchanged in kind** (they now degrade to the snapshots above): live UMAP (numba,
no WASM build); basemap tiles for an OFFLINE reader (online, they load); JBrowse / GenomeSpy remote tracks and references;
large bioimage pyramids; server state (time travel, comments, annotations, realtime, editing).

### 13.4 Measured costs

| what | raw | gzip | notes |
|---|---|---|---|
| static runtime (`static.html`) | 12.00 MB | 3.77 MB | unchanged; budget 4.2 MB |
| + structure viewer (`static-structure.html`) | 12.51 MB | 3.92 MB | 3Dmol.js 2.5.5's own minified UMD as a conditional add-on (+0.15 MB, vs +0.56 MB when Vite compiled the unminified ES entry in); second budget line, 4.4 MB |
| + Python runtime, demo job set (code figure + group_compare + PCA) | 81.5 MB | 52.4 MiB | the add-on is ~69 MB of base64 (already-compressed wheels barely gzip); size budget line 60 MiB |

Python add-on, base64 bytes each (`pin.json`): core (pyodide.asm.wasm gzip'd, asm.mjs gzip'd,
stdlib) 8.47 MB · numpy 3.95 · polars 24.43 · pandas + dateutil + pytz + six 6.57 · scipy 18.71 ·
scikit-learn + joblib + threadpoolctl 6.20 · plotly 6.9.0 stripped (9.9 → 3.9 MB wheel) 5.17 ·
narwhals 0.59 · packaging 0.13 · RestrictedPython 0.04. Floor (core + numpy + polars) 37 MB; a
code figure adds pandas + plotly + RestrictedPython (+12 MB); group_compare adds scipy (+19 MB);
t-SNE adds scikit-learn (+6 MB). Wheel: + 0.54 MB raw (3Dmol add-on) + pin.json; the Pyodide
files never enter the wheel (cap 24 MB, accepted).

### 13.5 Bioimage (`bioimage_viewer`, #1118 — not on this branch)

Decision: **live-precomputed** (LP), never live-by-elimination. When #1118 merges, its kind
must enter `SERVERLESS_KINDS` with path `objects` (the self-check forces an entry) — at worst
frozen as a downsampled snapshot of its opening view (the gallery-thumbnail path, §13.1), never
omitted — then move up in this order:

1. **Points overlay** (`sample_dc_id`, `x_col` / `y_col` / `cell_id_col`) is a plain data path:
   bundle it as a companion table with policy `none` (as on the branch), so lasso-to-filter works
   live even before images ship.
2. **Store shim**: a `path → bytes` map in the manifest — `BundleManifest.objects` now exists
   (the protein kinds use it, served as `blob:` URLs through the `authFetch` shim), answering
   `bioimageZarrStore` range reads and `fetchBioimageStores` from the manifest — no API proxy.
3. **Single-file**: only stores under a cap (the #1118 examples are 0.5–9.5 MB each), pruned to
   the coarse pyramid levels at export; above the cap a downsampled snapshot of the opening
   view ships instead, with the size in the reason.
4. **Runtime add-on**: deck.gl + viv (est. +1–1.5 MB gzip) would break the 4.2 MB budget for
   every bundle, so it ships as a conditional add-on, like 3Dmol.js (`serverless/addons.py`).
5. **Open in** (napari / vizarr / BigDataViewer): hidden — it hands another application a
   server URL with credentials.

### 13.6 The optional Python runtime (Pyodide) — spike and design

Spike (`chromium-1243` headless, `file://`, every non-file request aborted):

| question | answer |
|---|---|
| version | Pyodide **314.0.7** (CPython 3.14.2, emscripten 5.0.3), npm/CDN, two months old |
| boots from `file://`, everything inlined, zero network? | **yes** — files decoded from inert `<script type="application/octet-stream">` blocks (gzip'd wasm via `DecompressionStream`), served to Pyodide from memory under a fake origin through a scoped `fetch`; `pyodide.mjs` / `pyodide.asm.mjs` imported from `blob:` URLs; `loadPackage(…, {checkIntegrity: true})` against the lock's sha256. 0 network attempts in every run |
| polars? | **yes, 1.33.1** — but built without its Parquet reader (`PyLazyFrame.new_from_parquet` missing) and without JSON; IPC (incl. zstd / lz4) and CSV work → Python jobs get an Arrow IPC (zstd) copy of their table |
| plotly? | not in the distribution; the PyPI wheel (6.9.0, the server's version) is pure Python — unpacked into site-packages after stripping plotly.js, the widget bundle and datasets |
| RestrictedPython on 3.14? | yes (8.4, pure wheel); the server's executor runs **unmodified** (it needs pandas at import for its write guard, so code figures embed pandas) |
| boot time | decode 0.36 s · Pyodide 2.3 s · packages 3.8–4.4 s · server modules import 1.1 s → **~8 s** (code-figure + group_compare + PCA set); core + numpy + polars + plotly ≈ 7.7 s; numpy only ≈ 4.8 s |
| job timings (warm) | code figure (with_columns + px.scatter) 10k / 50k / 200k rows × 9 cols: 0.12 / 0.07 / 0.16 s · Wilcoxon 5k / 20k / 50k × 60: 0.08 / 0.28 / 0.75 s · PCA 1k / 5k / 20k × 200: 0.18 / 0.54 / 2.4 s · t-SNE 300 / 1k × 50: 3.8 / 13 s → limits 200k / 50k / 5k / 1k rows (`plan.MAX_ROWS`) |
| UMAP? | **no** — umap-learn needs numba / llvmlite, which have no WebAssembly build: export-time coordinates, filtered points |

Design: `depictio/serverless/pyodide/` — `pin.json` (version, files, sha256), `assets.py` (fetch
once, verify, cache: `DEPICTIO_PYODIDE_CACHE`; air-gapped: `DEPICTIO_PYODIDE_DIR`),
`modules.py` (the server code shipped: verbatim modules + functions extracted with every
module-level name they reach; an unshippable dependency fails the build, not the bundle),
`depictio_bundle.py` (entry points), `plan.py` (candidates, limits, sizes). Manifest:
`python_components` (job, table, spec, `max_rows`) + an `addons` entry. Runtime:
`static-runtime/pyodide/` boots lazily on the first tile that asks; the filter mask comes from
the same TypeScript engine every live tile uses (links resolved), so a Python tile filters
exactly like the others; above `max_rows`, without the add-on, or on a failed boot the
frozen payload is served. Mode `auto` (CLI and API default; library default `off`) embeds the
runtime exactly when a candidate survives the build; the export modal shows it as a switch with
the measured size. Not ported in this round: complex_heatmap (its task reads a second, metadata
collection per request and builds through plotly-complexheatmap + pandas — the next candidate,
via the same extraction).
