# Component export — embedding Depictio components elsewhere

`GET /depictio/api/v1/export/…` serves a single dashboard component for use on an
external website, in one of two formats.

Before this existed, the only exports were *config* exports — `/dashboards/{id}/yaml`
and `/dashboards/{id}/json` — which carry definitions for re-import into another
Depictio instance, not rendered output.

## The two formats, and why coverage differs

| Format | What you get | Size | Coverage |
|---|---|---|---|
| `json` | `{data, layout, config, meta}` — a Plotly spec for your own plotly.js | ~1–500 KB | Where a figure is built server-side |
| `html` | One self-contained HTML file, no network calls | ~7 MB | Every component type except `jbrowse` |

**Prefer `json`.** Depictio is visualisation-oriented and the consumer already
has the data, so what they want is a finished figure they can drop into their own
page and restyle. `html` is the fallback for component types with no server-side
figure, and for archiving a result next to a manuscript. It is ~7 MB because it
inlines the whole React renderer, of which the actual payload is 1–400 KB.

The asymmetry is not arbitrary. `html` injects a payload into a prebuilt React
bundle that runs the viewer's **real** `ComponentRenderer`, so component types with
no server-side figure — tables, cards, images, and the advanced-viz kinds whose
Plotly spec is assembled in TypeScript — render correctly with no Python
equivalent. `json` can only serve what Python can build.

### Per-component support

| Component type | `json` | `html` | Notes |
|---|:---:|:---:|---|
| `figure` | ✅ | ✅ | `services/figure/figure_builder.py` |
| `map` | ✅ | ✅ | `services/map/render.py` |
| `multiqc` | ✅ | ✅ | 503 while the figure cache warms; `html` waits it out |
| `advanced_viz` | 12 of 35 kinds | 32 of 35 | see below |
| `table` | ❌ | ✅ | AG Grid, not Plotly |
| `card` | ❌ | ✅ | scalar + DOM |
| `image` | ❌ | ✅ | S3 path list |
| `interactive` | ❌ | ✅ | a filter control, not a visualisation |
| `text` | ❌ | ✅ | live values (`{{name}}`) computed with the cards |
| `jbrowse` | ❌ | ❌ | an iframe onto a live JBrowse2 server; cannot be taken offline |
| `highlight` | ❌ | ❌ | another tab's component: the manifest names its `source`, export that |

**`advanced_viz`** is gated per `viz_kind`, and for three kinds per **view**:

- **Server-built already** — `complex_heatmap`, `upset_plot`, `sankey`. Their Celery
  compute tasks return a figure, so `json` works. The export prepares the payload
  through the dispatch route's own helpers (link filters, the heatmap's annotation
  join), see `services/export/compute.py`.
- **Ported to Python** — `volcano` (all three views), `pr_benchmark` (all three),
  `manhattan`, `embedding`, `stacked_taxonomy`, `da_barplot`, `sunburst`,
  `confusion_matrix`, `metric_ci_bars`, and `dot_plot` on its enrichment view
  (`services/advanced_viz/kinds/`).
- **Client-only** — the other 23 kinds. `json` answers **501** with
  `html_available: true` and an `html_url`; `html` works, except for the three
  below.
- **No offline page** — `genome_view` (GenomeSpy fetches its own tracks),
  `contact_map` and `group_compare` (they compute per zoom window / per pair of
  selections), and any tile saved on a GenomeSpy view (`coverage_track` and
  `cnv_profile` on `locus`, `sashimi` on `genomespy`). The manifest says why in
  `html_unavailable_reason`.

**Views.** Main folded `ma`/`qq` into `volcano`, `enrichment` into `dot_plot` and
`roc_pr_curve` into `pr_benchmark`, each behind a `view`. The Python builders stay
one per drawing, so `services/advanced_viz/views.py` reads the view a component is
saved on (or `?controls={"view": "ma"}`) and picks the builder. A stored component
of a retired kind and its survivor on the matching view resolve to the same plan.
`meta.view` names the view drawn.

Adding a module under `services/advanced_viz/kinds/` is the only change needed to
move a kind from the third group to the second — `capabilities.py` reads the
registry, so the manifest and the 501 branch both update on their own.

Ask the API rather than hardcoding any of this:

```
GET /depictio/api/v1/export/dashboards/{dashboard_id}/components
```

returns `[{component_id, component_type, viz_kind, title, formats,
json_unavailable_reason?, html_unavailable_reason?, filter?, source?}]`.

## From a tile

When the export API is on, every tile of the viewer carries an **Export / embed**
action (`mdi:code-json`). It opens a dialog that reads the manifest and offers:

- **Mode**: *Plotly spec (JSON)* or *Embeddable page (HTML)*. A mode the component
  lacks is disabled, with the manifest's reason as its tooltip. The dialog opens on
  JSON when the component has it.
- **Theme**: light or dark, defaulting to the viewer's.
- **Include the current filters (N)**: the tile's active filters, sent as `filters`.
- **Snippets**: the URL, `curl` (switching to the `POST` form once the URL passes
  2000 characters), a `plotly.js` snippet for JSON, an `<iframe>` for HTML. Copy,
  or open in a new tab.
- **Warnings**: a private project needs a bearer token (named `$DEPICTIO_TOKEN`
  in the snippets, never the session's own); no `<iframe>` will load until an
  origin is listed in `DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS`.

The action is absent when the API is off (`embed_enabled` on `/auth/me/optional`),
on JBrowse tiles, and while a past version is shown (`?version=`): the API serves
the live dashboard. A tile in a cross-tab section exports from its owner tab, and a
highlight exports its source component (`ChromeSource` in
`depictio-react-core/src/components/chrome/ExportContext.tsx`).

## Usage

```bash
# Plotly spec
curl "$BASE/export/dashboards/$DASH/components/$CID?format=json" | jq '.data | length'

# Self-contained page
curl "$BASE/export/dashboards/$DASH/components/$CID?format=html" > embed.html
```

Query parameters: `format` (`json` \| `html`), `theme` (`light` \| `dark`), and
`filters` (URL-encoded JSON array). A `POST` to the same path accepts
`{"filters": [...], "theme": "..."}` in the body when filters are too large for a
query string.

To embed:

```html
<iframe src="https://depictio.example.org/depictio/api/v1/export/dashboards/DASH/components/CID?format=html"
        width="100%" height="420" frameborder="0"></iframe>
```

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `DEPICTIO_FASTAPI_EMBED_ENABLED` | `false` | Master switch. While off, every export route 404s with `code: embed_disabled` |
| `DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS` | *(empty)* | Comma-separated origins allowed to frame an embed. Becomes CSP `frame-ancestors`; empty means `'none'`, so embeds render standalone but cannot be iframed. `*` is rejected |
| `DEPICTIO_FASTAPI_EMBED_CSP_UNSAFE_INLINE` | `false` | Escape hatch: use `script-src 'unsafe-inline'` instead of per-script SHA-256 hashes |

Off by default because serving embeds necessarily relaxes framing protections on
that path. Both keys are wired through the backend Helm ConfigMap
(`backend.env.DEPICTIO_FASTAPI_EMBED_*`), both compose files and `.env.example`.

## Access control

Reuses `check_project_permission(..., "viewer")` — the same gate every `render_*`
endpoint applies. **Public projects** are readable without a token; **private**
ones need a bearer token. That holds in **every auth mode**.

The deliberate deviation is `get_embed_user`. The standard `get_user_or_anonymous`
is the wrong fallback in both directions: on a multi-user deployment it raises 401
before any project check runs (no anonymous user is stored), and in single-user mode
the stored anonymous user is an *admin*, which `check_project_permission` lets
through before it looks at `is_public` — every project would be readable from any
allow-listed origin. So an export caller without a valid token is always a
non-admin anonymous principal (`public_only_principal`), and the project check
answers `is_public`. A token keeps its full rights.

### Known limitation: cross-DC link filters

`_resolve_link_filters` returns filters unchanged when there is no access token, so
an **anonymous** export of a public dashboard does not apply link-derived cross-DC
filters. A filter set on one data collection will not propagate to the embedded
component's collection. Authenticated exports are unaffected.

### Known limitation: intra-viz control state

Advanced-viz renderers seed controls (thresholds, top-N, rank pickers) from the
persisted config, then keep live tweaks in browser state. A server-side export
therefore renders at the **persisted config state**, which can differ from what a
user is currently looking at. Pin values explicitly via `controls` if you need a
specific state.

### Known limitation: live data only

The export serves the live dashboard and its latest data. It takes no
`?version=`: a time-travelling read needs both the data pins and the definition
version (see the versioning notes in `CLAUDE.md`), and only some kinds can honour
them (advanced-viz data and MultiQC are not versioned). The dialog is therefore
hidden while a version is previewed.

## Caching and pinning

Every response carries a weak `ETag` and `X-Depictio-Revision`, both exposed to
cross-origin JavaScript, and `meta.revision` / `meta.dashboard_version_id` in JSON.
The revision covers what can change the output:

- the **definition** — the family's latest `content_hash` in the version ledger
  (`dashboard_versions`), or the stored content for a family with no entry yet. Not
  the document's `version` (it counts imports) nor `last_saved_ts` (screenshots
  rewrite it);
- the **data** — the latest `aggregation_hash` of every collection the component
  reads (its own, an MA table, a tree, a text tile's values), so a re-ingest
  invalidates.

Poll with `If-None-Match` for a `304`; pin with `?expect_revision=<revision>` for a
`409` (`code: revision_mismatch`) when either moved. The ETag also covers format,
theme, filters and controls.

## Deployment

The `html` format needs the prebuilt bundle at
`depictio/viewer/dist-embed/embed.html`. `docker-images/Dockerfile.api` builds it in
the same discarded Node stage as the catalog preview and copies the single HTML file
in; no Node reaches runtime.
Building locally:

```bash
cd depictio/viewer && pnpm run build:embed
```

Without it, `format=html` answers **503** with `code: bundle_unavailable`.

Behind nginx, `docker-images/nginx.conf.template` carries a
`location ~ ^/depictio/api/v[0-9]+/export/` block. It exists because the
server-scope `add_header ... always` directives would otherwise apply here too, and
**multiple CSP headers are enforced as an intersection** — meaning the backend could
never loosen `frame-ancestors` on its own. An `add_header` inside a location
replaces the inherited set wholesale, so that block re-declares the baseline headers
and deliberately omits `Content-Security-Policy` and `X-Frame-Options`.

`SecurityHeadersMiddleware` (`depictio/api/main.py`) has a matching exemption:
`setdefault` lets a handler override a header but never *remove* one, and
`X-Frame-Options: SAMEORIGIN` has no "allow these origins" form — so it has to be
skipped in the middleware. The exemption is scoped to `text/html` responses, so the
`json` format keeps the strict defaults.

All four pieces — middleware exemption, handler headers, nginx block, script hashes
— are required. Any one missing leaves cross-origin embedding broken.

## Implementation map

| Path | Role |
|---|---|
| `api/v1/endpoints/export_endpoints/routes.py` | The three routes, `get_embed_user`, `public_only_principal` |
| `api/v1/services/export/capabilities.py` | The support matrix — single source of truth, per component |
| `api/v1/services/export/resolve.py` | Dashboard + component lookup, over `_viewable_dashboard` |
| `api/v1/services/export/plotly_export.py` | `json` format; calls the live render endpoints |
| `api/v1/services/export/embed.py` | `html` format: payload builder, bundle injection, CSP |
| `api/v1/services/export/compute.py` | Celery-backed kinds run inline, prepared as their dispatch route does |
| `api/v1/services/export/revision.py` | Revision, ETag, pin |
| `api/v1/services/export/cors.py` | Embed allowlist: CORS headers and preflights |
| `api/v1/services/export/bundle.py` | Offline-bundle injection |
| `api/v1/services/advanced_viz/views.py` | Which builder draws a component, given its view |
| `api/v1/services/advanced_viz/figure_registry.py` | Per-kind Python builder registry |
| `api/v1/services/advanced_viz/data.py` | Tidy data, through the `/advanced_viz/data` handler |
| `api/v1/services/advanced_viz/theme.py` | Python port of `plotlyTheme.ts` |
| `viewer/src/offline/mockApi.ts` | Offline API shim, shared with the catalog preview |
| `viewer/src/embed/` | The bare embed shell |
| `viewer/src/components/export/` | The tile dialog and its provider |
| `depictio-react-core/src/components/chrome/ExportContext.tsx` | The tile action's context and `ChromeSource` |

### Payload keying

`mockApi.ts` keys figure / table / map / image / multiqc payloads by component
`index`, and interactive / advanced_viz payloads by `dc_id`. Two components on a real
dashboard can share a data collection, so `embed.py` rewrites `dc_id` in the
*embedded copy* of the metadata to `embed::<index>` (and the phylogenetic tree's
separate `config.tree_dc_id` to `embed::<index>::tree`). Nothing inside the bundle
needs the real id.
