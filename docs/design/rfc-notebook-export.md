# RFC — Depictio → code (a dashboard as a runnable notebook, every component importable)

**Status:** Implemented in this branch; design recorded for review.
**Revision (2026-11):** the export is **Quarto only**. The marimo `.py` and the Jupyter `.ipynb`
are gone, and with them marimo, nbformat and the `format` field: the generator writes one `.qmd`
directly, and the rendered report is that same file through `quarto render`. Sections below are
updated; §4 records why.
**Audience:** maintainers.
**Related:** `depictio/models/models/analysis_state.py` (the contract),
`depictio/api/v1/services/notebook_export/` (the generator),
`depictio/api/v1/services/embed/` + `depictio/viewer/src/component-frame/` (figure extraction),
`depictio/notebook/` (the Python client), PR #975 (funnel filtering, the seam this reuses),
PR #962 / #1013 (groups, split panels), PR #963 (serverless bundle — the coverage-table shape
and the "frozen badge" tone this borrows; none of its code).

> Every dashboard tool is a dead end: what you build by clicking cannot be handed back to you as
> code. This is Depictio returning the code — and, the other way round, letting any component of
> a dashboard be pulled into a Quarto (or any Jupyter-kernel) cell.

## 1. Context

A scientist explores in the browser: filters, a funnel order, a lasso'd group, a split view. The
server runs real Polars queries against Delta tables for every tile. Nothing of that survives the
browser tab. Two capabilities close the loop:

1. **Export** — the whole dashboard family (all tabs) plus the *current analysis state* becomes a
   **Quarto document (`.qmd`)** that reproduces the same queries, and — opt-in — an HTML report
   rendered from it on the server.
2. **Import** — `depictio.notebook.DepictioClient` brings **any** component of a dashboard —
   figures, cards, tables, filters, text, maps, MultiQC, images, JBrowse, all 54 advanced-viz kinds
   — into a cell, bound to the same filters the dashboard applies.

## 2. Problem

Four things had to exist first, and none did on `main`:

- **The analysis state is scattered.** Active filters live in `App.tsx`'s React state; groups and
  the global colour-by in `localStorage` (`depictio:selection-groups:<family>`); the funnel stage
  order was *local state of the funnel modal*; split constraints are derived on the fly. The server
  can read none of it. (PR #967's server-side filter persistence and `filterShare.ts` are not
  merged; the brief assumed they were.)
- **The render pipeline yields expressions, not source.** `add_filter` builds `pl.Expr` objects.
  A notebook needs the same predicates as text, so "reuse the seam" cannot mean calling it.
- **No data path for a notebook.** There is no Parquet/Arrow endpoint, and no per-user S3
  credentials (agent configs hand out the instance root credentials, admin-gated).
- **Most components are not figures on the server.** Only figures, maps, MultiQC plots and three
  advanced-viz kinds (`complex_heatmap`, `upset_plot`, `sankey`) come back as Plotly JSON. The other
  15 advanced-viz kinds, tables, cards, filters and images are drawn by React renderers from
  data-only payloads; no single-component route existed.

## 3. Proposal

### 3.1 `AnalysisState` — one object, versioned, handed to the server

`depictio/models/models/analysis_state.py` (Pydantic, `version: 1`) holds `filters` (the viewer's
`combinedFilters`: user filters **plus** group projections, exactly what the render endpoints
receive, so the server never re-implements `groupsToFilters`), `groups`, `color_by`,
`display_mode`, `show_other`, `show_overall`, `compare_in_cards`, `funnel.{enabled, stage_order}`,
`split_panels` (the client's `panelsForGrouping` output — a panel is a list of filters) and
`context`. The committed `analysis_state.schema.json` is the contract; a Python test pins the model
to it and a vitest test validates the TypeScript builder (`analysisState.ts`) against it.

**Server-side reachability, honestly:** the state reaches the server *in the export and embed
requests*. Groups, stage order (now lifted from the funnel modal into `App.tsx`) and colour-by
still live in the browser. The share link (#967) and version snapshots (#919/#924) are the named
next consumers of this object; they were not migrated here.

### 3.2 Data access: the API, with the reader's own token

`GET /deltatables/data/{dc_id}?columns=` streams the unfiltered table as Parquet behind the same
permission pipeline as every other read endpoint (`_resolve_delta_location`), capped by
`DEPICTIO_NOTEBOOK_EXPORT_MAX_ROWS` (413 above it). The notebook applies the filters itself, in
code, so the reader can see them. The client reads `DEPICTIO_API_URL` + `DEPICTIO_API_TOKEN`
(a long-lived token from the *CLI agents* page) or `~/.depictio/CLI.yaml`.

Kept addable, not built: **`DEPICTIO_DATA_DIR`** already switches `client.data()` to local
`<dc_id>.parquet` files (offline mode; the test suite runs the generated notebook this way), which
is what a future "Parquet alongside the export" would fill; **direct Delta-on-S3** is documented
as a third mode and rejected for now because no per-user credentials exist to hand out.

### 3.3 The generator: funnel stages are cells

One generator, one artefact: a `.qmd` — YAML front matter (title, author, date, the HTML
report's layout, `jupyter: python3`), then markdown and ```` ```{python} ```` chunks in reading
order. Quarto runs the chunks top to bottom in one kernel, so the document is the cells in
sequence: no dependency graph, no converter, no second format. Every code chunk is parsed when it
is generated, so a generator bug fails the export rather than the reader's render.

Cell sequence: imports → `client = DepictioClient()` → header (title, provenance from
`template_origin.run_provenance`, how to run) → `depictio_state = {…}` (the exported state as a
literal, re-used by API-path cells) → one `df_<dc_tag> = client.data(...)` per data collection →
**one cell per funnel stage** (`stage_k_<tag> = stage_{k-1}_<tag>.filter(...)`, row counts from
`funnel_values` in the comment; link-resolved values inlined as literals, columns absent from a
collection skipped exactly as the server skips them) → `final_<tag>` → `group_<slug>` and
`panel_<slug>` frames → the tiles, in reading order.

**Predicates as source.** `predicates.py` mirrors `add_filter` / `_categorical_predicate` branch
for branch (categorical by dtype: String → bare `is_in`, numeric/Date → typed literals,
Datetime/Time → the same `str.to_datetime`/`to_time` conversion, unknown → the Utf8-cast fallback;
range, text, slider, date ranges with the same `coalesce`; `LINK_NO_MATCH` → `pl.lit(False)`;
`Switch` → nothing, because the server has no branch either). The equivalence test evaluates every
emitted branch against `add_filter` on a fixture frame. Card reductions mirror `_agg_expr` the
same way; `filter_expr` strings are already Polars spelled with bare `col`/`lit` and are emitted
verbatim after validation.

**Reading order (a product decision):** persistent sections pinned `top` (owner tab first) → each
tab in `tab_order`, main tab first: its declared `grid_sections` in order, then undeclared
sections by first appearance, then unsectioned tiles → persistent sections pinned `bottom`. Within
a section: `(layout.y, layout.x)` when a layout exists, stored order otherwise — **no seeded
dashboard carries a layout**, so the fallback is the common case. Interactive components are not
tiles; they are the stages.

**Naming:** `df_<dc_tag>`, `stage_<k>_<tag>`, `final_<tag>`, `group_<slug>`, `panel_<slug>`,
`fig_/card_/table_/viz_<slug>`; a `NameAllocator` dedupes and reserves the scaffolding names.
Scratch names use `_`. Code-mode figures are inlined **verbatim** inside `def _make_<name>(df): …;
return fig`, so the author's `df`/`fig` survive and never become globals; they run with the
globals the dashboard executes them with (`depictio_group_kwargs`, `depictio_group_by` — empty,
the export is ungrouped — and the family's `depictio_category_colors`). The AST guard test runs
the chunks in order and proves each one only reads what an earlier chunk defined, and that no
public global is defined by two chunks (a second one would replace what the first showed).

### 3.4 Coverage — how each component reaches the document and the report

Three verdicts (`classify.py`): **code** (Polars/Plotly in the `.qmd`, needs only the data),
**api** (`client.component(...)`, rendered by the instance with the exported state) and
**omitted** (only an unknown type or kind). An `api` tile also says what the reader gets
(`output` in the preflight): an interactive figure, static HTML/SVG, or a PNG **snapshot** of a
renderer that is not Plotly; `native` marks a tile the document draws itself from its data
(`depictio.notebook.native`) rather than the server rendering it. Every `AdvancedVizKind` has an
explicit verdict in `ADVANCED_VIZ_RENDERING`; the module refuses to import with one missing, and
the tests pin the non-Plotly set by name and require a native renderer for each of them, so a
new kind cannot reach a report by default.

**Native renderers** (`depictio/notebook/native/`). What the app draws with SVG, a canvas or
WebGL is drawn in the document with Python libraries from the rows the React renderer reads
(`/advanced_viz/data` with the state's filters as the renderer sends them, the newick route,
indexed-file manifests for structures and PAE files): Plotly for tracks, matrices, rings and
karyotypes; py3Dmol for structures, with 3Dmol.js 2.5.5 shipped in the package and inlined once
per document; SVG/HTML for layout (record card, ranked table, allele grid, pedigree, HMM logo).
Each renderer falls back on the server's snapshot when it cannot run (a library missing, a file
out of reach) and the caption says why; `use_native(False)` / `DEPICTIO_NOTEBOOK_NATIVE=0` asks
for snapshots everywhere. What only the live view does (fetch an annotation track, follow a
brush, refetch on zoom, let the reader pick) is named in each tile's caption.

**No tile can break the document.** Every display path of a `DepictioComponent` catches and
draws a placeholder with the tile's title, the reason and a link to the live dashboard (a
disabled JBrowse, a renderer that timed out, a 413 on the data). Asking for `.figure`/`.data`
explicitly still raises.

#### Component types

| component | `.qmd` | report | interactive? |
| --- | --- | --- | --- |
| figure, UI mode (incl. `heatmap`) | api: `render_figure`, with groups, colour-by, facet, "other" and the version pins | Plotly | yes |
| figure, code mode | code: the author's code verbatim; `depictio_group_kwargs` / `depictio_group_by` and the `__depictio_group__` label as the server hands them over | Plotly | yes |
| card, closed-form aggregation | code: `final.select(<expr>).item()` | static HTML | no |
| card, multi-metric / `secondary_layout` / `box_plot_stats` / `mode` | api: `bulk_compute_cards` (with the group comparison), drawn as static HTML from the server's numbers | static HTML | no |
| table | code: `final.select(cols).head(page_size)`, every row shown | DataTables (itables, offline) or plain HTML | sort, search, pages |
| interactive (filters) | code: one funnel stage each, read from `depictio_state` when the document runs | the active-filter summary and the funnel figure | the funnel figure |
| text | code: markdown; live values (`{{name}}`, `{{param:KEY}}`) printed by an `output: asis` cell from `bulk_compute_cards`, export-time values offline; `](tab:…)` links jump to the tab's heading; inline icons as SVG | static | no |
| map | api: `render_map` | Plotly (the basemap tiles load from the CDN when viewed) | yes |
| MultiQC plot | api: `render_multiqc` (live data only: not versioned server-side) | Plotly | yes |
| MultiQC General Statistics | api: the table and its violin summary | table + Plotly | violin |
| image gallery | api: `render_image_paths`, images inlined | static images | no |
| JBrowse | api: assembly, opening locus and shown tracks (`.tracks`), a snapshot of the opening view, a link to the live tile | static snapshot + table | no |
| highlight | code: a pointer to the tab that draws the figure | static text | no |

#### Advanced visualisations (54 kinds on this branch)

| kinds | how | report | interactive? |
| --- | --- | --- | --- |
| complex_heatmap, upset_plot, sankey (Celery computes); volcano, embedding, manhattan, stacked_bar, stacked_taxonomy, da_barplot, enrichment, ma, qq, sunburst, pr_benchmark, roc_pr_curve, confusion_matrix, metric_ci_bars (registered Python builders) — 17 | api: the server builds the Plotly figure (`build_plotly_export`, inline, no browser); a tile coloured by groups or a column goes through the renderer instead, which applies it | Plotly | yes |
| phylogenetic (tree), rarefaction, dot_plot, lollipop, oncoplot, coverage_track (track), profile, signal_matrix, fusion_structure, gene_arrow_track, gsea_running_score, sashimi (plotly view), scatter_xy, contact_map, knee_plot, damage_profile, group_compare, transcript_structure, cnv_profile (plotly view), parallel_coordinates, ramachandran, ranked_distribution, spatial_cells — 23 | api: the Plotly figure read off the real React renderer, headless (`/embed`, `gd.data`) | Plotly | yes; contact_map and group_compare on their opening window / pair only |
| genome_view (the opening window: the default region, the one contig, or genome-wide / the stretches the rows cover), genome_chord, ideogram, msa, sequence_track, secondary_structure, domain_architecture, pae_matrix — 8; and the views cnv_profile `locus`, sashimi `genomespy` (the busiest locus), phylogenetic with `collapse_rank` (rank summary: core clades, cladogram, shares, split strip) | **native**: a Plotly figure drawn in the document from the renderer's rows | Plotly (static native until this change: snapshot) | yes: hover, zoom, legend |
| molecule_3d — 1 | **native**: py3Dmol from the structure file (indexed collection), pLDDT colours, variant sites; the CA backbone in Plotly without py3Dmol | 3D viewer, 3Dmol.js inlined once | yes: rotate, zoom |
| record_card, ranked_table, allele_grid, pedigree, hmm_logo — 5 | **native**: HTML/SVG from the rows (the picked or default record, or with no pick the records the card picks from; medals, badges and bars; both haplotypes per cell; one pedigree per family; letter heights as `hmmlogo` computes them) | static native | no (tooltips on the SVG) |
| coverage_track `locus` view; genome_view over indexed files (`source` other than `table`) | api: a PNG of the real renderer, taken by the headless pass once the tile reports itself drawn (`data-embed-status`); also every native tile's fallback | static snapshot, captioned "interactive in the live dashboard" | no |

`bioimage_viewer` (#1118, unmerged) will need a verdict when it lands: the import guard says so.

#### Seeded families, before → after

Three states: the audit (before snapshots existed), snapshots (`21eab2a`), and native
renderers (this revision). Measured by rendering each family's `.qmd` with Quarto 1.9.37
against the seeds' own data; "drawn here" counts tiles the document draws itself.

| family | audit | with snapshots | native (now) |
| --- | --- | --- | --- |
| nf-core/viralrecon | 4 tiles abort the render, 1 blank JBrowse | 0 fatal; 5 snapshots | 4 drawn here (1 genome view interactive, 3 record cards static); 1 snapshot (JBrowse) |
| nf-core/ampliseq | 3 tiles abort the render | 0 fatal; 3 snapshots | 3 drawn here (2 phylogeny summaries interactive, 1 record card static); 0 snapshots |
| advanced_viz_showcase | 28 tiles abort the render | 0 fatal; 28 snapshots | 28 drawn here (20 interactive, 8 static); 0 snapshots |
| genome_tracks_examples | 2 blank JBrowse tiles | 2 JBrowse snapshots + track tables | unchanged: 2 JBrowse snapshots + track tables |
| **all seeds** | 35 fatal, 3 blank | 38 snapshots | **35 drawn here (24 interactive, 11 static), 3 snapshots (JBrowse)**; 0 placeholders among them |

Per kind, snapshot → native: interactive (Plotly) genome_view, genome_chord, ideogram, msa,
sequence_track, secondary_structure, domain_architecture, pae_matrix, cnv_profile `locus`,
sashimi `genomespy`, phylogenetic `collapse_rank`; interactive (py3Dmol) molecule_3d; static
(HTML/SVG) record_card, ranked_table, allele_grid, pedigree, hmm_logo. Still a snapshot:
JBrowse (§ below), coverage_track `locus` (GenomeSpy, not in any seed; its `track` view is a
Plotly figure already) and genome_view over indexed files.

What it costs a report: one copy of 3Dmol.js (538 KB) in a document with a structure, Inter
(three subsets, ~200 KB as data URIs) in every Paper report, and each tile's own data: on the
showcase the 28 native tiles come to ~3.3 MB of HTML (the 10 000-bin copy-number profile
0.46 MB, the three structures 0.85 MB with the library), against one PNG per tile before.

Against the audit's per-component targets (72 rows: 17 component types, 55 kinds counting
#1118's): **api-figure 45** — all reached (UI figures now carry grouping and pins; 17 kinds no
longer need a browser); **code 13** — 6 reached (code figures, closed-form cards, tables,
filters, plain and live text), 7 not (multi-metric and `box_plot_stats` cards stay api/static,
card variants keep the default look, highlights stay pointers; record_card / ranked_table /
pae_matrix are now drawn from their data, natively rather than as code cells);
**embedded-offline 10** — reached natively rather than by embedding the React bundle (§3.8):
interactive for the Plotly and py3Dmol ones, static for the SVG/HTML ones; **static-image 4** —
3 reached (images, JBrowse, and genome_view now beyond its target, as an interactive opening
window), bioimage_viewer not on this branch. Before: 14 kinds aborted every report and JBrowse was blank.

#### Cannot be exported (hard reasons)

1. **Live cross-tile filtering in a static report.** Server-rendered tiles are computed for one
   state; a file has no server to ask. Re-rendering with other parameters
   (`quarto render -P depictio_state:…`) is the supported substitute: every stage and tile
   follows the new state.
2. **JBrowse browsing offline.** Tracks (BAM, CRAM, bigWig, VCF) are read by HTTP range through
   the instance's signed, short-lived track proxy, often GB-scale. Ceiling: the opening view's
   snapshot plus the track table and a link.
3. **GenomeSpy views as GenomeSpy offline** (genome_view; coverage_track / cnv_profile `locus`;
   sashimi `genomespy`). GenomeSpy fetches its annotation tracks itself and zooming refetches;
   main's offline bundle refuses them too. Ceiling: the opening window's rows drawn natively in
   Plotly (hover and zoom over what the window holds, no annotation track, no refetch);
   coverage_track `locus` stays a snapshot.
4. **bioimage_viewer at full resolution** (#1118). Multiscale OME-Zarr chunks are fetched on
   demand with the viewer's credentials; the hand-off links are public-only or expire.
5. **contact_map beyond the opening window, group_compare beyond the opening pair.** One server
   compute per zoom window / per pair: no single result stands for the tile.
6. **Intra-tile controls that refetch** (live UMAP/t-SNE sliders, any control that re-queries).
   Only the persisted configuration is exported.
7. **Version-pinned MultiQC and advanced-viz data.** Not versioned server-side; a pinned export
   says those tiles show live data rather than claim otherwise.
8. **The live tile in an iframe inside a report.** `/embed` is served with `X-Frame-Options:
   SAMEORIGIN` / `frame-ancestors 'self'`, and partitioned storage hides the session anyway: a
   security boundary, not an export bug. `.html` works only for a reader logged into the
   instance, outside a report.
9. **Server-side rendering of author-written code for non-owners** (policy,
   `_require_owner_for_authored_code`): they can download the `.qmd` and run it themselves.
10. **Pixel parity of UI-built figures as pure `px.*` code.** The chart builder computes options
    it does not store, which is why those figures are `api`, not code.

### 3.5 Universal import — three representations per component

`client.component(dashboard, "Bill shape", filters=[...])` returns a `DepictioComponent` with
`.figure` (a `plotly.graph_objects.Figure`), `.data` (a `polars.DataFrame`, or a dict for cards)
and `.html` (the live tile, for a reader logged into the instance); a snapshot tile adds `.image`
(PNG bytes), a JBrowse tile `.tracks`. It displays itself through the kernel's
`_repr_mimebundle_` (what `quarto render` captures), never raising.

**Figures without a browser where the server has a builder.** `POST
/dashboards/component_figure/{d}/{c}` first asks main's `build_plotly_export` for the 17 kinds
with a server builder (no Chromium, no nested Celery). The rest go through **headless
extraction**: the viewer's `/embed/{dashboard}/{component}#state=<base64url JSON>&theme=…` mounts
the real `ComponentRenderer` (inside `DataVersionProvider` and the load registry) and reports the
*renderer's* status in `data-embed-status` (`ready` once the tile reported itself drawn, `error`
with `data-embed-reason`). The worker reads `gd.data`/`gd.layout` off a Plotly div, or, for a
renderer the classification marks as not Plotly (or one that turns out not to draw one), takes a
PNG of the tile after network idle and a paint budget (Chromium with SwiftShader for the WebGL
renderers). Results are cached per (component, whole state, theme, expected output).

**Queues.** The browser passes run on the `export` queue and reports on `report`
(`celery_app.task_routes`): a pass waits on the tile's compute task (default queue) and a report
on its passes, so on one pool of two slots they starved each other. The default worker consumes
`celery,export,report`; a dedicated worker (`docker compose --profile export`) can take the two.

**Version pins.** `AnalysisState.pins` (`as_of_version`, `data_versions`, `definition_version`)
rides on every render call, both halves together; `client.data(dc, version=N)` reads that Delta
commit (`/deltatables/data/{dc}?version=N`, scanned directly, never from a cache or the local
mirror); the export lays the version's component definitions over the family and warns that
MultiQC and advanced-viz data are not versioned server-side.

### 3.6 Opening the export

| target | file | open with | notes |
| --- | --- | --- | --- |
| Quarto document | `<name>.qmd` | `quarto render <name>.qmd` / `quarto preview`, or any editor with Quarto support (VS Code, Positron, RStudio) | front matter: title, author, date, `format: html` (toc, code-tools, embed-resources), `jupyter: python3`; PDF needs `kaleido` |
| Rendered report | `<name>.html` | a browser | the same document, rendered on the server (§3.6b) |

The client works in any `{python}` chunk a reader adds.

### 3.6a The report's look — Paper

The report reads as the dashboard does in the app's default chrome (id `glass`, "Paper",
`viewer/src/chrome/variants/glass/`), from the instance brand, with `theme: "classic"` on the
export request (a Look control in the modal) for Quarto's stock page and Plotly's own figures:

- **the page**: a Quarto brand inline in the front matter (`quarto.paper_brand`; the export stays
  one file), compiled into the report's Bootstrap theme: white page, gray-9 ink, the instance
  primary, Inter in front of the app's UI stack (or the brand's own `font_family`), Paper's
  radii and hairlines;
- **the chrome** the generator injects (`PAPER_CHROME` over `NOTEBOOK_CHROME`): sections as
  paper panels with the section's accent edge, every result a tile card, KPI cards, the contents
  list, the code toggle and DataTables in Paper's wells and pills, every value a `--gl-*` token
  of `glass.css` resolved for the light scheme;
- **the figures**: `depictio.notebook.theme` is `glassPlotly` + `glassPlotlyDefaults` in Python,
  merged as `applyChromePlotly` merges them (defaults under the figure, the patch over it), on
  every figure the document shows, server-built ones included, and registered as the
  `depictio_paper` Plotly template for figures built in the document;
- **the font**: Inter (latin, latin-ext, greek; OFL) ships with the package and the setup cell
  embeds it as data URIs: the report makes no font request.

### 3.6b The rendered report (server-side, opt-in)

The second choice in the export modal: **Rendered report**, the `.qmd` run here. The reader gets
one self-contained file with every result in it and nothing to install; the document is unchanged,
so the report is the export's own output rather than a second renderer.

It is a job, not a request. `POST /dashboards/notebook_export/{id}/render` builds the same `.qmd`
the download hands out, stages it in S3 under `notebook_reports/{user}/{job}/` (~10 MB is
not a broker message), mints a **short-lived token for the caller** and queues
`render_notebook_report` with the token's *id*. The worker runs `quarto render --execute` with
`QUARTO_PYTHON` pinned to its own interpreter, stores the HTML next to the notebook, deletes both
the staged notebook and the token, and the client polls `GET …/render/{job}` then downloads from
`GET …/render/{job}/download`. Keys are namespaced by user, so a download can only ever address the
caller's own reports.

Two Quarto behaviours cost a full render each to find, and both are guarded in `render.py`:
execution can be switched off (project config, freeze, or simply not asked for: `--execute`), and an interpreter without
Jupyter makes Quarto skip execution — in both cases it writes a report with every result missing and
exits 0. The service checks the log for the execution it asked for before believing the output.

**What it costs.** Quarto (~250 MB) is opt-in in the worker image (`--build-arg
WITH_QUARTO=true`, `Dockerfile.worker`; compose `DEPICTIO_WORKER_WITH_QUARTO`), plus the `render`
extra (`nbclient`, `ipykernel`, `itables`, `py3Dmol`). A worker without it refuses a render naming the build
arg; everything else in the export works without it. A render re-executes the notebook against this deployment's own
API: 45 s for the nf-core/viralrecon report with the figure cache warm, ~4 min cold, since every
API-path tile is a headless browser pass. `DEPICTIO_NOTEBOOK_EXPORT_RENDER_ENABLED` is **off by
default**.

**The trust boundary.** This is the path the RFC deferred as "arbitrary code execution", and the
answer is not a sandbox but a rule: everything in the notebook is generated by the server from the
dashboard **except code-mode figures**, which are Python an author wrote in the chart builder. So a
dashboard carrying any of those is rendered only for its owners — who can already change that code —
and refused with a 403 for everyone else, who can still download the notebook and run it themselves.
A flake in one tile no longer wastes the whole job either: `DepictioClient.poll` re-dispatches a
failed render job once, since a browser that drops its connection while closing is not an answer.

### 3.7 Correctness oracle

`funnel_values` already computes per-stage row counts. The endpoint test executes the generated
notebook offline (`DEPICTIO_DATA_DIR`, `App.run()`) and asserts that every stage's `df.height`
equals the funnel endpoint's count for that stage, for three stage orders; reordering changes the
intermediate counts and never the final one. Against a live instance,
`depictio/dev_scripts/verify_notebook_export.py` does the same for seeded dashboards.

### 3.8 Design note — embedded-offline tiles for what is not Plotly (superseded by §3.9)

**Superseded by the native renderers (§3.4).** The non-Plotly kinds are drawn in the document
from their data, in Python, which costs a report each tile's data plus 3Dmol.js once, against
~7 MB of React runtime per document below, and needs no build of its own. What it gives up is
pixel parity with the React renderer and the controls that need no refetch (a record picker, the
pedigree's family switch); the note is kept for the day that parity is wanted.

Before the native renderers, the 14 non-Plotly kinds (and the GenomeSpy views) reached the
report as PNG snapshots. Exact React
parity offline — medals, SVG, canvas, the interactions that need no refetch — is possible only
with main's offline component bundle (`viewer/dist-embed/embed.html`, `services/export/embed.py`),
which runs the real `ComponentRenderer` against a mock API fed by
`build_component_embed_payload`. One `<iframe srcdoc>` of it per tile is ~7 MB each (30 tiles
≈ 200 MB, the blow-up plotly.js once caused). The shape that fits a report:

1. A **multi-mount entry** (`viewer/src/embed/mountAll.tsx`, a second single-file Vite build):
   one copy of the runtime, included once in the document by the imports cell, as plotly.js is.
2. Each tile emits `<div data-depictio-embed="<index>">` and a
   `<script type="application/json" data-depictio-payload>` with
   `build_component_embed_payload(...)` for that tile (fetched by the client through a
   notebook-scoped endpoint, so it does not depend on `DEPICTIO_FASTAPI_EMBED_ENABLED`).
3. The payload buckets are already collision-free across tiles (component `index`, `embed::<index>`
   dc ids), so the mount script merges them into one `window.__DEPICTIO_EMBED__` and mounts each
   div.
4. Behind a generator option (`embed_offline`), off by default: ~7 MB once plus each tile's data,
   which is a data-download policy question the snapshots do not raise.
5. molecule_3d needs a non-stubbed 3Dmol and the structure in the payload; pae_matrix and
   ramachandran their files; GenomeSpy views and JBrowse stay snapshots (§3.4, cannot be
   exported).

Stopped at this note: the multi-mount build, the payload endpoint and the per-tile mounting are a
change of their own (L), and the snapshot already makes every one of these tiles render.
The multi-mount entry was then built — not over the embed bundle and a payload per tile, but
over the serverless runtime and one manifest for the whole document: §3.9.

### 3.9 The common trunk — the report hosts the serverless runtime

The rendered report embeds, once at its end, the serverless static runtime in mount mode and
the dashboard's `BundleManifest` — built by producer A, the same call `/export-static` makes,
with the exported state's filters as `initial_filters` (RFC `rfc-serverless-deployment.md`
§14). Every tile the generator lays out is wrapped in a placeholder that keeps the tile's own
output inside as its fallback:

```
::: {.depictio-tile data-depictio-tile="<tab_id>:<index>"}
::: {.depictio-fallback}
<the tile's cell, unchanged>
:::
:::
```

and the "Filters" part gets `<div data-depictio-filters="<entry tab>">`, where the runtime
draws the dashboard's own filter panel. The runtime replaces a fallback only when it can draw
the tile at the report's state (live tiles, frozen ones at the default state); the fallback
is hidden only once the tile is drawn, so there is never one tile twice, and it comes back if
the renderer throws. Quarto keeps what it is good at: the narrative, the reproducible Polars
funnel, the code (code-tools); the tiles are the dashboard's renderers, in Paper, and follow
the panel in the page, with no server.

**Generator option** `ExportPlan.embed_runtime` (`NotebookExportRequest.embed_runtime`):

* **Server-rendered report: on by default.** The endpoint clears it (owner on the project — a
  manifest is the data, as a static export is; a state the page can reproduce; the runtime
  built), the worker builds the manifest in-process with producer A and composes the block
  (`serverless/report.py`), and hands it to the document's last cell through
  `DEPICTIO_REPORT_RUNTIME_FILE`. Any failure leaves the block empty: the report renders
  exactly as before.
* **Downloaded `.qmd`: off by default.** Asked for, the last cell is
  `print(client.report_runtime(<entry tab>, depictio_state, config=…))`: the reader's client
  fetches `POST /serverless/report-manifest/{id}` (owner-gated, 404 on denial, 409 for a
  state it cannot reproduce, 413 over the size ceiling) and `GET /serverless/report-runtime`,
  and composes the same block (`depictio/notebook/report_runtime.py`, pure stdlib, shared by
  both paths). Without API access it prints nothing and the fallbacks stand.

The block is one raw-HTML block, inlined once: the runtime's scoped stylesheet, the report's
look (`NotebookBuilder.runtime_config`: the document's primary and Inter-first type), the
manifest, any add-on the manifest names (3Dmol.js), the runtime's script. Measured on the
seeded families (penguins, iris; Quarto 1.9.37): 9.0 MB → 19.4 MB raw, 2.5 MB → 5.6 MB gzip,
the difference being the runtime's 9.76 MB raw / 3.01 MB gzip floor plus a 0.13–0.15 MB
manifest. What stays fallback-only, and why: RFC serverless §14.

## 4. Alternatives considered

- **A self-contained HTML embed** (the catalog-preview bundle + a server-built payload per
  component). Rejected: the payload builder would re-implement what each React renderer requests
  (compute job bodies included), ~7 MB per embedded component, and the catalog shim only covers a
  subset of types. The live `/embed` route reuses the renderer and the API as they are.
- **Porting the advanced-viz renderers to Python.** Fifteen renderers, permanent drift.
- **marimo as the canonical file, with `.ipynb` and a Quarto `.ipynb` derived from it** (the first
  version of this branch). Three artefacts to keep equivalent, two Python dependencies on the API
  image (`marimo`, `nbformat`), a subprocess per download, a 501 when either was missing — for a
  reader who in practice wanted one document they can render, read and edit. Quarto alone covers
  that: the `.qmd` opens in the same editors, renders to the same report, and is plain text a
  diff can read. Rejected in favour of one `.qmd`.
- **Bundling Parquet with the export.** Bulk data exfiltration at viewer level; kept as an
  addable mode (`DEPICTIO_DATA_DIR`) rather than a default.
- **Direct Delta-on-S3 from the notebook.** No per-user credentials exist; would hand out root.

## 5. Costs / open questions

- No new dependency on the API image: the `.qmd` is generated text. The worker's `render` extra
  (`nbclient`, `ipykernel`) and Quarto are only needed for the rendered report.
- Extraction is a headless render per (component, filters): seconds, not milliseconds; cached.
- **JBrowse** is the embedded React linear view reading tracks through the instance's track
  proxy; the document carries its session as a table, a snapshot and a link (§3.4).
- Icons come from the viewer's build-time subset (`viewer/dist-icons/icon-subset.json`, shipped
  in the API image); only an id the subset lacks is asked of Iconify, under one 3 s budget.
- The dashboard's theme/brand colours are not reproduced in code-path figures (stated in the cell).
- Twelve stages at most (`FUNNEL_MAX_STAGES`), like the funnel view; the export warns.
- `EditorApp` is not wired (its filter state has a different shape); the viewer is.
- `.html` embeds need a Depictio session in the reader's browser; `.figure`/`.data` do not.
- Snapshots are PNGs of the opening view at 1200×720: 50–300 kB a tile.
- Render budget: a dashboard of 80 API tiles at 10–20 s per browser pass approaches
  `render_timeout_s` (900 s); the server builders and the cache are what keep it under.

## 6. Migration

None required. `AnalysisState` is additive; PR #967's per-user filter document and the share link
can embed it as-is. Version snapshots (#919/#924) can attach a generated notebook per snapshot
once merged (Phase 4 of the product plan).

## 7. Non-goals

Attaching notebooks to version snapshots; wasm/Pyodide export; narrower scopes (one tab, one component) in
the export modal — the client covers the "one component" case.

## 8. What contradicted the brief

| assumed | found |
| --- | --- |
| #967, #963, #919, #924 merged | none are; this branch creates the drawer's Export slot and the state object from scratch |
| funnel stage order is shell state | it was the funnel modal's local state; lifted to `App.tsx` |
| the #975 seam can be reused as-is | it yields `pl.Expr`; a source emitter pinned by an equivalence test is the honest reuse |
| an API data path exists | none did; `GET /deltatables/data/{dc}` is new |
| every component has a server figure | only figure/map/multiqc + 3 advanced-viz kinds; the rest are React-rendered |
| seeds carry grid layout | no `.db_seeds` component has one; reading order falls back to stored order |
| `Switch` filters rows | `add_filter` has no branch for it |

## 9. For depictio-docs (user-facing, to move)

**Export a dashboard as a notebook.** Open the dashboard settings (cog icon) → *Export* →
*Export as notebook*. The preview lists every tile and how it will appear: *as code* (Polars /
Plotly you can edit), *via Depictio* (rendered by the instance with your filters), or *omitted*
(with the reason). Download the Quarto document (`.qmd`), or — where the instance offers it — a
report rendered for you. Before rendering the document yourself, create a token on
the *CLI agents* page and set `DEPICTIO_API_URL` and `DEPICTIO_API_TOKEN`.

**Use any component in your own notebook.**

```python
from depictio.notebook import DepictioClient

client = DepictioClient()
dash = "6824cb3b89d2b72169309738"
species = client.filter(dash, "Species", ["Adelie", "Gentoo"])
client.component(dash, "Bill shape", filters=[species])  # Plotly figure
client.component(dash, "Raw data").data  # polars DataFrame
client.component(dash, "Sample embedding").figure  # advanced viz, extracted
client.data("646b0f3c1e4a2d7f8e5b8ca1")  # the whole table
```
