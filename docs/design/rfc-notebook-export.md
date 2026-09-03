# RFC — Depictio → code (a dashboard as a runnable notebook, every component importable)

**Status:** Implemented in this branch; design recorded for review.
**Audience:** maintainers.
**Related:** `depictio/models/models/analysis_state.py` (the contract),
`depictio/api/v1/services/notebook_export/` (the generator),
`depictio/api/v1/services/embed/` + `depictio/viewer/src/embed/` (figure extraction),
`depictio/notebook/` (the Python client), PR #975 (funnel filtering, the seam this reuses),
PR #962 / #1013 (groups, split panels), PR #963 (serverless bundle — the coverage-table shape
and the "frozen badge" tone this borrows; none of its code).

> Every dashboard tool is a dead end: what you build by clicking cannot be handed back to you as
> code. This is Depictio returning the code — and, the other way round, letting any component of
> a dashboard be pulled into a Jupyter, marimo or Quarto cell.

## 1. Context

A scientist explores in the browser: filters, a funnel order, a lasso'd group, a split view. The
server runs real Polars queries against Delta tables for every tile. Nothing of that survives the
browser tab. Two capabilities close the loop:

1. **Export** — the whole dashboard family (all tabs) plus the *current analysis state* becomes a
   **marimo `.py` notebook** that reproduces the same queries, with a derived Jupyter `.ipynb` and a
   Quarto-ready `.ipynb`.
2. **Import** — `depictio.notebook.DepictioClient` brings **any** component of a dashboard —
   figures, cards, tables, filters, text, maps, MultiQC, images, JBrowse, all 18 advanced-viz kinds
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

One generator, three artefacts. The marimo `.py` is canonical; the `.ipynb` is derived with
`marimo export ipynb --no-include-outputs --sort top-down` (never a second nbformat template); the
Quarto variant is that `.ipynb` plus a YAML front-matter *raw* cell added with `nbformat`
(metadata only — the cell code path stays marimo's).

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
Cell-locals use `_`. Code-mode figures are inlined **verbatim** inside `def _make_<name>(df): …;
return fig`, so the author's `df`/`fig` survive and never become globals. The AST guard test
proves no global is defined by two cells and that every cell's `return` matches its definitions;
`marimo check --strict` passes on the seeded exports.

### 3.4 Coverage — how each component reaches the notebook

| component | in the notebook | why |
| --- | --- | --- |
| text | **code** (markdown cell) | no data path |
| interactive | **code** (a funnel stage when active) | it *is* the query |
| card | **code** (`final.select(<reduction>).item()`) | mirrors `_agg_expr`; `box_plot_stats`/`mode` → via API |
| table | **code** (`final.select(cols).head(page_size)`) | the page the dashboard shows |
| figure, UI mode | **code** (`px.<visu_type>(final, **kwargs)`) | kwargs cleaned by the same `clean_px_kwargs` as the server; theme not reproduced |
| figure, code mode | **code** (verbatim) | the prologue *is* code |
| figure, `heatmap` | via API | plotly-complexheatmap on the server |
| map, MultiQC | via API (`.figure` = server Plotly) | built by the server |
| advanced_viz — `complex_heatmap`, `upset_plot`, `sankey` | via API (`.figure` = server Plotly) | Celery computes |
| advanced_viz — the other 15 kinds | via API (`.figure` **extracted** from the React renderer) | drawn client-side from data |
| image | via API (`.html`/`.data`) | object-store gallery |
| jbrowse | via API (`.html` iframe) | a session on the JBrowse host |

`omitted` is reserved for the case no path can serve (a collection with no Delta table). The
exhaustiveness test fails when a `ComponentType` or `AdvancedVizKind` gains a member without a
verdict.

### 3.5 Universal import — three representations per component

`client.component(dashboard, "Bill shape", filters=[...])` returns a `DepictioComponent` with
`.figure` (a `plotly.graph_objects.Figure`), `.data` (a `polars.DataFrame`, or a dict for cards)
and `.html` (the live tile). It displays itself in Jupyter and Quarto through
`_repr_mimebundle_` and in marimo through `_mime_`; the default is the closest thing to what the
dashboard shows (figure, DataFrame, a small HTML card, markdown, an image grid, an iframe).

**Headless figure extraction.** For the 15 React-rendered advanced-viz kinds there is no Plotly on
the server. Rather than port the renderers, the viewer gains `/embed/{dashboard}/{component}
#state=<base64url JSON>&theme=…`: one `ComponentRenderer`, the real one, fed through the ordinary
API with the state in the URL hash. The worker loads that page in headless Chromium (the screenshot
machinery, admin token injected) and reads `gd.data`/`gd.layout` off the Plotly div —
`POST /dashboards/component_figure/{d}/{c}` dispatches, `GET …/jobs/{id}` polls, results are
cached per (component, filters, theme). Same renderer, same numbers, no second implementation.
`POST /dashboards/embed/{d}/{c}` returns an HTML page framing the same route for a reader who is
logged into the instance.

### 3.6 Three ways to open the export

| target | file | open with | notes |
| --- | --- | --- | --- |
| marimo | `<name>.py` | `marimo edit <name>.py` | reactive: change a stage, downstream cells re-run |
| Jupyter | `<name>.ipynb` | `jupyter lab <name>.ipynb`, Run All | derived by marimo, outputs empty (nbstripout-safe) |
| Quarto | `<name>.quarto.ipynb` | `quarto render <name>.quarto.ipynb` / `quarto preview` | front matter: title, author, date, `format: html` (toc, code-fold, embed-resources), `jupyter: python3`; PDF needs `kaleido` |

The client also works inside a `.qmd` `{python}` block.

### 3.6b The rendered report (server-side, opt-in)

A fourth choice in the export modal: **Quarto report**, the Quarto notebook run here. The reader gets
one self-contained file with every result in it and nothing to install; the notebook is unchanged,
so the report is the export's own output rather than a second renderer.

It is a job, not a request. `POST /dashboards/notebook_export/{id}/render` builds the same Quarto
`.ipynb` the download hands out, stages it in S3 under `notebook_reports/{user}/{job}/` (~10 MB is
not a broker message), mints a **short-lived token for the caller** and queues
`render_notebook_report` with the token's *id*. The worker runs `quarto render --execute` with
`QUARTO_PYTHON` pinned to its own interpreter, stores the HTML next to the notebook, deletes both
the staged notebook and the token, and the client polls `GET …/render/{job}` then downloads from
`GET …/render/{job}/download`. Keys are namespaced by user, so a download can only ever address the
caller's own reports.

Two Quarto behaviours cost a full render each to find, and both are guarded in `render.py`:
rendering an `.ipynb` **does not execute it** unless asked (`--execute`), and an interpreter without
Jupyter makes Quarto skip execution — in both cases it writes a report with every result missing and
exits 0. The service checks the log for the execution it asked for before believing the output.

**What it costs.** The worker image gains Quarto (~250 MB, `Dockerfile.worker`) and the `render`
extra (`nbclient`, `ipykernel`). A render re-executes the notebook against this deployment's own
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

## 4. Alternatives considered

- **A self-contained HTML embed** (the catalog-preview bundle + a server-built payload per
  component). Rejected: the payload builder would re-implement what each React renderer requests
  (compute job bodies included), ~7 MB per embedded component, and the catalog shim only covers a
  subset of types. The live `/embed` route reuses the renderer and the API as they are.
- **Porting the advanced-viz renderers to Python.** Fifteen renderers, permanent drift.
- **`.qmd` as a third generator.** Quarto renders `.ipynb` natively; front matter is enough.
- **Bundling Parquet with the export.** Bulk data exfiltration at viewer level; kept as an
  addable mode (`DEPICTIO_DATA_DIR`) rather than a default.
- **Direct Delta-on-S3 from the notebook.** No per-user credentials exist; would hand out root.

## 5. Costs / open questions

- `marimo` and `nbformat` become base dependencies of the API image (pure Python; imported lazily
  by the ipynb path). The `.py` export works without them; the ipynb variants answer 501 otherwise.
- Extraction is a headless render per (component, filters): seconds, not milliseconds; cached.
- **JBrowse** sessions are built with hard-coded `localhost` hosts (`routes.py`,
  `render_jbrowse`); outside the instance's network the iframe cannot load. Pre-existing; flagged.
- The dashboard's theme/brand colours are not reproduced in code-path figures (stated in the cell).
- Twelve stages at most (`FUNNEL_MAX_STAGES`), like the funnel view; the export warns.
- `EditorApp` is not wired (its filter state has a different shape); the viewer is.
- `.html` embeds need a Depictio session in the reader's browser; `.figure`/`.data` do not.

## 6. Migration

None required. `AnalysisState` is additive; PR #967's per-user filter document and the share link
can embed it as-is. Version snapshots (#919/#924) can attach a generated notebook per snapshot
once merged (Phase 4 of the product plan).

## 7. Non-goals

Server-side execution or Quarto rendering; attaching notebooks to version snapshots; pinning data
versions (Delta time travel); wasm/Pyodide export; narrower scopes (one tab, one component) in
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
| marimo alone derives `.ipynb` | it also needs `nbformat` |

## 9. For depictio-docs (user-facing, to move)

**Export a dashboard as a notebook.** Open the dashboard settings (cog icon) → *Export* →
*Export as notebook*. The preview lists every tile and how it will appear: *as code* (Polars /
Plotly you can edit), *via Depictio* (rendered by the instance with your filters), or *omitted*
(with the reason). Pick marimo, Jupyter or Quarto and download. Before running, create a token on
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
