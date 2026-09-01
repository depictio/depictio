# Component export — embedding Depictio components elsewhere

`GET /depictio/api/v1/export/…` serves a single dashboard component for use on an
external website, in one of two formats.

Before this existed, the only exports were *config* exports — `/dashboards/{id}/yaml`
and `/dashboards/{id}/json` — which carry definitions for re-import into another
Depictio instance, not rendered output.

## The three formats, and why coverage differs

| Format | What you get | Size | Coverage |
|---|---|---|---|
| `json` | `{data, layout, config, meta}` — a Plotly spec for your own plotly.js | ~1–500 KB | Where a figure is built server-side |
| `data` | `{columns, rows, total, meta}` — one page of rows | ~1–200 KB | `table` |
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

`data` exists because "has no Plotly spec" and "has nothing a host can use" are
different statements, and a table is the case where they came apart. Framing a
table ships several MB of Depictio to render rows the host could style itself, in
a grid the host cannot theme. The rows were already computed server-side for the
embed payload; `data` is the way to ask for them. It is a third shape rather than
a second meaning for `json`, because a caller asking for `json` expects something
it can hand to Plotly.

Paging is explicit and belongs to the caller: `?start=` and `?limit=` name the
window, the response repeats the window it served and carries `total`, and
`meta.complete` says whether the page is the whole table. The limit is capped
(5000) rather than rejected, so an over-large ask is answered rather than refused.
Each window gets its own ETag; without that, page 2 would be served from page 1's
cache entry.

### Per-component support

| Component type | `json` | `html` | Notes |
|---|:---:|:---:|---|
| `figure` | ✅ | ✅ | `services/figure/figure_builder.py` |
| `map` | ✅ | ✅ | `services/map/render.py` |
| `multiqc` | ✅ | ✅ | 503 while the figure cache warms; `html` waits it out |
| `advanced_viz` | 12 of 18 kinds | ✅ | see below |
| `table` | ❌ | ✅ | AG Grid, not Plotly — but `data` returns its rows |
| `card` | ❌ | ✅ | scalar + DOM |
| `image` | ❌ | ✅ | S3 path list |
| `interactive` | ❌ | ✅ | a filter control, not a visualisation |
| `text` | ❌ | ✅ | needs no data at all |
| `jbrowse` | ❌ | ❌ | an iframe onto a live JBrowse2 server; cannot be taken offline |

`table` is the only type that supports `data` today. Nothing in the contract stops
another type from joining it; a card, for instance, is a number and could return
one. The reason to wait is that nobody has asked, and a format with one consumer
is easier to change than a format with three.

**`advanced_viz`** is gated per `viz_kind`:

- **Server-built already** — `complex_heatmap`, `upset_plot`, `sankey`. Their Celery
  compute tasks return a figure, so `json` works.
- **Ported to Python** — `volcano`, `ma`, `qq`, `manhattan`, `embedding`,
  `stacked_taxonomy`, `da_barplot`, `enrichment`, `sunburst`
  (`services/advanced_viz/kinds/`).
- **Client-only** — the remaining 6: `rarefaction`, `dot_plot`, `lollipop`,
  `oncoplot`, `coverage_track`, `phylogenetic`. `json` answers **501** with
  `html_available: true` and an `html_url`; `html` works today.

Adding a module under `services/advanced_viz/kinds/` is the only change needed to
move a kind from the third group to the second — `capabilities.py` reads the
registry, so the manifest and the 501 branch both update on their own.

Ask the API rather than hardcoding any of this:

```
GET /depictio/api/v1/export/dashboards/{dashboard_id}/components
```

returns `[{component_id, component_type, viz_kind, title, formats, json_unavailable_reason?}]`.

## Usage

```bash
# Plotly spec
curl "$BASE/export/dashboards/$DASH/components/$CID?format=json" | jq '.data | length'

# Self-contained page
curl "$BASE/export/dashboards/$DASH/components/$CID?format=html" > embed.html

# A table's rows, one page at a time
curl "$BASE/export/dashboards/$DASH/components/$CID?format=data&start=0&limit=50" \
  | jq '{rows: (.rows | length), total, complete: .meta.complete}'
```

Query parameters: `format` (`json` \| `data` \| `html`), `theme` (`light` \| `dark`), and
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
that path.

## Access control

Reuses `check_project_permission(..., "viewer")` — the same gate every `render_*`
endpoint applies. **Public projects** are readable without a token; **private**
ones need a bearer token.

The one deliberate deviation is `get_embed_user`. The standard
`get_user_or_anonymous` only falls back to the anonymous identity in public or
single-user mode and otherwise raises 401 *before* any project check runs, which
would make embeds unusable on a normal multi-user deployment. `get_embed_user`
always falls back to that same anonymous user, and the project check still runs —
so the effective widening is **public projects only**, on this router only, and
only when `embed_enabled`.

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

## Deployment

The `html` format needs the prebuilt bundle at
`depictio/viewer/dist-embed/embed.html`. `docker-images/Dockerfile.api` builds it in
a discarded Node stage and copies the single HTML file in; no Node reaches runtime.
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
| `api/v1/endpoints/export_endpoints/routes.py` | The three routes and `get_embed_user` |
| `api/v1/services/export/capabilities.py` | The support matrix — single source of truth |
| `api/v1/services/export/resolve.py` | Dashboard + component lookup and permission gate |
| `api/v1/services/export/plotly_export.py` | `json` format; dispatches to the live render paths |
| `api/v1/services/export/table_export.py` | `data` format: one page of a table's rows |
| `api/v1/services/export/embed.py` | `html` format: payload builder, bundle injection, CSP |
| `api/v1/services/export/bundle.py` | Shared offline-bundle injection (also used by the catalog) |
| `api/v1/services/advanced_viz/figure_registry.py` | Per-kind Python builder registry |
| `api/v1/services/advanced_viz/theme.py` | Python port of `plotlyTheme.ts` |
| `viewer/src/offline/mockApi.ts` | Offline API shim, shared with the catalog preview |
| `viewer/src/embed/` | The bare embed shell |

### Payload keying

`mockApi.ts` keys figure / table / map / image / multiqc payloads by component
`index`, and interactive / advanced_viz payloads by `dc_id`. Two components on a real
dashboard can share a data collection, so `embed.py` rewrites `dc_id` in the
*embedded copy* of the metadata to `embed::<index>` (and the phylogenetic tree's
separate `config.tree_dc_id` to `embed::<index>::tree`). Nothing inside the bundle
needs the real id.
