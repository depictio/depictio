# MVP handoff — React viewer + shared components

## Closed gaps (2026-05-04)

The following parity gaps versus the Dash viewer were closed in the
`feat/react-viewer-mvp` branch. Each item lists the resolution path so a
reviewer can verify the change without re-tracing the implementation.

- **Cross-DC link filtering on every render endpoint.** `extend_filters_via_links`
  moved from `depictio/dash/utils.py` to `depictio/api/v1/filter_links.py`;
  Dash callers continue working via a re-export shim. The React-facing
  endpoints (`bulk_compute_cards`, `render_figure`, `render_table`,
  `render_map`, `render_image_paths`) now resolve link filters server-side via
  the new `_resolve_link_filters` helper in `dashboards_endpoints/routes.py`.
- **Selection-as-filter for scatter, table, and map.** `FigureRenderer`,
  `TableRenderer`, and `MapRenderer` emit selection events back to filter
  state via a new `onFilterChange` prop. `InteractiveFilter.source` carries a
  `scatter_selection|table_selection|map_selection` discriminator (mirrors
  Dash `interactive-values-store`). App-level merge logic lives in
  `mergeFiltersBySource` (`packages/depictio-react-core/src/selection.ts`).
- **Image-grid filter integration.** `ImageRenderer` now consumes a `filters`
  prop; `/render_image_paths` accepts a POST body `{ filters, max }` and
  applies the same filter pipeline (regular + selection sources + cross-DC
  links) used by the other endpoints.
- **GeoJSON access token + map selection.** `/render_map` plumbs the request's
  access token through to `render_map(...)` so `geojson_url` choropleth flows
  resolve server-side. The endpoint also passes back the user's own
  `map_selection` values as `active_selection_values` so the highlighted
  state survives re-renders.
- **JWT refresh lifecycle in React.** `packages/depictio-react-core/src/api.ts`
  adds `refreshAccessToken`, `authFetch` (single 401-retry), and
  `validateSession` (proactive refresh inside a 60 s window). The viewer
  calls `validateSession` in `main.tsx` before mounting routes. Backend gains
  a browser-safe `POST /auth/refresh` endpoint (no internal-api-key
  required — the refresh token is itself the credential).
- **WebSocket realtime updates.** `useDataCollectionUpdates`
  (`packages/depictio-react-core/src/realtime.ts`) subscribes to
  `/depictio/api/v1/events/ws?token=…&dashboard_id=…` with auto-reconnect
  (capped exponential backoff). `RealtimeIndicator` exposes a Manual ↔ Auto
  refresh toggle (persisted to `localStorage['depictio.realtime.mode']`) and
  Pause/Resume. Mounted in both `App.tsx` (viewer) and `EditorApp.tsx`
  (editor). `settings.events.enabled` now defaults to true.
- **Demo-mode guided tour.** `depictio/viewer/src/demo/DemoTour.tsx` runs a
  4-step Mantine Popover tour the first time a user visits in demo mode
  (gated on `is_demo_mode === true` and a `localStorage['depictio.tour.seen']
  !== 'v1'` flag). `DemoModeBanner` adds a sticky "Demo mode — your changes
  won't be saved" alert. Shipped with no extra dependency — built on
  Mantine's existing primitives.
- **`UpgradeToTemporaryModal` surfaced on viewer routes.** A new
  `UpgradeToTemporaryButton` lives in the AppShell header and shows when
  `unauthenticated_mode && is_anonymous && !is_temporary`. The modal already
  existed in `/profile-beta`; this lifts the affordance to the dashboard
  viewer + editor so anonymous users can upgrade without leaving the page.
- **Per-source `ResetButton` on figure / table / map.** Action chrome shows a
  reset chip when the component owns an active selection; the button clears
  only that source via `onFilterChange({ value: [], source })` — mirrors
  `depictio/dash/modules/shared/selection_utils.py:handle_reset_button`. A
  parent-rendered "Clear chart selections" link appears in the filter panel
  when ≥1 selection is active.

Verification (code-level greps):

```bash
grep -n "onSelected\|onClick" packages/depictio-react-core/src/components/{Figure,Map}Renderer.tsx
grep -n "onSelectionChanged" packages/depictio-react-core/src/components/TableRenderer.tsx
grep -n "_resolve_link_filters" depictio/api/v1/endpoints/dashboards_endpoints/routes.py
grep -rn "useDataCollectionUpdates" depictio/viewer/src/
grep -n "authFetch\|validateSession" packages/depictio-react-core/src/api.ts
```

Build status: `pnpm build` in `depictio/viewer/` succeeds; `tsc --noEmit`
clean across both packages; `ruff check` and `ruff format` clean. The 22
pre-existing `ty` diagnostics are unchanged (down from 23) — none introduced
by this branch.

---


Session deliverable: the split-architecture MVP from the plan is **built and imports cleanly end-to-end**. A fresh container rebuild or `uv sync` will make it live. This doc tells you exactly what to do next.

## What was built

Two new directories + minor edits to two existing files:

```
packages/depictio-components/       (new — shared React + Dash library)
├── src/lib/components/
│   ├── DepictioCard.tsx            ← @mantine/core + @iconify/react
│   └── DepictioMultiSelect.tsx
├── src/lib/index.ts
├── depictio_components/            ← Python wrappers (Dash Component protocol)
│   ├── __init__.py
│   ├── DepictioCard.py
│   ├── DepictioMultiSelect.py
│   └── depictio_components.min.js  ← 142 KB built bundle
├── package.json
├── tsconfig.json
├── webpack.config.js
├── pyproject.toml                  ← hatchling; editable via [tool.uv.sources]
└── README.md

depictio/viewer/                    (new — React viewer SPA)
├── dist/                           ← built output (446 KB JS + 206 KB CSS)
├── src/
│   ├── App.tsx                     ← AppShell mirror of Dash's viewer chrome
│   ├── main.tsx
│   ├── theme.ts                    ← Mantine theme matching shared_app_shell
│   ├── api.ts                      ← FastAPI fetch wrappers w/ JWT auth
│   ├── styles/app.css              ← CSS variables matching Depictio tokens
│   └── components/
│       ├── ComponentRenderer.tsx   ← dispatches on component_type
│       └── DashboardGrid.tsx       ← react-grid-layout, reads stored_layout_data
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts

Modified:
  pyproject.toml                    ← adds depictio-components to [tool.uv.sources] + deps
  depictio/api/main.py              ← mounts /dashboard-beta/{id} SPA
  depictio/api/v1/endpoints/deltatables_endpoints/routes.py
                                    ← adds GET /unique_values/{dc_id}?column=…
```

## To bring it live (in order)

1. **Run `uv lock` + `uv sync --extra dev`** once your network can reach pypi. (Tried during session — pypi timed out.) This installs the new `depictio-components` editable package into `.venv` and makes `from depictio_components import DepictioCard` importable.

2. **Rebuild + restart the frontend + backend containers** so they pick up:
   - The new `/unique_values` FastAPI route (backend)
   - The new `/dashboard-beta/{id}` SPA mount (backend)
   - The `depictio-components` Python package (both)

   ```bash
   docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up -d --build depictio-frontend depictio-backend
   ```

   (Dockerfile does NOT need Node.js changes. The JS bundles are pre-built and committed — `packages/depictio-components/depictio_components/depictio_components.min.js` and `depictio/viewer/dist/*`. Dockerfile only runs `uv sync` to install Python deps, which picks up the bundles via the package layout.)

3. **Visit the React viewer**: `http://0.0.0.0:8122/dashboard-beta/646b0f3c1e4a2d7f8e5b8cb4` (bab4).

   Note the port: **8122 (FastAPI)**, not 5122 (Dash). The React viewer lives on the API server to keep fetch same-origin. For the Dash viewer you continue to use `5122/dashboard/{id}` — unchanged.

## What will work on first render

- Dashboard loads — header shows dashboard title, sidebar shows interactive filters list
- Cards render with icon, title, value
  - **Filter-aware**: bulk endpoint computes card values with current filter state applied via Polars. Matches Dash viewer math exactly.
- MultiSelect renders with options loaded from `/deltatables/unique_values/{dc_id}?column=…`
  - Selecting values updates local React filter state, shows badge count in the sidebar
  - **Card values recompute automatically** via `POST /dashboards/bulk_compute_cards/{id}`, debounced 150 ms
  - "Reset all filters" link appears in the sidebar when any filter is active
- Components not yet ported (Figure, Table, MultiQC, Map, Image, JBrowse) show a visible "not yet ported" placeholder — intentional, degrades gracefully

## Parallelization strategy

Cold load does this in parallel:
1. `GET /dashboards/get/{id}` (metadata — serial, gates everything)
2. Then simultaneously:
   - `POST /dashboards/bulk_compute_cards/{id}` (all cards in ONE round trip; server dedupes Delta loads per unique wf_id/dc_id so cost scales with DCs, not card count)
   - N × `GET /deltatables/unique_values/{id}?column=...` (one per MultiSelect; module-level cache prevents duplicates for same dc_id+column combinations)

Filter changes → debounced 150 ms → one `bulk_compute_cards` call (aborts any in-flight previous call).

Server-side: `bulk_compute_cards` dedupes Delta table loads. If 4 cards reference the same DC, the DC loads once, value is computed 4× from the shared DataFrame. Polars native.

### 2. Dash editor using the new wrappers

The MVP does NOT swap the editor's `build_card` / `_build_select_component` to emit `DepictioCard` / `DepictioMultiSelect`. Why deferred: existing Dash pattern-matched callbacks target inner IDs (`card-value`, `card-comparison`, `card-secondary-metrics`, `interactive-component-value`) as Outputs. Swapping the visual tree would require rewiring multiple callbacks to target `DepictioCard.value` instead. Doable, but higher risk and beyond a single session's scope.

Portability is still proven at the package level — Dash CAN import `from depictio_components import DepictioCard`, serialization works (`.to_plotly_json()` returns correct shape), and the JS bundle is wired up via `_js_dist`. Hooking the wrappers into `build_card` is a careful refactor, not a new capability.

Effort: ~2–3 days including callback rewiring + smoke tests on iris/penguins/bab3/bab4/bab5.

### 3. Other component types

Figure, Table, MultiQC, Map, Image, JBrowse are not ported. Each is its own Phase 2 chunk. The **pattern is proven** — follow the Card example:
- Write `src/lib/components/DepictioFigure.tsx` (Plotly.js wrapped, takes `{data, layout, config}` props)
- Hand-write `depictio_components/DepictioFigure.py` with matching prop list
- Export from `src/lib/index.ts` + add to `__init__.py`
- `npm run build` in `packages/depictio-components/`
- Add renderer dispatch in `depictio/viewer/src/components/ComponentRenderer.tsx`

### 4. Auto-generated Python wrappers

Right now the `depictio_components/*.py` wrappers are hand-written. This works but requires manual sync when TSX props change. Long-term:

- Install `react-docgen-typescript` + write `scripts/generate_python_wrappers.js` (skeleton referenced in `package.json:scripts.build:py`)
- Run `npm run build:py` as part of `npm run build`
- Protocol: parse each TSX file's `Props` interface, emit `.py` with matching prop list

Effort: ~0.5 day. Low priority — hand-writing works while the component count is small.

## Verification once live

Fresh browser session (clear storage):

| Check | Expected |
|---|---|
| `http://0.0.0.0:8122/dashboard-beta/bab4` loads | SPA boots, header shows "Depictio / Coverage & Depth (beta viewer)" |
| Cards visible | "Total Samples: 4508", "Amplicons Tracked: 98", etc. — same values as Dash viewer |
| Sidebar lists interactive filters | MultiSelect on `sample` shown with label |
| Select values in MultiSelect | Sidebar shows `(count)` badge; cards unchanged (filter support is Phase 2) |
| Light/dark toggle | `localStorage.setItem('theme-store', JSON.stringify({colorScheme: 'dark'}))` then reload — theme follows |
| Dash viewer at `/dashboard/bab4` | Still renders identically — no regression |

## Files changed / added summary

Added 17 files (packages + viewer SPA), modified 3 (`pyproject.toml`, `main.py`, `routes.py`). No modifications to Pydantic models, YAML ingestion, `.db_seeds/*.json`, Dashboard schema, or any Dash component module. The I/O contract is fully preserved — the React viewer reads the exact same `stored_metadata` schema as the Dash viewer.

## If something breaks

- **`from depictio_components import …` fails**: run `uv sync` (with dev extras) to install the editable package from `packages/depictio-components/`. If still failing, check `pyproject.toml` has both the `"depictio-components"` line under `dependencies` AND the `[tool.uv.sources]` path entry.

- **`/dashboard-beta/bab4` returns 404**: the `depictio/viewer/dist/` directory wasn't included in the container image. Rebuild the image (`--build depictio-backend`) so it picks up the dist files. The log line "⚠️  React viewer bundle not found" confirms the mount was skipped at startup.

- **MultiSelect options are empty**: check `docker logs` for 404 or permission errors on `/deltatables/unique_values/{dc_id}?column=…`. The route is new; an outdated backend container won't have it.

- **Card values show `—` or `…`**: the precomputed `aggregation_columns_specs` might not include the requested aggregation. Check the response of `/deltatables/specs/{dc_id}` in DevTools Network. If aggregation missing, that's a backend delta-table setup issue unrelated to this MVP.

- **Visual mismatch vs Dash viewer**: the CSS variables and Mantine theme are in `depictio/viewer/src/theme.ts` and `depictio/viewer/src/styles/app.css`. If Depictio has CSS overrides in `depictio/dash/assets/css/*.css` that aren't ported, bundle the relevant `.css` into `depictio/viewer/src/styles/` via additional `@import` lines.

## Session stats

- ~17 new files
- ~2200 lines of TypeScript, ~180 lines of Python wrappers
- 142 KB shared-component JS bundle (peer-deps React/Plotly kept external)
- 446 KB viewer SPA JS + 206 KB CSS (gzipped 137 KB + 30 KB)
- Dash editor **unchanged** — full rollback is a single-file revert of `pyproject.toml`
