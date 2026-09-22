# GenomeSpy for genome-scale tracks — evaluation and spike (#1083)

**Status:** Evaluation, then a landed kind (`viz_kind: genome_view`, renamed from the spike's
`genomespy_track`). Replacement of existing renderers is proposed, not done.
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
and never got built. The kind now consumes it: the brushed interval is mapped back to a
chromosome plus a base-pair range and emitted as two ordinary interactive filters (§6), so the
region reaches every other tile through the existing filter pipeline rather than a new channel.

### 2.3 Does it fit the `webglBudget.ts` slot accounting?

Yes, and cheaply. One `embed()` is one canvas and **one** WebGL context. Measured on the same
dashboard (§5), a Plotly `scattergl` manhattan tile allocated **two** WebGL contexts plus a 2D
canvas, against **one** context and one canvas for the genome view. The spike asks for one slot with `useWebglSlot(true)` and, when refused, passes
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
| `manhattan` (Plotly `scattergl`, 3 GL contexts) | chromosome sort, concatenated axis, alternating bands, threshold, top-N labels, lasso → filter | `locus` axis, `rule`, `text` (top-k via transform), interval brush | **Candidate 1.** §5 now says latency is a wash and the context cost halves; what still blocks the swap is the top-N label pass and lasso-to-group parity, not performance |
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

## 5. Measurement (run 2026-09-22)

Same collection bound to both renderers on one dashboard: `macs2_broad_peaks`
(nf-core/atacseq megatest), 224 137 rows, 11 columns, 24 chromosomes, 6 samples. Headless
Chromium 151.0.7922.34 at 1600x1000, `--enable-precise-memory-info`, driven by Playwright.
WebGL contexts are counted by instrumenting `HTMLCanvasElement.prototype.getContext` at call
time and attributing each canvas to its `.react-grid-item`: probing afterwards with
`getContext()` allocates a context on any canvas that has none, which is the number being
measured.

The dev viewer container could not serve the run. Its `node_modules` live in the image
(`docker-compose.dev.yaml` mounts source only), so `@genome-spy/core` is unresolvable there
until the image is rebuilt and Vite fails the transform. The numbers below come from a host
Vite dev server proxying the same API, which means they include dev-mode module loading and
are an upper bound on first paint, not a production figure.

| | `manhattan` (Plotly `scattergl`) | `genome_view` (GenomeSpy, WebGL) |
|---|---|---|
| WebGL contexts | 2 | 1 |
| Canvases | 3 (2 GL + 1 2D) | 1 |
| Median wheel-zoom frame | 8.3 ms | 8.3 ms |
| Median drag-pan frame | 8.3 ms | 8.3 ms |

Shared, whole-page: first canvas painted 3.45 s after navigation, settled at 5.95 s, 91.4 MB
used JS heap, no console errors. Both tiles sit at the vsync floor of the 120 Hz display
during gestures, so 8.3 ms is the monitor, not either renderer: neither is the bottleneck at
this row count, and the honest reading is "no worse", not "faster".

**The Canvas2D fallback is still unmeasured.** Disabling WebGL at the browser level is not a
valid method here, because Plotly then throws "Unable to initialize WebGL" and the comparison
collapses. The replacement, saturating the budget by mounting four `scattergl` tiles first,
did not settle: three manhattan tiles took 6 contexts between them and the fourth tile and the
genome view had painted no canvas at all 18.8 s in, so the gesture numbers collected there
describe an empty tile. That scenario needs a longer settle window, or a smaller collection,
before it says anything.

## 6. What the kind ships

- Backend: `GenomeViewConfig` (chr / pos / score, optional `feature`, `end`, `sample`,
  `category`; `mark`, `facet_by_sample`, `max_facets`, `annotation`, `assembly`,
  `score_threshold`, `point_size`, `opacity`, `region_filter_enabled`,
  `follow_region_filter`, selection fields); roles and aliases in `schemas.py`; `tail`
  sampling on `score`.
- Frontend: `genomespy/genomeSpySpec.ts` (pure spec builder), `genomespy/geneAnnotations.ts`
  (lazy gene asset loader), `genomespy/genomeViewData.ts` (fetch + filter plumbing, testable
  without a DOM), `genomespy/useGenomeSpy.ts` (embed / finalize / pick / brush / `zoomTo` /
  `datasets.set`), `GenomeViewRenderer.tsx`, dispatch and chunking entries.
  `@genome-spy/core` pinned at 0.88.1.
- Marks: `point`, `rect` (needs `end`), `bar` (score as height from a baseline, the coverage
  look). GenomeSpy core has no line or area mark, so a smooth coverage curve is not available;
  `bar` is the closest reading.
- Multi-track: an advanced_viz tile binds one data collection, so several genome tiles are
  stacked in one section and linked by the region filter. `facet_by_sample` stacks one lane
  per sample inside a single tile as a `vconcat` sharing the x scale, capped by `max_facets`.
- Gene annotation: `annotation: hg38 | mm10 | none` draws a rect plus text lane under the
  data, from a lazily fetched asset under `depictio/viewer/public/assets/genomes/`.
- Region brush to filter: the brushed interval becomes a `MultiSelect` on the chromosome
  column and a `RangeSlider` on the position column, both with source `genome_selection`, so
  any tile bound to a collection carrying the same columns (directly or through a project
  link) narrows with it. `follow_region_filter` makes a tile zoom to an incoming region
  instead of contributing one.
- Showcase: the `Genome view` tab of `advanced_viz_showcase`.

Not shipped: analysis-group colouring, file-backed sources, any renderer replacement.
