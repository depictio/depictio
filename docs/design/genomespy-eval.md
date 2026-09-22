# GenomeSpy for genome-scale tracks — evaluation and spike (#1083)

**Status:** Evaluation + landed spike (`viz_kind: genomespy_track`). Replacement of existing
renderers is proposed, not done.
**Audience:** maintainers deciding whether GenomeSpy earns a place in `advanced_viz`.
**Related:** `docs/design/advanced-viz.md` (row #8, §4 Layer B),
`depictio/projects/nf-core/TEMPLATE_BOTTLENECKS.md` ("Where the boundary with JBrowse sits"),
`packages/depictio-react-core/src/webglBudget.ts`,
[issue #1083](https://github.com/depictio/depictio/issues/1083).

> Facts below were checked against `@genome-spy/core` 0.88.1 (npm, 2026-09-16), the
> upstream repository's type declarations (`packages/core/src/types/embedApi.d.ts`) and
> its embed examples. Anything not measured is marked as such.

## 1. What GenomeSpy is, in Depictio terms

A Vega-Lite-derived grammar for tracks over genomic coordinates: a view spec (`mark`,
`encoding`, `params`, `layer` / `vconcat`) rendered to one `<canvas>` by WebGL, Canvas2D,
SVG or WebGPU. The grammar knows about chromosomes: `encoding.x = { chrom, pos, type: "locus" }`
concatenates contigs into one zoomable axis, `assembly: "hg38"` or a root
`genomes.<name>.contigs` list supplies the sizes, `x2` makes a row an interval, and transforms
such as `linearizeGenomicCoordinate` and `pileup` do what `ManhattanRenderer` and
`GeneArrowTrackRenderer` currently do by hand.

Where it lands in the architecture: it is **one more `viz_kind` in `advanced_viz`**, not a new
`component_type`. It takes the same `{ metadata, filters, refreshTick, onFilterChange?,
groupRender? }` props, fetches through `POST /advanced_viz/data` with the `tail` sampling
policy, and emits selections through `advancedVizSelectionFilter`. `jbrowse` stays what it is:
an iframe onto an external JBrowse 2 server for file-backed tracks.

## 2. The issue's six questions

### 2.1 Can the spec be generated server-side from the Delta schema?

Yes, trivially: a GenomeSpy spec is plain JSON keyed on column names, so the
`figure_builder.py` pattern (Polars frame + config → figure JSON) applies unchanged. The
spike does **not** do it, because nothing in `advanced_viz` does: every kind ships rows
(`/advanced_viz/data`, column-oriented, sampled per kind) and builds its figure client-side.
Building the spec client-side keeps the per-kind sampling, the `filtersExcludingOwn` rule and
the Load-All toggle without a second code path. The builder is a pure function
(`genomespy/genomeSpySpec.ts`, covered by vitest in node) and could move server-side later
by porting ~120 lines.

### 2.2 Selection events with row identity?

Yes, and better than Plotly's. `api.views.root().marks.subscribe("click", e => e.hit.datum)`
hands back the **whole row** as a detached object, so there is no `customdata` slot to thread
through. The spike maps `datum[selection_column]` onto the existing `scatter_selection`
filter, which is what the Analysis panel already turns into a group. Interval selections are
declared as a param (`{ select: { type: "interval", encodings: ["x"] } }`) and read with
`api.getParam("brush").subscribe(v => v.intervals.x)`; the value is a linearised genome
interval, which is exactly the `contexts.locus` channel the design doc's §4 Layer B describes
and never got built. The spike declares the param and subscribes to it; nothing consumes the
interval yet.

### 2.3 Does it fit the `webglBudget.ts` slot accounting?

Yes, and cheaply. One `embed()` is one canvas and **one** WebGL context; a Plotly `scattergl`
costs three. The spike asks for one slot with `useWebglSlot(true)` and, when refused, passes
`renderer: "canvas"`: GenomeSpy's Canvas2D backend keeps every feature (zoom, brush, picking)
and only paints slower, so the fallback is not the downsampled-SVG compromise `adaptGlTrace`
has to make. `MAX_GL_PLOTS = 4` is tuned for Plotly's three-canvas cost; if GenomeSpy tracks
become common, the budget should count contexts rather than plots.

### 2.4 Overlap with `jbrowse`

Neither is a full substitute for the other today, but the boundary is not where
TEMPLATE_BOTTLENECKS draws it:

- `jbrowse` is the only path for **file-backed** tracks (BAM, CRAM, BigWig, VCF, GFF3), and it
  needs an external JBrowse 2 server plus a session-config server, both of which the render
  endpoint 503s without. No onboarded project or template instantiates a `jbrowse` component.
- GenomeSpy also has **lazy file sources** for BAM, BigWig, BigBed, VCF (tabix), GFF3, indexed
  FASTA and Parquet, loading by range as the user zooms. That would cover the file-backed case
  from inside the same component family, with no JBrowse server. What it needs from Depictio
  is what row #8 of the design doc already asked for: `uri` resolved to a signed S3 URL
  server-side, and a MinIO / S3 CORS policy that allows range requests from the viewer origin.
  Not attempted in the spike.
- For **tabular** tracks (the aggregate tables `advanced_viz` owns) GenomeSpy is a genuine
  capability gain over Plotly: locus zoom, chromosome grid, interval marks and picking are
  declarative instead of hand-built.

### 2.5 React wrapper

The issue's premise is out of date: `@genome-spy/react-component` 0.88.1 exists (peer
`react ^18.2`). It is 40 lines: `useRef` + `embed()` in a `useEffect` with an empty dependency
list, `finalize()` on unmount, an `onEmbed(api)` callback. It does not react to a changed
`spec`, so the spike ships its own hook of the same shape (`genomespy/useGenomeSpy.ts`) that
re-embeds on spec / backend / theme change, swaps rows in place with `api.datasets.set()`,
and is the single module that touches the upstream API.

### 2.6 Mantine light / dark theming

Handled without colour literals. `embed()` takes a `theme: GenomeSpyConfig` and the spec
takes a `config` block with `view.fill`, `axis.labelColor / titleColor / tickColor /
domainColor / gridColor`, and per-mark defaults. The spike derives them from
`plotlyThemeColors(isDark, theme)` and the chromosome palette from
`resolveCategoricalPalette(theme)`, so a branded instance colours GenomeSpy tracks like its
Plotly figures. A colour-scheme switch rebuilds the spec and re-embeds.

## 3. Stack compatibility

| Axis | Depictio | GenomeSpy 0.88.1 | Outcome |
|---|---|---|---|
| Runtime | React 18.3, Vite 5.4, TS 5.3 (`moduleResolution: bundler`), Node 22, pnpm 10 | ESM, no peer deps, `exports` for `./minimal` and `./rendering/{webgl,canvas,svg}.js` | Imports directly |
| Types | strict TS | `.d.ts` shipped under `dist/src/**` (no root `types` field) | Import from `@genome-spy/core/types/*.js` |
| Size | plotly already split into `vendor-plotly` | 8.5 MB unpacked incl. BAM/VCF/BigWig/Parquet parsers | `./minimal` + one renderer registration, `import()`ed by the hook → async `vendor-genomespy` chunk |
| Transitive deps | `d3-array/color/format` already locked | `d3-*`, `vega-util/scale/expression`, `twgl.js`, `lit`, `@gmod/*` | No singletons in conflict; 409 lockfile lines added |
| Rendering | 16 live GL contexts per process, budgeted | 1 context per embed; `canvas` fallback | See §2.3 |
| Licence | MIT | MIT | — |
| API stability | — | 0.85 → 0.88.1 in 13 days, one breaking `fix(core)!` in 0.86, `addEventListener` deprecated for `events.subscribe` | Pinned to `0.88.1` exactly; all calls in one adapter module |
| Tests | vitest (node, no jsdom) + Playwright | same | Spec builder is unit-tested; the mount is an e2e matter |

## 4. Overlap with existing renderers, and what to replace

| Renderer | Built by hand today | GenomeSpy equivalent | Decision |
|---|---|---|---|
| `manhattan` (Plotly `scattergl`, 3 GL contexts) | chromosome sort, concatenated axis, alternating bands, threshold, top-N labels, lasso → filter | `locus` axis, `rule`, `text` (top-k via transform), interval brush | **Candidate 1.** Replace after the measurement in §5 on `macs2_broad_peaks` (atacseq) if latency is no worse and the selection→filter path is kept |
| `coverage_track` (Plotly + Celery `compute_coverage_track`) | server binning / smoothing, per-sample facets, annotation lane | `rect` with `x2`, `vconcat` with shared `x` | **Candidate 2.** Keep the Celery aggregation, change the rendering |
| `gene_arrow_track` (Plotly shapes) | lane packing, strand arrows, labels | `pileup` transform, `rect` / `text` marks | Candidate 3, low traffic |
| `sashimi` (junction arcs only, coverage delegated) | arcs | `link` mark + coverage `rect` in one `vconcat` | After candidate 2: it reunites the two halves the JBrowse boundary split |
| `jbrowse` (iframe, external server, zero onboarded use) | file tracks | lazy BAM / BigWig / VCF / GFF3 / FASTA sources | Open: needs signed S3 URLs and CORS (§2.4) |
| `lollipop`, `signal_matrix`, `profile`, `fusion_structure` | protein or offset coordinates | expressible, no gain | Out of scope |

**Replacement rule.** A Plotly renderer is replaced only when, on the same collection and the
same dashboard, GenomeSpy (a) renders no slower on first paint after fetch and on pan / zoom
frame time, measured in Playwright; (b) keeps the renderer contract and the selection → filter
path; (c) removes code (renderer lines plus tests); (d) still works on the `canvas` fallback
when the GL budget is spent. The old `viz_kind` string stays as an alias in `RENDERERS` for one
release, the way `ancombc_differentials` does.

## 5. Measurement protocol (not run: no browser against a live instance here)

Same collection (`macs2_broad_peaks`, nf-core/atacseq, ~10⁵ rows) bound to a `manhattan` tile
and a `genomespy_track` tile on one dashboard. A Playwright spec records, for each tile:
fetch-complete → first painted frame; median frame time over ten wheel-zoom and ten drag-pan
gestures; the same two numbers with the GL budget exhausted (mount four `scattergl` tiles
first) so the `canvas` fallback is measured too. Report both backends. The showcase tab
`genomespy_track.yaml` sits next to `manhattan.yaml` on the same `manhattan_demo` collection
for an eyeball comparison before that is automated.

## 6. What the spike ships

- Backend: `GenomeSpyTrackConfig` (chr / pos / score, optional `feature_col` and `end_col`,
  `mark`, `assembly`, `score_threshold`, `point_size`, `opacity`, selection fields); roles and
  aliases in `schemas.py`; `tail` sampling; catalog and Tool Studio snapshots regenerated.
- Frontend: `genomespy/genomeSpySpec.ts` (pure spec builder + tests), `genomespy/useGenomeSpy.ts`
  (embed / finalize / pick / brush / `datasets.set`), `GenomeSpyTrackRenderer.tsx`, dispatch and
  chunking entries. `@genome-spy/core` pinned at 0.88.1.
- Showcase: the `GenomeSpy track` tab of `advanced_viz_showcase`, bound to `manhattan_demo`.

Not shipped: interval brush → `contexts.locus` consumer, analysis-group colouring, file-backed
sources, any renderer replacement.
